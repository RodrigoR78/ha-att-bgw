"""Diagnostics download, with addresses and identifiers redacted."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import BgwConfigEntry

REDACT = {"serial", "mac", "ipv4", "gateway_ipv4", "ipv6", "dns", "host", "ip", "name"}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: BgwConfigEntry) -> dict[str, Any]:
    data = entry.runtime_data.data
    devices = list(data.devices.values())
    return async_redact_data(
        {
            "entry": {"host": entry.data.get("host"), "options": dict(entry.options)},
            "sysinfo": {k: v if isinstance(v, (str, int, type(None))) else str(v)
                        for k, v in asdict(data.sysinfo).items()},  # timedelta/datetime -> text
            "broadband": asdict(data.broadband),
            "lan": asdict(data.lan),
            "devices": {
                "count": len(devices),
                "online": sum(d.online for d in devices),
                "with_ipv4": sum(bool(d.ip) for d in devices),
                "named_by_gateway": sum(bool(d.name) for d in devices),
                "named_total": len(data.names),
                "connection_types": sorted({d.connection for d in devices}),
            },
            "rates": {"download_mbps": data.download_mbps, "upload_mbps": data.upload_mbps},
        },
        REDACT,
    )
