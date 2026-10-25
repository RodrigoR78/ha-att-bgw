"""Constants for the AT&T BGW gateway integration."""

from datetime import timedelta

DOMAIN = "att_bgw"
DEFAULT_HOST = "192.168.1.254"  # the gateway's factory LAN address

CONF_SCAN_INTERVAL = "scan_interval"
CONF_REVERSE_DNS = "reverse_dns"
CONF_TRACK_NEW = "track_new_devices"

DEFAULT_SCAN_INTERVAL = 60  # seconds
DEFAULT_REVERSE_DNS = True
DEFAULT_TRACK_NEW = True

REQUEST_TIMEOUT = 20
DNS_CACHE = timedelta(hours=1)
EVENT_NEW_DEVICE = f"{DOMAIN}_new_device"

PAGES = ("sysinfo", "broadbandstatistics", "lanstatistics", "devices")
TESTED_MODELS = {"BGW210-700"}
