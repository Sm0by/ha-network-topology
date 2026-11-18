"""Update coordinator: collects all sources and builds the topology graph."""

from __future__ import annotations

from datetime import timedelta
import logging
from pathlib import Path
from typing import Any

from fritzconnection.core.exceptions import (
    FritzAuthorizationError,
    FritzConnectionException,
)
import yaml

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SSL,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .collectors.fritz import FritzCredentials, FritzSource
from .const import (
    CONF_FRITZ_ENTRY_ID,
    CONFIG_FILE,
    DEFAULT_MIN_SWITCH_DEVICES,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .topology.fritz_parse import parse_mesh
from .topology.switches import apply_switches, load_config

_LOGGER = logging.getLogger(__name__)


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

        try:
            mesh, hosts = await self.hass.async_add_executor_job(self._fritz.fetch)
        except FritzAuthorizationError as err:
            raise UpdateFailed(f"FRITZ!Box rejected the login: {err}") from err
        except (FritzConnectionException, OSError) as err:
            raise UpdateFailed(f"FRITZ!Box not reachable: {err}") from err

        try:
            raw_config = await self.hass.async_add_executor_job(
                _read_config_file, Path(self.hass.config.path(CONFIG_FILE))
            )
        except (OSError, yaml.YAMLError) as err:
            _LOGGER.warning("Could not read %s: %s", CONFIG_FILE, err)
            raw_config = None

        topo = parse_mesh(mesh, hosts)
        configs, config_warnings = load_config(raw_config)
        topo.warnings.extend(config_warnings)
        apply_switches(topo, configs, min_devices=DEFAULT_MIN_SWITCH_DEVICES)
        # ZHA and Bluetooth collectors follow in later steps.
        return topo.to_dict(generated=dt_util.now().isoformat())
