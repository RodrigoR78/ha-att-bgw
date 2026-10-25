"""Parse the AT&T BGW gateway's status pages (/cgi-bin/*.ha). No Home Assistant imports,
so the parser can be tested on its own (tools/test_parser.py).

The pages need no login (only changing settings needs the device access code):
    sysinfo.ha              model, serial, firmware, uptime
    broadbandstatistics.ha  WAN state, addresses, link speed, byte/error counters
    lanstatistics.ha        LAN ports, active/inactive device counts
    devices.ha              every LAN device the gateway has seen
All of them are <table summary="..."> blocks of <th>label</th><td>value</td> rows.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

_TABLE_RE = re.compile(r"<table(?P<attrs>[^>]*)>(?P<body>.*?)</table>", re.S | re.I)
_SUMMARY_RE = re.compile(r'summary="([^"]*)"', re.I)
_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_CELL_RE = re.compile(r"<t[hd][^>]*>(.*?)</t[hd]>", re.S | re.I)
_DEVICE_ROW_RE = re.compile(r'<th scope="row">(.*?)</th>\s*<td[^>]*>(.*?)</td>', re.S)


class ParseError(Exception):
    """A page didn't have the expected structure (wrong device or new firmware layout)."""


def text(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def tables(page: str) -> dict[str, list[list[str]]]:
    """{table summary: [[cell, ...], ...]} for every table on the page."""
    out: dict[str, list[list[str]]] = {}
    for m in _TABLE_RE.finditer(page):
        summary = _SUMMARY_RE.search(m.group("attrs"))
        rows = [[text(c) for c in _CELL_RE.findall(r)] for r in _ROW_RE.findall(m.group("body"))]
        out[summary.group(1) if summary else f"table{len(out)}"] = [r for r in rows if any(r)]
    return out


def _kv(rows: list[list[str]]) -> dict[str, str]:
    return {r[0]: r[1] for r in rows if len(r) == 2}


def _find(tbls: dict[str, list[list[str]]], *words: str) -> list[list[str]]:
    """Rows of the first table whose summary contains all the words (case-insensitive)."""
    for summary, rows in tbls.items():
        if all(w.lower() in summary.lower() for w in words):
            return rows
    return []


def _int(value: str | None) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except ValueError:
        return None


# ---- sysinfo.ha ------------------------------------------------------------


@dataclass
class SystemInfo:
    manufacturer: str
    model: str
    serial: str
    software_version: str
    hardware_version: str
    mac: str
    uptime: timedelta | None
    clock: datetime | None  # gateway's local time when the page was rendered


def parse_uptime(value: str) -> timedelta | None:
    """'05:00:30:14' (days:hours:minutes:seconds) -> timedelta."""
    parts = value.split(":")
    if len(parts) != 4 or not all(p.isdigit() for p in parts):
        return None
    d, h, m, s = map(int, parts)
    return timedelta(days=d, hours=h, minutes=m, seconds=s)


def parse_sysinfo(page: str) -> SystemInfo:
    info = _kv(_find(tables(page), "system information"))
    if "Model Number" not in info or "Serial Number" not in info:
        raise ParseError("sysinfo.ha: no model/serial - not a BGW gateway?")
    try:
        clock = datetime.fromisoformat(info.get("Current Date/Time", ""))
    except ValueError:
        clock = None
    return SystemInfo(
        manufacturer=info.get("Manufacturer", ""),
        model=info["Model Number"],
        serial=info["Serial Number"],
        software_version=info.get("Software Version", ""),
        hardware_version=info.get("Hardware Version", ""),
        mac=info.get("MAC Address", "").lower(),
        uptime=parse_uptime(info.get("Time Since Last Reboot", "")),
        clock=clock,
    )


# ---- broadbandstatistics.ha --------------------------------------------------


@dataclass
class Broadband:
    connection: str  # "Up" / "Down" / ...
    source: str  # ETHERNET / DSL ...
    network_type: str
    ipv4: str
    gateway_ipv4: str
    dns: list[str]
    mtu: int | None
    line_state: str
    link_speed_mbps: int | None
    duplex: str
    ipv6_status: str
    ipv6: str
    counters: dict[str, int] = field(default_factory=dict)  # "Receive Bytes" -> 123, ...


def parse_broadband(page: str) -> Broadband:
    tbls = tables(page)
    summary = _kv(_find(tbls, "wan information"))
    if "Broadband Connection" not in summary:
        raise ParseError("broadbandstatistics.ha: no WAN summary table")
    link = _kv(_find(tbls, "ethernet statistics")) or _kv(_find(tbls, "line"))
    ipv6 = _kv(_find(tbls, "ipv6 table"))
    counters_raw = _kv(_find(tbls, "ipv4 statistics"))
    return Broadband(
        connection=summary.get("Broadband Connection", ""),
        source=summary.get("Broadband Connection Source", ""),
        network_type=summary.get("Broadband Network Type", ""),
        ipv4=summary.get("Broadband IPv4 Address", ""),
        gateway_ipv4=summary.get("Gateway IPv4 Address", ""),
        dns=[d for d in (summary.get("Primary DNS"), summary.get("Secondary DNS")) if d],
        mtu=_int(summary.get("MTU")),
        line_state=link.get("Line State", ""),
        link_speed_mbps=_int(link.get("Current Speed (Mbps)")),
        duplex=link.get("Current Duplex", ""),
        ipv6_status=ipv6.get("Status", ""),
        ipv6=ipv6.get("Global Unicast IPv6 Address", ""),
        counters={k: v for k, v in ((k, _int(v)) for k, v in counters_raw.items()) if v is not None},
    )


# ---- lanstatistics.ha ----------------------------------------------------------


@dataclass
class LanPort:
    port: int
    up: bool
    speed_bps: int | None


@dataclass
class Lan:
    gateway_ip: str
    dhcp_server: bool
    active_devices: int | None
    inactive_devices: int | None
    ports: list[LanPort]


def parse_lan(page: str) -> Lan:
    tbls = tables(page)
    status = _kv(_find(tbls, "critical lan status"))
    ifaces = _find(tbls, "lan interfaces")
    eth = next((r for r in ifaces if r and r[0] == "Ethernet" and len(r) >= 4), None)
    ports: list[LanPort] = []
    port_rows = {r[0]: r[1:] for r in _find(tbls, "lan ethernet statistics") if r}
    header = next((r for r in _find(tbls, "lan ethernet statistics") if r and r[0] == ""), [])
    for i, name in enumerate(header[1:]):
        m = re.search(r"\d+", name)
        state = port_rows.get("State", [])
        speed = port_rows.get("Transmit Speed", [])
        ports.append(
            LanPort(
                port=int(m.group()) if m else i + 1,
                up=(state[i] if i < len(state) else "").lower() == "up",
                speed_bps=_int(speed[i]) if i < len(speed) else None,
            )
        )
    return Lan(
        gateway_ip=status.get("Device IPv4 Address", ""),
        dhcp_server=status.get("DHCP Server", "").lower() == "on",
        active_devices=_int(eth[2]) if eth else None,
        inactive_devices=_int(eth[3]) if eth else None,
        ports=ports,
    )


# ---- devices.ha ------------------------------------------------------------------


@dataclass
class LanDevice:
    mac: str
    ip: str = ""
    name: str = ""  # the gateway's name for it ("unknown<mac>" names are dropped)
    status: str = ""  # "on" / "off"
    allocation: str = ""  # dhcp / static
    connection: str = ""  # "Ethernet LAN-2", "Wi-Fi 5 GHz" ...
    last_activity: datetime | None = None
    mesh_client: bool = False
    ipv6: list[str] = field(default_factory=list)

    @property
    def online(self) -> bool:
        return self.status == "on"


def _clean_name(name: str) -> str:
    name = name.strip()
    return "" if not name or name.lower().startswith("unknown") else name


def parse_devices(page: str) -> list[LanDevice]:
    """Each device is a run of <th>label</th><td>value</td> rows starting at 'MAC Address'.
    Devices with an IPv4 address have 'IPv4 Address / Name'; the rest have a bare 'Name'."""
    devices: list[LanDevice] = []
    cur: LanDevice | None = None
    for key, val in _DEVICE_ROW_RE.findall(page):
        key, val = text(key), text(val)
        if key == "MAC Address":
            cur = LanDevice(mac=val.lower())
            devices.append(cur)
        elif cur is None:
            continue
        elif key == "IPv4 Address / Name":
            ip, _, name = (x.strip() for x in val.partition("/"))
            cur.ip, cur.name = ip, _clean_name(name)
        elif key == "Name":
            cur.name = cur.name or _clean_name(val)
        elif key == "Status":
            cur.status = val.lower()
        elif key == "Allocation":
            cur.allocation = val
        elif key == "Connection Type":
            cur.connection = val
        elif key == "Last Activity":
            try:
                cur.last_activity = datetime.strptime(val, "%a %b %d %H:%M:%S %Y")
            except ValueError:
                cur.last_activity = None
        elif key == "Mesh Client":
            cur.mesh_client = val.lower() == "yes"
        elif key == "IPv6 Address":
            cur.ipv6.append(val)
    if not devices and "LAN-side device" not in page:
        raise ParseError("devices.ha: no device table")
    return devices
