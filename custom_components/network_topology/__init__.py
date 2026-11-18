"""Network Topology: combined LAN/WLAN/Zigbee/Bluetooth graph for Home Assistant."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .coordinator import NetworkTopologyCoordinator
from .websocket import async_register_websocket_commands

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type NetworkTopologyConfigEntry = ConfigEntry[NetworkTopologyCoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the websocket API once."""
    async_register_websocket_commands(hass)
    return True


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
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: NetworkTopologyConfigEntry
) -> bool:
    """Unload a config entry."""
    return True
