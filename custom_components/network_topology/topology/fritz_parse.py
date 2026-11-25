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
    PASSIVE_SWITCH,
    REPEATER,
    ROUTER,
    WAN,
    WLAN,
    Link,
    Node,
    Topology,
)

# Upstream rank: a link always points from the higher to the lower rank.
_KIND_RANK = {ROUTER: 3, REPEATER: 2, PASSIVE_SWITCH: 1, CLIENT: 0}
_BANDS = {"2G": "2.4", "5G": "5", "6G": "6", "60G": "60"}
_LAN_PORT = re.compile(r"^LAN[:\s_-]*(\d+)$", re.IGNORECASE)
_NULL_MACS = {"", "00:00:00:00:00:00"}
# FRITZ!OS gives switches it detects itself and their ports placeholder MACs.
_PLACEHOLDER_PREFIX = "fa:ce:"


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


def _node_ipv4(raw: dict[str, Any]) -> str | None:
    """First LAN IPv4 from the mesh node's own address list."""
    for addr in raw.get("ip_addresses") or []:
        if not isinstance(addr, dict) or addr.get("version") != "V4":
            continue
        attrs = addr.get("attributes") or []
        value = str(addr.get("value") or "").split("/")[0]
        if value and "LINK_LOCAL" not in attrs and "GUEST" not in attrs:
            return value
    return None


def _kind(raw: dict[str, Any]) -> str:
    role = raw.get("mesh_role")
    if role == "master":
        return ROUTER
    if role == "slave":
        return REPEATER
    if raw.get("device_class") == "NETWORK_SWITCH":
        return PASSIVE_SWITCH
    return CLIENT


def _int_or_none(value: Any, *, negative: bool = False) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = int(value)
    if negative:
        return value if value < 0 else None
    return value if value > 0 else None


def parse_mesh(
    mesh: dict[str, Any],
    hosts: list[dict[str, Any]] | None = None,
    wan: dict[str, Any] | None = None,
) -> Topology:
    """Build the LAN/WLAN part of the topology."""
    topo = Topology()
    hosts_by_mac: dict[str, dict[str, Any]] = {}
    for host in hosts or []:
        if mac := norm_mac(host.get("mac")):
            hosts_by_mac[mac] = host

    raw_nodes = [n for n in mesh.get("nodes", []) if isinstance(n, dict) and n.get("uid")]
    node_ids: dict[str, str] = {}
    ranks: dict[str, int] = {}
    ifaces: dict[str, dict[str, Any]] = {}
    mac_owner: dict[str, str] = {}  # every known MAC (device + interfaces) -> node id

    for raw in raw_nodes:
        mac = norm_mac(raw.get("device_mac_address"))
        kind = _kind(raw)
        node_id = f"mac:{mac}" if mac else f"fritz:{raw['uid']}"
        # Interface MACs: repeaters appear in the host list under one of them.
        own_macs = [mac] if mac else []
        for iface in raw.get("node_interfaces", []) or []:
            if isinstance(iface, dict) and iface.get("uid"):
                ifaces[iface["uid"]] = iface
                imac = norm_mac(iface.get("mac_address"))
                if imac and not imac.startswith(_PLACEHOLDER_PREFIX) and imac not in own_macs:
                    own_macs.append(imac)
        host = next((hosts_by_mac[m] for m in own_macs if m in hosts_by_mac), {})
        for m in own_macs:
            mac_owner.setdefault(m, node_id)

        name = (
            raw.get("device_friendly_name")
            or raw.get("device_name")
            or (host.get("name") if kind != PASSIVE_SWITCH else None)
            or (None if kind == PASSIVE_SWITCH else mac)
            or "Switch"
        )
        node = Node(
            id=node_id,
            name=name,
            kind=kind,
            mac=mac if mac and not mac.startswith(_PLACEHOLDER_PREFIX) else None,
            ip=host.get("ip") or _node_ipv4(raw),
            online=bool(host.get("status", True)) if kind == CLIENT else True,
            model=raw.get("device_model") or None,
            sources=["fritz"],
        )
        if kind in (ROUTER, REPEATER):
            node.attrs["mesh_role"] = raw.get("mesh_role")
            if raw.get("device_firmware_version"):
                node.attrs["firmware"] = raw["device_firmware_version"]
        elif kind == PASSIVE_SWITCH:
            node.layers = [LAN]
            node.attrs["detected_by"] = "fritz"
            node.model = None
        topo.add_node(node)
        node_ids[raw["uid"]] = node_id
        ranks[node_id] = _KIND_RANK[kind]

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
                link = _build_link(raw_link, node_ids, ranks, ifaces)
                if link is not None:
                    candidates.setdefault(link.target, []).append(link)

    for child, links in candidates.items():
        # Prefer a live link; otherwise keep the last known one (offline device).
        best = next((l for l in links if l.connected), links[0])
        topo.links.append(best)
        node = topo.nodes[child]
        if best.layer not in node.layers:
            node.layers.insert(0, best.layer)
        host_known = any(owner == child for m, owner in mac_owner.items() if m in hosts_by_mac)
        if node.kind == CLIENT and not host_known:
            node.online = best.connected

    # Internet uplink of the router.
    if router := topo.router_id():
        topo.nodes[router].layers = [LAN, WLAN]
        topo.add_node(Node(id="internet", name="Internet", kind=INTERNET, layers=[LAN]))
        topo.links.insert(0, _wan_link(router, wan))
    else:
        topo.warnings.append("Mesh topology contains no master (FRITZ!Box) node")

    # Known hosts that are missing from the mesh list (usually offline).
    for mac, host in hosts_by_mac.items():
        node_id = f"mac:{mac}"
        if mac in mac_owner or node_id in topo.nodes:
            continue
        if mac.startswith(_PLACEHOLDER_PREFIX):
            continue  # leftover entry of a switch the box once detected, not a device
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


def _wan_link(router: str, wan: dict[str, Any] | None) -> Link:
    """Internet -> router, with sync rates and current throughput if known.

    ``wan`` (bit/s): max_down, max_up (line sync; port speed when the box
    sits behind a modem on Ethernet), linked_down, linked_up (what the line
    could do), rate_down, rate_up (current throughput), connected,
    access_type (DSL, Ethernet, ...).
    """
    link = Link(source="internet", target=router, layer=WAN)
    if not wan:
        return link

    def kbit(key: str) -> int | None:
        bps = _int_or_none(wan.get(key))
        return bps // 1000 if bps else None

    link.rate_kbit = kbit("max_down")
    link.rate_tx_kbit = kbit("max_up")
    linked = [v for v in (kbit("linked_down"), kbit("linked_up")) if v]
    link.max_rate_kbit = max(linked) if linked else None
    synced = max((v for v in (link.rate_kbit, link.rate_tx_kbit) if v), default=0)
    access = wan.get("access_type")
    if access:
        link.attrs["access_type"] = access
    if (access and access != "DSL") or (link.max_rate_kbit and link.max_rate_kbit < synced):
        # Behind a modem/ONT there is no attainable line rate; the value is
        # the port speed or junk.
        link.max_rate_kbit = None
    for key in ("rate_down", "rate_up"):
        value = wan.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
            link.attrs[f"{key}_bps"] = int(value)
    if wan.get("connected") is False:
        link.connected = False
    return link


def _build_link(
    raw: dict[str, Any],
    node_ids: dict[str, str],
    ranks: dict[str, int],
    ifaces: dict[str, dict[str, Any]],
) -> Link | None:
    a = node_ids.get(raw.get("node_1_uid", ""))
    b = node_ids.get(raw.get("node_2_uid", ""))
    if not a or not b or a == b:
        return None

    if ranks.get(b, 0) > ranks.get(a, 0):
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
        rate_tx_kbit=_int_or_none(raw.get("cur_data_rate_tx")),
    )
    maxes = [v for v in (_int_or_none(raw.get("max_data_rate_rx")), _int_or_none(raw.get("max_data_rate_tx"))) if v]
    link.max_rate_kbit = max(maxes) if maxes else None
    if layer == WLAN:
        link.band = wlan_band(iface_name)
        # Older FRITZ!OS: rx_rssi. FRITZ!OS 8: rx_rcpi in dBm, 255 = not available.
        link.rssi = _int_or_none(raw.get("rx_rssi"), negative=True) or _int_or_none(
            raw.get("rx_rcpi"), negative=True
        )
        if ssid := parent_iface.get("ssid"):
            link.attrs["ssid"] = ssid
    else:
        link.port = lan_port(iface_name)
    if iface_name:
        link.attrs["interface"] = iface_name
    return link
