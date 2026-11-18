#!/usr/bin/env python3
"""Probe: liest die Mesh-Topologie der FRITZ!Box und zeigt die Zuordnung.

Beantwortet vor allem eine Frage: Liefert die Box pro LAN-Gerät den Port?
Nur dann lassen sich die passiven Switches automatisch ableiten.

Aufruf (Passwort wird abgefragt, wenn FRITZ_PASSWORD nicht gesetzt ist):

    pip install fritzconnection pyyaml
    python tools/fritz_mesh_probe.py --user <benutzer>
    python tools/fritz_mesh_probe.py --from-file tools/out/mesh_raw.json

Die Rohdaten landen in tools/out/ (per .gitignore ausgeschlossen, enthalten MACs).
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import getpass
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "custom_components" / "network_topology"))

from topology.fritz_parse import parse_mesh  # noqa: E402
from topology.model import LAN, WLAN, Topology  # noqa: E402
from topology.switches import apply_switches, load_config  # noqa: E402

OUT = Path(__file__).resolve().parent / "out"


def fetch(address: str, user: str, password: str, use_tls: bool):
    try:
        from fritzconnection import FritzConnection
        from fritzconnection.lib.fritzhosts import FritzHosts
    except ImportError:
        sys.exit("fritzconnection fehlt: pip install fritzconnection")
    fc = FritzConnection(address=address, user=user, password=password, use_tls=use_tls, timeout=15)
    print(f"Verbunden: {fc.modelname} · FRITZ!OS {fc.system_version}")
    hosts = FritzHosts(fc=fc)
    print("Lese Mesh-Topologie …")
    mesh = hosts.get_mesh_topology()
    print("Lese Host-Liste …")
    return mesh, hosts.get_hosts_info()


def name(topo: Topology, node_id: str) -> str:
    n = topo.nodes.get(node_id)
    return n.name if n else node_id


def report_before(topo: Topology) -> None:
    infra = [n for n in topo.nodes.values() if n.kind in ("router", "repeater")]
    print("\n== Mesh-Geräte ==")
    for n in infra:
        up = topo.parent_link(n.id)
        how = ""
        if up and up.source != "internet":
            how = f"  über {up.layer.upper()} {up.band + ' GHz' if up.band else up.port or ''} von {name(topo, up.source)}"
        print(f"  {n.name} ({n.kind}){how}")

    lan = defaultdict(list)
    no_port = []
    wlan = defaultdict(list)
    for l in topo.links:
        if l.layer == LAN and l.source != "internet":
            (lan[(l.source, l.port)] if l.port else no_port).append(l)
        elif l.layer == WLAN:
            wlan[(l.source, l.band)].append(l)

    print("\n== LAN-Ports ==")
    if not lan:
        print("  (keine Port-Angaben gefunden)")
    for (src, port), links in sorted(lan.items()):
        hint = "  -> mehrere Geräte: Switch vermutet" if len(links) > 1 else ""
        print(f"  {name(topo, src)} {port}: {len(links)} Gerät(e){hint}")
        for l in links:
            t = topo.nodes[l.target]
            state = "" if l.connected else "  [offline, letzter Stand]"
            print(f"      - {t.name:<28} {t.ip or '-':<16} {t.mac or ''}{state}")
    if no_port:
        print(f"\n  LAN-Verbindungen ohne Port-Angabe: {len(no_port)}")
        for l in no_port:
            print(f"      - {name(topo, l.target)} an {name(topo, l.source)} ({l.attrs.get('interface', '?')})")

    print("\n== WLAN ==")
    for (src, band), links in sorted(wlan.items(), key=lambda kv: (kv[0][0], kv[0][1] or "")):
        print(f"  {name(topo, src)} {band or '?'} GHz: {len(links)} Gerät(e)")
        for l in links:
            t = topo.nodes[l.target]
            rssi = f"{l.rssi} dBm" if l.rssi is not None else "RSSI ?"
            print(f"      - {t.name:<28} {rssi}")

    unlinked = topo.to_dict()["unlinked"]
    print(f"\n== Ohne Verbindung in den Mesh-Daten: {len(unlinked)} Gerät(e) ==")
    for nid in unlinked[:25]:
        n = topo.nodes[nid]
        print(f"      - {n.name:<28} {'online' if n.online else 'offline'}")
    if len(unlinked) > 25:
        print(f"      … und {len(unlinked) - 25} weitere")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--address", default=os.environ.get("FRITZ_ADDRESS", "192.168.178.1"))
    ap.add_argument("--user", default=os.environ.get("FRITZ_USER"))
    ap.add_argument("--tls", action="store_true")
    ap.add_argument("--from-file", type=Path, help="gespeicherte Rohdaten statt Live-Abfrage")
    ap.add_argument("--config", type=Path, help="network_topology.yaml zum Testen")
    args = ap.parse_args()

    if args.from_file:
        raw = json.loads(args.from_file.read_text(encoding="utf-8"))
        mesh, hosts = raw["mesh"], raw.get("hosts", [])
    else:
        if not args.user:
            sys.exit("--user fehlt (oder FRITZ_USER setzen)")
        password = os.environ.get("FRITZ_PASSWORD") or getpass.getpass("FRITZ!Box-Passwort: ")
        mesh, hosts = fetch(args.address, args.user, password, args.tls)
        OUT.mkdir(exist_ok=True)
        raw_file = OUT / "mesh_raw.json"
        raw_file.write_text(json.dumps({"mesh": mesh, "hosts": hosts}, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Rohdaten gespeichert: {raw_file}")

    topo = parse_mesh(mesh, hosts)
    print(f"\nSchema-Version: {mesh.get('schema_version', '?')} · {len(mesh.get('nodes', []))} Mesh-Knoten · {len(hosts)} Hosts")
    report_before(topo)

    raw_config = None
    if args.config:
        import yaml

        raw_config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    configs, warnings = load_config(raw_config)
    topo.warnings.extend(warnings)
    apply_switches(topo, configs)

    switches = [n for n in topo.nodes.values() if n.kind == "passive_switch"]
    print(f"\n== Ergebnis: {len(switches)} passive(r) Switch(es) ==")
    for s in switches:
        members = [name(topo, l.target) for l in topo.links if l.source == s.id]
        print(f"  {s.name} [{', '.join(s.sources)}] an {s.attrs.get('uplink')}: {', '.join(members)}")
    if topo.warnings:
        print("\n== Hinweise ==")
        for w in topo.warnings:
            print(f"  ! {w}")

    OUT.mkdir(exist_ok=True)
    out_file = OUT / "topology.json"
    out_file.write_text(json.dumps(topo.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nTopologie für die Karte: {out_file}")


if __name__ == "__main__":
    main()
