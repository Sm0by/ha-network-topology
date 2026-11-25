"""Remember where each LAN/WLAN device is usually connected.

The FRITZ!Box drops the mesh link of a device soon after it goes offline,
and now and then reports a device at a wrong place. We therefore count how
often each device was seen at which parent and use the most frequent one:

- offline devices without a link are re-attached there (disconnected link),
- online devices at an implausible place (link marked ``suspect``) are moved
  there.

Both work on the FRITZ!Box view, i.e. right after parse_mesh and before
switch inference: a device on a switch port then lands behind the same
(inferred) switch again.

memory: {mac: {"places": {key: {"parent": node id, "layer": "lan"|"wlan",
                                "port": "LAN2", "band": "5",
                                "fallback": node id, "fallback_port": "LAN1",
                                "count": 42, "seen": ISO timestamp}},
               "seen": ISO timestamp of the last connection}}
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .model import CLIENT, LAN, PASSIVE_SWITCH, WLAN, Link, Topology

MAX_AGE = timedelta(days=90)
_PLACE_KEYS = ("parent", "layer", "port", "band", "fallback", "fallback_port")
# Each observation of a device elsewhere shrinks the other places' counts:
# at one observation per minute a move wins after about two hours, while a
# few minutes at a wrong place barely count.
DECAY = 0.995
COUNT_CAP = 120  # about two hours; keeps a long-standing place from winning forever


def _key(place: dict[str, Any]) -> str:
    return "|".join(str(place.get(k) or "") for k in ("parent", "layer", "port", "band"))


def _places(entry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Places of a memory entry; converts the 0.4.0 format (one place) in place."""
    if "places" not in entry:
        old = {k: entry.pop(k) for k in list(entry) if k in _PLACE_KEYS}
        entry["places"] = {_key(old): {**old, "count": 1, "seen": entry.get("seen")}} if old.get("parent") else {}
    return entry["places"]


def _plausible(topo: Topology, place: dict[str, Any]) -> bool:
    """A device cannot hang on the port its parent uses as uplink."""
    parent = topo.nodes.get(place.get("parent"))
    return not (parent and place.get("port") and parent.attrs.get("uplink_port") == place["port"])


def remember_links(topo: Topology, memory: dict[str, dict[str, Any]], now: datetime) -> bool:
    """Count the current place of every connected client. Returns True if a new place appeared."""
    changed = False
    seen = now.isoformat()
    for link in topo.links:
        if not link.connected or link.layer not in (LAN, WLAN) or link.attrs.get("suspect"):
            continue
        node = topo.nodes.get(link.target)
        if node is None or node.kind != CLIENT or not node.mac or not node.online:
            continue
        place: dict[str, Any] = {"parent": link.source, "layer": link.layer}
        if link.port:
            place["port"] = link.port
        if link.band:
            place["band"] = link.band
        # A switch the FRITZ!Box detected itself may vanish once its devices are off.
        parent = topo.nodes.get(link.source)
        if parent is not None and parent.kind == PASSIVE_SWITCH:
            if (up := topo.parent_link(parent.id)) is not None:
                place["fallback"] = up.source
                if up.port:
                    place["fallback_port"] = up.port
        entry = memory.setdefault(node.mac, {})
        places = _places(entry)
        key = _key(place)
        if key not in places:
            changed = True
            places[key] = {**place, "count": 0}
        else:
            places[key].update(place)
        for other_key, other in places.items():
            if other_key != key:
                other["count"] = round(other.get("count", 0) * DECAY, 3)
        places[key]["count"] = min(COUNT_CAP, places[key]["count"] + 1)
        places[key]["seen"] = seen
        entry["seen"] = seen
    return changed


def best_place(topo: Topology, entry: dict[str, Any] | None) -> dict[str, Any] | None:
    """The most frequent plausible place whose parent (or fallback) still exists."""
    if not entry:
        return None
    options = []
    for place in _places(entry).values():
        parent, port = place.get("parent"), place.get("port")
        if parent not in topo.nodes and place.get("fallback") in topo.nodes:
            parent, port = place["fallback"], place.get("fallback_port")
        if parent not in topo.nodes:
            continue
        resolved = {**place, "parent": parent, "port": port}
        if _plausible(topo, resolved):
            options.append(resolved)
    if not options:
        return None
    return max(options, key=lambda p: (p.get("count", 0), str(p.get("seen") or "")))


def restore_links(topo: Topology, memory: dict[str, dict[str, Any]]) -> int:
    """Attach offline clients without a link to their usual place; move suspect links there."""
    linked = {l.target: l for l in topo.links}
    changed = 0
    for node in topo.nodes.values():
        if node.kind != CLIENT or not node.mac:
            continue
        link = linked.get(node.id)
        if link is not None and not link.attrs.get("suspect"):
            continue
        if link is None and node.online:
            continue
        place = best_place(topo, memory.get(node.mac))
        if place is None or place["parent"] == node.id:
            continue
        layer = place.get("layer", LAN)
        if link is None:
            link = Link(source=place["parent"], target=node.id, layer=layer, connected=False)
            link.attrs.update(remembered=True, last_connected=memory[node.mac].get("seen"))
            topo.links.append(link)
        else:
            link.attrs["reported_parent"] = topo.nodes[link.source].name
            if link.port:
                link.attrs["reported_parent"] += f":{link.port}"
            link.attrs["placed_by"] = "history"
            link.source, link.layer = place["parent"], layer
        link.port = place.get("port")
        link.band = place.get("band") if layer == WLAN else None
        if layer not in node.layers:
            node.layers.insert(0, layer)
        changed += 1
    return changed


def prune(memory: dict[str, dict[str, Any]], now: datetime, max_age: timedelta = MAX_AGE) -> bool:
    """Forget places (and devices) not seen for max_age. Returns True if anything was removed."""
    removed = False

    def stale(value: Any) -> bool:
        try:
            seen = datetime.fromisoformat(value or "")
        except (TypeError, ValueError):
            return True
        if seen.tzinfo is None and now.tzinfo is not None:
            seen = seen.replace(tzinfo=now.tzinfo)
        return now - seen > max_age

    for mac in list(memory):
        places = _places(memory[mac])
        for key in [k for k, p in places.items() if stale(p.get("seen"))]:
            places.pop(key)
            removed = True
        if not places:
            memory.pop(mac)
            removed = True
    return removed
