"""Gateway sensors: WAN throughput and totals, link, addresses, device counts, last boot."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfDataRate, UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BgwConfigEntry, BgwEntity
from .coordinator import BgwData


@dataclass(frozen=True, kw_only=True)
class BgwSensorDescription(SensorEntityDescription):
    value: Callable[[BgwData], Any]


def _counter(name: str) -> Callable[[BgwData], int | None]:
    return lambda d: d.broadband.counters.get(name)


SENSORS: tuple[BgwSensorDescription, ...] = (
    BgwSensorDescription(
        key="wan_download", icon="mdi:download-network",
        device_class=SensorDeviceClass.DATA_RATE, state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND, suggested_display_precision=2,
        value=lambda d: d.download_mbps,
    ),
    BgwSensorDescription(
        key="wan_upload", icon="mdi:upload-network",
        device_class=SensorDeviceClass.DATA_RATE, state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND, suggested_display_precision=2,
        value=lambda d: d.upload_mbps,
    ),
    BgwSensorDescription(
        key="wan_received", device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL_INCREASING, native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES, suggested_display_precision=2,
        value=_counter("Receive Bytes"),
    ),
    BgwSensorDescription(
        key="wan_sent", device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL_INCREASING, native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES, suggested_display_precision=2,
        value=_counter("Transmit Bytes"),
    ),
    BgwSensorDescription(
        key="link_speed", icon="mdi:speedometer", device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND, entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda d: d.broadband.link_speed_mbps,
    ),
    BgwSensorDescription(
        key="wan_ipv4", icon="mdi:ip-network", entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda d: d.broadband.ipv4 or None,
    ),
    BgwSensorDescription(
        key="wan_ipv6", icon="mdi:ip-network", entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False, value=lambda d: d.broadband.ipv6 or None,
    ),
    BgwSensorDescription(
        key="devices_online", icon="mdi:lan-connect", state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="devices",
        value=lambda d: sum(x.online for x in d.devices.values()),
    ),
    BgwSensorDescription(
        key="devices_known", icon="mdi:lan", state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="devices", value=lambda d: len(d.devices),
    ),
    BgwSensorDescription(
        key="last_boot", device_class=SensorDeviceClass.TIMESTAMP, entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda d: d.last_boot,
    ),
    *(
        BgwSensorDescription(
            key=key, icon="mdi:alert-circle-outline", state_class=SensorStateClass.TOTAL_INCREASING,
            entity_category=EntityCategory.DIAGNOSTIC, entity_registry_enabled_default=False,
            value=_counter(counter),
        )
        for key, counter in (
            ("wan_rx_errors", "Receive Errors"), ("wan_tx_errors", "Transmit Errors"),
            ("wan_rx_drops", "Receive Drops"), ("wan_tx_drops", "Transmit Drops"),
        )
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: BgwConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(BgwSensor(entry.runtime_data, desc) for desc in SENSORS)


class BgwSensor(BgwEntity, SensorEntity):
    entity_description: BgwSensorDescription

    def __init__(self, coordinator, description: BgwSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        d = self.coordinator.data
        if self.entity_description.key == "wan_ipv4":
            return {"gateway": d.broadband.gateway_ipv4, "dns": d.broadband.dns, "mtu": d.broadband.mtu,
                    "network_type": d.broadband.network_type, "source": d.broadband.source}
        if self.entity_description.key == "link_speed":
            return {"duplex": d.broadband.duplex, "line_state": d.broadband.line_state}
        return None
