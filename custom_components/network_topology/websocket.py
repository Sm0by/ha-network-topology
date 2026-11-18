"""Websocket API used by the Lovelace card."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN, WS_DEBUG, WS_GET, WS_SUBSCRIBE

if TYPE_CHECKING:
    from .coordinator import NetworkTopologyCoordinator


@callback
def _coordinator(hass: HomeAssistant) -> NetworkTopologyCoordinator | None:
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            return entry.runtime_data
    return None


@callback
def async_register_websocket_commands(hass: HomeAssistant) -> None:
    """Register all commands."""
    websocket_api.async_register_command(hass, ws_get)
    websocket_api.async_register_command(hass, ws_subscribe)
    websocket_api.async_register_command(hass, ws_debug_sources)


@websocket_api.websocket_command({vol.Required("type"): WS_GET})
@callback
def ws_get(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return the current topology."""
    coordinator = _coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_loaded", "Network Topology is not set up")
        return
    connection.send_result(msg["id"], coordinator.data)


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): WS_DEBUG})
@callback
def ws_debug_sources(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Raw collector input (Bluetooth, registry MACs), for checking against real data."""
    from .collectors.bluetooth import async_get_bluetooth, async_registry_by_mac

    bt = async_get_bluetooth(hass)
    connection.send_result(
        msg["id"],
        {
            "bluetooth_scanners": bt[0] if bt else None,
            "bluetooth_devices": bt[1] if bt else None,
            "registry_by_mac": async_registry_by_mac(hass),
        },
    )


@websocket_api.websocket_command({vol.Required("type"): WS_SUBSCRIBE})
@callback
def ws_subscribe(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Send the topology now and after every update."""
    coordinator = _coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_loaded", "Network Topology is not set up")
        return

    @callback
    def _forward() -> None:
        connection.send_message(
            websocket_api.event_message(msg["id"], coordinator.data)
        )

    connection.subscriptions[msg["id"]] = coordinator.async_add_listener(_forward)
    connection.send_result(msg["id"])
    _forward()
