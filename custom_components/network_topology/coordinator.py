"""Update coordinator: collects all sources and builds the topology graph."""

from __future__ import annotations

from datetime import timedelta
import logging
from pathlib import Path
import time
from typing import Any, Literal

from fritzconnection.core.exceptions import (
    FritzAuthorizationError,
    FritzConnectionException,
)
import yaml

from homeassistant.components.network import async_get_source_ip
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SSL,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .collectors.bluetooth import async_get_bluetooth, async_registry_by_mac
from .collectors.fritz import FritzCredentials, FritzSource
from .collectors.zha import (
    async_get_radio_path,
    async_get_zha_devices,
    async_scan_zha_devices,
    radio_host,
    zha_scan_running,
)
from .const import (
    CONF_AUTO_RESCAN,
    CONF_FRITZ_ENTRY_ID,
    CONFIG_FILE,
    DEFAULT_AUTO_RESCAN,
    DEFAULT_MIN_SWITCH_DEVICES,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .topology.ble_parse import add_bluetooth, enrich_from_registry
from .topology.fritz_parse import parse_mesh
from .topology.history import prune, remember_links, restore_links
from .topology.model import Topology
from .topology.rescan import RescanPlanner, all_routers, conflict_candidates
from .topology.switches import apply_switches, load_config
from .topology.zha_parse import add_zigbee, attach_point

RescanResult = Literal["started", "busy", "nothing"]

_LOGGER = logging.getLogger(__name__)

HISTORY_VERSION = 1
# Refresh the stored "last seen" times at least this often (seconds).
HISTORY_SAVE_INTERVAL = 900


def credentials_from_data(data: dict[str, Any]) -> FritzCredentials:
    """Build credentials from config entry data (ours or the fritz integration's)."""
    return FritzCredentials(
        host=data[CONF_HOST],
        username=data.get(CONF_USERNAME, ""),
        password=data.get(CONF_PASSWORD, ""),
        port=data.get(CONF_PORT),
        use_tls=bool(data.get(CONF_SSL, False)),
    )


def _read_config_file(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


class NetworkTopologyCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls all sources and returns the merged topology as a dict."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self._fritz: FritzSource | None = None
        self._creds: FritzCredentials | None = None
        self.topology: Topology | None = None
        self.rescan = RescanPlanner()
        self._rescan_running = False
        self._rescan_status: dict[str, Any] = {}
        self._history_store: Store[dict[str, Any]] = Store(
            hass, HISTORY_VERSION, f"{DOMAIN}.last_links"
        )
        self._history: dict[str, dict[str, Any]] | None = None
        self._history_saved = 0.0

    @property
    def zigbee_available(self) -> bool:
        return bool(self.topology and all_routers(self.topology))

    @callback
    def async_start_rescan(self, *, manual: bool = False) -> RescanResult:
        """Targeted Zigbee rescan; throttled unless manual."""
        if self.topology is None:
            return "nothing"
        if self._rescan_running or zha_scan_running(self.hass):
            return "busy"
        candidates = conflict_candidates(self.topology)
        if manual and not candidates:
            candidates = all_routers(self.topology)
        now = time.monotonic()
        devices = self.rescan.plan(candidates, now, force=manual)
        if not devices:
            return "nothing"
        self.rescan.mark(devices, now)
        self._rescan_running = True
        self._rescan_status = {
            "started": dt_util.now().isoformat(),
            "trigger": "manual" if manual else "conflict",
            "devices": len(devices),
        }
        self.config_entry.async_create_background_task(
            self.hass, self._async_run_rescan(devices), f"{DOMAIN} zigbee rescan"
        )
        return "started"

    async def _async_run_rescan(self, devices: list[str]) -> None:
        try:
            scanned = await async_scan_zha_devices(self.hass, devices)
            self._rescan_status["scanned"] = scanned
        except Exception as err:  # radio errors must not break the coordinator
            _LOGGER.warning("Zigbee rescan failed: %s", err)
            self._rescan_status["error"] = str(err)
        finally:
            self._rescan_running = False
            self._rescan_status["finished"] = dt_util.now().isoformat()
        await self.async_request_refresh()

    async def _async_apply_history(self, topo: Topology) -> None:
        """Remember current LAN/WLAN parents; re-attach offline devices."""
        if self._history is None:
            stored = await self._history_store.async_load()
            self._history = dict((stored or {}).get("devices", {}))
        now = dt_util.now()
        changed = remember_links(topo, self._history, now)
        changed |= prune(self._history, now)
        restore_links(topo, self._history)
        mono = time.monotonic()
        if changed or mono - self._history_saved > HISTORY_SAVE_INTERVAL:
            self._history_saved = mono
            history = self._history
            self._history_store.async_delay_save(lambda: {"devices": history}, 10)

    def _current_credentials(self) -> FritzCredentials:
        data = dict(self.config_entry.data)
        if fritz_id := data.get(CONF_FRITZ_ENTRY_ID):
            fritz_entry = self.hass.config_entries.async_get_entry(fritz_id)
            if fritz_entry is None:
                raise UpdateFailed(
                    "The linked FRITZ!Box Tools entry no longer exists; "
                    "remove and re-add Network Topology"
                )
            data = dict(fritz_entry.data)
        return credentials_from_data(data)

    async def _async_update_data(self) -> dict[str, Any]:
        creds = self._current_credentials()
        if self._fritz is None or creds != self._creds:
            self._fritz = FritzSource(creds)
            self._creds = creds

        # Each source may fail on its own; the others still produce a graph.
        fritz_error: str | None = None
        try:
            mesh, hosts, wan = await self.hass.async_add_executor_job(self._fritz.fetch)
        except FritzAuthorizationError as err:
            fritz_error = f"FRITZ!Box rejected the login: {err}"
        except (FritzConnectionException, OSError) as err:
            fritz_error = f"FRITZ!Box not reachable: {err}"

        if fritz_error is None:
            try:
                raw_config = await self.hass.async_add_executor_job(
                    _read_config_file, Path(self.hass.config.path(CONFIG_FILE))
                )
            except (OSError, yaml.YAMLError) as err:
                _LOGGER.warning("Could not read %s: %s", CONFIG_FILE, err)
                raw_config = None
            topo = parse_mesh(mesh, hosts, wan)
            await self._async_apply_history(topo)
            configs, config_warnings = load_config(raw_config)
            topo.warnings.extend(config_warnings)
            apply_switches(topo, configs, min_devices=DEFAULT_MIN_SWITCH_DEVICES)
            enrich_from_registry(topo, async_registry_by_mac(self.hass))
        else:
            _LOGGER.warning("%s; continuing without LAN/WLAN data", fritz_error)
            topo = Topology(warnings=[fritz_error])

        try:
            ha_ip = await async_get_source_ip(self.hass)
        except (OSError, ValueError):
            ha_ip = None
        radio_node, radio = attach_point(
            topo, ha_ip, radio_host(async_get_radio_path(self.hass))
        )
        host_id = next(
            (n.id for n in topo.nodes.values() if n.attrs.get("home_assistant")), None
        )

        if zha_devices := async_get_zha_devices(self.hass):
            add_zigbee(topo, zha_devices, host_id=radio_node, radio_link=radio)

        try:
            if (bt := async_get_bluetooth(self.hass)) is not None:
                scanners, ble_devices = bt
                add_bluetooth(topo, scanners, ble_devices, host_id=host_id)
        except Exception as err:  # Bluetooth internals change often; never fail the update
            _LOGGER.warning("Bluetooth data unavailable: %s", err, exc_info=True)
            topo.warnings.append(f"Bluetooth data unavailable: {err}")

        if fritz_error and len(topo.nodes) <= 1:
            raise UpdateFailed(fritz_error)

        self.topology = topo
        if self.config_entry.options.get(CONF_AUTO_RESCAN, DEFAULT_AUTO_RESCAN):
            self.async_start_rescan()

        data = topo.to_dict(generated=dt_util.now().isoformat())
        data["zigbee_rescan"] = {**self._rescan_status, "running": self._rescan_running}
        return data
