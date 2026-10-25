"""Broadband connectivity and per-port LAN link state."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BgwConfigEntry, BgwEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: BgwConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = [BgwBroadband(coordinator)]
    entities += [BgwLanPort(coordinator, p.port) for p in coordinator.data.lan.ports]
    async_add_entities(entities)


class BgwBroadband(BgwEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "broadband")

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.broadband.connection.lower() == "up"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        b = self.coordinator.data.broadband
        return {"status": b.connection, "line_state": b.line_state, "ipv6_status": b.ipv6_status}


class BgwLanPort(BgwEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, port: int) -> None:
        super().__init__(coordinator, f"lan_port_{port}")
        self._port = port
        self._attr_translation_key = "lan_port"
        self._attr_translation_placeholders = {"port": str(port)}

    def _data(self):
        return next((p for p in self.coordinator.data.lan.ports if p.port == self._port), None)

    @property
    def is_on(self) -> bool | None:
        p = self._data()
        return p.up if p else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        p = self._data()
        return {"speed_mbps": p.speed_bps // 1_000_000 if p and p.speed_bps else 0}
