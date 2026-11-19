"""Tests for link rates (LAN/WLAN/WAN) and HA-disabled devices."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "custom_components" / "network_topology"))

from topology.ble_parse import enrich_from_registry  # noqa: E402
from topology.fritz_parse import parse_mesh  # noqa: E402
from topology.model import Topology  # noqa: E402
from topology.rescan import all_routers, conflict_candidates  # noqa: E402
from topology.zha_parse import add_zigbee, attach_point  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
MESH = json.loads((FIX / "mesh_sample.json").read_text(encoding="utf-8"))
ZHA = json.loads((FIX / "zha_sample.json").read_text(encoding="utf-8"))
BOX = "mac:c8:0e:14:00:00:01"
PC = "mac:3c:22:fb:10:4e:a1"
R3 = "zigbee:00:17:88:00:00:00:00:33"


def mesh_topo(wan=None):
    data = copy.deepcopy(MESH)
    return parse_mesh(data["mesh"], data["hosts"], wan)


class RateTests(unittest.TestCase):
    def test_lan_rates(self):
        link = mesh_topo().parent_link(PC)
        self.assertEqual(link.rate_kbit, 1000000)

    def test_wlan_max_rate(self):
        data = copy.deepcopy(MESH)
        for node in data["mesh"]["nodes"]:
            for iface in node["node_interfaces"]:
                for l in iface.get("node_links", []):
                    if l["uid"] == "nl-phone":
                        l.update(cur_data_rate_rx=650000, cur_data_rate_tx=866700, max_data_rate_rx=1200000, max_data_rate_tx=1200000)
        link = parse_mesh(data["mesh"], data["hosts"]).parent_link("mac:5a:11:22:33:44:55")
        self.assertEqual((link.rate_kbit, link.rate_tx_kbit, link.max_rate_kbit), (650000, 866700, 1200000))

    def test_wan_link(self):
        wan = {"max_down": 262_000_000, "max_up": 46_000_000, "linked_down": 300_000_000, "linked_up": 50_000_000,
               "rate_down": 1_200_000, "rate_up": 0, "connected": True}
        link = mesh_topo(wan).parent_link(BOX)
        self.assertEqual((link.layer, link.rate_kbit, link.rate_tx_kbit, link.max_rate_kbit), ("wan", 262000, 46000, 300000))
        self.assertEqual((link.attrs["rate_down_bps"], link.attrs["rate_up_bps"]), (1_200_000, 0))
        self.assertTrue(link.connected)

    def test_wan_ethernet_port_drops_junk_line_rate(self):
        # FRITZ!Box behind a modem: 1 Gbit/s port speed, "linked" 1 Mbit/s is meaningless.
        wan = {"max_down": 1_000_000_000, "max_up": 1_000_000_000, "linked_down": 1_000_000,
               "linked_up": 1_000_000, "rate_down": 0, "rate_up": 0, "connected": True, "access_type": "Ethernet"}
        link = mesh_topo(wan).parent_link(BOX)
        self.assertEqual(link.rate_kbit, 1_000_000)
        self.assertIsNone(link.max_rate_kbit)
        self.assertEqual(link.attrs["access_type"], "Ethernet")

    def test_wan_disconnected_and_missing(self):
        self.assertFalse(mesh_topo({"max_down": 0, "max_up": 0, "connected": False}).parent_link(BOX).connected)
        link = mesh_topo(None).parent_link(BOX)
        self.assertIsNone(link.rate_kbit)
        self.assertEqual(link.attrs, {})


class DisabledTests(unittest.TestCase):
    def zigbee(self, disabled_nwk):
        devices = copy.deepcopy(ZHA)
        devices[0]["routes"] = [{"dest_nwk": "0xE111", "next_hop": "0x3333", "route_status": "Active"}]  # E1 conflict
        for d in devices:
            if d["nwk"] in disabled_nwk:
                d["disabled"] = True
        topo = Topology()
        host, radio = attach_point(topo, None, None)
        add_zigbee(topo, devices, host_id=host, radio_link=radio)
        return topo

    def test_disabled_flag_and_no_rescan(self):
        topo = self.zigbee({"0xE111", "0x3333"})
        self.assertTrue(topo.nodes["zigbee:00:15:8d:00:00:00:00:e1"].attrs["disabled"])
        self.assertEqual(conflict_candidates(topo), [], "conflict of a disabled device triggers no rescan")
        self.assertNotIn(R3[len("zigbee:"):], all_routers(topo))

    def test_enabled_conflict_still_rescans(self):
        self.assertTrue(conflict_candidates(self.zigbee(set())))

    def test_registry_disabled_marks_lan_node(self):
        topo = mesh_topo()
        enrich_from_registry(topo, {"3c:22:fb:10:4e:a1": {"ha_device_id": "x", "disabled": True}})
        self.assertTrue(topo.nodes[PC].attrs["disabled"])


if __name__ == "__main__":
    unittest.main()
