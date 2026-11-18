"""Read Bluetooth scanners and devices, and map HA devices by network MAC.

Runs in the event loop; everything comes from in-memory state.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.const import CONF_SOURCE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr

_LOGGER = logging.getLogger(__name__)

BT_DOMAIN = "bluetooth"
CONF_SOURCE_DEVICE_ID = "source_device_id"  # homeassistant.components.bluetooth.const


def _network_mac(device: dr.DeviceEntry | None) -> str | None:
    if device is None:
        return None
    for ctype, value in device.connections:
        if ctype == dr.CONNECTION_NETWORK_MAC:
            return dr.format_mac(value)
    return None


@callback
def async_registry_by_mac(hass: HomeAssistant) -> dict[str, dict[str, Any]]:
    """Network MAC -> HA device info, for every device with a MAC connection."""
    out: dict[str, dict[str, Any]] = {}
    for device in dr.async_get(hass).devices.values():
        if device.disabled_by:
            continue
        for ctype, value in device.connections:
            if ctype == dr.CONNECTION_NETWORK_MAC:
                out.setdefault(
                    dr.format_mac(value),
                    {
                        "ha_device_id": device.id,
                        "name": device.name,
                        "name_by_user": device.name_by_user,
                        "area_id": device.area_id,
                    },
                )
    return out


@callback
def async_get_bluetooth(
    hass: HomeAssistant,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | None:
    """Return (scanners, devices), or None if Bluetooth is not set up."""
    if BT_DOMAIN not in hass.config.components:
        return None
    from homeassistant.components import bluetooth

    registry = dr.async_get(hass)

    # Remote scanners (ESPHome proxies) get a bluetooth config entry that
    # records which HA device registered them.
    source_device: dict[str, str] = {}
    for entry in hass.config_entries.async_entries(BT_DOMAIN):
        source = entry.data.get(CONF_SOURCE)
        device_id = entry.data.get(CONF_SOURCE_DEVICE_ID)
        if source and device_id:
            source_device[str(source).upper()] = device_id

    scanners: list[dict[str, Any]] = []
    for scanner in bluetooth.async_current_scanners(hass):
        source = str(scanner.source).upper()
        device_id = source_device.get(source)
        scanners.append(
            {
                "source": source,
                "name": scanner.name,
                "local": not isinstance(scanner, bluetooth.BaseHaRemoteScanner),
                "connectable": bool(scanner.connectable),
                "network_mac": _network_mac(registry.async_get(device_id)) if device_id else None,
                "ha_device_id": device_id,
            }
        )
    scanner_sources = {s["source"] for s in scanners}

    devices: list[dict[str, Any]] = []
    for device in registry.devices.values():
        if device.disabled_by:
            continue
        address = next(
            (str(v).upper() for t, v in device.connections if t == dr.CONNECTION_BLUETOOTH),
            None,
        )
        if address is None or address in scanner_sources:
            continue  # not a BLE device, or the adapter/proxy itself
        try:
            seen = bluetooth.async_scanner_devices_by_address(hass, address, connectable=False)
            last = bluetooth.async_last_service_info(hass, address, connectable=False)
        except Exception:  # an odd address must not break the update
            _LOGGER.debug("Bluetooth lookup failed for %s", address, exc_info=True)
            continue
        devices.append(
            {
                "address": address,
                "name": device.name_by_user or device.name,
                "ha_device_id": device.id,
                "area_id": device.area_id,
                "network_mac": _network_mac(device),
                "heard": [
                    {"source": str(d.scanner.source).upper(), "rssi": d.advertisement.rssi}
                    for d in seen
                ],
                "last_source": last.source if last else None,
            }
        )
    return scanners, devices
