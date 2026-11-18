"""Decide when and which Zigbee routers to rescan.

A rescan re-reads neighbor and routing tables of a few routers (via zigpy's
targeted topology scan). It is triggered when the tree shows contradictions
(``route_conflict``) and is throttled so it never floods the network:

* at most one automatic rescan per ``min_interval``
* each device at most once per ``device_cooldown``
* a manual rescan (button) ignores both limits
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math

from .model import ZIGBEE, ZIGBEE_COORDINATOR, ZIGBEE_END_DEVICE, Topology

_PREFIX = "zigbee:"


def _ieee(node_id: str) -> str | None:
    return node_id[len(_PREFIX):] if node_id.startswith(_PREFIX) else None


def conflict_candidates(topo: Topology) -> list[str]:
    """Routers involved in route conflicts, plus the coordinator."""
    out: set[str] = set()
    for link in topo.links:
        if link.layer != ZIGBEE or not (conflict := link.attrs.get("route_conflict")):
            continue
        for node in (link.source, conflict):
            if ieee := _ieee(node):
                out.add(ieee)
    if out:
        out.update(
            ieee
            for n in topo.nodes.values()
            if n.kind == ZIGBEE_COORDINATOR and (ieee := _ieee(n.id))
        )
    return sorted(out)


def all_routers(topo: Topology) -> list[str]:
    """Every scannable Zigbee device (coordinator and routers)."""
    return sorted(
        ieee
        for n in topo.nodes.values()
        if ZIGBEE in n.layers and n.kind != ZIGBEE_END_DEVICE and n.online and (ieee := _ieee(n.id))
    )


@dataclass
class RescanPlanner:
    """Throttle state. Times are monotonic seconds."""

    min_interval: float = 3600
    device_cooldown: float = 6 * 3600
    last_run: float | None = None
    device_last: dict[str, float] = field(default_factory=dict)

    def plan(self, candidates: list[str], now: float, *, force: bool = False) -> list[str]:
        """Devices to scan now; empty if nothing is due."""
        if not candidates:
            return []
        if force:
            return sorted(candidates)
        if self.last_run is not None and now - self.last_run < self.min_interval:
            return []
        due = [
            c for c in candidates if now - self.device_last.get(c, -math.inf) >= self.device_cooldown
        ]
        return sorted(due)

    def mark(self, devices: list[str], now: float) -> None:
        self.last_run = now
        for dev in devices:
            self.device_last[dev] = now
