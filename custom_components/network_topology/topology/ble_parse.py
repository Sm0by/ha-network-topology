"""Bluetooth part of the topology, plus merging with the HA device registry.

Scanners (the HA host's adapter, ESPHome proxies) become Bluetooth hubs. A
proxy that is also in the LAN/WLAN data stays one node with two layers; the
link between them is the network MAC from the HA device registry (proxies
advertise with their Bluetooth MAC, which differs from the network MAC).

Only Bluetooth devices that belong to an HA device (registry connection
"bluetooth") are drawn; passers-by and neighbours' phones are skipped.

Input, prepared by collectors/bluetooth.py:

    scanners = [{"source": "E8:3D:C1:FB:9A:BD", "name": "bluetoothproxy",
                 "local": False, "connectable": True,
                 "network_mac": "e8:3d:c1:fb:9a:bb", "ha_device_id": "…"}]
    devices = [{"address": "A4:C1:38:2D:90:5B", "name": "Thermometer Küche",
                "ha_device_id": "…", "network_mac": None,
                "heard": [{"source": "E8:3D:C1:FB:9A:BD", "rssi": -64}],
                "last_source": "E8:3D:C1:FB:9A:BD"}]
"""

from __future__ import annotations

from typing import Any

from .fritz_parse import norm_mac
from .model import (
    BLUETOOTH,
    BLUETOOTH_DEVICE,
    BLUETOOTH_SCANNER,
    Link,
    Node,
    Topology,
)


def enrich_from_registry(topo: Topology, registry: dict[str, dict[str, Any]]) -> None:
    """Attach HA device ids and user names to LAN/WLAN nodes by network MAC.

    ``registry`` maps a lower-case network MAC to
    ``{"ha_device_id": …, "name": …, "name_by_user": …, "area_id": …}``.
    """
    for node in topo.nodes.values():
        if not node.mac or (entry := registry.get(node.mac)) is None:
            continue
        node.attrs.setdefault("ha_device_id", entry.get("ha_device_id"))
        if entry.get("area_id"):
            node.attrs.setdefault("area_id", entry["area_id"])
        if entry.get("name_by_user"):
            node.attrs.setdefault("fritz_name", node.name)
            node.name = entry["name_by_user"]
        if "ha" not in node.sources:
            node.sources.append("ha")


def add_bluetooth(
    topo: Topology,
    scanners: list[dict[str, Any]],
    devices: list[dict[str, Any]],
    *,
    host_id: str | None,
) -> None:
    """Add scanners, Bluetooth devices and their links."""
    scanner_node: dict[str, str] = {}  # scanner source (upper) -> node id

    for sc in scanners:
        source = str(sc.get("source") or "").upper()
        if not source:
            continue
        net = norm_mac(sc.get("network_mac"))
        if sc.get("local") and host_id and host_id in topo.nodes:
            nid = host_id
        elif net and f"mac:{net}" in topo.nodes:
            nid = f"mac:{net}"
        else:
            nid = f"ble_scanner:{source.lower()}"
            topo.add_node(
                Node(
                    id=nid,
                    name=sc.get("name") or source,
                    kind=BLUETOOTH_SCANNER,
                    mac=net,
                    sources=["bluetooth"],
                )
            )
            if not sc.get("local"):
                topo.warnings.append(
                    f"Bluetooth proxy '{sc.get('name') or source}' not found in LAN/WLAN data"
                )
        node = topo.nodes[nid]
        if BLUETOOTH not in node.layers:
            node.layers.append(BLUETOOTH)
        if "bluetooth" not in node.sources:
            node.sources.append("bluetooth")
        scanners_attr = node.attrs.setdefault("bluetooth_scanners", [])
        scanners_attr.append(
            {
                "source": source,
                "name": sc.get("name"),
                "connectable": bool(sc.get("connectable")),
                "local": bool(sc.get("local")),
            }
        )
        if sc.get("ha_device_id"):
            node.attrs.setdefault("ha_device_id", sc["ha_device_id"])
        scanner_node[source] = nid

    for dev in devices:
        address = str(dev.get("address") or "").upper()
        if not address:
            continue
        net = norm_mac(dev.get("network_mac"))
        if net and f"mac:{net}" in topo.nodes:
            nid = f"mac:{net}"  # e.g. a Wi-Fi device that also advertises via BLE
            node = topo.nodes[nid]
            if BLUETOOTH not in node.layers:
                node.layers.append(BLUETOOTH)
            if "bluetooth" not in node.sources:
                node.sources.append("bluetooth")
            node.attrs["bluetooth_address"] = address
            # Its LAN/WLAN link stays the tree link; Bluetooth goes to mesh.
            in_tree = topo.parent_link(nid) is not None
        else:
            nid = f"ble:{address.lower()}"
            topo.add_node(
                Node(
                    id=nid,
                    name=dev.get("name") or address,
                    kind=BLUETOOTH_DEVICE,
                    layers=[BLUETOOTH],
                    sources=["bluetooth"],
                    attrs={"bluetooth_address": address},
                )
            )
            in_tree = False
        node = topo.nodes[nid]
        if dev.get("ha_device_id"):
            node.attrs.setdefault("ha_device_id", dev["ha_device_id"])
        if dev.get("area_id"):
            node.attrs.setdefault("area_id", dev["area_id"])

        heard = sorted(
            (
                (h["rssi"], scanner_node[str(h["source"]).upper()])
                for h in dev.get("heard") or []
                if isinstance(h.get("rssi"), int) and str(h.get("source", "")).upper() in scanner_node
            ),
            reverse=True,
        )
        if node.kind == BLUETOOTH_DEVICE:
            node.online = bool(heard)
        node.attrs["heard_by"] = [{"node": s, "rssi": r} for r, s in heard]

        if heard:
            best_rssi, best = heard[0]
            others = heard[1:]
            if not in_tree:
                topo.links.append(Link(source=best, target=nid, layer=BLUETOOTH, rssi=best_rssi))
            else:
                others = heard
            for rssi, src in others:
                if src != nid:
                    topo.mesh.append(Link(source=src, target=nid, layer=BLUETOOTH, rssi=rssi))
        elif not in_tree:
            last = str(dev.get("last_source") or "").upper()
            if last in scanner_node:
                topo.links.append(
                    Link(source=scanner_node[last], target=nid, layer=BLUETOOTH, connected=False)
                )
