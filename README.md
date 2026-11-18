# Network Topology für Home Assistant

Custom Integration, die das Heimnetz als einen Graphen zusammenführt:

- **LAN und WLAN** aus der Mesh-Topologie der FRITZ!Box (TR-064), inklusive Repeater, Band und RSSI
- **Passive Switches**: Manche erkennt die FRITZ!Box selbst (`device_class: NETWORK_SWITCH`). Die übrigen werden abgeleitet, wenn mehrere Geräte an einem LAN-Port hängen. Namen und Standorte kommen aus `network_topology.yaml`.
- **Zigbee (ZHA)** und **Bluetooth**: folgen in den nächsten Schritten

Die Daten stehen über die WebSocket-API bereit und werden später von der Lovelace-Karte `network-topology-card` gezeichnet.

## Stand

| Schritt | Inhalt | Status |
|---|---|---|
| 1 | FRITZ!Box-Collector, Probe-Skript | fertig, an FRITZ!Box 7590 AX (FRITZ!OS 8.25, Mesh-Schema 8.7) geprüft |
| 2 | Switch-Ableitung + YAML | fertig, mit echten Daten geprüft |
| 3 | ZHA-Collector | offen |
| 4 | Bluetooth-Collector, Zusammenführung über MAC | offen |
| 5 | Lovelace-Karte | offen |
| 6 | Sensoren, HACS-Paket | offen |

## Erst prüfen: liefert die FRITZ!Box die LAN-Ports?

```bash
pip install fritzconnection pyyaml
python tools/fritz_mesh_probe.py --user <fritzbox-benutzer>
```

Das Skript fragt das Passwort ab, zeigt Mesh-Geräte, LAN-Ports, WLAN-Clients und die abgeleiteten Switches. Die Rohdaten landen in `tools/out/` (nicht im Git, enthalten MAC-Adressen). Mit `--from-file tools/out/mesh_raw.json` lässt sich die Auswertung ohne Box wiederholen, mit `--config network_topology.example.yaml` die YAML testen.

## Installation in Home Assistant

1. Ordner `custom_components/network_topology` nach `/config/custom_components/` kopieren.
2. Home Assistant neu starten.
3. *Einstellungen → Geräte & Dienste → Integration hinzufügen → Network Topology*. Ist FRITZ!Box Tools eingerichtet, werden deren Zugangsdaten übernommen.
4. Optional `network_topology.example.yaml` als `/config/network_topology.yaml` anlegen.

Der FRITZ!Box-Benutzer braucht das Recht „FRITZ!Box Einstellungen“.

## WebSocket-API

| Befehl | Antwort |
|---|---|
| `network_topology/get` | aktueller Graph |
| `network_topology/subscribe` | Graph sofort und nach jeder Aktualisierung (alle 60 s) |

Zum Ausprobieren in den Entwicklerwerkzeugen des Browsers:

```js
await document.querySelector("home-assistant").hass.callWS({ type: "network_topology/get" })
```

Format:

```json
{
  "generated": "2026-11-18T10:42:18+01:00",
  "nodes": [{ "id": "mac:…", "name": "NAS", "kind": "client", "layers": ["lan"], "ip": "…", "online": true }],
  "links": [{ "source": "switch:sw_buero", "target": "mac:…", "layer": "lan", "connected": true }],
  "unlinked": ["mac:…"],
  "warnings": []
}
```

## Entwicklung

Die Logik in `topology/` hat keine Home-Assistant-Abhängigkeit und lässt sich direkt testen:

```bash
python -m unittest discover -s tests -v
```
