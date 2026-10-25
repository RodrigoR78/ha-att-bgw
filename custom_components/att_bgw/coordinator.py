"""Polls the gateway's status pages and keeps the derived state (rates, names, known MACs)."""

from __future__ import annotations

import asyncio
import logging
import socket
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_REVERSE_DNS,
    CONF_SCAN_INTERVAL,
    DEFAULT_REVERSE_DNS,
    DEFAULT_SCAN_INTERVAL,
    DNS_CACHE,
    DOMAIN,
    EVENT_NEW_DEVICE,
    REQUEST_TIMEOUT,
)
from .parser import (
    Broadband,
    Lan,
    LanDevice,
    ParseError,
    SystemInfo,
    parse_broadband,
    parse_devices,
    parse_lan,
    parse_sysinfo,
)

_LOGGER = logging.getLogger(__name__)


async def fetch_page(session: aiohttp.ClientSession, host: str, page: str) -> str:
    async with session.get(
        f"http://{host}/cgi-bin/{page}.ha", timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
    ) as resp:
        resp.raise_for_status()
        return await resp.text(errors="replace")


async def fetch_sysinfo(session: aiohttp.ClientSession, host: str) -> SystemInfo:
    return parse_sysinfo(await fetch_page(session, host, "sysinfo"))


@dataclass
class BgwData:
    sysinfo: SystemInfo
    broadband: Broadband
    lan: Lan
    devices: dict[str, LanDevice]  # by MAC
    names: dict[str, str]  # MAC -> best name (reverse DNS, else gateway name)
    download_mbps: float | None = None
    upload_mbps: float | None = None
    last_boot: datetime | None = None
    new_macs: list[str] = field(default_factory=list)


class BgwCoordinator(DataUpdateCoordinator[BgwData]):
    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )
        self.host: str = entry.data[CONF_HOST]
        self._session = async_get_clientsession(hass)
        self._store: Store[list[str]] = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.known_macs")
        self.known_macs: set[str] | None = None  # None until loaded; empty store = first run
        self._dns: dict[str, tuple[str, float]] = {}  # ip -> (name, resolved at)
        self._last_counters: tuple[int, int, float] | None = None  # rx, tx, monotonic

    async def async_load_known(self) -> None:
        stored = await self._store.async_load()
        self.known_macs = set(stored) if stored is not None else None

    async def _async_update_data(self) -> BgwData:
        try:
            # one page at a time: the gateway's web server is slow under parallel load
            pages = {p: await fetch_page(self._session, self.host, p)
                     for p in ("sysinfo", "broadbandstatistics", "lanstatistics", "devices")}
            sysinfo = parse_sysinfo(pages["sysinfo"])
            broadband = parse_broadband(pages["broadbandstatistics"])
            lan = parse_lan(pages["lanstatistics"])
            devices = {d.mac: d for d in parse_devices(pages["devices"])}
        except (aiohttp.ClientError, TimeoutError) as err:
            raise UpdateFailed(f"Gateway at {self.host} not reachable: {err}") from err
        except ParseError as err:
            raise UpdateFailed(f"Unexpected page from {self.host}: {err}") from err

        data = BgwData(sysinfo, broadband, lan, devices, names={})
        self._rates(data)
        self._boot_time(data)
        data.names = await self._names(devices)
        await self._detect_new(data)
        return data

    # ---- derived values ---------------------------------------------------------

    def _rates(self, data: BgwData) -> None:
        rx = data.broadband.counters.get("Receive Bytes")
        tx = data.broadband.counters.get("Transmit Bytes")
        now = time.monotonic()
        if rx is None or tx is None:
            return
        if self._last_counters:
            prx, ptx, pt = self._last_counters
            dt = now - pt
            if dt > 0 and rx >= prx and tx >= ptx:  # counters reset on reboot: skip that sample
                data.download_mbps = round((rx - prx) * 8 / dt / 1e6, 2)
                data.upload_mbps = round((tx - ptx) * 8 / dt / 1e6, 2)
        self._last_counters = (rx, tx, now)

    def _boot_time(self, data: BgwData) -> None:
        if not data.sysinfo.uptime:
            return
        boot = (dt_util.utcnow() - data.sysinfo.uptime).replace(second=0, microsecond=0)
        previous = self.data.last_boot if self.data else None
        # page timing jitters by a few seconds; keep the old value unless it really moved
        data.last_boot = previous if previous and abs(boot - previous) < timedelta(minutes=2) else boot

    async def _names(self, devices: dict[str, LanDevice]) -> dict[str, str]:
        names = {mac: d.name for mac, d in devices.items() if d.name}
        if not self.config_entry.options.get(CONF_REVERSE_DNS, DEFAULT_REVERSE_DNS):
            return names
        now = time.monotonic()
        todo = {d.ip for d in devices.values() if d.ip and (
            d.ip not in self._dns or now - self._dns[d.ip][1] > DNS_CACHE.total_seconds())}
        if todo:
            sem = asyncio.Semaphore(8)

            async def lookup(ip: str) -> None:
                async with sem:
                    self._dns[ip] = (await self.hass.async_add_executor_job(_reverse_dns, ip), now)

            await asyncio.gather(*(lookup(ip) for ip in todo))
        for mac, d in devices.items():
            if d.ip and (name := self._dns.get(d.ip, ("", 0))[0]):
                names[mac] = name
        return names

    async def _detect_new(self, data: BgwData) -> None:
        macs = set(data.devices)
        if self.known_macs is None:  # first run ever: seed, don't announce the whole LAN
            self.known_macs = macs
            await self._store.async_save(sorted(macs))
            return
        data.new_macs = sorted(macs - self.known_macs)
        for mac in data.new_macs:
            d = data.devices[mac]
            self.hass.bus.async_fire(
                EVENT_NEW_DEVICE,
                {"mac": mac, "ip": d.ip, "name": data.names.get(mac, ""), "connection": d.connection,
                 "online": d.online, "gateway": self.host},
            )
            _LOGGER.info("New LAN device %s (%s) on %s", mac, data.names.get(mac) or d.ip or "no IPv4", d.connection)
        if data.new_macs:
            self.known_macs |= macs
            await self._store.async_save(sorted(self.known_macs))


def _reverse_dns(ip: str) -> str:
    try:
        name = socket.gethostbyaddr(ip)[0]
    except OSError:
        return ""
    # some resolvers (Pi-hole) answer unknown PTRs with the address itself
    return "" if name == ip else name.split(".")[0]
