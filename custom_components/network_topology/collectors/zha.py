"""Read device info and neighbor/route tables from a loaded ZHA integration.

Runs in the event loop: ZHA keeps its topology in memory (it rescans on its
own schedule), so reading it does no radio traffic.
"""

from __future__ import annotations

import enum
import logging
from typing import Any
from urllib.parse import urlparse

from homeassistant.core import HomeAssistant, callback

_LOGGER = logging.getLogger(__name__)

ZHA_DOMAIN = "zha"


def _plain(value: Any) -> Any:
    """zigpy types (EUI64, NWK, enums) -> JSON-friendly values."""
    if value is None:
        return None
    if isinstance(value, enum.Enum):
        return value.name
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return int(value) if isinstance(value, int) else float(value)
    return str(value)


@callback
def async_get_zha_devices(hass: HomeAssistant) -> list[dict[str, Any]] | None:
    """Return ZHA device info dicts, or None if ZHA is not loaded."""
    if ZHA_DOMAIN not in hass.config.components:
        return None
    try:
        from homeassistant.components.zha.helpers import get_zha_gateway_proxy

        proxy = get_zha_gateway_proxy(hass)
    except (ImportError, KeyError, ValueError) as err:
        _LOGGER.debug("ZHA gateway not available: %s", err)
        return None

    devices: list[dict[str, Any]] = []
    for device_proxy in list(proxy.device_proxies.values()):
        try:
            info = device_proxy.zha_device_info
        except Exception:  # one broken device must not hide the others
            _LOGGER.debug("Skipping ZHA device %s", device_proxy, exc_info=True)
            continue
        devices.append(
            {
                "ieee": _plain(info.get("ieee")),
                "nwk": _plain(info.get("nwk")),
                "name": info.get("name"),
                "user_given_name": info.get("user_given_name"),
                "manufacturer": info.get("manufacturer"),
                "model": info.get("model"),
                "device_type": _plain(info.get("device_type")),
                "active_coordinator": bool(info.get("active_coordinator")),
                "power_source": _plain(info.get("power_source")),
                "lqi": _plain(info.get("lqi")),
                "rssi": _plain(info.get("rssi")),
                "last_seen": _plain(info.get("last_seen")),
                "available": bool(info.get("available", True)),
                "device_reg_id": info.get("device_reg_id"),
                "area_id": info.get("area_id"),
                "neighbors": [
                    {k: _plain(v) for k, v in nb.items()} for nb in info.get("neighbors") or []
                ],
                "routes": [
                    {k: _plain(v) for k, v in r.items()} for r in info.get("routes") or []
                ],
            }
        )
    return devices


def _application(hass: HomeAssistant) -> Any | None:
    """The zigpy ControllerApplication of the loaded ZHA gateway."""
    if ZHA_DOMAIN not in hass.config.components:
        return None
    try:
        from homeassistant.components.zha.helpers import get_zha_gateway_proxy

        return get_zha_gateway_proxy(hass).gateway.application_controller
    except (ImportError, KeyError, ValueError, AttributeError):
        return None


@callback
def zha_scan_running(hass: HomeAssistant) -> bool:
    """True while zigpy runs a topology scan (ZHA's own or ours)."""
    app = _application(hass)
    task = getattr(getattr(app, "topology", None), "_scan_task", None)
    return task is not None and not task.done()


async def async_scan_zha_devices(hass: HomeAssistant, ieees: list[str]) -> int:
    """Re-read neighbor and route tables of the given devices.

    Uses zigpy's targeted scan, the same mechanism as ZHA's
    "Refresh topology" button, limited to these devices. Returns the number
    of devices scanned. Caller must check ``zha_scan_running`` first: a new
    scan cancels one that is running.
    """
    app = _application(hass)
    if app is None:
        return 0
    from zigpy.types import EUI64

    devices = []
    for ieee in ieees:
        try:
            device = app.devices.get(EUI64.convert(ieee))
        except ValueError:
            continue
        if device is not None:
            devices.append(device)
    if devices:
        _LOGGER.debug("Rescanning Zigbee topology of %d devices", len(devices))
        await app.topology.scan(devices=devices)
    return len(devices)


@callback
def async_get_radio_path(hass: HomeAssistant) -> str | None:
    """Serial path or socket:// URL of the ZHA radio."""
    for entry in hass.config_entries.async_entries(ZHA_DOMAIN):
        device = entry.data.get("device") or {}
        if path := device.get("path"):
            return str(path)
    return None


def radio_host(path: str | None) -> str | None:
    """Host of a network coordinator ('socket://192.168.178.50:6638')."""
    if not path or "://" not in path:
        return None
    return urlparse(path).hostname
