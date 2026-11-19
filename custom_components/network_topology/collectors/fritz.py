"""Read mesh topology and host list from a FRITZ!Box via TR-064.

All methods are blocking and must run in the executor.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from fritzconnection import FritzConnection
from fritzconnection.lib.fritzhosts import FritzHosts
from fritzconnection.lib.fritzstatus import FritzStatus

_LOGGER = logging.getLogger(__name__)

TIMEOUT = 15


@dataclass(frozen=True)
class FritzCredentials:
    """Connection data for a FRITZ!Box."""

    host: str
    username: str
    password: str
    port: int | None = None
    use_tls: bool = False


class FritzSource:
    """Keeps one TR-064 connection and fetches the raw data."""

    def __init__(self, creds: FritzCredentials) -> None:
        self._creds = creds
        self._hosts: FritzHosts | None = None

    def _connect(self) -> FritzHosts:
        if self._hosts is None:
            kwargs: dict[str, Any] = {
                "address": self._creds.host,
                "user": self._creds.username,
                "password": self._creds.password,
                "use_tls": self._creds.use_tls,
                "timeout": TIMEOUT,
            }
            if self._creds.port:
                kwargs["port"] = self._creds.port
            self._hosts = FritzHosts(fc=FritzConnection(**kwargs))
        return self._hosts

    def fetch_mesh(self) -> dict[str, Any]:
        """Return the mesh topology JSON (X_AVM-DE_GetMeshListPath)."""
        try:
            return self._connect().get_mesh_topology()
        except Exception:
            self._hosts = None
            raise

    def fetch(self) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any] | None]:
        """Return (mesh topology, host list, WAN status)."""
        try:
            hosts = self._connect()
            mesh, host_list = hosts.get_mesh_topology(), hosts.get_hosts_info()
        except Exception:
            # Drop the connection so the next update reconnects cleanly.
            self._hosts = None
            raise
        return mesh, host_list, self._fetch_wan(hosts.fc)

    @staticmethod
    def _fetch_wan(fc: FritzConnection) -> dict[str, Any] | None:
        """Sync rates and current throughput of the internet line (bit/s).

        Optional: a failure here must not cost the LAN/WLAN data.
        """
        try:
            status = FritzStatus(fc=fc)
            max_up, max_down = status.max_bit_rate
            wan: dict[str, Any] = {
                "max_up": max_up,
                "max_down": max_down,
                "connected": bool(status.is_connected),
            }
            try:
                linked_up, linked_down = status.max_linked_bit_rate
                wan.update(linked_up=linked_up, linked_down=linked_down)
            except Exception:  # not offered by every line type
                pass
            up_bytes, down_bytes = status.transmission_rate
            wan.update(rate_up=int(up_bytes) * 8, rate_down=int(down_bytes) * 8)
            return wan
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("WAN status not available: %s", err)
            return None
