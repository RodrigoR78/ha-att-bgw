"""One router-style tracker per MAC the gateway has seen.

Home Assistant's ScannerEntity rules apply: a tracker is enabled by default only if
another integration already knows the device by its MAC; the rest are created disabled
for you to enable the ones you care about."""

from __future__ import annotations

from typing import Any

from homeassistant.components.device_tracker import ScannerEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import BgwConfigEntry
from .const import CONF_TRACK_NEW, DEFAULT_TRACK_NEW
from .coordinator import BgwCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: BgwConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    added: set[str] = set()

    @callback
    def add_new() -> None:
        new = [mac for mac in coordinator.data.devices if mac not in added]
        if added and not entry.options.get(CONF_TRACK_NEW, DEFAULT_TRACK_NEW):
            return
        added.update(new)
        async_add_entities(BgwTracker(coordinator, mac) for mac in new)

    add_new()
    entry.async_on_unload(coordinator.async_add_listener(add_new))


class BgwTracker(CoordinatorEntity[BgwCoordinator], ScannerEntity):
    def __init__(self, coordinator: BgwCoordinator, mac: str) -> None:
        super().__init__(coordinator)
        self._mac = mac
        self._attr_mac_address = mac
        self._attr_name = coordinator.data.names.get(mac) or mac

    @property
    def _device(self):
        return self.coordinator.data.devices.get(self._mac)

    @property
    def is_connected(self) -> bool:
        d = self._device
        return bool(d and d.online)

    @property
    def ip_address(self) -> str | None:
        d = self._device
        return d.ip or None if d else None

    @property
    def hostname(self) -> str | None:
        return self.coordinator.data.names.get(self._mac) or None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self._device
        if not d:
            return {"seen_by_gateway": False}
        last = d.last_activity
        return {
            "connection": d.connection,
            "allocation": d.allocation,
            "last_activity": dt_util.as_utc(last.replace(tzinfo=dt_util.get_default_time_zone())).isoformat()
            if last else None,
            "ipv6_addresses": len(d.ipv6),
        }
