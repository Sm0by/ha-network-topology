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
from topology.history import best_place, prune, remember_links, restore_links  # noqa: E402
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

    def place(self, mac):
        (place,) = self.memory[mac]["places"].values()
        return place

    def test_remembers_port_and_band(self):
        self.assertEqual((self.place(PC)["parent"], self.place(PC)["port"]), (BOX, "LAN1"))
        wlan = [p for e in self.memory.values() for p in e["places"].values() if p["layer"] == "wlan"]
        self.assertTrue(wlan and all(p.get("band") for p in wlan))

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
        self.assertEqual(link.band, self.place(mac)["band"])

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
        self.place(mac).update(parent="mac:fa:ce:00:00:00:99", fallback=BOX, fallback_port="LAN4")
        restore_links(topo, self.memory)
        link = topo.parent_link(f"mac:{mac}")
        self.assertEqual((link.source, link.port), (BOX, "LAN4"))

    def test_stale_placeholder_host_is_no_device(self):
        data = copy.deepcopy(MESH)
        data["hosts"].append({"name": "Switch", "mac": "FA:CE:4B:16:AF:DE", "status": False})
        self.assertNotIn("mac:fa:ce:4b:16:af:de", _topo(data).nodes)

    def test_most_frequent_place_wins_and_moves_take_over(self):
        topo = _topo(MESH)
        entry = self.memory[PC]
        for minute in range(1, 30):  # 30 observations at LAN1 in total
            remember_links(topo, self.memory, NOW + timedelta(minutes=minute))
        link = topo.parent_link(f"mac:{PC}")
        link.port = "LAN3"  # moved to another port
        for minute in range(30, 35):  # a short excursion does not win
            remember_links(topo, self.memory, NOW + timedelta(minutes=minute))
        self.assertEqual(best_place(topo, entry)["port"], "LAN1")
        for minute in range(35, 60):  # staying there does
            remember_links(topo, self.memory, NOW + timedelta(minutes=minute))
        self.assertEqual(best_place(topo, entry)["port"], "LAN3")

    def test_long_standing_place_still_gives_way(self):
        topo = _topo(MESH)
        for minute in range(1, 2000):
            remember_links(topo, self.memory, NOW + timedelta(minutes=minute))
        topo.parent_link(f"mac:{PC}").port = "LAN3"
        for minute in range(2000, 2120):
            remember_links(topo, self.memory, NOW + timedelta(minutes=minute))
        self.assertEqual(best_place(topo, self.memory[PC])["port"], "LAN3")

    def test_old_format_is_converted(self):
        entry = {"parent": BOX, "layer": "lan", "port": "LAN2", "seen": NOW.isoformat()}
        self.assertEqual(best_place(_topo(MESH), entry)["port"], "LAN2")
        self.assertNotIn("parent", entry)

    def test_prune_forgets_old_devices(self):
        self.memory["aa:bb:cc:dd:ee:ff"] = {"parent": BOX, "layer": "lan", "seen": (NOW - timedelta(days=91)).isoformat()}
        self.memory["11:22:33:44:55:66"] = {"parent": BOX, "layer": "lan", "seen": "kaputt"}
        self.assertTrue(prune(self.memory, NOW))
        self.assertNotIn("aa:bb:cc:dd:ee:ff", self.memory)
        self.assertNotIn("11:22:33:44:55:66", self.memory)
        self.assertIn(PC, self.memory)
        self.assertFalse(prune(self.memory, NOW))


def _repeater_mesh(shield_on_repeater_uplink: bool):
    """Box LAN2 -> switch (tower, shield); box LAN3 -> repeater LAN1."""
    def iface(uid, name, links=()):
        return {"uid": uid, "name": name, "type": "LAN", "node_links": list(links)}

    def link(uid, n1, i1, n2, i2):
        return {"uid": uid, "type": "LAN", "state": "CONNECTED", "node_1_uid": n1,
                "node_interface_1_uid": i1, "node_2_uid": n2, "node_interface_2_uid": i2}

    shield = (link("l-sh", "n-box", "i-box2", "n-sh", "i-sh") if not shield_on_repeater_uplink
              else link("l-sh", "n-rep", "i-rep1", "n-sh", "i-sh"))
    tower = link("l-tw", "n-box", "i-box2", "n-tw", "i-tw")
    rep = link("l-rep", "n-box", "i-box3", "n-rep", "i-rep1")
    nodes = [
        {"uid": "n-box", "device_name": "box", "device_mac_address": "C8:0E:14:00:00:01", "mesh_role": "master",
         "node_interfaces": [iface("i-box2", "LAN:2", [tower] + ([shield] if not shield_on_repeater_uplink else [])),
                             iface("i-box3", "LAN:3", [rep])]},
        {"uid": "n-rep", "device_name": "repeater", "device_mac_address": "D4:24:DD:46:55:E8", "mesh_role": "slave",
         "node_interfaces": [iface("i-rep1", "LAN:1", [rep] + ([shield] if shield_on_repeater_uplink else []))]},
        {"uid": "n-tw", "device_name": "tower", "device_mac_address": "30:5A:3A:7F:47:70", "mesh_role": "unknown",
         "node_interfaces": [iface("i-tw", "", [tower])]},
        {"uid": "n-sh", "device_name": "shield", "device_mac_address": "00:04:4B:71:72:B7", "mesh_role": "unknown",
         "node_interfaces": [iface("i-sh", "", [shield])]},
    ]
    hosts = [{"name": "shield", "mac": "00:04:4B:71:72:B7", "status": True},
             {"name": "tower", "mac": "30:5A:3A:7F:47:70", "status": True}]
    return {"nodes": nodes}, hosts


class UplinkPortTests(unittest.TestCase):
    SHIELD = "mac:00:04:4b:71:72:b7"
    REPEATER = "mac:d4:24:dd:46:55:e8"

    def test_client_on_repeater_uplink_is_suspect_and_not_remembered(self):
        topo = parse_mesh(*_repeater_mesh(True))
        self.assertEqual(topo.nodes[self.REPEATER].attrs["uplink_port"], "LAN1")
        self.assertEqual(topo.parent_link(self.SHIELD).attrs["suspect"], "uplink_port")
        memory = {}
        remember_links(topo, memory, NOW)
        self.assertNotIn("00:04:4b:71:72:b7", memory)

    def test_suspect_link_moves_to_usual_place_behind_switch(self):
        memory = {}
        remember_links(parse_mesh(*_repeater_mesh(False)), memory, NOW)
        topo = parse_mesh(*_repeater_mesh(True))
        restore_links(topo, memory)
        apply_switches(topo, [])
        link = topo.parent_link(self.SHIELD)
        self.assertEqual(link.source, topo.parent_link("mac:30:5a:3a:7f:47:70").source, "same switch as the tower")
        self.assertEqual(link.attrs["placed_by"], "history")
        self.assertEqual(link.attrs["reported_parent"], "repeater:LAN1")

    def test_stored_wrong_place_from_0_4_0_is_ignored(self):
        mesh, hosts = _repeater_mesh(True)
        hosts[0]["status"] = False
        mesh["nodes"] = [n for n in mesh["nodes"] if n["uid"] != "n-sh"]
        for node in mesh["nodes"]:
            for i in node["node_interfaces"]:
                i["node_links"] = [l for l in i["node_links"] if l["uid"] != "l-sh"]
        topo = parse_mesh(mesh, hosts)
        memory = {"00:04:4b:71:72:b7": {"parent": self.REPEATER, "layer": "lan", "port": "LAN1",
                                        "seen": NOW.isoformat()}}
        self.assertEqual(restore_links(topo, memory), 0)


if __name__ == "__main__":
    unittest.main()
