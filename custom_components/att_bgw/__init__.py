"""AT&T BGW gateway (BGW210 / BGW320): local polling of the gateway's status pages."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import BgwCoordinator

PLATFORMS = [Platform.BINARY_SENSOR, Platform.DEVICE_TRACKER, Platform.SENSOR]

type BgwConfigEntry = ConfigEntry[BgwCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: BgwConfigEntry) -> bool:
    coordinator = BgwCoordinator(hass, entry)
    await coordinator.async_load_known()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_reload_on_options))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: BgwConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _reload_on_options(hass: HomeAssistant, entry: BgwConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


class BgwEntity(CoordinatorEntity[BgwCoordinator]):
    """An entity on the gateway's own device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: BgwCoordinator, key: str) -> None:
        super().__init__(coordinator)
        info = coordinator.data.sysinfo
        self._attr_unique_id = f"{info.serial}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, info.serial)},
            connections={(CONNECTION_NETWORK_MAC, info.mac)} if info.mac else set(),
            manufacturer=info.manufacturer or "AT&T",
            model=info.model,
            name=info.model,
            serial_number=info.serial,
            sw_version=info.software_version,
            hw_version=info.hardware_version,
            configuration_url=f"http://{coordinator.host}/",
        )
