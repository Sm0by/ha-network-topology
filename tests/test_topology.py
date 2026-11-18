"""Tests for the pure topology logic (no Home Assistant needed).

Run:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "custom_components" / "network_topology"))

from topology.fritz_parse import lan_port, parse_mesh, wlan_band  # noqa: E402
from topology.model import PASSIVE_SWITCH  # noqa: E402
from topology.switches import apply_switches, load_config, resolve_uplink  # noqa: E402

SAMPLE = json.loads((ROOT / "tests" / "fixtures" / "mesh_sample.json").read_text(encoding="utf-8"))

BOX = "mac:c8:0e:14:00:00:01"
REP = "mac:c8:0e:14:00:00:02"
PC = "mac:3c:22:fb:10:4e:a1"
NAS = "mac:00:11:32:af:09:5e"
HA = "mac:d8:3a:dd:41:7c:02"
TV = "mac:a8:23:fe:6c:12:90"
CONSOLE = "mac:70:9e:29:44:b1:0c"
PRINTER = "mac:00:1b:a9:77:01:02"
PROXY = "mac:24:0a:c4:9b:11:02"


def build():
    data = copy.deepcopy(SAMPLE)
    return parse_mesh(data["mesh"], data["hosts"])


def parent(topo, node_id):
    link = topo.parent_link(node_id)
    return link.source if link else None


class HelperTests(unittest.TestCase):
    def test_lan_port(self):
        self.assertEqual(lan_port("LAN:1"), "LAN1")
        self.assertEqual(lan_port("lan 4"), "LAN4")
        self.assertIsNone(lan_port("AP:5G:0"))
        self.assertIsNone(lan_port(None))

    def test_wlan_band(self):
        self.assertEqual(wlan_band("AP:5G:0"), "5")
        self.assertEqual(wlan_band("UPLINK:2G:0"), "2.4")
        self.assertIsNone(wlan_band("LAN:1"))


class ParseMeshTests(unittest.TestCase):
    def test_roles_and_internet(self):
        topo = build()
        self.assertEqual(topo.nodes[BOX].kind, "router")
        self.assertEqual(topo.nodes[REP].kind, "repeater")
        self.assertEqual(parent(topo, BOX), "internet")

    def test_links_are_deduplicated_and_oriented(self):
        topo = build()
        targets = [l.target for l in topo.links]
        self.assertEqual(len(targets), len(set(targets)), "each node has one parent link")
        # Link written as client->box in the raw data must still point box->client.
        self.assertEqual(parent(topo, PRINTER), BOX)
        # Laptop link lists the laptop as node_1; repeater must still be the parent.
        self.assertEqual(parent(topo, "mac:5a:11:22:33:44:57"), REP)

    def test_lan_port_and_wlan_details(self):
        topo = build()
        pc = topo.parent_link(PC)
        self.assertEqual((pc.layer, pc.port, pc.rate_kbit), ("lan", "LAN1", 1000000))
        rep = topo.parent_link(REP)
        self.assertEqual((rep.layer, rep.band, rep.rssi), ("wlan", "5", -55))
        proxy = topo.parent_link(PROXY)
        self.assertEqual((proxy.source, proxy.band, proxy.rssi), (REP, "2.4", -58))

    def test_host_enrichment_and_offline(self):
        topo = build()
        self.assertEqual(topo.nodes[HA].ip, "192.168.178.20")
        self.assertFalse(topo.nodes[CONSOLE].online)
        # Offline device keeps its last known port.
        self.assertEqual(topo.parent_link(CONSOLE).port, "LAN2")
        # Host only known from the host list appears unlinked and offline.
        old = topo.nodes["mac:5a:11:22:33:44:99"]
        self.assertFalse(old.online)
        self.assertIn(old.id, topo.to_dict()["unlinked"])

    def test_warning_without_ports(self):
        data = copy.deepcopy(SAMPLE)
        for node in data["mesh"]["nodes"]:
            for iface in node["node_interfaces"]:
                if iface.get("name", "").startswith("LAN"):
                    iface["name"] = "eth"
        topo = parse_mesh(data["mesh"], data["hosts"])
        self.assertTrue(any("No LAN port" in w for w in topo.warnings))


class SwitchTests(unittest.TestCase):
    def test_inference_without_config(self):
        topo = build()
        apply_switches(topo, [])
        switches = {n.id: n for n in topo.nodes.values() if n.kind == PASSIVE_SWITCH}
        self.assertEqual(len(switches), 2, "LAN1 (3 devices) and LAN2 (2 devices)")
        sw1 = parent(topo, PC)
        self.assertIn(sw1, switches)
        self.assertEqual(parent(topo, NAS), sw1)
        self.assertEqual(parent(topo, HA), sw1)
        self.assertEqual(parent(topo, sw1), BOX)
        self.assertEqual(topo.parent_link(sw1).port, "LAN1")
        self.assertEqual(switches[sw1].attrs["inferred_from_devices"], 3)
        # Single device at LAN3 stays directly on the box.
        self.assertEqual(parent(topo, PRINTER), BOX)

    def test_config_names_inferred_switch(self):
        topo = build()
        configs, warnings = load_config(
            {
                "passive_switches": [
                    {"id": "sw_buero", "name": "Switch Büro", "location": "Arbeitszimmer", "ports": 8, "uplink": "fritzbox:LAN1"},
                    {"id": "sw_wohnzimmer", "name": "Switch Wohnzimmer", "uplink": "fritzbox:LAN2"},
                ]
            }
        )
        self.assertEqual(warnings, [])
        apply_switches(topo, configs)
        sw = topo.nodes["switch:sw_buero"]
        self.assertEqual(sw.name, "Switch Büro")
        self.assertEqual(sw.sources, ["inferred", "config"])
        self.assertEqual(sw.attrs["location"], "Arbeitszimmer")
        self.assertEqual(parent(topo, PC), "switch:sw_buero")
        self.assertEqual(parent(topo, CONSOLE), "switch:sw_wohnzimmer")
        self.assertEqual(sum(n.kind == PASSIVE_SWITCH for n in topo.nodes.values()), 2)

    def test_configured_switch_with_single_device(self):
        topo = build()
        configs, _ = load_config({"passive_switches": [{"id": "sw_flur", "uplink": "fritzbox:LAN3"}]})
        apply_switches(topo, configs)
        self.assertEqual(parent(topo, PRINTER), "switch:sw_flur")
        self.assertEqual(topo.nodes["switch:sw_flur"].sources, ["config"])

    def test_cascade_and_members(self):
        topo = build()
        configs, _ = load_config(
            {
                "passive_switches": [
                    {"id": "sw_buero", "uplink": "fritzbox:LAN1"},
                    {"id": "sw_tisch", "name": "Switch Schreibtisch", "uplink": "switch:sw_buero", "members": ["3C:22:FB:10:4E:A1"]},
                ]
            }
        )
        apply_switches(topo, configs)
        self.assertEqual(parent(topo, "switch:sw_tisch"), "switch:sw_buero")
        self.assertEqual(parent(topo, PC), "switch:sw_tisch")
        self.assertEqual(parent(topo, NAS), "switch:sw_buero")

    def test_member_moves_device_out_of_inferred_switch(self):
        topo = build()
        # Both LAN2 devices assigned elsewhere -> inferred LAN2 switch disappears.
        configs, _ = load_config(
            {"passive_switches": [{"id": "sw_x", "uplink": "fritzbox:LAN3", "members": [TV[4:], CONSOLE[4:]]}]}
        )
        apply_switches(topo, configs)
        self.assertEqual(parent(topo, TV), "switch:sw_x")
        self.assertEqual(parent(topo, CONSOLE), "switch:sw_x")
        self.assertFalse(any(n.kind == PASSIVE_SWITCH and n.sources == ["inferred"] and "lan2" in n.id for n in topo.nodes.values()))

    def test_bad_config_entries_warn(self):
        configs, warnings = load_config(
            {"passive_switches": [{"name": "ohne id"}, {"id": "Ungültig!"}, {"id": "ok"}, {"id": "ok"}]}
        )
        self.assertEqual([c.id for c in configs], ["ok"])
        self.assertEqual(len(warnings), 3)

    def test_unknown_uplink_warns(self):
        topo = build()
        configs, _ = load_config({"passive_switches": [{"id": "sw", "uplink": "keller:LAN1"}]})
        apply_switches(topo, configs)
        self.assertTrue(any("not found" in w for w in topo.warnings))

    def test_resolve_uplink_by_name_and_mac(self):
        topo = build()
        self.assertEqual(resolve_uplink(topo, "FRITZ!Repeater:LAN1"), (REP, "LAN1"))
        self.assertEqual(resolve_uplink(topo, "c8:0e:14:00:00:01:LAN2"), (BOX, "LAN2"))
        self.assertIsNone(resolve_uplink(topo, "fritzbox:AP"))

    def test_output_is_json_serialisable(self):
        topo = build()
        apply_switches(topo, [])
        out = json.loads(json.dumps(topo.to_dict(generated="2026-11-18T10:00:00+01:00")))
        self.assertEqual(out["links"][0], {"source": "internet", "target": BOX, "layer": "wan", "connected": True})


if __name__ == "__main__":
    unittest.main()
