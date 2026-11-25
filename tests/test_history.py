"""Tests for remembering the last LAN/WLAN connection of offline devices."""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "custom_components" / "network_topology"))

from topology.fritz_parse import norm_mac, parse_mesh  # noqa: E402
from topology.history import prune, remember_links, restore_links  # noqa: E402
from topology.switches import apply_switches  # noqa: E402

MESH = json.loads((ROOT / "tests" / "fixtures" / "mesh_sample.json").read_text(encoding="utf-8"))
NOW = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)
BOX = "mac:c8:0e:14:00:00:01"
PC = "3c:22:fb:10:4e:a1"


def _without(data, node_uid):
    """Drop a device from the mesh (as FRITZ!OS does once it is gone) and mark its host offline."""
    data = copy.deepcopy(data)
    mesh = data["mesh"]
    gone = next(n for n in mesh["nodes"] if n["uid"] == node_uid)
    mac = norm_mac(gone["device_mac_address"])
    link_uids = {l["uid"] for i in gone["node_interfaces"] for l in i.get("node_links", [])}
    mesh["nodes"] = [n for n in mesh["nodes"] if n["uid"] != node_uid]
    for node in mesh["nodes"]:
        for iface in node["node_interfaces"]:
            iface["node_links"] = [l for l in iface.get("node_links", []) if l["uid"] not in link_uids]
    hosts = [h for h in data["hosts"] if norm_mac(h["mac"]) == mac]
    if not hosts:  # the real host list knows every device; the fixture does not
        hosts = [{"name": gone["device_name"], "mac": gone["device_mac_address"]}]
        data["hosts"].append(hosts[0])
    for host in hosts:
        host["status"] = False
    return data, mac


def _topo(data):
    return parse_mesh(data["mesh"], data["hosts"])


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.memory = {}
        self.assertTrue(remember_links(_topo(MESH), self.memory, NOW))

    def test_remembers_port_and_band(self):
        self.assertEqual(self.memory[PC]["parent"], BOX)
        self.assertEqual(self.memory[PC]["port"], "LAN1")
        wlan = [e for e in self.memory.values() if e["layer"] == "wlan"]
        self.assertTrue(wlan and all(e.get("band") for e in wlan))

    def test_unchanged_run_reports_no_change(self):
        self.assertFalse(remember_links(_topo(MESH), self.memory, NOW + timedelta(minutes=1)))

    def test_offline_lan_device_returns_behind_inferred_switch(self):
        data, mac = _without(MESH, "n-pc")
        topo = _topo(data)
        node_id = f"mac:{mac}"
        self.assertIsNone(topo.parent_link(node_id), "FRITZ!Box dropped the link")
        self.assertEqual(restore_links(topo, self.memory), 1)
        apply_switches(topo, [])
        link = topo.parent_link(node_id)
        self.assertFalse(link.connected)
        self.assertTrue(link.attrs["remembered"])
        self.assertEqual(link.attrs["last_connected"], NOW.isoformat())
        self.assertTrue(link.source.startswith("switch:"), "same switch as the other LAN1 devices")
        self.assertFalse(topo.nodes[node_id].online)

    def test_offline_wlan_device_keeps_repeater_and_band(self):
        data, mac = _without(MESH, "n-laptop")
        topo = _topo(data)
        restore_links(topo, self.memory)
        link = topo.parent_link(f"mac:{mac}")
        self.assertEqual(link.layer, "wlan")
        self.assertEqual(topo.nodes[link.source].kind, "repeater")
        self.assertEqual(link.band, self.memory[mac]["band"])

    def test_online_or_unknown_devices_untouched(self):
        topo = _topo(MESH)
        before = len(topo.links)
        self.assertEqual(restore_links(topo, self.memory), 0)
        self.assertEqual(len(topo.links), before)
        data, _ = _without(MESH, "n-pc")
        self.assertEqual(restore_links(_topo(data), {}), 0)

    def test_falls_back_when_parent_is_gone(self):
        data, mac = _without(MESH, "n-pc")
        topo = _topo(data)
        self.memory[mac] = {**self.memory[mac], "parent": "mac:fa:ce:00:00:00:99",
                            "fallback": BOX, "fallback_port": "LAN4"}
        restore_links(topo, self.memory)
        link = topo.parent_link(f"mac:{mac}")
        self.assertEqual((link.source, link.port), (BOX, "LAN4"))

    def test_prune_forgets_old_devices(self):
        self.memory["aa:bb:cc:dd:ee:ff"] = {"parent": BOX, "layer": "lan", "seen": (NOW - timedelta(days=91)).isoformat()}
        self.memory["11:22:33:44:55:66"] = {"parent": BOX, "layer": "lan", "seen": "kaputt"}
        self.assertTrue(prune(self.memory, NOW))
        self.assertNotIn("aa:bb:cc:dd:ee:ff", self.memory)
        self.assertNotIn("11:22:33:44:55:66", self.memory)
        self.assertIn(PC, self.memory)
        self.assertFalse(prune(self.memory, NOW))


if __name__ == "__main__":
    unittest.main()
