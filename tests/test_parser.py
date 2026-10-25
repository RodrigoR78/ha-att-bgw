"""Parser tests against sanitized pages from a real BGW210-700 (firmware 4.28.8).
Runs with plain `python tests/test_parser.py` (no Home Assistant needed) or pytest."""

import importlib.util
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIX = Path(__file__).resolve().parent / "fixtures"

_spec = importlib.util.spec_from_file_location("bgw_parser", ROOT / "custom_components/att_bgw/parser.py")
p = importlib.util.module_from_spec(_spec)
sys.modules["bgw_parser"] = p
_spec.loader.exec_module(p)


def page(name: str) -> str:
    return (FIX / f"{name}.html").read_text(encoding="utf-8")


def test_sysinfo():
    s = p.parse_sysinfo(page("sysinfo"))
    assert (s.manufacturer, s.model, s.serial) == ("ARRIS", "BGW210-700", "R00000000000000")
    assert s.software_version == "4.28.8"
    assert s.uptime == timedelta(days=5, minutes=30, seconds=14)
    assert s.clock == datetime(2026, 10, 25, 7, 42, 42)
    assert s.mac.count(":") == 5


def test_broadband():
    b = p.parse_broadband(page("broadbandstatistics"))
    assert (b.connection, b.source, b.line_state, b.duplex) == ("Up", "ETHERNET", "Up", "full")
    assert b.link_speed_mbps == 1000 and b.mtu == 1500
    assert b.ipv4.startswith("203.0.113.") and b.gateway_ipv4.startswith("203.0.113.")
    assert b.ipv6.startswith("2001:db8::") and b.ipv6_status == "Available"
    assert b.counters["Receive Bytes"] == 375255001720
    assert b.counters["Transmit Bytes"] == 341168898709
    assert {"Receive Errors", "Transmit Errors", "Receive Drops", "Transmit Drops"} <= b.counters.keys()


def test_lan():
    lan = p.parse_lan(page("lanstatistics"))
    assert lan.gateway_ip == "10.20.30.254" and lan.dhcp_server is False
    assert (lan.active_devices, lan.inactive_devices) == (53, 85)
    assert [(x.port, x.up, x.speed_bps) for x in lan.ports] == [
        (1, False, 0), (2, True, 1_000_000_000), (3, False, 0), (4, False, 0)
    ]


def test_devices():
    devs = p.parse_devices(page("devices"))
    assert len(devs) == 133
    assert sum(d.online for d in devs) == 52
    assert sum(bool(d.ip) for d in devs) == 56
    assert all(d.mac.count(":") == 5 for d in devs) and len({d.mac for d in devs}) == 133
    assert all(d.last_activity for d in devs)
    assert {d.connection for d in devs} == {"Ethernet LAN-2", "Ethernet LAN-3", "Ethernet LAN-4"}
    assert not any(d.name for d in devs)  # this gateway doesn't run DHCP, so it knows no names
    first = devs[0]
    assert first.online and first.allocation == "static" and first.ip.startswith("10.20.30.")
    assert len(first.ipv6) == 2


def test_names_and_bad_pages():
    row = '<th scope="row">{}</th><td>{}</td>'
    html_ = "LAN-side device" + "".join(
        row.format(k, v) for k, v in [
            ("MAC Address", "AA:BB:CC:DD:EE:01"), ("IPv4 Address / Name", "10.0.0.5 / printer"),
            ("Status", "on"), ("MAC Address", "aa:bb:cc:dd:ee:02"), ("Name", "doorbell"), ("Status", "off"),
            ("MAC Address", "aa:bb:cc:dd:ee:03"), ("Name", "unknownaabbccddee03"),
        ]
    )
    a, b, c = p.parse_devices(html_)
    assert (a.mac, a.ip, a.name, a.online) == ("aa:bb:cc:dd:ee:01", "10.0.0.5", "printer", True)
    assert (b.ip, b.name, b.online) == ("", "doorbell", False)
    assert c.name == ""
    for fn in (p.parse_sysinfo, p.parse_broadband, p.parse_devices):
        try:
            fn("<html>login page</html>")
        except p.ParseError:
            continue
        raise AssertionError(f"{fn.__name__} accepted a non-BGW page")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
    print("OK")
