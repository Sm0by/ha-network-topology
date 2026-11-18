"""Graph model shared by all collectors and sent to the Lovelace card."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# Node kinds
INTERNET = "internet"
ROUTER = "router"
REPEATER = "repeater"
CLIENT = "client"
PASSIVE_SWITCH = "passive_switch"

INFRA_KINDS = {ROUTER, REPEATER}

ZIGBEE_COORDINATOR = "zigbee_coordinator"
ZIGBEE_ROUTER = "zigbee_router"
ZIGBEE_END_DEVICE = "zigbee_end_device"

# Link layers
WAN = "wan"
LAN = "lan"
WLAN = "wlan"
ZIGBEE = "zigbee"
USB = "usb"  # radio attached to the Home Assistant host


def _compact(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None and v != {} and v != []}


@dataclass
class Node:
    """A device or a piece of infrastructure."""

    id: str
    name: str
    kind: str
    layers: list[str] = field(default_factory=list)
    mac: str | None = None
    ip: str | None = None
    online: bool = True
    model: str | None = None
    sources: list[str] = field(default_factory=list)
    attrs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _compact(asdict(self))


@dataclass
class Link:
    """A connection; source is the upstream side."""

    source: str
    target: str
    layer: str
    port: str | None = None
    band: str | None = None
    rssi: int | None = None
    rate_kbit: int | None = None
    lqi: int | None = None
    connected: bool = True
    attrs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _compact(asdict(self))


@dataclass
class Topology:
    """The merged graph."""

    nodes: dict[str, Node] = field(default_factory=dict)
    links: list[Link] = field(default_factory=list)  # tree: one upstream link per node
    mesh: list[Link] = field(default_factory=list)  # extra radio links outside the tree
    warnings: list[str] = field(default_factory=list)

    def add_node(self, node: Node) -> Node:
        """Add a node or merge it into an existing one with the same id."""
        existing = self.nodes.get(node.id)
        if existing is None:
            self.nodes[node.id] = node
            return node
        for attr in ("mac", "ip", "model"):
            if getattr(existing, attr) is None:
                setattr(existing, attr, getattr(node, attr))
        for layer in node.layers:
            if layer not in existing.layers:
                existing.layers.append(layer)
        for src in node.sources:
            if src not in existing.sources:
                existing.sources.append(src)
        existing.attrs = {**node.attrs, **existing.attrs}
        return existing

    def parent_link(self, node_id: str) -> Link | None:
        """Return the upstream link of a node."""
        return next((l for l in self.links if l.target == node_id), None)

    def find_by_ip(self, ip: str | None) -> str | None:
        if not ip:
            return None
        return next((n.id for n in self.nodes.values() if n.ip == ip), None)

    def router_id(self) -> str | None:
        return next((n.id for n in self.nodes.values() if n.kind == ROUTER), None)

    def to_dict(self, generated: str | None = None) -> dict[str, Any]:
        linked = {l.target for l in self.links}
        unlinked = sorted(
            n.id for n in self.nodes.values() if n.id not in linked and n.kind != INTERNET
        )
        return {
            "generated": generated,
            "nodes": [n.to_dict() for n in self.nodes.values()],
            "links": [l.to_dict() for l in self.links],
            "mesh": [l.to_dict() for l in self.mesh],
            "unlinked": unlinked,
            "warnings": list(self.warnings),
        }
