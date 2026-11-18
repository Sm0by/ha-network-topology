"""Network Topology: combined LAN/WLAN/Zigbee/Bluetooth graph for Home Assistant."""

from __future__ import annotations

import hashlib
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import CARD_FILE, CARD_URL_BASE, DOMAIN
from .coordinator import NetworkTopologyCoordinator
from .websocket import async_register_websocket_commands

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS = [Platform.BUTTON]

type NetworkTopologyConfigEntry = ConfigEntry[NetworkTopologyCoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the websocket API and serve the Lovelace card."""
    async_register_websocket_commands(hass)
    await _async_register_card(hass)
    return True


async def _async_register_card(hass: HomeAssistant) -> None:
    """Serve www/ and load the card in every frontend; no manual resource needed."""
    card = Path(__file__).parent / "www" / CARD_FILE
    # Content hash as cache buster, so browsers pick up a new card after updates.
    digest = await hass.async_add_executor_job(
        lambda: hashlib.sha1(card.read_bytes()).hexdigest()[:8]
    )
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL_BASE, str(card.parent), cache_headers=False)]
    )
    add_extra_js_url(hass, f"{CARD_URL_BASE}/{CARD_FILE}?v={digest}")


async def async_setup_entry(
    hass: HomeAssistant, entry: NetworkTopologyConfigEntry
) -> bool:
    """Set up Network Topology from a config entry."""
    coordinator = NetworkTopologyCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    # A DataUpdateCoordinator only keeps polling while it has listeners.
    # Until sensors exist, keep one permanent listener so the websocket API
    # always serves fresh data.
    entry.async_on_unload(coordinator.async_add_listener(lambda: None))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: NetworkTopologyConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
