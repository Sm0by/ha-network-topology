# Network Topology für Home Assistant

Custom Integration, die das Heimnetz als einen Graphen zusammenführt:

- **LAN und WLAN** aus der Mesh-Topologie der FRITZ!Box (TR-064), inklusive Repeater, Band und RSSI
- **Passive Switches**: Manche erkennt die FRITZ!Box selbst (`device_class: NETWORK_SWITCH`). Die übrigen werden abgeleitet, wenn mehrere Geräte an einem LAN-Port hängen. Namen und Standorte kommen aus `network_topology.yaml`.
- **Zigbee (ZHA)**: Koordinator am HA-Host, Router und End Devices als Baum mit LQI. Weitere Funkverbindungen zwischen Routern stehen in `mesh`.
- **Bluetooth**: Scanner (Adapter am HA-Host, ESPHome-Proxys) mit den BLE-Geräten, die zu einem HA-Gerät gehören. Jedes Gerät hängt am Scanner mit dem stärksten RSSI, weitere Scanner stehen in `mesh`. Proxys werden über das HA-Geräteregister mit ihrem LAN/WLAN-Knoten zusammengeführt, weil ihre Bluetooth-MAC von der Netzwerk-MAC abweicht.
- **HA-Geräteregister**: LAN/WLAN-Geräte bekommen über ihre MAC die HA-Geräte-ID und den in HA vergebenen Namen.
- **Robust**: Ist die FRITZ!Box nicht erreichbar, erscheinen Zigbee und Bluetooth trotzdem. Die Meldung steht dann in `warnings`.

Die Daten stehen über die WebSocket-API bereit und werden später von der Lovelace-Karte `network-topology-card` gezeichnet.

## Stand

| Schritt | Inhalt | Status |
|---|---|---|
| 1 | FRITZ!Box-Collector, Probe-Skript | fertig, an FRITZ!Box 7590 AX (FRITZ!OS 8.25, Mesh-Schema 8.7) geprüft |
| 2 | Switch-Ableitung + YAML | fertig, mit echten Daten geprüft |
| 3 | ZHA-Collector, Zigbee-Baum | fertig, mit echten ZHA-Daten geprüft (46 Geräte) |
| 4 | Bluetooth-Collector, Zusammenführung über MAC | fertig (Unit-Tests), wartet auf Test in HA |
| 5 | Lovelace-Karte | fertig, im Browser mit echten LAN- und Zigbee-Daten geprüft, wartet auf Test in HA |
| 6 | Sensoren, HACS-Paket | offen |

## Erst prüfen: liefert die FRITZ!Box die LAN-Ports?

```bash
pip install fritzconnection pyyaml
python tools/fritz_mesh_probe.py --user <fritzbox-benutzer>
```

Das Skript fragt das Passwort ab, zeigt Mesh-Geräte, LAN-Ports, WLAN-Clients und die abgeleiteten Switches. Die Rohdaten landen in `tools/out/` (nicht im Git, enthalten MAC-Adressen). Mit `--from-file tools/out/mesh_raw.json` lässt sich die Auswertung ohne Box wiederholen, mit `--config network_topology.example.yaml` die YAML testen.

## Zigbee-Baum prüfen

Die Integration rechnet aus den Nachbar- und Routing-Tabellen von ZHA einen Baum:

- **Router** hängen dort, wohin die Routing-Tabelle des Koordinators zeigt: direkt am Koordinator oder hinter dem ersten Hop. Den Rest des Weges ergänzt der beste Pfad mit Zigbee-Linkkosten (1–7 je nach LQI).
- **End Devices** hängen an dem Router, der sie als Kind führt.
- **Widersprüche:** Liegt der erste Hop des Koordinators nicht auf dem Weg zu diesem Router, bekommt die Verbindung `route_conflict`. Eine der beiden Tabellen ist dann veraltet. Zum Prüfen die ZHA-Daten im Browser exportieren (in HA angemeldet, Konsole mit F12):

```js
copy(JSON.stringify(await document.querySelector("home-assistant").hass.callWS({type: "zha/devices"})))
```

Als `tools/out/zha_devices.json` speichern und ausführen:

```bash
python tools/zha_probe.py tools/out/zha_devices.json --mesh tools/out/mesh_raw.json --ha-ip <ip-von-home-assistant>
```

ZHA liest die Tabellen alle 4 Stunden neu ein. Für frische Werte vorher in ZHA *Einstellungen → Visualisierung → Topologie aktualisieren* ausführen.

### Gezielter Nachscan bei Widersprüchen

Findet die Integration `route_conflict`-Verbindungen, liest sie die Tabellen der beteiligten Router neu ein. Beteiligt sind der Router, der das Gerät als Kind führt, der erste Hop der Koordinator-Route und der Koordinator selbst. Dafür nutzt sie den gezielten Scan von zigpy, also denselben Mechanismus wie *Topologie aktualisieren*, nur für wenige Geräte.

- Höchstens ein automatischer Nachscan pro Stunde, jeder Router höchstens alle 6 Stunden.
- Läuft gerade ein Scan von ZHA, wird nicht dazwischengefunkt.
- Abschaltbar unter *Integration → Konfigurieren*.
- Die Schaltfläche **Zigbee-Topologie prüfen** startet sofort einen Scan, ohne Drosselung. Gibt es keine Widersprüche, scannt sie alle Router.
- Der Stand steht in der WebSocket-Antwort unter `zigbee_rescan`.

Ein Nachscan räumt veraltete Router-Tabellen auf, erzwingt aber keine neuen Routen. Die Route des Koordinators zu einem schlafenden End Device ändert sich erst, wenn er wieder Daten an das Gerät schickt.

## Installation in Home Assistant

1. Ordner `custom_components/network_topology` nach `/config/custom_components/` kopieren.
2. Home Assistant neu starten.
3. *Einstellungen → Geräte & Dienste → Integration hinzufügen → Network Topology*. Ist FRITZ!Box Tools eingerichtet, werden deren Zugangsdaten übernommen.
4. Optional `network_topology.example.yaml` als `/config/network_topology.yaml` anlegen.

Der FRITZ!Box-Benutzer braucht das Recht „FRITZ!Box Einstellungen“.

## Karte

Die Integration liefert die Lovelace-Karte selbst aus und meldet sie im Frontend an. Eine Ressource musst du nicht eintragen. Im Dashboard *Karte hinzufügen → Network Topology* wählen oder per YAML:

```yaml
type: custom:network-topology-card
title: Netzwerk            # optional
height: 600                # Höhe der Zeichenfläche in px, oder "full" für die volle Fensterhöhe
layout: horizontal         # oder "vertical": von oben nach unten, besser auf breiten Bildschirmen
layers: [lan, wlan, zigbee, bluetooth]
show_mesh: false           # zusätzliche Funkverbindungen außerhalb des Baums
hide_offline: false
warn_lqi_below: 100
warn_rssi_below: -80
collapsed: []              # Knoten-IDs, die beim Start zugeklappt sind
```

Funktionen:

- **Baum** von links nach rechts oder von oben nach unten (Schalter ⇅/⇄ in der Karte), mit Linienstil je Verbindungsart: LAN durchgezogen, WLAN gestrichelt, Zigbee gepunktet, Bluetooth Strich-Punkt. Von oben nach unten stapeln sich Endgeräte unter ihrem Parent als Liste, damit große Gruppen wie WLAN-Clients oder Zigbee-End-Devices nicht in die Breite gehen.
- **Beschriftung** je Verbindung: Port, Band und RSSI, LQI.
- **Bedienung:** Ebenen-Filter, Teilbäume auf- und zuklappen (− / +N am Knoten), Zoomen mit Mausrad, Verschieben durch Ziehen, Suche nach Name, IP oder MAC.
- **Detailpanel** mit Werten, Datenquelle, Weg zum Internet und Link zur HA-Geräteseite.
- **Warnungen:** offline, schwaches LQI oder RSSI, `route_conflict` (rot), unbekannter Parent.
- **Hinweise:** Warnungen der Integration und Geräte ohne Verbindung unten in der Karte.

Ohne Home Assistant testen: `python dev/build_sample.py` erzeugt Beispieldaten. Danach im Repo-Ordner einen Webserver starten (`python -m http.server 8765`) und `http://localhost:8765/dev/harness.html` öffnen. Mit `?data=real` nutzt das Harness `tools/out/topology_full.json`, die `python dev/build_sample.py --real` aus den Probe-Exporten erzeugt.

## WebSocket-API

| Befehl | Antwort |
|---|---|
| `network_topology/get` | aktueller Graph |
| `network_topology/subscribe` | Graph sofort und nach jeder Aktualisierung (alle 60 s) |
| `network_topology/debug_sources` | Rohdaten der Bluetooth- und Registry-Collectors (nur Admin) |

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
