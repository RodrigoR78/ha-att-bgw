<p align="center"><img src="assets/icon.svg" width="140" alt="Gateway icon"></p>

# AT&T BGW Gateway (Local)

A Home Assistant integration for AT&T fiber gateways (**BGW210**, likely **BGW320**). It reads the gateway's own status pages on your LAN:

- **Broadband:** connected or not, WAN **download/upload in Mbit/s**, total data, link speed, WAN IPv4/IPv6, last reboot.
- **LAN:** link state of each Ethernet port, number of devices online and known.
- **Presence:** a router-style **device tracker for every device** the gateway has seen.
- **New devices:** an `att_bgw_new_device` event the first time a new MAC shows up on the network.

It needs **no password, no cloud and no extra Python packages**. The status pages are readable without the device access code, and the integration never changes any settings.

## Installation

### HACS

1. HACS → ⋮ → **Custom repositories** → add `https://github.com/RodrigoR78/ha-att-bgw`, category **Integration**.
2. Install **AT&T BGW Gateway (Local)** and restart Home Assistant.

### Manual

Copy `custom_components/att_bgw` into `config/custom_components/` and restart.

## Setup

**Settings → Devices & services → Add integration → AT&T BGW Gateway (Local)**, then enter the gateway's address (default `192.168.1.254`). The integration reads the gateway's system information page to make sure it's a BGW before adding it.

**Options** (integration → ⚙ Configure):

| Option | Default | |
|---|---|---|
| Polling interval | 60 s | 15-3600 s. Each poll reads four pages, about 140 KB in total. |
| Name devices from reverse DNS | on | Use this when another server (Pi-hole, AdGuard, a router in IP passthrough) does DHCP and DNS, so the gateway itself doesn't know device names. |
| Create trackers for newly seen devices | on | New devices still fire the event when this is off. |

To change the address later, open the integration → ⋮ → **Reconfigure**.

## Entities

On the gateway device:

| Entity | Notes |
|---|---|
| Broadband (binary sensor) | connectivity; attributes: status, line state, IPv6 status |
| WAN download / WAN upload | Mbit/s, worked out from the byte counters between polls |
| WAN data received / sent | total bytes (shown in GB), usable in the Energy-style statistics graphs |
| Devices online / Devices known | counts from the device list |
| WAN link speed | diagnostic; attributes: duplex, line state |
| WAN IPv4 address | diagnostic; attributes: gateway, DNS, MTU, network type |
| WAN IPv6 address | diagnostic, disabled by default |
| Last boot | diagnostic timestamp |
| LAN port 1-4 (binary sensors) | diagnostic; link state and speed |
| WAN receive/transmit errors and drops | diagnostic, disabled by default |

### Device trackers

There's one tracker per MAC address the gateway lists, and it shows **Home** while the gateway reports the device as online. These follow Home Assistant's standard rules for router trackers:

- A tracker is **enabled automatically only if another integration already knows the device** (an ESPHome node, a Sonos speaker, a printer…).
- **All the others are created disabled.** Enable the ones you care about in **Settings → Entities** (filter by this integration).

Attributes: `connection` (for example `Ethernet LAN-2`), `allocation` (dhcp/static), `last_activity`, `ipv6_addresses`.

Note that the gateway sees devices by MAC on its own LAN ports. If your Wi-Fi access points or switches sit behind one port, every device behind them shows that port as its connection.

### New-device event

The first time a MAC appears, the integration fires `att_bgw_new_device` with `mac`, `ip`, `name`, `connection`, `online` and `gateway`. On first setup, the current device list is stored silently, so you don't get one event per existing device.

```yaml
automation:
  - alias: New device on the LAN
    triggers:
      - trigger: event
        event_type: att_bgw_new_device
    actions:
      - action: notify.notify
        data:
          title: New LAN device
          message: >
            {{ trigger.event.data.name or 'Unnamed device' }} ({{ trigger.event.data.mac }})
            {{ 'at ' ~ trigger.event.data.ip if trigger.event.data.ip }} via {{ trigger.event.data.connection }}
```

## Supported gateways

| Model | Status |
|---|---|
| BGW210-700 (firmware 4.28.8) | tested |
| BGW320-500 / -505 | expected to work (same web interface), untested: please open an issue with your results |

Other models are added with "(untested model)" in their title. If a page layout differs, the integration reports that it got an unexpected page, and the diagnostics download (integration → ⋮ → **Download diagnostics**, with addresses redacted) shows what was parsed.

## How it works

Every poll reads `sysinfo.ha`, `broadbandstatistics.ha`, `lanstatistics.ha` and `devices.ha` from `http://<gateway>/cgi-bin/`, one page at a time, because the gateway's web server is slow under parallel requests. The parser (`custom_components/att_bgw/parser.py`) has no Home Assistant dependencies and is tested against sanitized pages from a real gateway (`tests/`).

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Could not reach the gateway" | Wrong address, or Home Assistant is on another network. Open `http://<address>/cgi-bin/sysinfo.ha` in a browser from the same network. |
| "Not a BGW gateway's system information page" | Something else answered on that address (another router, Pi-hole…). |
| Devices show MAC addresses instead of names | The gateway doesn't run DHCP on your network. Keep **reverse DNS** on and make sure your DNS server has PTR records (Pi-hole does, for its DHCP clients). |
| WAN download/upload unknown | They need two polls; wait one polling interval. After a gateway reboot the counters reset, and that one sample is skipped. |

## Disclaimer

An unofficial project, not affiliated with or endorsed by AT&T or the gateway manufacturers. "AT&T" and model names identify compatible hardware only.

## License

MIT
