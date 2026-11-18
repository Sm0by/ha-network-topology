"""Tests for the Zigbee (ZHA) part of the topology."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "custom_components" / "network_topology"))

from topology.fritz_parse import parse_mesh  # noqa: E402
from topology.model import Topology  # noqa: E402
from topology.zha_parse import add_zigbee, attach_point  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
ZHA = json.loads((FIX / "zha_sample.json").read_text(encoding="utf-8"))
MESH = json.loads((FIX / "mesh_sample.json").read_text(encoding="utf-8"))

C = "zigbee:00:12:4b:00:00:00:00:01"
R1 = "zigbee:00:17:88:00:00:00:00:11"
R2 = "zigbee:00:17:88:00:00:00:00:22"
R3 = "zigbee:00:17:88:00:00:00:00:33"
E1, E2, E3, E4 = (f"zigbee:00:15:8d:00:00:00:00:e{i}" for i in range(1, 5))
HA_LAN = "mac:d8:3a:dd:41:7c:02"


def build(devices=None, *, ha_ip="192.168.178.20", radio_ip=None, with_lan=True):
    if with_lan:
        data = copy.deepcopy(MESH)
        topo = parse_mesh(data["mesh"], data["hosts"])
    else:
        topo = Topology()
    host, radio = attach_point(topo, ha_ip, radio_ip)
    add_zigbee(topo, copy.deepcopy(devices if devices is not None else ZHA), host_id=host, radio_link=radio)
    return topo


def up(topo, node):
    link = topo.parent_link(node)
    return (link.source, link.attrs.get("parent"), link.lqi) if link else None


class ZigbeeTreeTests(unittest.TestCase):
    def test_kinds_names_attrs(self):
        topo = build()
        self.assertEqual(topo.nodes[C].kind, "zigbee_coordinator")
        self.assertEqual(topo.nodes[R1].kind, "zigbee_router")
        self.assertEqual(topo.nodes[E1].kind, "zigbee_end_device")
        r1 = topo.nodes[R1]
        self.assertEqual(r1.name, "Steckdose Flur", "user-given name wins")
        self.assertEqual((r1.attrs["nwk"], r1.attrs["ha_device_id"], r1.attrs["area_id"]), ("0x1111", "dev-r1", "flur"))
        self.assertFalse(topo.nodes[E3].online)

    def test_coordinator_hangs_on_ha_host(self):
        topo = build()
        link = topo.parent_link(C)
        self.assertEqual((link.source, link.layer, link.attrs["radio"]), (HA_LAN, "usb", "usb"))
        self.assertTrue(topo.nodes[HA_LAN].attrs["home_assistant"])

    def test_router_parents(self):
        topo = build()
        self.assertEqual(up(topo, R1), (C, "route", 230))
        self.assertEqual(up(topo, R2), (R1, "route", 170))
        # No route: best path. Direct to C (LQI 60) beats R2 -> R1 -> C.
        self.assertEqual(up(topo, R3), (C, "neighbors", 60))

    def test_end_device_parents(self):
        topo = build()
        self.assertEqual(up(topo, E1), (R1, "neighbors", 180))
        self.assertEqual(up(topo, E2), (R2, "neighbors", 120), "own Parent entry")
        self.assertEqual(up(topo, E3), (C, "unknown", 80), "fallback, LQI from the device")
        self.assertEqual(up(topo, E4), (C, "neighbors", 150))
        self.assertFalse(topo.parent_link(E3).connected)

    def test_mesh_links_outside_tree(self):
        topo = build()
        pairs = {frozenset((l.source, l.target)) for l in topo.mesh}
        self.assertEqual(pairs, {frozenset((C, R2)), frozenset((R2, R3))})
        self.assertNotIn("aa:aa", json.dumps(topo.to_dict()), "devices unknown to ZHA are ignored")

    def test_route_loop_is_repaired(self):
        devices = copy.deepcopy(ZHA)
        for dev in devices:
            if dev["nwk"] == "0x2222":
                dev["routes"] = [{"dest_nwk": "0x0000", "next_hop": "0x3333", "route_status": "Active"}]
            if dev["nwk"] == "0x3333":
                dev["routes"] = [{"dest_nwk": "0x0000", "next_hop": "0x2222", "route_status": "Active"}]
        topo = build(devices)
        for node in (R2, R3):
            seen, cur = set(), node
            while cur != C:
                self.assertNotIn(cur, seen, "loop in Zigbee tree")
                seen.add(cur)
                cur = topo.parent_link(cur).source

    def test_inactive_route_ignored(self):
        devices = copy.deepcopy(ZHA)
        for dev in devices:
            if dev["nwk"] == "0x2222":
                dev["routes"][1]["route_status"] = "Inactive"
        topo = build(devices)
        self.assertEqual(up(topo, R2)[1], "neighbors")

    def test_every_zigbee_node_has_one_parent(self):
        topo = build()
        targets = [l.target for l in topo.links]
        self.assertEqual(len(targets), len(set(targets)))
        for n in topo.nodes.values():
            if n.kind.startswith("zigbee"):
                self.assertIsNotNone(topo.parent_link(n.id), n.name)


class AttachPointTests(unittest.TestCase):
    def test_stand_in_host_without_lan_data(self):
        topo = build(with_lan=False)
        self.assertEqual(up(topo, C)[0], "homeassistant")
        self.assertEqual(topo.nodes["homeassistant"].kind, "home_assistant")

    def test_network_coordinator(self):
        topo = build(radio_ip="192.168.178.31")  # the Desktop-PC IP in the sample
        link = topo.parent_link(C)
        self.assertEqual((link.source, link.attrs["radio"]), ("mac:3c:22:fb:10:4e:a1", "network"))

    def test_no_coordinator_warns(self):
        devices = [d for d in ZHA if d.get("device_type") != "Coordinator"]
        topo = build(devices)
        self.assertTrue(any("no coordinator" in w for w in topo.warnings))
        self.assertFalse(any(n.kind.startswith("zigbee") for n in topo.nodes.values()))


if __name__ == "__main__":
    unittest.main()
