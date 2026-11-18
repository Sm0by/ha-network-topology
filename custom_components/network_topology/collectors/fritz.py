"""Read mesh topology and host list from a FRITZ!Box via TR-064.

All methods are blocking and must run in the executor.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fritzconnection import FritzConnection
from fritzconnection.lib.fritzhosts import FritzHosts

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

    def fetch(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Return (mesh topology, host list)."""
        try:
            hosts = self._connect()
            return hosts.get_mesh_topology(), hosts.get_hosts_info()
        except Exception:
            # Drop the connection so the next update reconnects cleanly.
            self._hosts = None
            raise
