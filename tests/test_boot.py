"""Boot test: set the integration up on the real Home Assistant core (latest release in CI), with the
device mocked, and fail on any error or deprecation warning it logs. Catches HA API changes that
hassfest and the unit tests can't. Run with `pip install homeassistant && python tests/test_boot.py`."""

import asyncio
import json
import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import homeassistant.const as ha_const
from homeassistant import bootstrap, config_entries, core, loader
from homeassistant.helpers import device_registry as dr, entity_registry as er

ROOT = Path(__file__).resolve().parent.parent
SRC = Path(os.environ.get("BOOT_SRC", ROOT / "custom_components"))
DOMAIN = "att_bgw"
problems: list[str] = []


class Collect(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        msg = record.getMessage()
        if record.levelno >= logging.WARNING and DOMAIN in msg + record.name and "has not been tested" not in msg:
            problems.append(f"{record.levelname}: {msg[:400]}")


def fail_if(condition: bool, message: str) -> None:
    if condition:
        problems.append(f"CHECK: {message}")


async def start_hass(config_dir: Path) -> core.HomeAssistant:
    hass = core.HomeAssistant(str(config_dir))
    hass.config.skip_pip = True
    hass.config_entries = config_entries.ConfigEntries(hass, {})
    loader.async_setup(hass)
    await bootstrap.async_load_base_functionality(hass)
    hass.set_state(core.CoreState.running)
    return hass


def make_entry(data: dict, options: dict) -> config_entries.ConfigEntry:
    return config_entries.ConfigEntry(
        domain=DOMAIN, title="boot test", version=1, minor_version=1, source="user", unique_id="boot-test",
        discovery_keys={}, subentries_data=None, data=data, options=options,
    )


def entities(hass: core.HomeAssistant, entry: config_entries.ConfigEntry) -> list[er.RegistryEntry]:
    return er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)


def devices(hass: core.HomeAssistant, entry: config_entries.ConfigEntry) -> list[dr.DeviceEntry]:
    return dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)


def check_available(hass: core.HomeAssistant, entry: config_entries.ConfigEntry, domain: str) -> None:
    enabled = [e for e in entities(hass, entry) if e.domain == domain and not e.disabled_by]
    fail_if(not enabled, f"no enabled {domain} entities")
    down = [e.entity_id for e in enabled if (s := hass.states.get(e.entity_id)) is None or s.state == "unavailable"]
    fail_if(bool(down), f"unavailable {domain}: {down[:5]}")


async def check_rename_and_reload(hass: core.HomeAssistant, entry: config_entries.ConfigEntry) -> None:
    """Registry edits re-add the entity, and that fails on some invalid device info (seen with via_device)."""
    ent = next(e for e in entities(hass, entry) if not e.disabled_by)
    new_id = f"{ent.domain}.boot_test_renamed"
    er.async_get(hass).async_update_entity(ent.entity_id, new_entity_id=new_id)
    await hass.async_block_till_done()
    fail_if(hass.states.get(new_id) is None, f"{ent.entity_id} was not re-added after a rename")
    fail_if(not await hass.config_entries.async_reload(entry.entry_id), "reload failed")
    await hass.async_block_till_done()


def run(main) -> None:
    logging.getLogger().addHandler(Collect())
    logging.getLogger().setLevel(logging.WARNING)
    config_dir = Path(tempfile.mkdtemp())
    try:
        shutil.copytree(SRC / DOMAIN, config_dir / "custom_components" / DOMAIN, ignore=shutil.ignore_patterns("__pycache__"))
        (config_dir / "custom_components" / "__init__.py").touch()
        manifest = config_dir / "custom_components" / DOMAIN / "manifest.json"
        # these would pull in the HTTP server (diagnostics), which isn't what's being tested
        manifest.write_text(json.dumps(json.loads(manifest.read_text()) | {"dependencies": []}))
        sys.path.insert(0, str(config_dir))
        asyncio.run(main(config_dir))
    finally:
        shutil.rmtree(config_dir, ignore_errors=True)
    print(f"Home Assistant {ha_const.__version__}")
    if problems:
        print("\n".join(problems))
        sys.exit(1)
    print("boot test passed")


async def main(config_dir: Path) -> None:
    fixtures = ROOT / "tests" / "fixtures"

    async def fetch_page(session, host: str, page: str) -> str:
        return (fixtures / f"{page}.html").read_text(errors="replace")

    hass = await start_hass(config_dir)
    entry = make_entry({"host": "gw.test"}, {"reverse_dns": False})
    coordinator = "custom_components.att_bgw.coordinator"
    with patch(f"{coordinator}.fetch_page", fetch_page), patch(f"{coordinator}.async_get_clientsession", MagicMock()):
        await hass.config_entries.async_add(entry)
        await hass.async_block_till_done()
        for domain in ("sensor", "binary_sensor"):
            check_available(hass, entry, domain)
        trackers = [e for e in entities(hass, entry) if e.domain == "device_tracker"]
        fail_if(not trackers, "no trackers")
        fail_if(any(not e.device_id for e in trackers), "a tracker has no device")
        names = {d.id: d.name for d in devices(hass, entry)}
        fail_if(any(not n for n in names.values()), "a device has no name")
        print(f"{len(trackers)} trackers, {len(names)} devices")
        # a device's name must survive its tracker losing its hostname
        with patch(f"{coordinator}.BgwCoordinator._names", AsyncMock(return_value={})):
            fail_if(not await hass.config_entries.async_reload(entry.entry_id), "reload failed")
            await hass.async_block_till_done()
            after = {d.id: d.name for d in devices(hass, entry)}
            fail_if(after != names, "device names changed when the hostnames went away")
        await check_rename_and_reload(hass, entry)
        await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_stop(force=True)


run(main)
