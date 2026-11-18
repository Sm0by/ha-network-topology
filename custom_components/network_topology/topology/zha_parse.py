"""Turn ZHA device info into the Zigbee part of the topology.

Input: a list of device dicts in the format of ZHA's ``zha_device_info``
(the same JSON the websocket command ``zha/devices`` returns):

    {"ieee": "00:12:4b:…", "nwk": "0x0000", "name": "…", "user_given_name": None,
     "device_type": "Coordinator" | "Router" | "EndDevice",
     "lqi": 200, "available": True, "device_reg_id": "…", "area_id": "…",
     "neighbors": [{"ieee": "…", "nwk": "0x1a2b", "relationship": "Child",
                    "device_type": "EndDevice", "lqi": "180"}],
     "routes": [{"dest_nwk": "0x0000", "next_hop": "0x1a2b", "route_status": "Active"}]}

Zigbee is a mesh, the card draws a tree. Parent choice:

* End device: the router/coordinator that lists it as ``Child`` (best LQI),
  else the end device's own ``Parent`` entry.
* Router: next hop of its own active route to the coordinator (0x0000);
  else the coordinator's routing table (direct, or the first hop it sends
  through, with the rest of the path filled in by best path); else the best
  path over neighbor links with Zigbee-PRO-style link costs (1..7 by LQI).
  Loops from stale routes are repaired.
* End devices listed as Child by several routers: the coordinator's route
  decides.
* Nothing known: coordinator, marked ``parent: "unknown"``.

All router-router neighbor links that are not tree links go to ``topo.mesh``.
"""

from __future__ import annotations

import heapq
from typing import Any

from .model import (
    USB,
    ZIGBEE,
    ZIGBEE_COORDINATOR,
    ZIGBEE_END_DEVICE,
    ZIGBEE_ROUTER,
    Link,
    Node,
    Topology,
)

_KIND = {
    "coordinator": ZIGBEE_COORDINATOR,
    "router": ZIGBEE_ROUTER,
    "enddevice": ZIGBEE_END_DEVICE,
    "end_device": ZIGBEE_END_DEVICE,
}


def _ieee(value: Any) -> str | None:
    if not value:
        return None
    text = str(value).strip().lower()
    return None if text in ("", "00:00:00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff:ff:ff") else text


def _nwk(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    try:
        text = str(value).strip().lower()
        return int(text, 16) if text.startswith("0x") else int(text)
    except ValueError:
        return None


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def node_id(ieee: str) -> str:
    return f"zigbee:{ieee}"


def _kind(dev: dict[str, Any]) -> str:
    if dev.get("active_coordinator"):
        return ZIGBEE_COORDINATOR
    key = str(dev.get("device_type") or "").replace(" ", "").lower()
    return _KIND.get(key, ZIGBEE_END_DEVICE)


def attach_point(
    topo: Topology, ha_ip: str | None, radio_ip: str | None
) -> tuple[str, str]:
    """Node the Zigbee radio hangs on, and how ('usb' or 'network').

    Marks the Home Assistant host; creates a stand-in node if the host is not
    in the LAN data (e.g. FRITZ!Box not reachable).
    """
    ha_node = topo.find_by_ip(ha_ip)
    if ha_node is None:
        ha_node = "homeassistant"
        topo.add_node(
            Node(id=ha_node, name="Home Assistant", kind="home_assistant", sources=["ha"])
        )
    topo.nodes[ha_node].attrs["home_assistant"] = True
    if radio_ip and (radio_node := topo.find_by_ip(radio_ip)):
        return radio_node, "network"
    return ha_node, "network" if radio_ip else "usb"


def add_zigbee(
    topo: Topology,
    devices: list[dict[str, Any]],
    *,
    host_id: str | None = None,
    radio_link: str = "usb",
) -> None:
    """Add Zigbee nodes and links. ``host_id`` is the node the radio hangs on."""
    devs: dict[str, dict[str, Any]] = {}
    for dev in devices:
        if isinstance(dev, dict) and (ieee := _ieee(dev.get("ieee"))):
            devs[ieee] = dev
    if not devs:
        return

    kinds = {ieee: _kind(dev) for ieee, dev in devs.items()}
    coordinators = [i for i, k in kinds.items() if k == ZIGBEE_COORDINATOR]
    if not coordinators:
        topo.warnings.append("ZHA: no coordinator in device list, Zigbee skipped")
        return
    coord = coordinators[0]
    by_nwk = {n: i for i, d in devs.items() if (n := _nwk(d.get("nwk"))) is not None}

    # Neighbor tables: reported[(a, b)] = (lqi, relationship) as seen by a.
    reported: dict[tuple[str, str], tuple[int | None, str]] = {}
    for ieee, dev in devs.items():
        for nb in dev.get("neighbors") or []:
            other = _ieee(nb.get("ieee"))
            if other in devs and other != ieee:
                reported[(ieee, other)] = (_int(nb.get("lqi")), str(nb.get("relationship") or ""))

    def link_lqi(a: str, b: str) -> int | None:
        values = [v[0] for k, v in reported.items() if k in ((a, b), (b, a)) and v[0] is not None]
        return max(values) if values else None

    # --- nodes -----------------------------------------------------------
    for ieee, dev in devs.items():
        attrs: dict[str, Any] = {"ieee": ieee}
        if (nwk := _nwk(dev.get("nwk"))) is not None:
            attrs["nwk"] = f"0x{nwk:04X}"
        for key in ("manufacturer", "power_source", "area_id", "last_seen"):
            if dev.get(key) not in (None, ""):
                attrs[key] = dev[key]
        for key in ("lqi", "rssi"):
            if (val := _int(dev.get(key))) is not None:
                attrs[key] = val
        if dev.get("device_reg_id"):
            attrs["ha_device_id"] = dev["device_reg_id"]
        topo.add_node(
            Node(
                id=node_id(ieee),
                name=dev.get("user_given_name") or dev.get("name") or ieee,
                kind=kinds[ieee],
                layers=[ZIGBEE],
                online=bool(dev.get("available", True)),
                model=dev.get("model") or None,
                sources=["zha"],
                attrs=attrs,
            )
        )

    # --- routers: best path to the coordinator ----------------------------
    backbone = {i for i, k in kinds.items() if k != ZIGBEE_END_DEVICE}
    graph: dict[str, dict[str, int | None]] = {i: {} for i in backbone}
    for a, b in reported:
        if a in backbone and b in backbone:
            lqi = link_lqi(a, b)
            graph[a][b] = lqi
            graph[b][a] = lqi

    best_pred = _best_paths(graph, coord)
    # The coordinator's routing table: destination -> first hop it sends through.
    first_hop = _routes_by_dest(devs[coord], by_nwk)
    via_cache: dict[str, dict[str, str]] = {}

    def via(hop: str, target: str) -> str:
        """Parent of target on the best path that starts at hop (not via coordinator)."""
        if hop not in via_cache:
            via_cache[hop] = _best_paths(graph, hop, exclude={coord})
        return via_cache[hop].get(target, hop)

    parent: dict[str, tuple[str, str]] = {}  # child -> (parent, how)
    for ieee in sorted(backbone - {coord}):
        own_hop = _route_next_hop(devs[ieee], by_nwk)
        first = first_hop.get(ieee)
        if own_hop and own_hop != ieee and own_hop in backbone:
            parent[ieee] = (own_hop, "route")
        elif first == ieee:
            parent[ieee] = (coord, "route")
        elif first in backbone and first != coord:
            parent[ieee] = (via(first, ieee), "route")
        elif ieee in best_pred:
            parent[ieee] = (best_pred[ieee], "neighbors")
        else:
            parent[ieee] = (coord, "unknown")

    # Stale routes can form loops or dead ends: fall back to the best path.
    for _ in range(len(backbone)):
        changed = False
        for ieee in backbone - {coord}:
            seen = {ieee}
            cur = parent[ieee][0]
            while cur != coord and cur not in seen:
                seen.add(cur)
                cur = parent.get(cur, (coord, ""))[0]
            if cur != coord:
                parent[ieee] = (best_pred[ieee], "neighbors") if ieee in best_pred else (coord, "unknown")
                changed = True
        if not changed:
            break

    # --- end devices --------------------------------------------------------
    for ieee in (i for i, k in kinds.items() if k == ZIGBEE_END_DEVICE):
        first = first_hop.get(ieee)
        if first == ieee:
            parent[ieee] = (coord, "route")
            continue
        listed_by = [
            (lqi if lqi is not None else -1, a)
            for (a, b), (lqi, rel) in reported.items()
            if b == ieee and rel == "Child" and a in backbone
        ]
        if listed_by:
            # Several routers may still list it (stale tables): prefer the route's hop.
            chosen = next((a for _, a in listed_by if a == first), max(listed_by)[1])
            parent[ieee] = (chosen, "neighbors")
            continue
        own = [
            b for (a, b), (_, rel) in reported.items() if a == ieee and rel == "Parent" and b in backbone
        ]
        if own:
            parent[ieee] = (own[0], "neighbors")
        elif first in backbone:
            parent[ieee] = (first, "route")
        else:
            parent[ieee] = (coord, "unknown")

    # --- links ----------------------------------------------------------------
    if host_id and host_id in topo.nodes:
        topo.links.append(
            Link(source=host_id, target=node_id(coord), layer=USB, attrs={"radio": radio_link})
        )
    def ancestors(ieee: str) -> set[str]:
        """All routers on the tree path from the coordinator to ieee."""
        out: set[str] = set()
        cur = ieee
        while cur in parent and parent[cur][0] not in out:
            cur = parent[cur][0]
            out.add(cur)
        return out

    tree: set[frozenset[str]] = set()
    for child, (par, how) in sorted(parent.items()):
        tree.add(frozenset((child, par)))
        lqi = link_lqi(child, par)
        if lqi is None:
            lqi = _int(devs[child].get("lqi"))
        attrs: dict[str, Any] = {"parent": how}
        # Neighbor tables and the coordinator's route disagree: show it, don't guess.
        first = first_hop.get(child)
        if (
            kinds[child] == ZIGBEE_END_DEVICE
            and how == "neighbors"
            and first in backbone
            and first not in (child, coord)
            and first not in ancestors(child)
        ):
            attrs["route_conflict"] = node_id(first)
        topo.links.append(
            Link(
                source=node_id(par),
                target=node_id(child),
                layer=ZIGBEE,
                lqi=lqi,
                connected=bool(devs[child].get("available", True)),
                attrs=attrs,
            )
        )
    for a in sorted(graph):
        for b in sorted(graph[a]):
            if a < b and frozenset((a, b)) not in tree:
                topo.mesh.append(
                    Link(source=node_id(a), target=node_id(b), layer=ZIGBEE, lqi=graph[a][b])
                )


def _route_next_hop(dev: dict[str, Any], by_nwk: dict[int, str]) -> str | None:
    for route in dev.get("routes") or []:
        if _nwk(route.get("dest_nwk")) == 0 and str(route.get("route_status", "")).lower() == "active":
            hop = _nwk(route.get("next_hop"))
            return by_nwk.get(hop) if hop is not None else None
    return None


def _routes_by_dest(dev: dict[str, Any], by_nwk: dict[int, str]) -> dict[str, str]:
    """Active routes of one device: destination ieee -> next hop ieee."""
    out: dict[str, str] = {}
    for route in dev.get("routes") or []:
        if str(route.get("route_status", "")).lower() != "active":
            continue
        dest = by_nwk.get(_nwk(route.get("dest_nwk")) if route.get("dest_nwk") is not None else -1)
        hop_nwk = _nwk(route.get("next_hop"))
        hop = by_nwk.get(hop_nwk) if hop_nwk is not None else None
        if dest and hop:
            out[dest] = hop
    return out


def link_cost(lqi: int | None) -> int:
    """Zigbee PRO style link cost: min(7, round(1/p^4)) with p = LQI/255."""
    p = (lqi if lqi is not None else 100) / 255
    if p <= 0:
        return 7
    return max(1, min(7, round(1 / p**4)))


def _best_paths(
    graph: dict[str, dict[str, int | None]], root: str, exclude: set[str] | None = None
) -> dict[str, str]:
    """Dijkstra from root over the router graph; returns predecessor per node."""
    exclude = exclude or set()
    dist = {root: 0.0}
    pred: dict[str, str] = {}
    heap = [(0.0, root)]
    while heap:
        d, node = heapq.heappop(heap)
        if d > dist.get(node, float("inf")):
            continue
        for nxt, lqi in sorted(graph.get(node, {}).items()):
            if nxt in exclude:
                continue
            nd = d + link_cost(lqi)
            if nd < dist.get(nxt, float("inf")):
                dist[nxt] = nd
                pred[nxt] = node
                heapq.heappush(heap, (nd, nxt))
    return pred
