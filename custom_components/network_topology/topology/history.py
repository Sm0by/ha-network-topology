"""Remember the last LAN/WLAN connection of each device.

The FRITZ!Box drops the mesh link of a device soon after it goes offline;
the device is then only left in the host list. To keep it in the tree, we
remember where it was connected and re-attach it as a disconnected link.

Both functions work on the FRITZ!Box view, i.e. right after parse_mesh and
before switch inference: a remembered device on a switch port then lands
behind the same (inferred) switch again.

memory: {mac: {"parent": node id, "layer": "lan"|"wlan", "port": "LAN2",
               "band": "5", "seen": ISO timestamp,
               "fallback": node id, "fallback_port": "LAN1"}}
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .model import CLIENT, LAN, PASSIVE_SWITCH, WLAN, Link, Topology

MAX_AGE = timedelta(days=90)


def remember_links(topo: Topology, memory: dict[str, dict[str, Any]], now: datetime) -> bool:
    """Store the current connection of every connected client. Returns True if changed."""
    changed = False
    seen = now.isoformat()
    for link in topo.links:
        if not link.connected or link.layer not in (LAN, WLAN):
            continue
        node = topo.nodes.get(link.target)
        if node is None or node.kind != CLIENT or not node.mac or not node.online:
            continue
        entry: dict[str, Any] = {"parent": link.source, "layer": link.layer}
        if link.port:
            entry["port"] = link.port
        if link.band:
            entry["band"] = link.band
        # A switch the FRITZ!Box detected itself may vanish once its devices are off.
        parent = topo.nodes.get(link.source)
        if parent is not None and parent.kind == PASSIVE_SWITCH:
            if (up := topo.parent_link(parent.id)) is not None:
                entry["fallback"] = up.source
                if up.port:
                    entry["fallback_port"] = up.port
        old = memory.get(node.mac)
        if old is None or {k: v for k, v in old.items() if k != "seen"} != entry:
            changed = True
        entry["seen"] = seen
        memory[node.mac] = entry
    return changed


def restore_links(topo: Topology, memory: dict[str, dict[str, Any]]) -> int:
    """Attach offline clients without a link to their last known parent."""
    linked = {l.target for l in topo.links}
    restored = 0
    for node in topo.nodes.values():
        if node.kind != CLIENT or node.online or node.id in linked or not node.mac:
            continue
        entry = memory.get(node.mac)
        if not entry:
            continue
        parent, port = entry.get("parent"), entry.get("port")
        if parent not in topo.nodes and entry.get("fallback") in topo.nodes:
            parent, port = entry["fallback"], entry.get("fallback_port")
        if parent not in topo.nodes or parent == node.id:
            continue
        layer = entry.get("layer", LAN)
        topo.links.append(
            Link(
                source=parent,
                target=node.id,
                layer=layer,
                port=port,
                band=entry.get("band") if layer == WLAN else None,
                connected=False,
                attrs={"remembered": True, "last_connected": entry.get("seen")},
            )
        )
        if layer not in node.layers:
            node.layers.insert(0, layer)
        restored += 1
    return restored


def prune(memory: dict[str, dict[str, Any]], now: datetime, max_age: timedelta = MAX_AGE) -> bool:
    """Forget devices not seen for max_age. Returns True if anything was removed."""
    stale = []
    for mac, entry in memory.items():
        try:
            seen = datetime.fromisoformat(entry.get("seen", ""))
        except (TypeError, ValueError):
            stale.append(mac)
            continue
        if seen.tzinfo is None and now.tzinfo is not None:
            seen = seen.replace(tzinfo=now.tzinfo)
        if now - seen > max_age:
            stale.append(mac)
    for mac in stale:
        memory.pop(mac)
    return bool(stale)
