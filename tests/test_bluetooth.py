"""Tests for the Bluetooth part and the HA registry merge."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "custom_components" / "network_topology"))

from topology.ble_parse import add_bluetooth, enrich_from_registry  # noqa: E402
from topology.fritz_parse import parse_mesh  # noqa: E402
from topology.model import Topology  # noqa: E402
from topology.zha_parse import attach_point  # noqa: E402

MESH = json.loads((ROOT / "tests" / "fixtures" / "mesh_sample.json").read_text(encoding="utf-8"))

HA = "mac:d8:3a:dd:41:7c:02"
PROXY_LAN = "mac:24:0a:c4:9b:11:02"  # bt-proxy-kueche in the mesh sample (WLAN at repeater)
PROXY_BT = "24:0A:C4:9B:11:04"  # its Bluetooth MAC differs from the network MAC
LOCAL_BT = "D8:3A:DD:41:7C:03"

SCANNERS = [
    {"source": LOCAL_BT, "name": "hci0", "local": True, "connectable": True},
    {"source": PROXY_BT, "name": "bt-proxy-kueche", "local": False, "connectable": True,
     "network_mac": "24:0a:c4:9b:11:02", "ha_device_id": "dev-proxy"},
]
DEVICES = [
    {"address": "A4:C1:38:2D:90:5B", "name": "Thermometer Küche", "ha_device_id": "dev-thermo",
     "heard": [{"source": LOCAL_BT, "rssi": -91}, {"source": PROXY_BT, "rssi": -64}], "last_source": PROXY_BT},
    {"address": "C4:7C:8D:6A:3F:21", "name": "Pflanzensensor", "ha_device_id": "dev-plant",
     "heard": [{"source": LOCAL_BT, "rssi": -78}], "last_source": LOCAL_BT},
    {"address": "B0:D2:78:11:4C:E7", "name": "Zahnbürste", "heard": [], "last_source": PROXY_BT},
    # Wi-Fi device that also advertises BLE (e.g. a hub): stays on its WLAN link.
    {"address": "5A:11:22:33:44:58", "name": "Tablet BLE", "network_mac": "5a:11:22:33:44:56",
     "heard": [{"source": PROXY_BT, "rssi": -70}]},
    # Heard only by a scanner HA does not know.
    {"address": "11:22:33:44:55:66", "name": "Fremd", "heard": [{"source": "FF:FF:FF:00:00:01", "rssi": -50}]},
]


def build(scanners=SCANNERS, devices=DEVICES):
    data = copy.deepcopy(MESH)
    topo = parse_mesh(data["mesh"], data["hosts"])
    attach_point(topo, "192.168.178.20", None)
    add_bluetooth(topo, copy.deepcopy(scanners), copy.deepcopy(devices), host_id=HA)
    return topo


def up(topo, node):
    link = topo.parent_link(node)
    return (link.source, link.layer, link.rssi, link.connected) if link else None


class ScannerTests(unittest.TestCase):
    def test_proxy_merged_with_lan_node(self):
        topo = build()
        proxy = topo.nodes[PROXY_LAN]
        self.assertEqual(proxy.layers, ["wlan", "bluetooth"])
        self.assertEqual(proxy.attrs["bluetooth_scanners"][0]["source"], PROXY_BT)
        self.assertEqual(proxy.attrs["ha_device_id"], "dev-proxy")
        self.assertNotIn(f"ble_scanner:{PROXY_BT.lower()}", topo.nodes)

    def test_local_adapter_on_ha_host(self):
        topo = build()
        self.assertIn("bluetooth", topo.nodes[HA].layers)

    def test_unknown_proxy_gets_own_node_and_warning(self):
        scanners = SCANNERS + [{"source": "AA:BB:CC:00:00:01", "name": "proxy-garage", "local": False}]
        topo = build(scanners)
        self.assertEqual(topo.nodes["ble_scanner:aa:bb:cc:00:00:01"].kind, "bluetooth_scanner")
        self.assertTrue(any("proxy-garage" in w for w in topo.warnings))


class DeviceTests(unittest.TestCase):
    def test_strongest_scanner_is_parent_others_mesh(self):
        topo = build()
        thermo = "ble:a4:c1:38:2d:90:5b"
        self.assertEqual(up(topo, thermo), (PROXY_LAN, "bluetooth", -64, True))
        mesh = [(l.source, l.rssi) for l in topo.mesh if l.target == thermo]
        self.assertEqual(mesh, [(HA, -91)])
        self.assertEqual(topo.nodes[thermo].attrs["ha_device_id"], "dev-thermo")

    def test_local_adapter_device(self):
        topo = build()
        self.assertEqual(up(topo, "ble:c4:7c:8d:6a:3f:21"), (HA, "bluetooth", -78, True))

    def test_not_heard_is_offline_at_last_scanner(self):
        topo = build()
        node = "ble:b0:d2:78:11:4c:e7"
        self.assertFalse(topo.nodes[node].online)
        self.assertEqual(up(topo, node), (PROXY_LAN, "bluetooth", None, False))

    def test_wifi_device_with_ble_keeps_wlan_tree_link(self):
        topo = build()
        tablet = "mac:5a:11:22:33:44:56"
        self.assertEqual(up(topo, tablet)[1], "wlan")
        self.assertIn("bluetooth", topo.nodes[tablet].layers)
        self.assertIn((PROXY_LAN, tablet), [(l.source, l.target) for l in topo.mesh])
        self.assertNotIn("ble:5a:11:22:33:44:58", topo.nodes)

    def test_device_heard_only_by_unknown_scanner(self):
        topo = build()
        node = "ble:11:22:33:44:55:66"
        self.assertFalse(topo.nodes[node].online)
        self.assertIsNone(topo.parent_link(node))
        self.assertIn(node, topo.to_dict()["unlinked"])

    def test_one_parent_per_node(self):
        topo = build()
        targets = [l.target for l in topo.links]
        self.assertEqual(len(targets), len(set(targets)))


class RegistryTests(unittest.TestCase):
    def test_enrich_names_and_ids(self):
        data = copy.deepcopy(MESH)
        topo = parse_mesh(data["mesh"], data["hosts"])
        enrich_from_registry(
            topo,
            {
                "d8:3a:dd:41:7c:02": {"ha_device_id": "dev-ha", "name_by_user": "HA-Pi", "area_id": "keller"},
                "00:11:32:af:09:5e": {"ha_device_id": "dev-nas", "name_by_user": None},
            },
        )
        ha = topo.nodes[HA]
        self.assertEqual((ha.name, ha.attrs["fritz_name"], ha.attrs["area_id"]), ("HA-Pi", "homeassistant", "keller"))
        self.assertEqual(topo.nodes["mac:00:11:32:af:09:5e"].name, "NAS")
        self.assertIn("ha", topo.nodes["mac:00:11:32:af:09:5e"].sources)

    def test_bluetooth_without_lan(self):
        topo = Topology()
        attach_point(topo, None, None)
        add_bluetooth(topo, SCANNERS[:1], DEVICES[1:2], host_id="homeassistant")
        self.assertEqual(up(topo, "ble:c4:7c:8d:6a:3f:21")[0], "homeassistant")


if __name__ == "__main__":
    unittest.main()
