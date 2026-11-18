"""Tests for the Zigbee rescan planner."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "custom_components" / "network_topology"))

from topology.model import Topology  # noqa: E402
from topology.rescan import RescanPlanner, all_routers, conflict_candidates  # noqa: E402
from topology.zha_parse import add_zigbee, attach_point  # noqa: E402

ZHA = json.loads((ROOT / "tests" / "fixtures" / "zha_sample.json").read_text(encoding="utf-8"))
C = "00:12:4b:00:00:00:00:01"
R1 = "00:17:88:00:00:00:00:11"
R2 = "00:17:88:00:00:00:00:22"
R3 = "00:17:88:00:00:00:00:33"


def build(conflict: bool) -> Topology:
    devices = copy.deepcopy(ZHA)
    if conflict:
        # E1 listed as Child by R1, coordinator routes through R3.
        devices[0]["routes"] = [{"dest_nwk": "0xE111", "next_hop": "0x3333", "route_status": "Active"}]
    topo = Topology()
    host, radio = attach_point(topo, None, None)
    add_zigbee(topo, devices, host_id=host, radio_link=radio)
    return topo


class CandidateTests(unittest.TestCase):
    def test_conflict_routers_and_coordinator(self):
        self.assertEqual(conflict_candidates(build(True)), sorted([C, R1, R3]))

    def test_no_conflict_no_candidates(self):
        self.assertEqual(conflict_candidates(build(False)), [])

    def test_all_routers_skips_end_devices(self):
        self.assertEqual(all_routers(build(False)), sorted([C, R1, R2, R3]))


class PlannerTests(unittest.TestCase):
    def test_first_run_scans_all_candidates(self):
        p = RescanPlanner()
        self.assertEqual(p.plan([R3, C], now=0), [C, R3])

    def test_min_interval_blocks_second_auto_run(self):
        p = RescanPlanner(min_interval=3600, device_cooldown=0)
        p.mark([R1], now=0)
        self.assertEqual(p.plan([R1], now=1800), [])
        self.assertEqual(p.plan([R1], now=3600), [R1])

    def test_device_cooldown(self):
        p = RescanPlanner(min_interval=0, device_cooldown=6 * 3600)
        p.mark([R1, C], now=0)
        # One hour later only the router not scanned yet is due.
        self.assertEqual(p.plan([R1, R3, C], now=3600), [R3])
        self.assertEqual(p.plan([R1, C], now=3600), [])

    def test_manual_ignores_limits(self):
        p = RescanPlanner()
        p.mark([R1], now=0)
        self.assertEqual(p.plan([R1], now=10, force=True), [R1])

    def test_nothing_to_do(self):
        self.assertEqual(RescanPlanner().plan([], now=0, force=True), [])


if __name__ == "__main__":
    unittest.main()
