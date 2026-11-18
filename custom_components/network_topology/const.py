"""Constants for the Network Topology integration."""

from __future__ import annotations

DOMAIN = "network_topology"

CONF_FRITZ_ENTRY_ID = "fritz_entry_id"
CONF_SOURCE_ENTRY = "source_entry"
MANUAL_ENTRY = "__manual__"

CONF_AUTO_RESCAN = "auto_rescan"
DEFAULT_AUTO_RESCAN = True

CONFIG_FILE = "network_topology.yaml"

DEFAULT_HOST = "192.168.178.1"
DEFAULT_SCAN_INTERVAL = 60  # seconds
DEFAULT_MIN_SWITCH_DEVICES = 2

CARD_URL_BASE = f"/{DOMAIN}_static"
CARD_FILE = "network-topology-card.js"

WS_GET = f"{DOMAIN}/get"
WS_SUBSCRIBE = f"{DOMAIN}/subscribe"
WS_DEBUG = f"{DOMAIN}/debug_sources"
