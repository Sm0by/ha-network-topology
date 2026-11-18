"""Passive (unmanaged) switches: infer them and apply network_topology.yaml.

Inference: if two or more devices report the same LAN port of the
FRITZ!Box (or of a repeater), something sits in between. We insert a
placeholder switch node there.

Configuration (all keys except id optional):

    passive_switches:
      - id: sw_buero
        name: Switch Büro
        location: Arbeitszimmer
        ports: 8
        uplink: fritzbox:LAN1        # <router|device name|mac>:LAN<n>
      - id: sw_schreibtisch
        uplink: switch:sw_buero       # cascaded behind another switch
        members: [aa:bb:cc:dd:ee:ff]  # devices placed here explicitly
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
import re
from typing import Any

from .fritz_parse import lan_port, norm_mac
from .model import INFRA_KINDS, LAN, PASSIVE_SWITCH, Link, Node, Topology

_ROUTER_ALIASES = {"fritzbox", "fritz.box", "router", "box"}
_ID_OK = re.compile(r"^[a-z0-9_]+$")


@dataclass
class SwitchConfig:
    id: str
    name: str | None = None
    location: str | None = None
    ports: int | None = None
    uplink: str | None = None
    members: list[str] = field(default_factory=list)

    @property
    def node_id(self) -> str:
        return f"switch:{self.id}"


def load_config(raw: dict[str, Any] | None) -> tuple[list[SwitchConfig], list[str]]:
    """Validate the YAML content. Returns (configs, warnings)."""
    if not raw:
        return [], []
    warnings: list[str] = []
    entries = raw.get("passive_switches") or []
    if not isinstance(entries, list):
        return [], ["passive_switches must be a list"]
    configs: list[SwitchConfig] = []
    seen: set[str] = set()
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict) or not entry.get("id"):
            warnings.append(f"passive_switches[{i}]: missing id, skipped")
            continue
        sid = str(entry["id"]).strip().lower()
        if not _ID_OK.match(sid) or sid in seen:
            warnings.append(f"passive_switches[{i}]: invalid or duplicate id '{sid}', skipped")
            continue
        seen.add(sid)
        members = []
        for m in entry.get("members") or []:
            if mac := norm_mac(str(m)):
                members.append(mac)
        ports = entry.get("ports")
        configs.append(
            SwitchConfig(
                id=sid,
                name=entry.get("name"),
                location=entry.get("location"),
                ports=ports if isinstance(ports, int) else None,
                uplink=str(entry["uplink"]).strip() if entry.get("uplink") else None,
                members=members,
            )
        )
    return configs, warnings


def _resolve_device(topo: Topology, ref: str) -> str | None:
    ref_l = ref.strip().lower()
    if ref_l in _ROUTER_ALIASES:
        return topo.router_id()
    if mac := norm_mac(ref_l):
        if f"mac:{mac}" in topo.nodes:
            return f"mac:{mac}"
    for node in topo.nodes.values():
        if node.name.lower() == ref_l:
            return node.id
    return None


def resolve_uplink(topo: Topology, uplink: str) -> tuple[str, str | None] | None:
    """'fritzbox:LAN1' -> (router_id, 'LAN1'); 'switch:x' -> ('switch:x', None)."""
    if uplink.lower().startswith("switch:"):
        return f"switch:{uplink.split(':', 1)[1].strip().lower()}", None
    ref, sep, port = uplink.rpartition(":")
    if not sep or not (port_norm := lan_port(port)):
        return None
    device = _resolve_device(topo, ref)
    return (device, port_norm) if device else None


def _switch_node(
    topo: Topology,
    node_id: str,
    parent: str,
    port: str | None,
    cfg: SwitchConfig | None,
    inferred_count: int | None,
) -> Node:
    parent_name = topo.nodes[parent].name if parent in topo.nodes else parent
    sources = []
    if inferred_count:
        sources.append("inferred")
    if cfg:
        sources.append("config")
    attrs: dict[str, Any] = {"uplink": f"{parent_name}:{port}" if port else parent_name}
    if inferred_count:
        attrs["inferred_from_devices"] = inferred_count
    if cfg and cfg.location:
        attrs["location"] = cfg.location
    if cfg and cfg.ports:
        attrs["ports"] = cfg.ports
    name = (cfg.name if cfg and cfg.name else None) or (
        f"Switch an {port}" if port else "Switch"
    )
    return topo.add_node(
        Node(id=node_id, name=name, kind=PASSIVE_SWITCH, layers=[LAN], sources=sources, attrs=attrs)
    )


def _rename_node(topo: Topology, old: str, new: str) -> None:
    if old == new or new in topo.nodes:
        return
    node = topo.nodes.pop(old)
    node.id = new
    topo.nodes[new] = node
    for link in topo.links:
        if link.source == old:
            link.source = new
        if link.target == old:
            link.target = new


def _adopt_detected(
    topo: Topology, node_id: str, parent: str, port: str, cfg: SwitchConfig | None
) -> None:
    """Apply config / a readable name to a switch the FRITZ!Box reported itself."""
    node = topo.nodes[node_id]
    parent_name = topo.nodes[parent].name if parent in topo.nodes else parent
    node.attrs["uplink"] = f"{parent_name}:{port}"
    if cfg is None:
        if node.name == "Switch":
            node.name = f"Switch an {port}"
        return
    _rename_node(topo, node_id, cfg.node_id)
    node = topo.nodes[cfg.node_id]
    if cfg.name:
        node.name = cfg.name
    if cfg.location:
        node.attrs["location"] = cfg.location
    if cfg.ports:
        node.attrs["ports"] = cfg.ports
    if "config" not in node.sources:
        node.sources.append("config")


def apply_switches(
    topo: Topology, configs: list[SwitchConfig], min_devices: int = 2
) -> None:
    """Insert inferred and configured switch nodes into the topology (in place)."""
    # 1. Group LAN links by (infrastructure device, port).
    groups: dict[tuple[str, str], list[Link]] = defaultdict(list)
    for link in topo.links:
        src = topo.nodes.get(link.source)
        if link.layer == LAN and link.port and src is not None and src.kind in INFRA_KINDS:
            groups[(link.source, link.port)].append(link)

    # 2. Map configured switches to their uplink port.
    by_port: dict[tuple[str, str], SwitchConfig] = {}
    cascaded: list[tuple[SwitchConfig, str]] = []
    for cfg in configs:
        if not cfg.uplink:
            continue
        resolved = resolve_uplink(topo, cfg.uplink)
        if resolved is None:
            topo.warnings.append(f"Switch '{cfg.id}': uplink '{cfg.uplink}' not found")
            continue
        parent, port = resolved
        if port is None:
            cascaded.append((cfg, parent))
        elif (parent, port) in by_port:
            topo.warnings.append(
                f"Switch '{cfg.id}': port {port} already used by '{by_port[(parent, port)].id}'"
            )
        else:
            by_port[(parent, port)] = cfg

    # 3. Insert switches at ports with several devices or a configured switch.
    for key in sorted(set(groups) | set(by_port)):
        parent, port = key
        links = groups.get(key, [])
        cfg = by_port.get(key)

        # The FRITZ!Box sometimes detects a switch itself: adopt it instead.
        if len(links) == 1 and topo.nodes[links[0].target].kind == PASSIVE_SWITCH:
            _adopt_detected(topo, links[0].target, parent, port, cfg)
            continue

        inferred = len(links) >= min_devices
        if not inferred and cfg is None:
            continue
        node_id = cfg.node_id if cfg else f"switch:{parent.split(':', 1)[-1].replace(':', '')}_{port.lower()}"
        _switch_node(topo, node_id, parent, port, cfg, len(links) if inferred else None)
        for link in links:
            link.source = node_id
            link.attrs["via_port"] = port
            link.port = None
        topo.links.append(Link(source=parent, target=node_id, layer=LAN, port=port))

    # 4. Cascaded switches (uplink: switch:<id>).
    for cfg, parent in cascaded:
        if parent not in topo.nodes:
            topo.warnings.append(f"Switch '{cfg.id}': parent '{parent}' does not exist")
            continue
        _switch_node(topo, cfg.node_id, parent, None, cfg, None)
        topo.links.append(Link(source=parent, target=cfg.node_id, layer=LAN))

    # 5. Configured switches without any uplink.
    for cfg in configs:
        if cfg.node_id not in topo.nodes and not cfg.uplink:
            _switch_node(topo, cfg.node_id, "?", None, cfg, None)
            topo.warnings.append(f"Switch '{cfg.id}' has no uplink and is not connected")

    # 6. Explicit members override whatever was inferred.
    for cfg in configs:
        if cfg.node_id not in topo.nodes:
            continue
        for mac in cfg.members:
            child = f"mac:{mac}"
            node = topo.nodes.get(child)
            if node is None:
                topo.warnings.append(f"Switch '{cfg.id}': member {mac} unknown")
                continue
            link = topo.parent_link(child)
            if link is None:
                topo.links.append(
                    Link(source=cfg.node_id, target=child, layer=LAN, connected=node.online)
                )
            else:
                link.source = cfg.node_id
                link.layer = LAN
                link.port = None
                link.attrs["assigned"] = "config"
            if LAN not in node.layers:
                node.layers.insert(0, LAN)

    # 7. Inferred switches that lost all members to explicit assignments.
    for node in list(topo.nodes.values()):
        if node.kind == PASSIVE_SWITCH and node.sources == ["inferred"]:
            if not any(l.source == node.id for l in topo.links):
                topo.nodes.pop(node.id)
                topo.links = [l for l in topo.links if l.target != node.id]
