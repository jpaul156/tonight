// ============================================================
// Tonight — front end logic
// Loads data/events.json, renders the feed, wires up filter
// chips, and handles the event detail overlay.
// ============================================================

const ICONS = {
  music: `<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>`,
  trivia: `<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 0 1 5 0c0 1.5-1.5 2-2.5 3"/><line x1="12" y1="17" x2="12" y2="17.01"/>`,
  comedy: `<path d="M9 9a3 3 0 1 1 6 0c0 2-3 3-3 5"/><line x1="12" y1="17" x2="12" y2="17.01"/><circle cx="12" cy="12" r="9"/>`,
  film: `<rect x="3" y="5" width="18" height="14" rx="1"/><line x1="7" y1="5" x2="7" y2="19"/><line x1="17" y1="5" x2="17" y2="19"/><line x1="3" y1="10" x2="7" y2="10"/><line x1="17" y1="10" x2="21" y2="10"/><line x1="3" y1="15" x2="7" y2="15"/><line x1="17" y1="15" x2="21" y2="15"/>`,
  market: `<path d="M4 8h16l-1.5 11a1 1 0 0 1-1 1H6.5a1 1 0 0 1-1-1L4 8z"/><path d="M8 8V6a4 4 0 0 1 8 0v2"/>`,
  karaoke: `<rect x="9" y="2" width="6" height="11" rx="3"/><path d="M5 10a7 7 0 0 0 14 0"/><line x1="12" y1="17" x2="12" y2="21"/><line x1="9" y1="21" x2="15" y2="21"/>`,
  community: `<path d="M4 19V5a2 2 0 0 1 2-2h9l5 5v11a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z"/><line x1="8" y1="8" x2="14" y2="8"/><line x1="8" y1="12" x2="16" y2="12"/><line x1="8" y1="16" x2="13" y2="16"/>`,
  food: `<path d="M3 2v7a3 3 0 0 0 3 3v10"/><path d="M6 2v6"/><path d="M9 2v6"/><path d="M18 2c-1.7 0-3 2-3 5s1.3 4 3 4v11"/>`
};

// ============================================================
// Transit model — the location filter is built like a metro map.
// Each line is an ordered list of stops (north/west → south/east).
// A handful of those stops are "squares" we actually surface as
// filters (they have events); the rest are connectors that exist
// only so the map shows real neighbors above and below your stop.
// A stop's line(s) — and therefore its color(s) — are *derived*
// from membership here, never stored, mirroring how transit_color
// is derived from transit_line elsewhere.
// ============================================================
// Each key is a *route* — a full end-to-end ride, north/west → south/east —
// imported from prototype/stations.csv (only its Include=TRUE stops, plus any
// stop that has events). Branching lines (Red, Green) get one route per branch
// because a single vertical strip can't show a fork; they share a brand color.
// Lechmere is Include=FALSE in the CSV but kept because it has events — see the
// SQUARE filter rule below (a stop is only a *filter* if events happen there).
const LINES = {
  "Red":          ["Alewife", "Davis", "Porter", "Harvard", "Central", "Kendall/MIT", "Charles/MGH", "Park Street", "Downtown Crossing", "South Station", "Broadway", "JFK/UMass", "Wollaston", "Quincy Center", "Braintree"],
  "Red (Ashmont)":["Alewife", "Davis", "Porter", "Harvard", "Central", "Kendall/MIT", "Charles/MGH", "Park Street", "Downtown Crossing", "South Station", "Broadway", "JFK/UMass", "Fields Corner", "Ashmont"],
  "Orange":       ["Oak Grove", "Malden Center", "Assembly", "Sullivan Square", "North Station", "Haymarket", "State", "Downtown Crossing", "Chinatown", "Tufts Medical Center", "Back Bay", "Forest Hills"],
  "Green (B)":    ["Government Center", "Park Street", "Boylston", "Copley", "Kenmore", "Babcock Street", "Harvard Avenue", "Boston College"],
  "Green (C)":    ["Government Center", "Park Street", "Boylston", "Copley", "Kenmore", "Coolidge Corner", "Washington Square", "Cleveland Circle"],
  "Green (D)":    ["Lechmere", "Government Center", "Park Street", "Boylston", "Copley", "Kenmore", "Fenway", "Brookline Village", "Reservoir", "Newton Centre"],
  "Green (E)":    ["Lechmere", "Government Center", "Park Street", "Boylston", "Copley", "Symphony", "Brigham Circle"],
  "Blue":         ["Wonderland", "Maverick", "Aquarium", "State", "Government Center"],
};

// Route → brand color name. Branch routes ("Red (Ashmont)", "Green (D)") all
// fold back to their trunk color, so the map never invents a new hue.
const LINE_BASE = {
  "Red": "Red", "Red (Ashmont)": "Red",
  "Orange": "Orange",
  "Green (B)": "Green", "Green (C)": "Green", "Green (D)": "Green", "Green (E)": "Green",
  "Blue": "Blue",
};

// Friendlier display labels for a few stops (the CSV's "Alt Square Name").
// Cosmetic only — events still store the canonical station name in e.square.
const STATION_ALIASES = {
  "Broadway": "Southie",
  "Sullivan Square": "East Somerville",
  "Kenmore": "Fenway Park",
  "Babcock Street": "BU",
  "Harvard Avenue": "Allston",
};
function stationLabel(name) {
  return STATION_ALIASES[name] || name;
}

// Tab order in the metro overlay (one tab per route).
const LINE_ORDER = ["Red", "Red (Ashmont)", "Orange", "Green (B)", "Green (C)", "Green (D)", "Green (E)", "Blue"];
// Brand-color order, used when collapsing a stop's routes down to colored dots.
const BASE_LINE_ORDER = ["Red", "Orange", "Green", "Blue"];

// Routes a stop sits on (used to pick which tab to open).
function routesForStation(name) {
  return LINE_ORDER.filter(route => LINES[route].includes(name));
}
// Distinct brand colors a stop sits on, for badges/dots — so a stop on two
// Green branches reads as one Green dot, not two.
function stationLines(name) {
  const bases = new Set(routesForStation(name).map(r => LINE_BASE[r]));
  return BASE_LINE_ORDER.filter(b => bases.has(b));
}

// Stops that are actually offered as filters: only those where events happen.
// Populated from loaded events (incl. food deals) in init() — a stop with no
// events shows on the map as a connector but can't be selected.
let eventSquares = new Set();

const CATEGORIES = ["music", "trivia", "comedy", "film", "market", "karaoke", "community", "sports", "fitness", "food"];

// MBTA line/mode → brand color. Color is presentation, derived from the line
// name at render time, so the data only stores the fact (which line) and never
// a hex. A known line therefore can never render the wrong color.
const LINE_COLORS = {
  Red: "#DA291C",
  Orange: "#ED8B00",
  Green: "#00843D",
  Blue: "#003DA5",
  Silver: "#7C878E",
  Bus: "#FFC72C",            // yellow
  "Commuter Rail": "#80276C", // purple
  Ferry: "#008EAA",           // teal
};
const DEFAULT_LINE_COLOR = "#8b93ad"; // text-muted, for unknown/missing lines
function lineColor(line) {
  // Accepts a brand name ("Red", from e.transit_line) or a branch route id
  // ("Red (Ashmont)", from the metro tabs) — both resolve to one trunk color.
  return LINE_COLORS[LINE_BASE[line] || line] || DEFAULT_LINE_COLOR;
}

// Real clock — 4am rollover so late-night events stay on "tonight"
function getNow() {
  const d = new Date();
  if (d.getHours() < 4) d.setDate(d.getDate() - 1);
  return d;
}
const NOW = getNow();
// The weekday "tonight" falls on, after the 4am rollover — drives which
// recurring food deals are live (a deal lists the weekdays it runs).
const NOW_WEEKDAY = NOW.toLocaleDateString("en-US", { weekday: "long" });

// Wall-clock "now" for "has this moment passed?" checks. Distinct from NOW,
// which rolls the DATE back before 4am to decide which day counts as "tonight."
// That shifted value must NOT be used to test whether an event has ended, or
// every event looks un-ended for the whole midnight-to-4am window.
const REAL_NOW = new Date();

let allEvents = [];
let venueData = {};
let activeSquare = "all";
let activeCategory = "all";
// Your "home" square — where the metro map centers and the train departs when
// no square is selected ("Near me"). Hardcoded for now; will come from a user
// profile once profiles land, letting each user pick their own Home Square.
const HOME_SQUARE = "Davis";

init();

async function init() {
  setDate();
  buildFilterChips();
  renderSquareIndicator();
  wireMetroOverlay();
  let deals, transit;
  [allEvents, venueData, deals, transit] = await Promise.all([loadEvents(), loadVenues(), loadDeals(), loadTransit()]);
  // Recurring food deals live alongside one-off events in the same feed; they
  // just match "tonight" by weekday instead of a calendar date (see isTonightEvent).
  allEvents = allEvents.concat(deals);
  // A stop is filterable only if something happens there tonight-or-otherwise.
  eventSquares = new Set(allEvents.map(e => e.square).filter(Boolean));
  // Build the overlay's metro map once events are known (eventSquares decides
  // which stations light up). Tapping a station applies its square as the filter.
  if (transit) MetroMap.setup(transit, selectSquare);
  render();
  wireDetailOverlay();
  wireCollapsingHeader();
  window.addEventListener("hashchange", handleHash);
  handleHash();
}

async function loadVenues() {
  try {
    const res = await fetch("data/venues.json");
    return await res.json();
  } catch (err) {
    console.warn("Could not load venues.json", err);
    return {};
  }
}

// Recurring food/drink specials, hand-curated (they change rarely). Kept out of
// data/events.json so the scraper's daily rewrite can't clobber them. Each deal
// carries the same display fields an event does, plus recurring_days + deal:true.
async function loadDeals() {
  try {
    const res = await fetch("data/deals.json");
    return await res.json();
  } catch (err) {
    console.warn("Could not load deals.json", err);
    return [];
  }
}

// The traced MBTA network (schema tonight.transit/1) that drives the metro
// overlay's canvas map. Optional — if it's missing the overlay still opens with
// the "Near me" button, just without a map (MetroMap.setup is simply skipped).
async function loadTransit() {
  try {
    const res = await fetch("transit-layer.json");
    if (!res.ok) return null;
    return await res.json();
  } catch (err) {
    console.warn("Could not load transit-layer.json", err);
    return null;
  }
}

// ============================================================
// Collapsing header — the wide logo shrinks toward a compact
// width as the page scrolls, while staying pinned to the top.
// ============================================================

const LOGO_RATIO = 1000 / 529; // intrinsic width / height of logo-wide-transparent.png
const HERO_WIDTH = 420;
const COMPACT_WIDTH = 130;
const SHRINK_DISTANCE = 180; // px scrolled to go from hero to compact

function wireCollapsingHeader() {
  const update = () => {
    const progress = Math.min(window.scrollY / SHRINK_DISTANCE, 1);
    const width = HERO_WIDTH - (HERO_WIDTH - COMPACT_WIDTH) * progress;
    document.getElementById("logo-img").style.width = `${width}px`;
  };

  let ticking = false;
  window.addEventListener("scroll", () => {
    if (!ticking) {
      requestAnimationFrame(() => { update(); ticking = false; });
      ticking = true;
    }
  }, { passive: true });

  update();
}

function setDate() {
  const el = document.getElementById("today-date");
  el.textContent = NOW.toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric"
  });
}

async function loadEvents() {
  try {
    const res = await fetch("data/events.json");
    const data = await res.json();

    // Handle both bare array (old format) and {generated_at, events} envelope
    const events = Array.isArray(data) ? data : (data.events || []);
    const generatedAt = data.generated_at || null;

    // Freshness check — warn if data is more than 26 hours old
    if (generatedAt) {
      const ageHours = (Date.now() - new Date(generatedAt).getTime()) / 3600000;
      const el = document.getElementById("today-date");
      if (ageHours > 26) {
        el.textContent = "⚠ Listings may be outdated";
        el.style.color = "#e05c5c";
      }
    }

    return events;
  } catch (err) {
    console.error("Could not load events.json", err);
    return [];
  }
}

function buildFilterChips() {
  const categoryRow = document.getElementById("category-filters");
  addChip(categoryRow, "All", "all");
  CATEGORIES.forEach(cat => addChip(categoryRow, capitalize(cat), cat));
}

function addChip(row, label, value) {
  const btn = document.createElement("button");
  btn.className = "chip" + (value === "all" ? " active" : "");
  btn.textContent = label;
  btn.dataset.value = value;
  btn.addEventListener("click", () => {
    row.querySelectorAll(".chip").forEach(c => c.classList.remove("active"));
    btn.classList.add("active");
    activeCategory = value;
    render();
  });
  row.appendChild(btn);
}

// ============================================================
// Square indicator — the destination board pinned at the top.
// Reads like the transit badge on a card, but bigger and built
// from line color(s): one colored dot per line the stop sits on,
// so a multi-line hub (Downtown Crossing) shows two dots. Tapping
// it opens the metro-map overlay.
// ============================================================
function lineDots(lines) {
  // One dot per line, overlapping slightly so a multi-line stop reads as a
  // little cluster — the "part of the outline in each color" idea, as dots.
  if (lines.length === 0) {
    return `<span class="line-dot line-dot-all"></span>`;
  }
  return lines
    .map(l => `<span class="line-dot" style="--line-color:${lineColor(l)}"></span>`)
    .join("");
}

function renderSquareIndicator() {
  const el = document.getElementById("square-indicator");
  const isAll = activeSquare === "all";
  const lines = isAll ? [] : stationLines(activeSquare);
  const name = isAll ? "Near me" : activeSquare;
  const sub = isAll
    ? "All squares"
    : (lines.length ? lines.join(" · ") + (lines.length > 1 ? " lines" : " Line") : "");

  el.classList.toggle("is-all", isAll);
  el.innerHTML = `
    <span class="si-dots">${lineDots(lines)}</span>
    <span class="si-text">
      <span class="si-name">${name}</span>
      <span class="si-sub">${sub}</span>
    </span>
    <span class="si-chevron" aria-hidden="true">
      <svg viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg>
    </span>
  `;
}

// ============================================================
// Metro overlay — the "get on the train" location picker.
// Opens like the detail panel and shows the real MBTA network on a
// canvas (the same traced map as transit-layer.json). Your current
// square is the origin; tapping a lit-up station routes a train there
// (Dijkstra + transfer dwell), then applies the filter on arrival.
// The map/graph/animation all live in the MetroMap module below.
// ============================================================
function wireMetroOverlay() {
  document.getElementById("square-indicator").addEventListener("click", openMetro);
  const overlay = document.getElementById("metro-overlay");
  document.getElementById("metro-close").addEventListener("click", closeMetro);
  overlay.addEventListener("click", ev => { if (ev.target === overlay) closeMetro(); });
  document.getElementById("metro-nearme").addEventListener("click", () => selectSquare("all"));
  document.addEventListener("keydown", ev => {
    if (ev.key === "Escape" && !overlay.hidden) closeMetro();
  });
}

function openMetro() {
  const overlay = document.getElementById("metro-overlay");
  overlay.hidden = false;
  document.body.style.overflow = "hidden";
  // Origin is your current square, or your Home Square when nothing's selected
  // ("Near me") — so the map always opens zoomed in around a real place. The
  // canvas can't measure itself until the panel is on screen, so wait a frame.
  const origin = activeSquare === "all" ? HOME_SQUARE : activeSquare;
  requestAnimationFrame(() => MetroMap.show(origin));
}

function closeMetro() {
  const overlay = document.getElementById("metro-overlay");
  overlay.hidden = true;
  document.body.style.overflow = "";
  MetroMap.stop();
}

// ============================================================
// MetroMap — the canvas network inside the overlay.
//
// Ported from transit-animation-preview.html (the standalone tool):
// builds a coordinate-keyed graph from transit-layer.json, routes
// origin→destination with Dijkstra + a transfer penalty, and animates
// a train along the path with a brief dwell (color morph + rotate) at
// every line change or sharp branch reversal — never at plain stops.
//
// Adapted for the app: no dropdowns/readout/base image. The current
// square is the fixed origin; a tap picks the nearest *filterable*
// station (one with events) as the destination and, on arrival, calls
// onArrive(name) → selectSquare. Color is always lineColor(), and only
// stations with events are drawn lit + labelled; the rest are dimmed
// connectors so the network still reads as a real map.
// ============================================================
const MetroMap = (() => {
  const CELL = 16;                 // world px per grid cell — the editor/Tiled contract
  const TRANSFER_PENALTY = 6;      // extra cost (in cells) to change trains
  const keyOf = (c, r) => c + "," + r;
  const cellCenter = (c, r) => ({ x: (c + 0.5) * CELL, y: (r + 0.5) * CELL });

  // Pixel-art terrain (land/water) drawn under the network. It's a 140×140-tile
  // export, so it stretches to the grid extent — tile count, not pixel size, is
  // the contract with the Tiled map. Drawn dimmed so the lines/labels still read.
  const BASE_IMG_SRC = encodeURI("tilemap/boston v1.png");
  const BASE_IMG_ALPHA = 0.8;
  let baseImg = null;

  let canvas, ctx, stage;
  let graph = null, data = null;
  let cols = 0, rows = 0;
  let nameToKey = new Map();       // station name → graph key, for resolving the origin
  let view = { scale: 1, x: 0, y: 0 };
  let originKey = null;            // current square's node (green "you are here"); null for "Near me"
  let onArrive = () => {};
  let train = null;                // {x,y,angle,color} while a trip runs
  let anim = null, raf = 0, lastTs = 0;

  const s2w = (sx, sy) => ({ x: (sx - view.x) / view.scale, y: (sy - view.y) / view.scale });
  const w2s = (wx, wy) => ({ x: wx * view.scale + view.x, y: wy * view.scale + view.y });
  const isFilterable = name => name && eventSquares.has(name);

  // ---- graph build: nodes keyed by coordinate, so a shared (c,r) is a junction/transfer
  function buildGraph(d) {
    const nodes = new Map(), adj = new Map();
    const ensure = (n, line) => {
      const k = keyOf(n.c, n.r);
      let nd = nodes.get(k);
      if (!nd) { nd = { c: n.c, r: n.r, name: n.name || "", station: !!n.station, lines: new Set() }; nodes.set(k, nd); adj.set(k, []); }
      if (n.name) nd.name = n.name;   // never let "" overwrite a real name (branch-start convention)
      if (n.station) nd.station = true;
      nd.lines.add(line);
      return k;
    };
    d.lines.forEach(ln => ln.branches.forEach(br => {
      for (let i = 0; i < br.nodes.length; i++) {
        const k = ensure(br.nodes[i], ln.line);
        if (i > 0) {
          const a = br.nodes[i - 1], ka = keyOf(a.c, a.r);
          const w = Math.hypot(br.nodes[i].c - a.c, br.nodes[i].r - a.r);
          adj.get(ka).push({ to: k, w, line: ln.line });
          adj.get(k).push({ to: ka, w, line: ln.line });
        }
      }
    }));
    return { nodes, adj };
  }

  // ---- routing: Dijkstra over (node, came-from, line). Penalty applies once per
  // "change trains" moment — a line transfer OR a sharp (>90°) same-line reversal.
  function route(srcKey, dstKey) {
    if (srcKey === dstKey) return { path: [srcKey], segLines: [] };
    const { adj, nodes } = graph;
    const dist = new Map(), prev = new Map();
    const startId = srcKey + "||";
    dist.set(startId, 0);
    const pq = [{ id: startId, key: srcKey, from: null, line: null, d: 0 }];
    let end = null;
    while (pq.length) {
      let mi = 0; for (let i = 1; i < pq.length; i++) if (pq[i].d < pq[mi].d) mi = i;
      const cur = pq.splice(mi, 1)[0];
      if (cur.d > (dist.get(cur.id) ?? Infinity)) continue;
      if (cur.key === dstKey) { end = cur; break; }
      const here = nodes.get(cur.key);
      let inAng = null;
      if (cur.from) { const f = nodes.get(cur.from); inAng = Math.atan2(here.r - f.r, here.c - f.c); }
      for (const e of (adj.get(cur.key) || [])) {
        const to = nodes.get(e.to);
        const outAng = Math.atan2(to.r - here.r, to.c - here.c);
        const lineChange = cur.line && cur.line !== e.line;
        const sharp = inAng !== null && cur.line === e.line &&
          Math.abs(angleDiff(inAng, outAng)) > Math.PI / 2 + 1e-6;
        const pen = (lineChange || sharp) ? TRANSFER_PENALTY : 0;
        const nd = cur.d + e.w + pen;
        const nid = e.to + "|" + cur.key + "|" + e.line;
        if (nd < (dist.get(nid) ?? Infinity)) {
          dist.set(nid, nd);
          prev.set(nid, { from: cur.id, key: cur.key, line: e.line });
          pq.push({ id: nid, key: e.to, from: cur.key, line: e.line, d: nd });
        }
      }
    }
    if (!end) return null;
    const path = [], segLines = [];
    let id = end.id, key = end.key;
    while (id) {
      path.push(key);
      const p = prev.get(id);
      if (!p) break;
      segLines.push(p.line);
      id = p.from; key = p.key;
    }
    path.reverse(); segLines.reverse();
    return { path, segLines };
  }

  // ---- geometry / view
  function resize() {
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = stage.clientWidth * dpr;
    canvas.height = stage.clientHeight * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    draw();
  }
  function fit() {
    const w = stage.clientWidth, h = stage.clientHeight, pad = 36;
    if (!w || !h) return;
    const s = Math.min((w - pad) / (cols * CELL), (h - pad) / (rows * CELL));
    view.scale = s;
    view.x = (w - cols * CELL * s) / 2;
    view.y = (h - rows * CELL * s) / 2;
    draw();
  }
  function zoomAt(sx, sy, f) {
    const b = s2w(sx, sy);
    view.scale = Math.max(0.1, Math.min(8, view.scale * f));
    view.x = sx - b.x * view.scale; view.y = sy - b.y * view.scale;
    draw();
  }
  // Center a node and zoom so ~radius tiles are visible to the nearest edge —
  // the "start near home" view. Falls back to fit() when the node is unknown.
  const FOCUS_RADIUS = 30;
  function focusOn(key, radius = FOCUS_RADIUS) {
    const nd = key && graph.nodes.get(key);
    const w = stage.clientWidth, h = stage.clientHeight;
    if (!nd || !w || !h) { fit(); return; }
    const c = cellCenter(nd.c, nd.r);
    view.scale = Math.max(0.1, Math.min(8, Math.min(w, h) / (2 * radius * CELL)));
    view.x = w / 2 - c.x * view.scale;
    view.y = h / 2 - c.y * view.scale;
    draw();
  }

  // ---- render
  function strokeRounded(pts) {
    ctx.beginPath();
    if (pts.length === 1) { ctx.moveTo(pts[0].x, pts[0].y); ctx.lineTo(pts[0].x, pts[0].y); ctx.stroke(); return; }
    ctx.moveTo(pts[0].x, pts[0].y);
    const baseT = CELL * 0.85;
    for (let i = 1; i < pts.length - 1; i++) {
      const a = pts[i - 1], b = pts[i], c2 = pts[i + 1];
      const L1 = Math.hypot(a.x - b.x, a.y - b.y), L2 = Math.hypot(c2.x - b.x, c2.y - b.y);
      let cosA = ((a.x - b.x) * (c2.x - b.x) + (a.y - b.y) * (c2.y - b.y)) / ((L1 * L2) || 1);
      cosA = Math.max(-1, Math.min(1, cosA));
      const alpha = Math.acos(cosA);
      if (alpha > Math.PI - 0.05) { ctx.lineTo(b.x, b.y); continue; }
      const t = Math.min(baseT, L1 / 2, L2 / 2);
      ctx.arcTo(b.x, b.y, c2.x, c2.y, t * Math.tan(alpha / 2));
    }
    ctx.lineTo(pts.at(-1).x, pts.at(-1).y);
    ctx.stroke();
  }
  function roundRect(x, y, w, h, r) {
    ctx.beginPath(); ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
  }

  function draw() {
    if (!ctx || !graph) return;
    ctx.clearRect(0, 0, canvas.clientWidth, canvas.clientHeight);
    ctx.save(); ctx.translate(view.x, view.y); ctx.scale(view.scale, view.scale);
    ctx.lineJoin = "round"; ctx.lineCap = "round";

    // terrain base, stretched to the grid extent (nearest-neighbor to stay crisp)
    if (baseImg && baseImg.complete && baseImg.naturalWidth) {
      ctx.globalAlpha = BASE_IMG_ALPHA;
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(baseImg, 0, 0, cols * CELL, rows * CELL);
      ctx.imageSmoothingEnabled = true;
      ctx.globalAlpha = 1;
    }

    // lines
    data.lines.forEach(ln => {
      ctx.strokeStyle = lineColor(ln.line);
      ctx.lineWidth = 4 / view.scale;
      ln.branches.forEach(br => { if (br.nodes.length) strokeRounded(br.nodes.map(n => cellCenter(n.c, n.r))); });
    });

    // nodes — lit + labelled where events happen, dimmed connectors otherwise
    graph.nodes.forEach((nd, k) => {
      const p = cellCenter(nd.c, nd.r);
      const lit = isFilterable(nd.name) || k === originKey;
      ctx.globalAlpha = lit ? 1 : 0.4;
      if (nd.lines.size > 1) {                  // interchange — white diamond
        ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(Math.PI / 4);
        ctx.fillStyle = "#fff"; ctx.strokeStyle = "#10131a"; ctx.lineWidth = 2 / view.scale;
        const s = CELL * 0.42; ctx.fillRect(-s, -s, 2 * s, 2 * s); ctx.strokeRect(-s, -s, 2 * s, 2 * s); ctx.restore();
      } else if (nd.station) {                  // plain station — ring
        ctx.fillStyle = "#fff"; ctx.strokeStyle = lineColor([...nd.lines][0]); ctx.lineWidth = 2.5 / view.scale;
        ctx.beginPath(); ctx.arc(p.x, p.y, CELL * 0.3, 0, 7); ctx.fill(); ctx.stroke();
      }
      ctx.globalAlpha = 1;

      if (k === originKey) {                     // "you are here" — amber halo
        ctx.strokeStyle = "#f5b942"; ctx.lineWidth = 3 / view.scale;
        ctx.beginPath(); ctx.arc(p.x, p.y, CELL * 0.62, 0, 7); ctx.stroke();
      }
      if (lit && nd.name) {                       // label only the stops you can pick
        const label = stationLabel(nd.name), lx = p.x + CELL * 0.7;
        ctx.font = `${600} ${11 / view.scale}px ${getComputedStyle(document.body).getPropertyValue("--font-display") || "sans-serif"}`;
        ctx.textAlign = "left"; ctx.textBaseline = "middle";
        // thin black outline so names stay legible over the terrain
        ctx.lineJoin = "round";
        ctx.strokeStyle = "rgba(0, 0, 0, 0.85)";
        ctx.lineWidth = 2.5 / view.scale;
        ctx.strokeText(label, lx, p.y);
        ctx.fillStyle = k === originKey ? "#f5b942" : "#fff";
        ctx.fillText(label, lx, p.y);
      }
    });

    // train
    if (train) {
      ctx.save(); ctx.translate(train.x, train.y); ctx.rotate(train.angle);
      const L = CELL * 1.5, W = CELL * 0.9;
      ctx.fillStyle = train.color; ctx.strokeStyle = "#fff"; ctx.lineWidth = 2 / view.scale;
      roundRect(-L / 2, -W / 2, L, W, CELL * 0.3); ctx.fill(); ctx.stroke();
      ctx.fillStyle = "#fff"; ctx.beginPath(); ctx.arc(L / 2 - CELL * 0.35, 0, CELL * 0.16, 0, 7); ctx.fill();
      ctx.restore();
    }
    ctx.restore();
  }

  // ---- animation helpers
  const lerp = (a, b, t) => a + (b - a) * t;
  function hex2rgb(h) { const n = parseInt(h.slice(1), 16); return [n >> 16 & 255, n >> 8 & 255, n & 255]; }
  function mixColor(a, b, t) { const A = hex2rgb(a), B = hex2rgb(b); return `rgb(${Math.round(lerp(A[0], B[0], t))},${Math.round(lerp(A[1], B[1], t))},${Math.round(lerp(A[2], B[2], t))})`; }
  function angleDiff(a, b) { let d = (b - a) % (2 * Math.PI); if (d > Math.PI) d -= 2 * Math.PI; if (d < -Math.PI) d += 2 * Math.PI; return d; }
  function lerpAngle(a, b, t) { return a + angleDiff(a, b) * t; }
  function segAngle(pts, i) { const a = pts[i], b = pts[i + 1]; return Math.atan2(b.y - a.y, b.x - a.x); }

  // ---- run a trip from origin → destination, then fire onArrive(destName)
  function runTrip(srcKey, dstKey, destName) {
    cancelAnimationFrame(raf);
    const r = route(srcKey, dstKey);
    if (!r || r.path.length < 2) { onArrive(destName); return; }
    const pts = r.path.map(k => { const n = graph.nodes.get(k); return { ...cellCenter(n.c, n.r), name: n.name, station: n.station, key: k }; });
    const segColors = r.segLines.map(lineColor);
    anim = { pts, segColors, segLines: r.segLines, i: 0, t: 0, mode: "run", destName,
             color: segColors[0], angle: segAngle(pts, 0) };
    lastTs = performance.now();
    raf = requestAnimationFrame(tick);
  }

  const SPEED = 27;   // cells/sec — brisk but readable on a phone-sized map
  function tick(ts) {
    const dt = Math.min(0.05, (ts - lastTs) / 1000); lastTs = ts;
    const a = anim, pts = a.pts;
    if (a.mode === "run") {
      const A = pts[a.i], B = pts[a.i + 1];
      const segLen = Math.hypot(B.x - A.x, B.y - A.y) / CELL || 0.001;
      a.t += SPEED * dt / segLen;
      a.color = a.segColors[a.i];
      a.angle = segAngle(pts, a.i);
      if (a.t >= 1) {
        a.t = 1;
        if (a.i + 1 >= pts.length - 1) { train = trainAt(B.x, B.y, a.angle, a.color); draw(); finishTrip(); return; }
        // Dwell only at a "change trains" moment — a line transfer or a sharp
        // (>90°) reversal through a branch junction. Plain stops get no pause.
        const inA = segAngle(pts, a.i), outA = segAngle(pts, a.i + 1);
        const transfer = a.segLines[a.i] !== a.segLines[a.i + 1];
        const sharp = Math.abs(angleDiff(inA, outA)) > Math.PI / 2 + 1e-6;
        if (transfer || sharp) {
          a.mode = "dwell"; a.dwellT = 0; a.dwellDur = 0.475;
          a.fromAngle = inA; a.toAngle = outA;
          a.fromColor = a.segColors[a.i]; a.toColor = transfer ? a.segColors[a.i + 1] : a.segColors[a.i];
        } else { a.i++; a.t = 0; }
      }
    } else if (a.mode === "dwell") {
      a.dwellT += dt;
      const k = Math.min(1, a.dwellT / a.dwellDur);
      a.angle = lerpAngle(a.fromAngle, a.toAngle, k);
      a.color = mixColor(a.fromColor, a.toColor, k);
      if (a.dwellT >= a.dwellDur) { a.i++; a.t = 0; a.mode = "run"; a.angle = a.toAngle; a.color = a.toColor; }
    }
    const A = pts[a.i], B = pts[Math.min(a.i + 1, pts.length - 1)];
    train = trainAt(lerp(A.x, B.x, a.t), lerp(A.y, B.y, a.t), a.angle, a.color);
    draw();
    raf = requestAnimationFrame(tick);
  }
  function trainAt(x, y, angle, color) { return { x, y, angle, color }; }
  function finishTrip() { cancelAnimationFrame(raf); const name = anim && anim.destName; anim = null; onArrive(name); }

  // ---- pointer: pan / pinch-zoom, with a tap = pick destination
  function nearestFilterable(sx, sy) {
    let best = null, bd = 26 * 26;
    graph.nodes.forEach((nd, k) => {
      if (!isFilterable(nd.name)) return;
      const cc = cellCenter(nd.c, nd.r), p = w2s(cc.x, cc.y);
      const d = (p.x - sx) ** 2 + (p.y - sy) ** 2;
      if (d < bd) { bd = d; best = { key: k, name: nd.name }; }
    });
    return best;
  }
  function pickAt(sx, sy) {
    const hit = nearestFilterable(sx, sy);
    if (!hit) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce || !originKey || originKey === hit.key) { onArrive(hit.name); return; }
    runTrip(originKey, hit.key, hit.name);
  }
  function wirePointer() {
    const pts = new Map(); let dragging = false, pinch = 0, downPt = null, moved = false;
    const local = e => { const r = canvas.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; };
    canvas.addEventListener("pointerdown", e => {
      canvas.setPointerCapture(e.pointerId); const p = local(e); pts.set(e.pointerId, p);
      if (pts.size === 2) { const [a, b] = [...pts.values()]; pinch = Math.hypot(a.x - b.x, a.y - b.y); }
      dragging = true; downPt = p; moved = false;
    });
    canvas.addEventListener("pointermove", e => {
      const p = local(e), prev = pts.get(e.pointerId); if (pts.has(e.pointerId)) pts.set(e.pointerId, p);
      if (pts.size === 2) { const [a, b] = [...pts.values()]; const d = Math.hypot(a.x - b.x, a.y - b.y); const m = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }; if (pinch) zoomAt(m.x, m.y, d / pinch); pinch = d; moved = true; return; }
      if (downPt && Math.hypot(p.x - downPt.x, p.y - downPt.y) > 4) moved = true;
      if (dragging && prev) { view.x += p.x - prev.x; view.y += p.y - prev.y; draw(); }
    });
    const up = e => {
      const p = local(e), wasClick = (!moved && pts.size === 1);
      pts.delete(e.pointerId); if (pts.size < 2) pinch = 0; if (pts.size === 0) dragging = false;
      if (wasClick) pickAt(p.x, p.y);
    };
    canvas.addEventListener("pointerup", up); canvas.addEventListener("pointercancel", up);
    stage.addEventListener("wheel", e => { e.preventDefault(); const p = local(e); zoomAt(p.x, p.y, e.deltaY < 0 ? 1.12 : 1 / 1.12); }, { passive: false });
  }

  // ---- public API
  function setup(transitData, arriveCb) {
    data = transitData;
    cols = data.grid.cols; rows = data.grid.rows;
    graph = buildGraph(data);
    nameToKey = new Map();
    graph.nodes.forEach((nd, k) => { if (nd.name) nameToKey.set(nd.name, k); });
    onArrive = arriveCb;
    canvas = document.getElementById("metro-canvas");
    stage = document.getElementById("metro-stage");
    ctx = canvas.getContext("2d");
    baseImg = new Image();
    baseImg.onload = () => draw();   // redraw once the terrain arrives
    baseImg.src = BASE_IMG_SRC;
    wirePointer();
    window.addEventListener("resize", () => { if (!document.getElementById("metro-overlay").hidden) resize(); });
  }
  function show(originName) {
    if (!graph) return;
    cancelAnimationFrame(raf); train = null; anim = null;
    originKey = originName ? (nameToKey.get(originName) || null) : null;
    // resize first (panel now has real dimensions), then open zoomed in around
    // your origin/home square rather than framing the whole network.
    resize();
    originKey ? focusOn(originKey) : fit();
  }
  function stop() { cancelAnimationFrame(raf); train = null; anim = null; }
  function ready() { return !!graph; }
  return { setup, show, stop, ready };
})();

function selectSquare(value) {
  activeSquare = value;
  renderSquareIndicator();
  render();
  closeMetro();
}

// ============================================================
// Locality + sponsored helpers
// ============================================================

// Joins an event to its venue's display config in data/venues.json. Prefers
// the stamped venue_id; falls back to parsing it out of the event id for
// older events scraped before venue_id was stamped.
function venueFor(e) {
  return venueData[e.venue_id]
    || venueData[e.id?.split("-").slice(0, 2).join("-")]
    || {};
}

function localityState(e) {
  const venueLocal = !!e.venue_is_local;
  const perfLocal  = e.performer && e.performer_is_local === true;
  const perfPresent = !!e.performer;

  if (venueLocal && perfPresent && perfLocal)  return "both";
  if (venueLocal && (!perfPresent || !perfLocal)) return "venue";
  if (!venueLocal && perfPresent && perfLocal)  return "performer";
  return "none";
}

const LOCALITY_CONFIG = {
  venue: {
    cls: "pill-venue",
    icon: `<svg viewBox="0 0 24 24"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>`,
    label: "Local spot"
  },
  performer: {
    cls: "pill-performer",
    icon: `<svg viewBox="0 0 24 24"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>`,
    label: "Local artist"
  },
  both: {
    cls: "pill-both",
    icon: `<svg viewBox="0 0 24 24"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>`,
    label: "Homegrown"
  }
};

function buildLocalityPill(e, extraClass) {
  const state = localityState(e);
  if (state === "none") return null;
  const cfg = LOCALITY_CONFIG[state];
  const pill = document.createElement("span");
  pill.className = `locality-pill ${cfg.cls}${extraClass ? " " + extraClass : ""}`;
  pill.innerHTML = `${cfg.icon} ${cfg.label}`;
  return pill;
}



const DEFAULT_EVENT_HOURS = 3;

function eventEndTime(e) {
  // Use the listed end if we have one. Otherwise assume a DEFAULT_EVENT_HOURS
  // event. This estimate is deliberately NOT shown anywhere (we never set
  // e.end, so the card/detail keep showing just the start time) — it only
  // decides when the event counts as "past", so it drops to the bottom of the
  // list and dims like every other ended event instead of lingering until 4am.
  if (e.end) return new Date(e.end);
  if (e.start) {
    const d = new Date(e.start);
    d.setHours(d.getHours() + DEFAULT_EVENT_HOURS);
    return d;
  }
  return new Date(0);
}

function isTonightEvent(e) {
  // A recurring deal is "tonight" whenever today's weekday is one it runs on.
  if (e.deal) return Array.isArray(e.recurring_days) && e.recurring_days.includes(NOW_WEEKDAY);
  if (!e.start) return false;
  const start = new Date(e.start);
  const todayStr = NOW.toDateString();
  // Include all events that start today, whether or not they've ended
  return start.toDateString() === todayStr;
}

function hasEnded(e) {
  // Deals run all night with no clock time, so they never drop to "ended".
  if (e.deal) return false;
  return eventEndTime(e) <= REAL_NOW;
}

// Sort key in ms. Deals have no start time; float them after timed events.
function startMs(e) {
  return e.start ? new Date(e.start).getTime() : (e.deal ? Infinity : 0);
}

// Stable pseudo-random key derived from the event id, so "Near me" can shuffle
// events without them jumping around on every re-render.
function randKey(e) {
  const s = String(e.id ?? "");
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0) / 4294967296;
}

function render() {
  const list = document.getElementById("event-list");
  const empty = document.getElementById("empty-state");
  list.innerHTML = "";

  const filtered = allEvents
    .filter(isTonightEvent)
    .filter(e => {
      const squareMatch = activeSquare === "all" || e.square === activeSquare;
      const categoryMatch = activeCategory === "all" || e.category === activeCategory;
      return squareMatch && categoryMatch;
    });

  // In "Near me" there is no user location, so walk_minutes (distance from the
  // event's own station) is not a meaningful order — it just floats whichever
  // venue happens to sit closest to any station (e.g. The Lilypad, 1 min from
  // Inman) to the top. Until we have a real location, randomize instead. The
  // random key is stable per event id so the order doesn't reshuffle on every
  // re-render.
  const sortFn = (a, b) =>
    activeSquare === "all"
      ? randKey(a) - randKey(b)
      : startMs(a) - startMs(b);

  const active = filtered.filter(e => !hasEnded(e)).sort(sortFn);
  const ended  = filtered.filter(e =>  hasEnded(e)).sort((a, b) => startMs(a) - startMs(b));

  if (active.length === 0 && ended.length === 0) {
    empty.hidden = false;
    return;
  }
  empty.hidden = true;

  active.forEach(e => list.appendChild(renderCard(e)));
  ended.forEach(e => list.appendChild(renderCard(e)));
}

function renderCard(e) {
  const article = document.createElement("article");
  article.className = "card" + (e.sponsored ? " is-sponsored" : "") + (hasEnded(e) ? " is-ended" : "");
  article.tabIndex = 0;
  article.setAttribute("role", "button");
  article.addEventListener("click", () => { location.hash = e.id; });
  article.addEventListener("keydown", ev => {
    if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); location.hash = e.id; }
  });

  // Sponsored corner tag
  if (e.sponsored && e.sponsor) {
    const tag = document.createElement("span");
    tag.className = "sponsored-tag";
    tag.textContent = e.sponsor.label || "Featured";
    article.appendChild(tag);
  }

  const art = document.createElement("div");
  art.className = `card-art cat-${e.category}`;
  if (e.image_url) {
    const img = document.createElement("img");
    img.src = e.image_url;
    img.alt = "";
    img.style.cssText = "width:100%;height:100%;object-fit:cover;";
    art.appendChild(img);
  } else {
    art.appendChild(buildArt(e));
  }

  const body = document.createElement("div");
  body.className = "card-body";
  body.innerHTML = `
    <h2 class="card-title">${e.title}</h2>
    <div class="card-venue-row">
      <span class="card-venue">${e.venue}</span>
      ${e.cost ? `<span class="cost">${e.cost}</span>` : ""}
    </div>
    <p class="card-time">${e.deal ? dealTimeLabel(e) : formatTimeRange(e.start, e.end)}</p>
    <div class="card-footer">
      <div class="transit-badge" style="--line-color:${lineColor(e.transit_line)}">
        <span class="transit-dot"></span>
        <span class="transit-text">${e.transit_stop} → ${e.walk_minutes} min</span>
      </div>
    </div>
  `;

  // Locality pill — sits inline with the transit badge
  const pill = buildLocalityPill(e);
  if (pill) body.querySelector(".card-footer").appendChild(pill);

  article.appendChild(art);
  article.appendChild(body);
  return article;
}

function buildArt(e, large) {
  if (e.image_url) {
    const img = document.createElement("img");
    img.src = e.image_url;
    img.alt = "";
    if (!large) {
      img.style.width = "100%";
      img.style.height = "100%";
      img.style.objectFit = "cover";
    }
    return img;
  }
  const wrapper = document.createElement("div");
  wrapper.innerHTML = `<svg viewBox="0 0 24 24">${ICONS[e.category] || ""}</svg>`;
  return wrapper.firstElementChild;
}

// ============================================================
// Detail overlay
// ============================================================

function handleHash() {
  const id = decodeURIComponent(location.hash.replace(/^#/, ""));
  if (!id) {
    closeDetail();
    return;
  }
  const event = allEvents.find(e => e.id === id);
  if (event) openDetail(event);
  else closeDetail();
}

function wireDetailOverlay() {
  const overlay = document.getElementById("detail-overlay");
  document.getElementById("detail-close").addEventListener("click", () => { history.back(); });
  overlay.addEventListener("click", ev => {
    if (ev.target === overlay) history.back();
  });
  document.getElementById("detail-calendar").addEventListener("click", () => {
    const e = currentEvent;
    if (e) downloadICS(e);
  });
  document.getElementById("detail-share").addEventListener("click", () => {
    const e = currentEvent;
    if (e) shareEvent(e);
  });
}

let currentEvent = null;

function openDetail(e) {
  currentEvent = e;
  const overlay = document.getElementById("detail-overlay");

  const art = document.getElementById("detail-art");
  art.className = `detail-art cat-${e.category}`;
  art.innerHTML = "";
  art.appendChild(buildArt(e, true));

  document.getElementById("detail-title").textContent = e.title;
  const timeEl = document.getElementById("detail-time");
  timeEl.textContent = e.deal ? dealFullTimeLabel(e) : formatFullTimeRange(e.start, e.end);
  // A standing weekly deal isn't a calendar event — hide "Add to calendar".
  document.getElementById("detail-calendar").hidden = !!e.deal;
  if (e.cost) {
    const costSpan = document.createElement("span");
    costSpan.className = "cost";
    costSpan.textContent = e.cost;
    timeEl.append(document.createTextNode(" · "), costSpan);
  }
  document.getElementById("detail-description").textContent = e.description || "";

  // Locality pill in detail
  const existingPill = document.getElementById("detail-locality");
  if (existingPill) existingPill.remove();
  const detailPill = buildLocalityPill(e, "detail-locality-pill");
  if (detailPill) {
    detailPill.id = "detail-locality";
    document.getElementById("detail-transit").insertAdjacentElement("afterend", detailPill);
  }

  // Sponsored attribution line
  const existingAttr = document.getElementById("detail-sponsor-attr");
  if (existingAttr) existingAttr.remove();
  if (e.sponsored && e.sponsor) {
    const attr = document.createElement("p");
    attr.id = "detail-sponsor-attr";
    attr.style.cssText = "font-family:var(--font-mono);font-size:0.65rem;color:var(--amber);letter-spacing:0.08em;text-transform:uppercase;margin:2px 0 0;";
    attr.textContent = `★ Featured listing · ${e.sponsor.attributed_to}`;
    document.getElementById("detail-time").insertAdjacentElement("afterend", attr);
  }

  const transit = document.getElementById("detail-transit");
  transit.style.setProperty("--line-color", lineColor(e.transit_line));
  document.getElementById("detail-transit-text").textContent =
    `${e.transit_stop} → ${e.walk_minutes} min`;

  const vd = venueFor(e);
  // Event location wins over the venue's home address: e.address is only set
  // when the event is somewhere other than the venue (e.g. a street festival).
  // When it's null the event is at the venue, so fall back to vd.address.
  const eventAddress = e.address || vd.address || "";
  const avatarEl = document.getElementById("detail-venue-avatar");
  const logoSrc = vd.logo_thumb_url || vd.logo_url;
  if (logoSrc) {
    avatarEl.innerHTML = `<img src="${logoSrc}" alt="${vd.name || e.venue} logo">`;
  } else {
    avatarEl.textContent = e.venue.charAt(0);
  }
  document.getElementById("detail-venue-name").textContent = vd.name || e.venue;
  document.getElementById("detail-venue-address").textContent = eventAddress;

  document.getElementById("detail-directions").href =
    `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(eventAddress || e.venue)}`;

  const ticketBtn = document.getElementById("detail-tickets");
  if (e.ticket_url) {
    ticketBtn.href = e.ticket_url;
    ticketBtn.hidden = false;
  } else {
    ticketBtn.hidden = true;
  }

  renderMoreFrom("more-venue", "more-venue-list", null,
    allEvents.filter(o => o.venue === e.venue && o.id !== e.id && eventEndTime(o) > REAL_NOW));

  const performerHeading = document.getElementById("more-performer-heading");
  if (e.performer) performerHeading.textContent = `More from ${e.performer}`;
  renderMoreFrom("more-performer", "more-performer-list", null,
    e.performer
      ? allEvents.filter(o => o.performer === e.performer && o.id !== e.id && eventEndTime(o) > REAL_NOW)
      : []);

  overlay.hidden = false;
  document.body.style.overflow = "hidden";
  overlay.querySelector(".detail-panel").scrollTop = 0;
}

function renderMoreFrom(sectionId, listId, _unused, events) {
  const section = document.getElementById(sectionId);
  const list = document.getElementById(listId);
  list.innerHTML = "";

  if (events.length === 0) {
    section.hidden = true;
    return;
  }
  section.hidden = false;

  events
    .sort((a, b) => new Date(a.start) - new Date(b.start))
    .forEach(o => {
      const item = document.createElement("button");
      item.className = "more-item";
      item.innerHTML = `
        <span class="more-title">${o.title}</span>
        <span class="more-date">${formatShortDate(o.start)}</span>
      `;
      item.addEventListener("click", () => { location.hash = o.id; });
      list.appendChild(item);
    });
}

function closeDetail() {
  const overlay = document.getElementById("detail-overlay");
  overlay.hidden = true;
  document.body.style.overflow = "";
  currentEvent = null;
}

// ============================================================
// Actions: calendar export, share
// ============================================================

function downloadICS(e) {
  if (e.deal) return; // recurring deals have no single date to export

  // Event-specific address (street festival, etc.) wins over the venue's home
  // address, matching the detail view. See venueFor / showDetail.
  const icsAddress = e.address || venueFor(e).address || "";
  const pad = n => String(n).padStart(2, "0");
  // Event times are floating local wall-clock strings (e.g. "2026-06-15T20:00:00"),
  // which is how the app displays them. Emit them as floating local (no Z) so the
  // calendar shows 8:00 PM, not a UTC-shifted time. (The old code ran the value
  // through toISOString() — UTC — then stripped the Z, shifting events 4-5 hours.)
  const fmtLocal = d =>
    `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}T` +
    `${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
  // DTSTAMP must be a real UTC timestamp (with Z). It is required by RFC 5545;
  // iOS Calendar silently refuses to open an event that lacks it.
  const fmtUTC = d => d.toISOString().replace(/[-:]/g, "").split(".")[0] + "Z";
  const esc = s =>
    String(s == null ? "" : s)
      .replace(/\\/g, "\\\\")
      .replace(/;/g, "\\;")
      .replace(/,/g, "\\,")
      .replace(/\r?\n/g, "\\n");

  const ics = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//Tonight//Events//EN",
    "CALSCALE:GREGORIAN",
    "BEGIN:VEVENT",
    `UID:${e.id}@tonight`,
    `DTSTAMP:${fmtUTC(new Date())}`,
    `DTSTART:${fmtLocal(new Date(e.start))}`,
    ...(e.end ? [`DTEND:${fmtLocal(new Date(e.end))}`] : []),
    `SUMMARY:${esc(e.title)}`,
    `LOCATION:${esc(e.venue + (icsAddress ? ", " + icsAddress : ""))}`,
    `DESCRIPTION:${esc(e.description || "")}`,
    "END:VEVENT",
    "END:VCALENDAR"
  ].join("\r\n");

  // iOS Safari ignores the <a download> attribute and won't hand a blob: URL to
  // Calendar. Navigating to a text/calendar data URL opens the import sheet there.
  const isIOS = /iP(hone|ad|od)/.test(navigator.userAgent) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  if (isIOS) {
    window.location.href = "data:text/calendar;charset=utf-8," + encodeURIComponent(ics);
    return;
  }

  const blob = new Blob([ics], { type: "text/calendar;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${e.id}.ics`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function shareEvent(e) {
  const url = `${location.origin}${location.pathname}#${e.id}`;
  if (navigator.share) {
    navigator.share({ title: e.title, text: `${e.title} at ${e.venue}`, url }).catch(() => {});
  } else if (navigator.clipboard) {
    navigator.clipboard.writeText(url);
    alert("Link copied to clipboard");
  }
}

// ============================================================
// Formatting helpers
// ============================================================

function dealLabel(e) {
  return (e.recurring_days || []).join(" & ");
}
// Short form for cards: "All night · every Tuesday".
function dealTimeLabel(e) {
  const days = dealLabel(e);
  return days ? `All night · every ${days}` : "All night";
}
// Long form for the detail panel: "Every Tuesday · all night".
function dealFullTimeLabel(e) {
  const days = dealLabel(e);
  return days ? `Every ${days} · all night` : "All night";
}

function formatTimeRange(start, end) {
  const opts = { hour: "numeric", minute: "2-digit" };
  const s = new Date(start).toLocaleTimeString("en-US", opts);
  if (!end) return s;
  const en = new Date(end).toLocaleTimeString("en-US", opts);
  return `${s} – ${en}`;
}

function formatFullTimeRange(start, end) {
  const dateOpts = { weekday: "long", month: "long", day: "numeric" };
  const d = new Date(start).toLocaleDateString("en-US", dateOpts);
  return `${d} · ${formatTimeRange(start, end)}`;
}

function formatShortDate(dateStr) {
  return new Date(dateStr).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function capitalize(s) {
  return s.charAt(0).toUpperCase() + s.slice(1);
}
