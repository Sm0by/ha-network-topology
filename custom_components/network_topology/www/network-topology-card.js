/*
 * Network Topology Card for Home Assistant.
 * Draws the graph of the network_topology integration: LAN, WLAN, Zigbee, Bluetooth.
 *
 *   type: custom:network-topology-card
 *   title: Netzwerk            # optional
 *   height: 600                # px, or "full" to fill the window below the card's top
 *   layout: horizontal         # or "vertical" (top-down, better on wide screens)
 *   layers: [lan, wlan, zigbee, bluetooth]
 *   show_mesh: false           # extra radio links outside the tree
 *   hide_offline: false
 *   show_speeds: false         # link rates as labels and line width
 *   warn_lqi_below: 100
 *   warn_rssi_below: -80
 *   collapsed: []              # node ids collapsed at start
 *
 * No build step, no external libraries.
 */

const CARD_VERSION = "0.3.0";
const NS = "http://www.w3.org/2000/svg";
const NODE_W = 184;
const NODE_H = 46;
const COL = 244; // horizontal: distance between levels
const ROW = 56; // horizontal: distance between rows
const SLOT = NODE_W + 96; // vertical: width of one column
const NODE_X = 40; // vertical: node offset inside its column
const RAIL_X = 64; // vertical: x of the rail a stacked list hangs on
const STACK_INDENT = 88; // vertical: x of stacked leaves (labels fit left of the rail)
const LEVEL = 116; // vertical: distance between levels
const STACK_ROW = 54; // vertical: distance in a stacked leaf list
const STACK_MAX = 10; // vertical: leaves per stacked column
const ALL_LAYERS = ["lan", "wlan", "zigbee", "bluetooth"];
const LINK_FILTER = { wan: "lan", lan: "lan", wlan: "wlan", zigbee: "zigbee", usb: "zigbee", bluetooth: "bluetooth" };
const INFRA = new Set(["internet", "router", "repeater", "passive_switch", "home_assistant", "zigbee_coordinator", "bluetooth_scanner"]);
const KIND_ORDER = ["router", "repeater", "passive_switch", "zigbee_coordinator", "zigbee_router", "bluetooth_scanner", "client", "zigbee_end_device", "bluetooth_device"];

const STRINGS = {
  de: {
    title: "Netzwerk", layers: { lan: "LAN", wlan: "WLAN", zigbee: "Zigbee", bluetooth: "Bluetooth" },
    mesh: "Mesh-Verbindungen", hideOffline: "Offline ausblenden", speeds: "Geschwindigkeit", search: "Gerät suchen …",
    disabled: "deaktiviert", disabledHint: "In Home Assistant deaktiviert. Keine Warnung, kein Zigbee-Nachscan; offline ausgeblendet.",
    fit: "Alles zeigen", zoomIn: "Vergrößern", zoomOut: "Verkleinern", direction: "Ausrichtung wechseln",
    horizontal: "Von links", vertical: "Von oben",
    online: "online", offline: "offline", warnings: "Warnungen", rescan: "Zigbee-Nachscan läuft",
    updated: "aktualisiert", loading: "Lade Topologie …", notLoaded: "Die Integration Network Topology ist nicht eingerichtet oder liefert keine Daten.",
    noSelection: "Kein Gerät gewählt", noSelectionHint: "Klicke auf ein Gerät, um Verbindungsweg, Signalwerte und Datenquelle zu sehen.",
    path: "Weg", openDevice: "Gerät in Home Assistant öffnen", hints: "Hinweise", unlinked: "Ohne Verbindung",
    notFound: "Kein Gerät gefunden", collapse: "Zuklappen", expand: "Aufklappen", hidden: "ausgeblendet",
    kinds: {
      internet: "Internet", router: "Router", repeater: "Repeater", passive_switch: "Passiver Switch", client: "Gerät",
      home_assistant: "Home Assistant", zigbee_coordinator: "Zigbee-Koordinator", zigbee_router: "Zigbee-Router",
      zigbee_end_device: "Zigbee-End-Device", bluetooth_device: "Bluetooth-Gerät", bluetooth_scanner: "Bluetooth-Proxy",
    },
    f: {
      kind: "Typ", ip: "IP", mac: "MAC", model: "Modell", manufacturer: "Hersteller", connection: "Verbindung",
      rate: "Linkrate", rateMax: "Maximal", sync: "Sync-Rate", throughput: "Aktueller Durchsatz", lineMax: "Leitung möglich",
      port: "Port", band: "Band", signal: "Signal", lqi: "LQI", ieee: "IEEE", nwk: "NWK", power: "Stromquelle",
      location: "Standort", detected: "Erkannt", sources: "Quellen", scanners: "Bluetooth-Scanner", heard: "Auch gehört von",
      firmware: "Firmware", lastSeen: "Zuletzt gesehen", parent: "Zuordnung",
    },
    w: {
      offline: "Gerät ist offline.", weakLqi: (v, t) => `Schwaches Zigbee-Signal (LQI ${v}, Schwelle ${t}).`,
      weakRssi: (v, t) => `Schwaches Signal (${v} dBm, Schwelle ${t} dBm).`,
      conflict: (n) => `Nachbartabelle und Route widersprechen sich: Der Koordinator routet über ${n}.`,
      unknownParent: "Parent unbekannt, vorläufig am Koordinator.",
    },
    parentHow: { route: "aus Routing-Tabelle", neighbors: "aus Nachbartabelle", unknown: "unbekannt" },
    detectedBy: { fritz: "von der FRITZ!Box", inferred: (n) => `abgeleitet, ${n} Geräte an einem Port`, config: "aus network_topology.yaml" },
  },
  en: {
    title: "Network", layers: { lan: "LAN", wlan: "Wi-Fi", zigbee: "Zigbee", bluetooth: "Bluetooth" },
    mesh: "Mesh links", hideOffline: "Hide offline", speeds: "Speed", search: "Find device …",
    disabled: "disabled", disabledHint: "Disabled in Home Assistant. No warning, no Zigbee rescan; hidden while offline.",
    fit: "Show all", zoomIn: "Zoom in", zoomOut: "Zoom out", direction: "Switch direction",
    horizontal: "Left to right", vertical: "Top down",
    online: "online", offline: "offline", warnings: "warnings", rescan: "Zigbee rescan running",
    updated: "updated", loading: "Loading topology …", notLoaded: "The Network Topology integration is not set up or returns no data.",
    noSelection: "No device selected", noSelectionHint: "Click a device to see its path, signal values and data source.",
    path: "Path", openDevice: "Open device in Home Assistant", hints: "Notes", unlinked: "Not connected",
    notFound: "No device found", collapse: "Collapse", expand: "Expand", hidden: "hidden",
    kinds: {
      internet: "Internet", router: "Router", repeater: "Repeater", passive_switch: "Passive switch", client: "Device",
      home_assistant: "Home Assistant", zigbee_coordinator: "Zigbee coordinator", zigbee_router: "Zigbee router",
      zigbee_end_device: "Zigbee end device", bluetooth_device: "Bluetooth device", bluetooth_scanner: "Bluetooth proxy",
    },
    f: {
      kind: "Type", ip: "IP", mac: "MAC", model: "Model", manufacturer: "Manufacturer", connection: "Connection",
      rate: "Link rate", rateMax: "Maximum", sync: "Sync rate", throughput: "Current throughput", lineMax: "Line capability",
      port: "Port", band: "Band", signal: "Signal", lqi: "LQI", ieee: "IEEE", nwk: "NWK", power: "Power source",
      location: "Location", detected: "Detected", sources: "Sources", scanners: "Bluetooth scanners", heard: "Also heard by",
      firmware: "Firmware", lastSeen: "Last seen", parent: "Placement",
    },
    w: {
      offline: "Device is offline.", weakLqi: (v, t) => `Weak Zigbee signal (LQI ${v}, threshold ${t}).`,
      weakRssi: (v, t) => `Weak signal (${v} dBm, threshold ${t} dBm).`,
      conflict: (n) => `Neighbor table and route disagree: the coordinator routes through ${n}.`,
      unknownParent: "Parent unknown, placed at the coordinator for now.",
    },
    parentHow: { route: "from routing table", neighbors: "from neighbor table", unknown: "unknown" },
    detectedBy: { fritz: "by the FRITZ!Box", inferred: (n) => `inferred, ${n} devices on one port`, config: "from network_topology.yaml" },
  },
};

const STYLE = `
  :host { display: block; }
  ha-card { overflow: hidden; display: flex; flex-direction: column; }
  .head { display: flex; flex-wrap: wrap; gap: 8px 16px; align-items: center; justify-content: space-between; padding: 16px 16px 8px; }
  .title { font-size: 1.25rem; font-weight: 500; color: var(--primary-text-color); }
  .sub { font-size: 0.8rem; color: var(--secondary-text-color); }
  .stats { display: flex; flex-wrap: wrap; gap: 6px; }
  .stat { font-size: 0.78rem; padding: 2px 9px; border-radius: 999px; border: 1px solid var(--divider-color); color: var(--primary-text-color); font-variant-numeric: tabular-nums; }
  .stat.warn { color: var(--warning-color, #ff9800); border-color: var(--warning-color, #ff9800); }
  .stat.busy { color: var(--primary-color); border-color: var(--primary-color); }
  .toolbar { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; padding: 4px 16px 10px; border-bottom: 1px solid var(--divider-color); }
  button { font: inherit; cursor: pointer; }
  .chip { display: inline-flex; align-items: center; gap: 7px; font-size: 0.82rem; padding: 4px 10px; border-radius: 999px; border: 1px solid var(--divider-color); background: transparent; color: var(--primary-text-color); }
  .chip[aria-pressed="false"] { opacity: 0.45; }
  .chip[aria-pressed="false"] .lbl { text-decoration: line-through; }
  .chip .sw { width: 20px; height: 0; border-top: 2.5px solid var(--c); }
  .chip .sw.wlan { border-top-style: dashed; } .chip .sw.zigbee { border-top-style: dotted; border-top-width: 3px; } .chip .sw.bluetooth { border-top-style: dashed; border-top-width: 2px; }
  .chip .n { font-size: 0.72rem; color: var(--secondary-text-color); }
  .toggle { font-size: 0.8rem; display: inline-flex; gap: 5px; align-items: center; color: var(--secondary-text-color); }
  .spacer { flex: 1; }
  input[type=search] { font: inherit; font-size: 0.85rem; padding: 4px 10px; border-radius: 6px; border: 1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-text-color); width: 160px; }
  .zoom { width: 30px; height: 28px; border-radius: 6px; border: 1px solid var(--divider-color); background: transparent; color: var(--primary-text-color); }
  .body { display: flex; flex-wrap: wrap; }
  .canvas { flex: 999 1 480px; min-width: 0; position: relative; overflow: hidden; touch-action: none; background: var(--secondary-background-color, transparent); }
  .canvas svg { display: block; width: 100%; height: 100%; cursor: grab; user-select: none; }
  .canvas svg.dragging { cursor: grabbing; }
  .msg { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; padding: 24px; text-align: center; color: var(--secondary-text-color); }
  .detail { flex: 1 1 280px; padding: 14px 16px; border-left: 1px solid var(--divider-color); display: flex; flex-direction: column; gap: 10px; min-width: 0; max-height: var(--nt-height); overflow: auto; }
  .d-name { font-size: 1.05rem; font-weight: 500; color: var(--primary-text-color); overflow-wrap: anywhere; }
  .tags { display: flex; flex-wrap: wrap; gap: 5px; }
  .tag { font-size: 0.7rem; padding: 1px 7px; border-radius: 5px; border: 1px solid var(--c, var(--divider-color)); color: var(--c, var(--secondary-text-color)); }
  dl { margin: 0; display: grid; grid-template-columns: auto 1fr; gap: 4px 12px; font-size: 0.84rem; }
  dt { color: var(--secondary-text-color); } dd { margin: 0; color: var(--primary-text-color); overflow-wrap: anywhere; }
  dd.mono { font-family: var(--code-font-family, monospace); font-size: 0.78rem; }
  .path { font-size: 0.8rem; color: var(--primary-text-color); padding: 8px 10px; border-radius: 8px; border: 1px solid var(--divider-color); }
  .path b { display: block; font-size: 0.7rem; font-weight: 500; color: var(--secondary-text-color); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 2px; }
  .note { font-size: 0.82rem; border-left: 3px solid var(--warning-color, #ff9800); padding-left: 8px; color: var(--primary-text-color); }
  .note.info { border-left-color: var(--primary-color); }
  .open { align-self: flex-start; font-size: 0.82rem; padding: 6px 12px; border-radius: 6px; border: 1px solid var(--primary-color); background: transparent; color: var(--primary-color); }
  .hint { font-size: 0.84rem; color: var(--secondary-text-color); }
  details.extra { border-top: 1px solid var(--divider-color); padding: 8px 16px; font-size: 0.84rem; color: var(--primary-text-color); }
  details.extra summary { cursor: pointer; color: var(--secondary-text-color); }
  details.extra ul { margin: 6px 0; padding-left: 18px; }
  details.extra li.off { color: var(--secondary-text-color); }
  [hidden] { display: none !important; }

  .edge { fill: none; stroke-width: 2; stroke: var(--c); }
  .edge.wlan { stroke-dasharray: 7 5; }
  .edge.zigbee { stroke-dasharray: 1.5 5; stroke-linecap: round; stroke-width: 2.6; }
  .edge.bluetooth { stroke-dasharray: 9 3 2 3; }
  .edge.wan { stroke-width: 3; }
  .edge.down { opacity: 0.35; }
  .edge.warn { stroke: var(--warning-color, #ff9800); }
  .edge.conflict { stroke: var(--error-color, #db4437); }
  .edge.on-path { stroke-width: 4; }
  .meshlink { fill: none; stroke: var(--c); stroke-width: 1; stroke-dasharray: 2 4; opacity: 0.45; }
  .elabel { font-size: 10.5px; fill: var(--secondary-text-color); paint-order: stroke; stroke: var(--secondary-background-color, var(--card-background-color)); stroke-width: 4px; stroke-linejoin: round; text-anchor: end; dominant-baseline: middle; font-variant-numeric: tabular-nums; }
  .node { cursor: pointer; }
  .node rect.box { fill: var(--card-background-color, #fff); stroke: var(--divider-color); stroke-width: 1.3; }
  .node.infra rect.box { stroke: var(--primary-text-color); stroke-width: 1.5; }
  .node.passive_switch rect.box { stroke: var(--c); stroke-dasharray: 5 4; }
  .node.off { opacity: 0.5; }
  .node.disabled { opacity: 0.4; }
  .node.disabled rect.box { stroke-dasharray: 2 3; }
  .node.sel rect.box { stroke: var(--primary-color); stroke-width: 2.6; stroke-dasharray: none; }
  .node:focus { outline: none; } .node:focus-visible rect.box { stroke: var(--primary-color); stroke-width: 2.6; }
  .node .nm { font-size: 13px; font-weight: 500; fill: var(--primary-text-color); }
  .node .sb { font-size: 10.5px; fill: var(--secondary-text-color); font-variant-numeric: tabular-nums; }
  .node .dot { fill: var(--c); }
  .node .flag { fill: var(--warning-color, #ff9800); }
  .node .tg circle { fill: var(--card-background-color, #fff); stroke: var(--divider-color); }
  .node .tg text { font-size: 11px; fill: var(--secondary-text-color); text-anchor: middle; dominant-baseline: central; }
  .node .tg:hover circle { stroke: var(--primary-color); }
  svg.has-sel .dim { opacity: 0.25; }
`;

const LAYER_COLOR = {
  lan: "var(--nt-lan, var(--blue-grey-color, #5b7fa8))",
  wan: "var(--nt-lan, var(--blue-grey-color, #5b7fa8))",
  wlan: "var(--nt-wlan, var(--teal-color, #009688))",
  zigbee: "var(--nt-zigbee, var(--amber-color, #e0a000))",
  usb: "var(--nt-zigbee, var(--amber-color, #e0a000))",
  bluetooth: "var(--nt-bluetooth, var(--indigo-color, #5c6bc0))",
};

function svgEl(tag, attrs, parent) {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) el.setAttribute(k, v);
  if (parent) parent.appendChild(el);
  return el;
}

function htmlEl(tag, props, parent) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (k === "text") el.textContent = v;
    else if (k === "cls") el.className = v;
    else if (k === "style") el.style.cssText = v;
    else el.setAttribute(k, v);
  }
  if (parent) parent.appendChild(el);
  return el;
}

/** Current link rate in kbit/s: the faster direction (link rates are asymmetric on Wi-Fi). */
function linkRate(l) {
  const v = [l?.rate_kbit, l?.rate_tx_kbit].filter((x) => typeof x === "number" && x > 0);
  return v.length ? Math.max(...v) : null;
}

/** 1000000 -> "1G", 866700 -> "867M", 54000 -> "54M", 512 -> "512k". */
function rateShort(kbit) {
  if (!kbit) return "";
  if (kbit >= 1e6) return `${+(kbit / 1e6).toFixed(kbit % 1e6 ? 1 : 0)}G`;
  if (kbit >= 1000) return `${Math.round(kbit / 1000)}M`;
  return `${Math.round(kbit)}k`;
}

/** kbit/s -> "1 Gbit/s", "866 Mbit/s". */
function rateLong(kbit, lang) {
  if (kbit == null) return null;
  const nf = (v, d) => v.toLocaleString(lang, { maximumFractionDigits: d });
  if (kbit >= 1e6) return `${nf(kbit / 1e6, 1)} Gbit/s`;
  if (kbit >= 1000) return `${nf(kbit / 1000, kbit >= 1e4 ? 0 : 1)} Mbit/s`;
  return `${nf(kbit, 0)} kbit/s`;
}

/** Stroke width for a link rate: 1 Mbit/s thin, 1 Gbit/s thick. */
function rateWidth(kbit) {
  return kbit ? Math.max(1.2, Math.min(6, 1.2 + Math.log10(kbit / 1000 + 1) * 1.6)) : null;
}

function clip(text, max) {
  text = String(text ?? "");
  return text.length > max ? text.slice(0, max - 1) + "…" : text;
}

class NetworkTopologyCard extends HTMLElement {
  static getStubConfig() {
    return {};
  }

  setConfig(config) {
    this._config = {
      height: 600, layers: ALL_LAYERS, show_mesh: false, hide_offline: false,
      warn_lqi_below: 100, warn_rssi_below: -80, collapsed: [], ...config,
    };
    this._filters = new Set(this._config.layers);
    this._collapsed = new Set(this._config.collapsed);
    this._showMesh = !!this._config.show_mesh;
    this._hideOffline = !!this._config.hide_offline;
    this._showSpeeds = !!this._config.show_speeds;
    this._vertical = this._config.layout === "vertical";
    this._fullHeight = this._config.height === "full";
    if (this._root) {
      this._applyHeight();
      this._fitted = false;
      this._update();
    }
  }

  /** Fixed px height, or "full": fill the window below the card's top edge. */
  _applyHeight() {
    if (!this._canvas) return;
    let h = Number(this._config.height) || 600;
    if (this._fullHeight) {
      const top = this._canvas.getBoundingClientRect().top;
      const below = (this._extra && !this._extra.hidden ? this._extra.offsetHeight : 0) + 16;
      // Before the first layout top is 0; fall back to a typical header height.
      h = Math.max(320, window.innerHeight - (top > 0 ? top : 150) - below);
    }
    if (h !== this._height) {
      this._height = h;
      this._canvas.style.height = `${h}px`;
      this._root.host.style.setProperty("--nt-height", `${h}px`);
    }
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) {
      this._t = STRINGS[(hass.language || "en").startsWith("de") ? "de" : "en"];
      this._build();
    }
    this._subscribe();
  }

  connectedCallback() {
    this._subscribe();
    if (!this._onResize) this._onResize = () => this._applyHeight();
    window.addEventListener("resize", this._onResize);
    // HA may still move the card while the view settles (header, sidebar, edit mode).
    requestAnimationFrame(() => this._applyHeight());
    for (const ms of [300, 1000, 2500]) setTimeout(() => this._applyHeight(), ms);
  }

  disconnectedCallback() {
    if (this._unsub) this._unsub.then((u) => u && u()).catch(() => {});
    this._unsub = null;
    if (this._onResize) window.removeEventListener("resize", this._onResize);
  }

  getCardSize() {
    return Math.ceil((Number(this._config?.height) || 800) / 50) + 3;
  }

  // Sections view: a full-height card spans the whole row.
  getGridOptions() {
    return { columns: "full", rows: this._fullHeight ? "auto" : Math.ceil((Number(this._config?.height) || 600) / 56) + 3 };
  }

  _subscribe() {
    if (this._unsub || !this._hass || !this.isConnected) return;
    if (this._retryAt && Date.now() < this._retryAt) return;
    this._unsub = this._hass.connection
      .subscribeMessage((data) => {
        this._data = data;
        this._error = null;
        this._update();
      }, { type: "network_topology/subscribe" })
      .catch((err) => {
        this._error = err?.message || String(err);
        this._unsub = null;
        this._retryAt = Date.now() + 30000;
        this._update();
        return null;
      });
  }

  // ---------------------------------------------------------------- DOM
  _build() {
    this._root = this.attachShadow({ mode: "open" });
    htmlEl("style", { text: STYLE }, this._root);
    const card = htmlEl("ha-card", {}, this._root);
    const t = this._t;

    const head = htmlEl("div", { cls: "head" }, card);
    const titleBox = htmlEl("div", {}, head);
    this._titleEl = htmlEl("div", { cls: "title", text: this._config.title || t.title }, titleBox);
    this._subEl = htmlEl("div", { cls: "sub" }, titleBox);
    this._statsEl = htmlEl("div", { cls: "stats" }, head);

    const bar = htmlEl("div", { cls: "toolbar" }, card);
    this._chips = {};
    for (const layer of ALL_LAYERS) {
      const b = htmlEl("button", { cls: "chip", "aria-pressed": String(this._filters.has(layer)), style: `--c:${LAYER_COLOR[layer]}` }, bar);
      htmlEl("span", { cls: `sw ${layer}` }, b);
      htmlEl("span", { cls: "lbl", text: t.layers[layer] }, b);
      const n = htmlEl("span", { cls: "n" }, b);
      b.addEventListener("click", () => {
        this._filters.has(layer) ? this._filters.delete(layer) : this._filters.add(layer);
        b.setAttribute("aria-pressed", String(this._filters.has(layer)));
        this._update();
      });
      this._chips[layer] = n;
    }
    const meshLbl = htmlEl("label", { cls: "toggle" }, bar);
    const meshCb = htmlEl("input", { type: "checkbox" }, meshLbl);
    meshCb.checked = this._showMesh;
    htmlEl("span", { text: t.mesh }, meshLbl);
    meshCb.addEventListener("change", () => { this._showMesh = meshCb.checked; this._update(); });
    const offLbl = htmlEl("label", { cls: "toggle" }, bar);
    const offCb = htmlEl("input", { type: "checkbox" }, offLbl);
    offCb.checked = this._hideOffline;
    htmlEl("span", { text: t.hideOffline }, offLbl);
    offCb.addEventListener("change", () => { this._hideOffline = offCb.checked; this._update(); });
    const spLbl = htmlEl("label", { cls: "toggle" }, bar);
    const spCb = htmlEl("input", { type: "checkbox" }, spLbl);
    spCb.checked = this._showSpeeds;
    htmlEl("span", { text: t.speeds }, spLbl);
    spCb.addEventListener("change", () => { this._showSpeeds = spCb.checked; this._update(); });
    htmlEl("span", { cls: "spacer" }, bar);
    const search = htmlEl("input", { type: "search", placeholder: t.search, "aria-label": t.search }, bar);
    search.addEventListener("keydown", (e) => { if (e.key === "Enter") this._search(search.value); });
    search.addEventListener("search", () => this._search(search.value));
    const dirBtn = htmlEl("button", { cls: "chip dir", title: t.direction, "aria-label": t.direction }, bar);
    const dirIcon = () => { dirBtn.textContent = this._vertical ? `↕ ${t.vertical}` : `↔ ${t.horizontal}`; };
    dirIcon();
    dirBtn.addEventListener("click", () => {
      this._vertical = !this._vertical;
      dirIcon();
      this._update();
      this._fit(true);
    });
    for (const [label, title, fn] of [["−", t.zoomOut, () => this._zoomBy(1 / 1.25)], ["+", t.zoomIn, () => this._zoomBy(1.25)], ["⤢", t.fit, () => this._fit()]]) {
      const zb = htmlEl("button", { cls: "zoom", title, "aria-label": title, text: label }, bar);
      zb.addEventListener("click", fn);
    }

    const body = htmlEl("div", { cls: "body" }, card);
    this._canvas = htmlEl("div", { cls: "canvas" }, body);
    this._svg = svgEl("svg", { role: "img" }, this._canvas);
    this._vp = svgEl("g", {}, this._svg);
    this._gMesh = svgEl("g", {}, this._vp);
    this._gEdges = svgEl("g", {}, this._vp);
    this._gLabels = svgEl("g", {}, this._vp);
    this._gNodes = svgEl("g", {}, this._vp);
    this._msg = htmlEl("div", { cls: "msg", text: t.loading }, this._canvas);
    this._detail = htmlEl("aside", { cls: "detail", "aria-live": "polite" }, body);
    this._extra = htmlEl("details", { cls: "extra" }, card);

    this._view = { k: 1, x: 20, y: 20 };
    this._applyHeight();
    this._initPanZoom();
  }

  _initPanZoom() {
    const svg = this._svg;
    let drag = null;
    svg.addEventListener("wheel", (e) => {
      e.preventDefault();
      const r = svg.getBoundingClientRect();
      this._zoomAt(Math.exp(-e.deltaY * 0.0015), e.clientX - r.left, e.clientY - r.top);
    }, { passive: false });
    svg.addEventListener("pointerdown", (e) => {
      if (e.button !== 0 || e.target.closest(".node")) return;
      drag = { x: e.clientX, y: e.clientY, vx: this._view.x, vy: this._view.y, moved: false };
      svg.setPointerCapture(e.pointerId);
      svg.classList.add("dragging");
    });
    svg.addEventListener("pointermove", (e) => {
      if (!drag) return;
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
      this._view.x = drag.vx + dx;
      this._view.y = drag.vy + dy;
      this._applyView();
    });
    const end = (e) => {
      if (!drag) return;
      if (!drag.moved && !e.target.closest?.(".node")) { this._selected = null; this._update(); }
      drag = null;
      svg.classList.remove("dragging");
    };
    svg.addEventListener("pointerup", end);
    svg.addEventListener("pointercancel", end);
  }

  _applyView() {
    const { k, x, y } = this._view;
    this._vp.setAttribute("transform", `translate(${x},${y}) scale(${k})`);
  }

  _zoomAt(factor, px, py) {
    const v = this._view;
    const k = Math.min(2.5, Math.max(0.15, v.k * factor));
    v.x = px - ((px - v.x) * k) / v.k;
    v.y = py - ((py - v.y) * k) / v.k;
    v.k = k;
    this._applyView();
  }

  _zoomBy(factor) {
    const r = this._svg.getBoundingClientRect();
    this._zoomAt(factor, r.width / 2, r.height / 2);
  }

  _fit(readable = false) {
    if (!this._bounds) return;
    const r = this._svg.getBoundingClientRect();
    const b = this._bounds;
    const w = b.x2 - b.x1 + 40, h = b.y2 - b.y1 + 40;
    const fitK = Math.min(r.width / w, r.height / h);
    if (readable && fitK < 0.55) {
      // Large network: start readable at the root instead of a tiny overview.
      const k = 0.55;
      const root = this._pos.get(this._rootId) || { x: b.x1, y: (b.y1 + b.y2) / 2 };
      this._view = this._vertical
        ? { k, x: r.width / 2 - (root.x + NODE_W / 2) * k, y: 20 - (root.y - NODE_H / 2) * k }
        : { k, x: 20 - root.x * k, y: r.height / 2 - root.y * k };
    } else {
      const k = Math.min(1.2, Math.max(0.1, fitK));
      this._view = { k, x: (r.width - w * k) / 2 - (b.x1 - 20) * k, y: (r.height - h * k) / 2 - (b.y1 - 20) * k };
    }
    this._applyView();
  }

  _center(id) {
    const p = this._pos?.get(id);
    if (!p) return;
    const r = this._svg.getBoundingClientRect();
    const k = Math.max(this._view.k, 0.8);
    this._view = { k, x: r.width / 2 - (p.x + NODE_W / 2) * k, y: r.height / 2 - p.y * k };
    this._applyView();
  }

  // ---------------------------------------------------------------- model
  _model() {
    const d = this._data;
    const nodes = new Map(d.nodes.map((n) => [n.id, n]));
    const parentLink = new Map();
    const children = new Map();
    for (const l of d.links) {
      if (!nodes.has(l.source) || !nodes.has(l.target) || parentLink.has(l.target)) continue;
      parentLink.set(l.target, l);
      if (!children.has(l.source)) children.set(l.source, []);
      children.get(l.source).push(l);
    }
    const order = (id) => {
      const k = KIND_ORDER.indexOf(nodes.get(id).kind);
      return k < 0 ? 99 : k;
    };
    for (const list of children.values()) {
      list.sort((a, b) => order(a.target) - order(b.target) || (nodes.get(a.target).name || "").localeCompare(nodes.get(b.target).name || ""));
    }
    const roots = [...nodes.keys()].filter((id) => !parentLink.has(id) && (children.has(id) || id === "internet"));
    roots.sort((a, b) => (a === "internet" ? -1 : b === "internet" ? 1 : 0) || (nodes.get(a).name || "").localeCompare(nodes.get(b).name || ""));
    return { nodes, parentLink, children, roots };
  }

  _warnings(node, link) {
    if (node.attrs?.disabled) return [];
    const w = this._t.w, c = this._config, out = [];
    if (node.online === false) out.push(w.offline);
    if (link?.lqi != null && link.lqi < c.warn_lqi_below) out.push(w.weakLqi(link.lqi, c.warn_lqi_below));
    if (link?.rssi != null && link.rssi < c.warn_rssi_below) out.push(w.weakRssi(link.rssi, c.warn_rssi_below));
    if (link?.attrs?.route_conflict) out.push(w.conflict(this._m.nodes.get(link.attrs.route_conflict)?.name || link.attrs.route_conflict));
    if (link?.attrs?.parent === "unknown") out.push(w.unknownParent);
    return out;
  }

  _countDesc(id, m, seen = new Set()) {
    let n = 0;
    for (const l of m.children.get(id) || []) {
      if (seen.has(l.target)) continue;
      seen.add(l.target);
      n += 1 + this._countDesc(l.target, m, seen);
    }
    return n;
  }

  _visibleTree(m) {
    const seen = new Set();
    const visit = (id, link, isRoot) => {
      if (seen.has(id)) return null;
      seen.add(id);
      const node = m.nodes.get(id);
      const collapsed = this._collapsed.has(id);
      const kids = collapsed ? [] : (m.children.get(id) || []).map((l) => visit(l.target, l, false)).filter(Boolean);
      const layerOn = isRoot || this._filters.has(LINK_FILTER[link.layer] || "lan");
      // Disabled in HA and currently gone (e.g. unplugged): not worth a box.
      const offHidden = node.online === false && (this._hideOffline || node.attrs?.disabled);
      if ((layerOn && !offHidden) || kids.length) {
        return { id, node, link, kids, total: (m.children.get(id) || []).length ? this._countDesc(id, m) : 0, collapsed };
      }
      return null;
    };
    return m.roots.map((id) => visit(id, null, true)).filter(Boolean);
  }

  _layout(trees) {
    // pos: x = left edge, y = vertical center, entry = where the edge enters the node.
    const pos = this._vertical ? this._layoutVertical(trees) : this._layoutHorizontal(trees);
    this._finishLayout(pos);
  }

  _layoutHorizontal(trees) {
    const pos = new Map();
    let next = 0;
    const place = (t, depth) => {
      let y;
      if (!t.kids.length) {
        y = next * ROW;
        next += 1;
      } else {
        t.kids.forEach((k) => place(k, depth + 1));
        y = (pos.get(t.kids[0].id).y + pos.get(t.kids[t.kids.length - 1].id).y) / 2;
      }
      pos.set(t.id, { x: depth * COL, y, entry: "left" });
    };
    for (const t of trees) {
      place(t, 0);
      next += 0.6;
    }
    return pos;
  }

  _layoutVertical(trees) {
    // Top-down. Leaf children (3 or more) are stacked as a list below their
    // parent, so wide fan-outs (Wi-Fi clients, Zigbee end devices) stay narrow.
    const pos = new Map();
    let slot = 0;
    const place = (t, depth) => {
      const top = depth * LEVEL;
      const leaves = t.kids.filter((k) => !k.kids.length);
      const stack = leaves.length >= 3;
      const centers = [];
      let center = null;
      if (stack) {
        // The parent sits directly above its first stack column; the list hangs
        // on a rail below it, branch children continue to the right.
        center = slot;
        for (let i = 0; i < leaves.length; i += STACK_MAX) {
          leaves.slice(i, i + STACK_MAX).forEach((leaf, j) => {
            pos.set(leaf.id, { x: slot * SLOT + STACK_INDENT, y: top + LEVEL * 0.85 + j * STACK_ROW, entry: "left", rail: slot * SLOT + RAIL_X });
          });
          slot += 1;
        }
      }
      for (const k of stack ? t.kids.filter((k) => k.kids.length) : t.kids) centers.push(place(k, depth + 1));
      if (center === null) {
        if (!centers.length) {
          center = slot;
          slot += 1;
        } else {
          center = (Math.min(...centers) + Math.max(...centers)) / 2;
        }
      }
      pos.set(t.id, { x: center * SLOT + NODE_X, y: top, entry: "top" });
      return center;
    };
    for (const t of trees) {
      place(t, 0);
      slot += 0.4;
    }
    return pos;
  }

  _finishLayout(pos) {
    let x1 = Infinity, y1 = Infinity, x2 = -Infinity, y2 = -Infinity;
    for (const p of pos.values()) {
      x1 = Math.min(x1, p.x); x2 = Math.max(x2, p.x + NODE_W);
      y1 = Math.min(y1, p.y - NODE_H / 2); y2 = Math.max(y2, p.y + NODE_H / 2);
    }
    this._pos = pos;
    this._bounds = pos.size ? { x1, y1, x2, y2 } : null;
  }

  // ---------------------------------------------------------------- render
  _update() {
    if (!this._root) return;
    const t = this._t;
    if (!this._data) {
      this._msg.hidden = false;
      this._msg.textContent = this._error ? `${t.notLoaded} (${this._error})` : t.loading;
      this._renderDetail();
      return;
    }
    this._msg.hidden = true;
    const m = (this._m = this._model());
    const trees = this._visibleTree(m);
    this._layout(trees);
    this._draw(trees, m);
    this._renderHead(m);
    this._renderDetail();
    this._renderExtra(m);
    this._applyHeight();
    if (!this._fitted && this._bounds) {
      this._fitted = true;
      this._rootId = trees[0]?.id;
      requestAnimationFrame(() => this._fit(true));
    }
  }

  _subLine(n, link) {
    const t = this._t;
    if (n.kind === "passive_switch") return [t.kinds.passive_switch, n.attrs?.uplink?.split(":").pop()].filter(Boolean).join(" · ");
    if (n.kind?.startsWith("zigbee")) return [t.kinds[n.kind].replace("Zigbee-", "").replace("Zigbee ", ""), link?.lqi != null ? `LQI ${link.lqi}` : null].filter(Boolean).join(" · ");
    if (n.kind === "bluetooth_device") return ["BLE", link?.rssi != null ? `${link.rssi} dBm` : null].filter(Boolean).join(" · ");
    if (n.attrs?.disabled) return t.disabled;
    if (n.online === false) return t.offline;
    if (this._showSpeeds && link && ["lan", "wlan"].includes(link.layer) && linkRate(link)) return [n.ip, rateLong(linkRate(link), this._hass.language)].filter(Boolean).join(" · ");
    return n.ip || n.model || t.kinds[n.kind] || "";
  }

  _edgeLabel(l) {
    const speed = this._showSpeeds ? rateShort(linkRate(l)) : null;
    if (l.layer === "wan") return this._showSpeeds && l.rate_kbit ? `↓${rateShort(l.rate_kbit)} ↑${rateShort(l.rate_tx_kbit)}` : "";
    if (l.layer === "lan") return [l.port, speed].filter(Boolean).join(" · ");
    if (l.layer === "wlan") return [[l.band ? `${l.band.replace(".", ",")}G` : null, l.rssi != null ? `${l.rssi}` : null].filter(Boolean).join(" "), speed].filter(Boolean).join(" · ");
    if (l.layer === "zigbee" && l.lqi != null) return `LQI ${l.lqi}`;
    if (l.layer === "bluetooth" && l.rssi != null) return `${l.rssi} dBm`;
    if (l.layer === "usb") return l.attrs?.radio === "network" ? "LAN" : "USB";
    return "";
  }

  _draw(trees, m) {
    for (const g of [this._gMesh, this._gEdges, this._gLabels, this._gNodes]) g.replaceChildren();
    const pos = this._pos;
    const sel = this._selected && pos.has(this._selected) ? this._selected : null;
    const onPath = new Set();
    if (sel) {
      let cur = sel;
      onPath.add(cur);
      while (m.parentLink.has(cur)) { cur = m.parentLink.get(cur).source; onPath.add(cur); }
    }
    this._svg.classList.toggle("has-sel", !!sel);

    if (this._showMesh) {
      for (const l of this._data.mesh || []) {
        const a = pos.get(l.source), b = pos.get(l.target);
        if (!a || !b || !this._filters.has(LINK_FILTER[l.layer])) continue;
        const ax = a.x + NODE_W / 2, bx = b.x + NODE_W / 2;
        const bend = Math.min(120, Math.abs(a.y - b.y) * 0.3 + 30);
        svgEl("path", { d: `M${ax},${a.y} C${ax + bend},${a.y} ${bx + bend},${b.y} ${bx},${b.y}`, class: "meshlink", style: `--c:${LAYER_COLOR[l.layer]}` }, this._gMesh);
      }
    }

    const walk = (t) => {
      const n = t.node, p = pos.get(t.id);
      if (t.link && pos.has(t.link.source)) {
        const s = pos.get(t.link.source);
        const g = this._edgeGeometry(s, p);
        const warn = this._warnings(n, t.link).length && n.online !== false;
        const cls = ["edge", t.link.layer, t.link.connected === false ? "down" : "", t.link.attrs?.route_conflict ? "conflict" : warn ? "warn" : "", onPath.has(t.id) ? "on-path" : "", sel && !onPath.has(t.id) ? "dim" : ""].join(" ");
        const width = this._showSpeeds && ["wan", "lan", "wlan"].includes(t.link.layer) ? rateWidth(linkRate(t.link)) : null;
        svgEl("path", { d: g.d, class: cls, style: `--c:${LAYER_COLOR[t.link.layer] || LAYER_COLOR.lan}${width ? `;stroke-width:${width.toFixed(1)}` : ""}` }, this._gEdges);
        const label = this._edgeLabel(t.link);
        if (label) {
          // Next to the child, where every row has its own space (no pile-up at fan-outs).
          const tl = svgEl("text", { x: g.lx, y: g.ly, class: `elabel${sel && !onPath.has(t.id) ? " dim" : ""}`, style: `text-anchor:${g.anchor}` }, this._gLabels);
          tl.textContent = label;
        }
      }
      this._drawNode(t, p, sel, onPath);
      t.kids.forEach(walk);
    };
    trees.forEach(walk);
  }

  _edgeGeometry(s, p) {
    if (!this._vertical) {
      const sx = s.x + NODE_W, tx = p.x, mx = (sx + tx) / 2;
      return { d: `M${sx},${s.y} C${mx},${s.y} ${mx},${p.y} ${tx},${p.y}`, lx: tx - 5, ly: p.y - 7, anchor: "end" };
    }
    const sx = s.x + NODE_W / 2, sy = s.y + NODE_H / 2;
    if (p.entry === "left") {
      // Stacked leaf: down the rail below the parent, then right into the leaf.
      // Further stack columns branch off the first rail just below the parent.
      const rail = p.rail ?? p.x - 24, ty = p.y, start = s.x + (RAIL_X - NODE_X), jog = sy + 14;
      return {
        d: `M${start},${sy} V${jog} H${rail} V${ty - 6} Q${rail},${ty} ${rail + 6},${ty} H${p.x}`,
        lx: rail - 4, ly: ty - 6, anchor: "end",
      };
    }
    const tx = p.x + NODE_W / 2, ty = p.y - NODE_H / 2, my = (sy + ty) / 2;
    return { d: `M${sx},${sy} C${sx},${my} ${tx},${my} ${tx},${ty}`, lx: tx + 6, ly: ty - 9, anchor: "start" };
  }

  _drawNode(t, p, sel, onPath) {
    const n = t.node;
    const layer = LINK_FILTER[t.link?.layer] || (n.kind?.startsWith("zigbee") ? "zigbee" : n.kind?.startsWith("bluetooth") ? "bluetooth" : "lan");
    const warn = this._warnings(n, t.link).length > 0;
    const cls = ["node", n.kind, INFRA.has(n.kind) ? "infra" : "", n.attrs?.disabled ? "disabled" : n.online === false ? "off" : "", t.id === sel ? "sel" : "", sel && !onPath.has(t.id) ? "dim" : ""].join(" ");
    const g = svgEl("g", { class: cls, transform: `translate(${p.x},${p.y - NODE_H / 2})`, tabindex: "0", role: "button", "aria-label": n.name, style: `--c:${LAYER_COLOR[layer]}` }, this._gNodes);
    svgEl("rect", { class: "box", width: NODE_W, height: NODE_H, rx: 9 }, g);
    svgEl("circle", { class: "dot", cx: 14, cy: NODE_H / 2, r: 4.5 }, g);
    const extra = (n.layers || []).filter((l) => l !== layer && LAYER_COLOR[l]);
    extra.forEach((l, i) => svgEl("circle", { class: "dot", cx: 14, cy: NODE_H / 2 + 11 + i * 7, r: 2.6, style: `--c:${LAYER_COLOR[l]}` }, g));
    const nm = svgEl("text", { class: "nm", x: 26, y: 19 }, g);
    nm.textContent = clip(n.name, 21);
    const sb = svgEl("text", { class: "sb", x: 26, y: 35 }, g);
    sb.textContent = clip(this._subLine(n, t.link), 27);
    const title = svgEl("title", {}, g);
    title.textContent = n.name;
    if (warn) svgEl("circle", { class: "flag", cx: NODE_W - 9, cy: 9, r: 4.5 }, g);
    if (t.total) {
      const at = this._vertical ? `${NODE_W / 2},${NODE_H}` : `${NODE_W},${NODE_H / 2}`;
      const tg = svgEl("g", { class: "tg", transform: `translate(${at})` }, g);
      svgEl("circle", { r: t.collapsed ? 11 : 8 }, tg);
      const tt = svgEl("text", {}, tg);
      tt.textContent = t.collapsed ? `+${t.total}` : "−";
      const tl = svgEl("title", {}, tg);
      tl.textContent = t.collapsed ? this._t.expand : this._t.collapse;
      tg.addEventListener("click", (e) => {
        e.stopPropagation();
        this._collapsed.has(t.id) ? this._collapsed.delete(t.id) : this._collapsed.add(t.id);
        this._update();
      });
    }
    const select = () => { this._selected = t.id; this._update(); };
    g.addEventListener("click", select);
    g.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(); } });
  }

  _renderHead(m) {
    const t = this._t;
    const devices = [...m.nodes.values()].filter((n) => !INFRA.has(n.kind) && !n.attrs?.disabled);
    const on = devices.filter((n) => n.online !== false).length;
    let warns = 0;
    for (const n of m.nodes.values()) if (this._warnings(n, m.parentLink.get(n.id)).length) warns += 1;
    const stats = [[`${on} ${t.online}`, ""], [`${devices.length - on} ${t.offline}`, ""], [`${warns} ${t.warnings}`, warns ? "warn" : ""]];
    if (this._data.zigbee_rescan?.running) stats.push([t.rescan, "busy"]);
    this._statsEl.replaceChildren(...stats.map(([text, cls]) => htmlEl("span", { cls: `stat ${cls}`, text })));
    const time = this._data.generated ? new Date(this._data.generated).toLocaleTimeString(this._hass.language || undefined) : "";
    this._subEl.textContent = time ? `${t.updated} ${time}` : "";
    const counts = { lan: 0, wlan: 0, zigbee: 0, bluetooth: 0 };
    for (const n of devices) {
      const l = LINK_FILTER[m.parentLink.get(n.id)?.layer];
      if (l in counts) counts[l] += 1;
    }
    for (const [l, el] of Object.entries(this._chips)) el.textContent = counts[l];
  }

  _renderDetail() {
    const t = this._t, d = this._detail;
    d.replaceChildren();
    const node = this._selected && this._m?.nodes.get(this._selected);
    if (!node) {
      htmlEl("div", { cls: "d-name", text: t.noSelection }, d);
      htmlEl("div", { cls: "hint", text: t.noSelectionHint }, d);
      return;
    }
    const m = this._m, link = m.parentLink.get(node.id), a = node.attrs || {};
    htmlEl("div", { cls: "d-name", text: node.name }, d);
    const tags = htmlEl("div", { cls: "tags" }, d);
    for (const l of node.layers || []) if (LAYER_COLOR[l]) htmlEl("span", { cls: "tag", text: t.layers[l] || l, style: `--c:${LAYER_COLOR[l]}` }, tags);
    if (node.attrs?.disabled) htmlEl("span", { cls: "tag", text: t.disabled }, tags);
    else if (node.online === false) htmlEl("span", { cls: "tag", text: t.offline }, tags);

    const rows = [];
    const add = (k, v, mono) => { if (v !== undefined && v !== null && v !== "") rows.push([k, String(v), mono]); };
    add(t.f.kind, t.kinds[node.kind] || node.kind);
    add(t.f.ip, node.ip, true);
    add(t.f.mac, node.mac, true);
    add(t.f.ieee, a.ieee, true);
    add(t.f.nwk, a.nwk, true);
    add(t.f.manufacturer, a.manufacturer);
    add(t.f.model, node.model);
    add(t.f.firmware, a.firmware);
    add(t.f.location, a.location);
    add(t.f.power, a.power_source);
    if (link) {
      add(t.f.connection, [t.layers[LINK_FILTER[link.layer]] || link.layer, m.nodes.get(link.source)?.name].filter(Boolean).join(" · "));
      add(t.f.port, link.port || link.attrs?.via_port);
      if (link.band) add(t.f.band, `${link.band.replace(".", ",")} GHz${link.attrs?.ssid ? ` · ${link.attrs.ssid}` : ""}`);
      if (link.rssi != null) add(t.f.signal, `${link.rssi} dBm`);
      if (link.lqi != null) add(t.f.lqi, link.lqi);
      const lang = this._hass.language;
      if (link.layer === "wan") {
        if (link.rate_kbit) add(t.f.sync, `↓ ${rateLong(link.rate_kbit, lang)} · ↑ ${rateLong(link.rate_tx_kbit, lang)}`);
        if (link.max_rate_kbit) add(t.f.lineMax, rateLong(link.max_rate_kbit, lang));
        const a2 = link.attrs || {};
        if (a2.rate_down_bps != null) add(t.f.throughput, `↓ ${rateLong(a2.rate_down_bps / 1000, lang)} · ↑ ${rateLong((a2.rate_up_bps || 0) / 1000, lang)}`);
      } else if (link.rate_kbit || link.rate_tx_kbit) {
        const parts = [link.rate_kbit, link.rate_tx_kbit].filter((v) => v).map((v) => rateLong(v, lang));
        add(t.f.rate, [...new Set(parts)].join(" / "));
        if (link.max_rate_kbit && link.max_rate_kbit !== linkRate(link)) add(t.f.rateMax, rateLong(link.max_rate_kbit, lang));
      }
      if (link.attrs?.parent) add(t.f.parent, t.parentHow[link.attrs.parent] || link.attrs.parent);
    }
    if (node.kind === "passive_switch") {
      const how = (node.sources || []).map((s) => (s === "inferred" ? t.detectedBy.inferred(a.inferred_from_devices || "?") : t.detectedBy[s])).filter(Boolean);
      add(t.f.detected, how.join(", "));
    }
    if (a.bluetooth_scanners) add(t.f.scanners, a.bluetooth_scanners.map((s) => s.name || s.source).join(", "));
    if (a.heard_by?.length > 1) add(t.f.heard, a.heard_by.slice(1).map((h) => `${m.nodes.get(h.node)?.name || h.node} (${h.rssi} dBm)`).join(", "));
    if (a.last_seen) add(t.f.lastSeen, String(a.last_seen).replace("T", " ").slice(0, 16));
    add(t.f.sources, (node.sources || []).join(" + "));
    const dl = htmlEl("dl", {}, d);
    for (const [k, v, mono] of rows) {
      htmlEl("dt", { text: k }, dl);
      htmlEl("dd", { text: v, cls: mono ? "mono" : "" }, dl);
    }

    if (link) {
      const names = [node.name];
      let cur = node.id;
      const seen = new Set([cur]);
      while (m.parentLink.has(cur)) {
        cur = m.parentLink.get(cur).source;
        if (seen.has(cur)) break;
        seen.add(cur);
        names.push(m.nodes.get(cur)?.name || cur);
      }
      const path = htmlEl("div", { cls: "path" }, d);
      htmlEl("b", { text: t.path }, path);
      htmlEl("span", { text: names.reverse().join(" → ") }, path);
    }
    for (const w of this._warnings(node, link)) htmlEl("div", { cls: "note", text: w }, d);
    if (node.attrs?.disabled) htmlEl("div", { cls: "note info", text: t.disabledHint }, d);

    if (a.ha_device_id) {
      const b = htmlEl("button", { cls: "open", text: t.openDevice }, d);
      b.addEventListener("click", () => {
        history.pushState(null, "", `/config/devices/device/${a.ha_device_id}`);
        window.dispatchEvent(new CustomEvent("location-changed"));
      });
    }
  }

  _renderExtra(m) {
    const t = this._t, el = this._extra;
    const open = el.open;
    el.replaceChildren();
    const warnings = this._data.warnings || [];
    const unlinked = (this._data.unlinked || []).map((id) => m.nodes.get(id)).filter((n) => n && !m.roots.includes(n.id));
    el.hidden = !warnings.length && !unlinked.length;
    htmlEl("summary", { text: `${t.hints} (${warnings.length}) · ${t.unlinked} (${unlinked.length})` }, el);
    if (warnings.length) {
      const ul = htmlEl("ul", {}, el);
      for (const w of warnings) htmlEl("li", { text: w }, ul);
    }
    if (unlinked.length) {
      htmlEl("div", { text: `${t.unlinked}:` }, el);
      const ul = htmlEl("ul", {}, el);
      for (const n of unlinked.sort((a, b) => (a.name || "").localeCompare(b.name || ""))) {
        htmlEl("li", { text: `${n.name}${n.online === false ? ` (${t.offline})` : ""}`, cls: n.online === false ? "off" : "" }, ul);
      }
    }
    el.open = open;
  }

  _search(query) {
    const q = String(query || "").trim().toLowerCase();
    if (!q || !this._m) return;
    const m = this._m;
    const hit = [...m.nodes.values()].find((n) => (n.name || "").toLowerCase().includes(q) || (n.ip || "") === q || (n.mac || "") === q);
    if (!hit) {
      this._subEl.textContent = this._t.notFound;
      return;
    }
    // Make it visible: open collapsed ancestors and its layer.
    let cur = hit.id;
    const l = m.parentLink.get(cur);
    if (l) this._filters.add(LINK_FILTER[l.layer]);
    while (m.parentLink.has(cur)) {
      cur = m.parentLink.get(cur).source;
      this._collapsed.delete(cur);
    }
    if (this._hideOffline && hit.online === false) this._hideOffline = false;
    for (const [layer, n] of Object.entries(this._chips)) n.parentElement.setAttribute("aria-pressed", String(this._filters.has(layer)));
    this._selected = hit.id;
    this._update();
    this._center(hit.id);
  }
}

if (!customElements.get("network-topology-card")) {
  customElements.define("network-topology-card", NetworkTopologyCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "network-topology-card",
    name: "Network Topology",
    description: "LAN, WLAN, Zigbee and Bluetooth as one tree (network_topology integration).",
    preview: false,
  });
  console.info(`%c NETWORK-TOPOLOGY-CARD %c ${CARD_VERSION} `, "background:#3b5b86;color:#fff", "");
}
