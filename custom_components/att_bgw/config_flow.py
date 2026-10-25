"""Config flow: the gateway's address, checked by reading its system info page."""

from __future__ import annotations

from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_REVERSE_DNS,
    CONF_SCAN_INTERVAL,
    CONF_TRACK_NEW,
    DEFAULT_HOST,
    DEFAULT_REVERSE_DNS,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TRACK_NEW,
    DOMAIN,
    TESTED_MODELS,
)
from .coordinator import fetch_sysinfo
from .parser import ParseError


class BgwConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        reconfiguring = self.source == SOURCE_RECONFIGURE
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            try:
                info = await fetch_sysinfo(async_get_clientsession(self.hass), host)
            except (aiohttp.ClientResponseError, ParseError):
                errors["base"] = "not_bgw"  # a web server answered, but not with a BGW status page
            except (aiohttp.ClientError, TimeoutError):
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(info.serial)
                if reconfiguring:
                    self._abort_if_unique_id_mismatch(reason="wrong_device")
                    return self.async_update_reload_and_abort(
                        self._get_reconfigure_entry(), data_updates={CONF_HOST: host}
                    )
                self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                title = info.model if info.model in TESTED_MODELS else f"{info.model} (untested model)"
                return self.async_create_entry(title=title, data={CONF_HOST: host})
        default = self._get_reconfigure_entry().data[CONF_HOST] if reconfiguring else DEFAULT_HOST
        return self.async_show_form(
            step_id="reconfigure" if reconfiguring else "user",
            data_schema=vol.Schema({vol.Required(CONF_HOST, default=default): str}),
            errors=errors,
        )

    async_step_reconfigure = async_step_user

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return BgwOptionsFlow()


class BgwOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        o = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCAN_INTERVAL, default=o.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)):
                        vol.All(vol.Coerce(int), vol.Range(min=15, max=3600)),
                    vol.Required(CONF_REVERSE_DNS, default=o.get(CONF_REVERSE_DNS, DEFAULT_REVERSE_DNS)): bool,
                    vol.Required(CONF_TRACK_NEW, default=o.get(CONF_TRACK_NEW, DEFAULT_TRACK_NEW)): bool,
                }
            ),
        )
