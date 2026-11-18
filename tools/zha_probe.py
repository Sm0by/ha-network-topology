#!/usr/bin/env python3
"""Probe: zeigt den Zigbee-Baum, den die Integration aus ZHA-Daten baut.

ZHA-Daten exportieren (Browser, in Home Assistant angemeldet, Entwicklerkonsole F12):

    copy(JSON.stringify(await document.querySelector("home-assistant").hass.callWS({type: "zha/devices"})))

Den Inhalt der Zwischenablage als tools/out/zha_devices.json speichern, dann:

    python tools/zha_probe.py tools/out/zha_devices.json
    python tools/zha_probe.py tools/out/zha_devices.json --mesh tools/out/mesh_raw.json --ha-ip 192.168.178.3
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "custom_components" / "network_topology"))

from topology.fritz_parse import parse_mesh  # noqa: E402
from topology.model import ZIGBEE, Topology  # noqa: E402
from topology.switches import apply_switches  # noqa: E402
from topology.zha_parse import add_zigbee, attach_point  # noqa: E402

ROLE = {"zigbee_coordinator": "Koordinator", "zigbee_router": "Router", "zigbee_end_device": "End Device"}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("zha_file", type=Path)
    ap.add_argument("--mesh", type=Path, help="mesh_raw.json vom fritz_mesh_probe")
    ap.add_argument("--ha-ip", help="IP von Home Assistant, um den Koordinator anzuhängen")
    ap.add_argument("--radio-ip", help="IP eines Netzwerk-Koordinators (socket://)")
    ap.add_argument("--weak-lqi", type=int, default=100)
    args = ap.parse_args()

    devices = json.loads(args.zha_file.read_text(encoding="utf-8"))
    if args.mesh:
        raw = json.loads(args.mesh.read_text(encoding="utf-8"))
        topo = parse_mesh(raw["mesh"], raw.get("hosts", []))
        apply_switches(topo, [])
    else:
        topo = Topology()
    host, radio = attach_point(topo, args.ha_ip, args.radio_ip)
    add_zigbee(topo, devices, host_id=host, radio_link=radio)

    zb = [n for n in topo.nodes.values() if ZIGBEE in n.layers]
    children: dict[str, list] = {}
    for link in topo.links:
        if link.layer == ZIGBEE:
            children.setdefault(link.source, []).append(link)
    coord = next(n for n in zb if n.kind == "zigbee_coordinator")
    up = topo.parent_link(coord.id)
    print(f"Koordinator: {coord.name} ({coord.model or '?'}), angebunden an {topo.nodes[up.source].name if up else '?'} per {radio}")
    counts = {k: sum(n.kind == k for n in zb) for k in ROLE}
    print(f"{len(zb)} Geräte: {counts['zigbee_router']} Router, {counts['zigbee_end_device']} End Devices\n")

    weak, unknown, offline = [], [], []

    def walk(node_id: str, depth: int) -> None:
        for link in sorted(children.get(node_id, []), key=lambda l: (topo.nodes[l.target].kind != "zigbee_router", topo.nodes[l.target].name.lower())):
            n = topo.nodes[link.target]
            flags = []
            if link.lqi is not None and link.lqi < args.weak_lqi:
                flags.append("schwach")
                weak.append(n.name)
            if link.attrs.get("parent") == "unknown":
                flags.append("Parent unbekannt")
                unknown.append(n.name)
            if not n.online:
                flags.append("offline")
                offline.append(n.name)
            how = {"route": "Route", "neighbors": "Nachbarn", "unknown": "?"}[link.attrs.get("parent", "unknown")]
            lqi = f"LQI {link.lqi:>3}" if link.lqi is not None else "LQI   ?"
            print(f"{'   ' * depth}├─ {n.name:<34} {ROLE[n.kind]:<11} {lqi}  [{how}]{'  ! ' + ', '.join(flags) if flags else ''}")
            walk(n.id, depth + 1)

    walk(coord.id, 0)
    print(f"\nWeitere Mesh-Verbindungen zwischen Routern (nicht im Baum): {len(topo.mesh)}")
    print(f"Schwaches Signal (< {args.weak_lqi}): {len(weak)} · Parent unbekannt: {len(unknown)} · offline: {len(offline)}")
    for w in topo.warnings:
        print(f"  ! {w}")


if __name__ == "__main__":
    main()
