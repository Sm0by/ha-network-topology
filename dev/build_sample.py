#!/usr/bin/env python3
"""Build topology JSON for the card harness.

    python dev/build_sample.py            # dev/sample_topology.json from test fixtures
    python dev/build_sample.py --real     # tools/out/topology_full.json from probe exports
                                          # (mesh_raw.json, zha_devices.json; stays out of git)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "custom_components" / "network_topology"))

from topology.ble_parse import add_bluetooth  # noqa: E402
from topology.fritz_parse import parse_mesh  # noqa: E402
from topology.switches import apply_switches, load_config  # noqa: E402
from topology.zha_parse import add_zigbee, attach_point  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
OUT = ROOT / "tools" / "out"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--real", action="store_true")
    ap.add_argument("--ha-ip", default="192.168.178.3")
    args = ap.parse_args()

    if args.real:
        mesh = load(OUT / "mesh_raw.json")
        zha = load(OUT / "zha_devices.json") if (OUT / "zha_devices.json").exists() else []
        ha_ip, target = args.ha_ip, OUT / "topology_full.json"
        scanners, ble = [], []
    else:
        mesh = load(FIX / "mesh_sample.json")
        zha = load(FIX / "zha_sample.json")
        ha_ip, target = "192.168.178.20", ROOT / "dev" / "sample_topology.json"
        proxy_bt = "24:0A:C4:9B:11:04"
        scanners = [
            {"source": "D8:3A:DD:41:7C:03", "name": "hci0", "local": True, "connectable": True},
            {"source": proxy_bt, "name": "bt-proxy-kueche", "network_mac": "24:0a:c4:9b:11:02", "connectable": True},
        ]
        ble = [
            {"address": "A4:C1:38:2D:90:5B", "name": "Thermometer Küche", "ha_device_id": "demo",
             "heard": [{"source": proxy_bt, "rssi": -64}, {"source": "D8:3A:DD:41:7C:03", "rssi": -91}]},
            {"address": "C4:7C:8D:6A:3F:21", "name": "Pflanzensensor", "heard": [{"source": "D8:3A:DD:41:7C:03", "rssi": -84}]},
            {"address": "B0:D2:78:11:4C:E7", "name": "Zahnbürste", "heard": [], "last_source": proxy_bt},
        ]

    topo = parse_mesh(mesh["mesh"], mesh.get("hosts", []))
    configs, warnings = load_config(None)
    apply_switches(topo, configs)
    radio_node, radio = attach_point(topo, ha_ip, None)
    host = next((n.id for n in topo.nodes.values() if n.attrs.get("home_assistant")), None)
    if zha:
        add_zigbee(topo, zha, host_id=radio_node, radio_link=radio)
    add_bluetooth(topo, scanners, ble, host_id=host)
    data = topo.to_dict(generated="2026-11-18T14:30:00+01:00")
    data["zigbee_rescan"] = {"running": False}
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{target}: {len(data['nodes'])} nodes, {len(data['links'])} links, {len(data['mesh'])} mesh")


if __name__ == "__main__":
    main()
