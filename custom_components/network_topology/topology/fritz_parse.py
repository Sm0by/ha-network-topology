"""Turn the FRITZ!Box mesh topology JSON into a Topology.

Input format (FRITZ!OS mesh list, as returned by
fritzconnection's FritzHosts.get_mesh_topology()):

    {"nodes": [{"uid": "n-1", "device_name": "fritz.box",
                "device_mac_address": "..", "mesh_role": "master",
                "node_interfaces": [{"uid": "ni-1", "name": "LAN:1",
                                     "type": "LAN", "node_links": [...]}]}]}

Every link appears on both ends; it is de-duplicated by its uid.
The parser is defensive: unknown or missing fields are skipped.
"""

from __future__ import annotations

import re
from typing import Any

from .model import (
    CLIENT,
    INTERNET,
    LAN,
    REPEATER,
    ROUTER,
    WAN,
    WLAN,
    Link,
    Node,
    Topology,
)

_ROLE_RANK = {"master": 2, "slave": 1}
_BANDS = {"2G": "2.4", "5G": "5", "6G": "6", "60G": "60"}
_LAN_PORT = re.compile(r"^LAN[:\s_-]*(\d+)$", re.IGNORECASE)
_NULL_MACS = {"", "00:00:00:00:00:00"}


def norm_mac(mac: Any) -> str | None:
    if not isinstance(mac, str):
        return None
    mac = mac.strip().lower().replace("-", ":")
    return None if mac in _NULL_MACS else mac


def lan_port(iface_name: str | None) -> str | None:
    """'LAN:1' -> 'LAN1'."""
    if not iface_name:
        return None
    match = _LAN_PORT.match(iface_name.strip())
    return f"LAN{match.group(1)}" if match else None


def wlan_band(iface_name: str | None) -> str | None:
    """'AP:5G:0' -> '5', 'UPLINK:2G:0' -> '2.4'."""
    if not iface_name:
        return None
    for part in iface_name.upper().split(":"):
        if part in _BANDS:
            return _BANDS[part]
    return None


def _int_or_none(value: Any, *, negative: bool = False) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = int(value)
    if negative:
        return value if value < 0 else None
    return value if value > 0 else None


def parse_mesh(
    mesh: dict[str, Any], hosts: list[dict[str, Any]] | None = None
) -> Topology:
    """Build the LAN/WLAN part of the topology."""
    topo = Topology()
    hosts_by_mac: dict[str, dict[str, Any]] = {}
    for host in hosts or []:
        if mac := norm_mac(host.get("mac")):
            hosts_by_mac[mac] = host

    raw_nodes = [n for n in mesh.get("nodes", []) if isinstance(n, dict) and n.get("uid")]
    node_ids: dict[str, str] = {}
    roles: dict[str, str] = {}
    ifaces: dict[str, dict[str, Any]] = {}

    for raw in raw_nodes:
        mac = norm_mac(raw.get("device_mac_address"))
        role = raw.get("mesh_role") or "unknown"
        node_id = f"mac:{mac}" if mac else f"fritz:{raw['uid']}"
        kind = ROUTER if role == "master" else REPEATER if role == "slave" else CLIENT
        host = hosts_by_mac.get(mac or "", {})
        node = Node(
            id=node_id,
            name=raw.get("device_name") or host.get("name") or mac or raw["uid"],
            kind=kind,
            mac=mac,
            ip=host.get("ip") or None,
            online=bool(host.get("status", True)) if kind == CLIENT else True,
            model=raw.get("device_model") or None,
            sources=["fritz"],
        )
        if kind != CLIENT:
            node.attrs["mesh_role"] = role
            if raw.get("device_firmware_version"):
                node.attrs["firmware"] = raw["device_firmware_version"]
        topo.add_node(node)
        node_ids[raw["uid"]] = node_id
        roles[node_id] = role
        for iface in raw.get("node_interfaces", []) or []:
            if isinstance(iface, dict) and iface.get("uid"):
                ifaces[iface["uid"]] = iface

    # Collect links, oriented upstream -> downstream.
    seen: set[str] = set()
    candidates: dict[str, list[Link]] = {}
    for raw in raw_nodes:
        for iface in raw.get("node_interfaces", []) or []:
            for raw_link in iface.get("node_links", []) or []:
                uid = raw_link.get("uid") or id(raw_link)
                if uid in seen:
                    continue
                seen.add(uid)
                link = _build_link(raw_link, node_ids, roles, ifaces)
                if link is not None:
                    candidates.setdefault(link.target, []).append(link)

    for child, links in candidates.items():
        # Prefer a live link; otherwise keep the last known one (offline device).
        best = next((l for l in links if l.connected), links[0])
        topo.links.append(best)
        node = topo.nodes[child]
        if best.layer not in node.layers:
            node.layers.insert(0, best.layer)
        if node.kind == CLIENT and node.mac not in hosts_by_mac:
            node.online = best.connected

    # Internet uplink of the router.
    if router := topo.router_id():
        topo.nodes[router].layers = [LAN, WLAN]
        topo.add_node(Node(id="internet", name="Internet", kind=INTERNET, layers=[LAN]))
        topo.links.insert(0, Link(source="internet", target=router, layer=WAN))
    else:
        topo.warnings.append("Mesh topology contains no master (FRITZ!Box) node")

    # Known hosts that are missing from the mesh list (usually offline).
    for mac, host in hosts_by_mac.items():
        node_id = f"mac:{mac}"
        if node_id in topo.nodes:
            continue
        iface_type = (host.get("interface_type") or "").lower()
        layer = WLAN if "802.11" in iface_type else LAN if "ethernet" in iface_type else None
        topo.add_node(
            Node(
                id=node_id,
                name=host.get("name") or mac,
                kind=CLIENT,
                layers=[layer] if layer else [],
                mac=mac,
                ip=host.get("ip") or None,
                online=bool(host.get("status", False)),
                sources=["fritz_hosts"],
            )
        )

    if not any(l.port for l in topo.links if l.layer == LAN):
        topo.warnings.append(
            "No LAN port information in the mesh topology; "
            "passive switches cannot be inferred"
        )
    return topo


def _build_link(
    raw: dict[str, Any],
    node_ids: dict[str, str],
    roles: dict[str, str],
    ifaces: dict[str, dict[str, Any]],
) -> Link | None:
    a = node_ids.get(raw.get("node_1_uid", ""))
    b = node_ids.get(raw.get("node_2_uid", ""))
    if not a or not b or a == b:
        return None

    rank_a = _ROLE_RANK.get(roles.get(a, ""), 0)
    rank_b = _ROLE_RANK.get(roles.get(b, ""), 0)
    if rank_b > rank_a:
        parent, child = b, a
        parent_iface = ifaces.get(raw.get("node_interface_2_uid", ""), {})
    else:
        parent, child = a, b
        parent_iface = ifaces.get(raw.get("node_interface_1_uid", ""), {})

    link_type = (raw.get("type") or parent_iface.get("type") or "").upper()
    layer = WLAN if link_type == "WLAN" else LAN
    iface_name = parent_iface.get("name")
    link = Link(
        source=parent,
        target=child,
        layer=layer,
        connected=(raw.get("state") or "CONNECTED").upper() == "CONNECTED",
        rate_kbit=_int_or_none(raw.get("cur_data_rate_rx"))
        or _int_or_none(raw.get("max_data_rate_rx")),
    )
    if layer == WLAN:
        link.band = wlan_band(iface_name)
        link.rssi = _int_or_none(raw.get("rx_rssi"), negative=True)
        if ssid := parent_iface.get("ssid"):
            link.attrs["ssid"] = ssid
    else:
        link.port = lan_port(iface_name)
    if iface_name:
        link.attrs["interface"] = iface_name
    return link
