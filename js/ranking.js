// ============================================================
// TonightRanking — multi-factor feed ranking (window.TonightRanking).
//
// Shared by the app (js/app.js) and the ranking tuner tool, the same
// split as js/artist-match.js — keep this file free of app globals.
//
// Geography is a *score*, not a filter: selecting a place ranks the
// whole feed by transit distance from it instead of hiding everything
// else. Distance is measured in STATIONS PASSED (hops), not cells, via
// a multi-source Dijkstra over the traced map in transit-layer.json —
// so "+selected, +adjacent, 0, −5, …" falls out of one linear formula,
// and a line change costs extra hops (a two-seat ride reads farther).
//
// Two-level geography (station vs area) comes straight from the map
// data: a node's `name` is the station, its optional `square` is the
// area it belongs to (Courthouse → Seaport). Selecting an AREA seeds
// Dijkstra with every member station at distance 0 (Courthouse, World
// Trade Center and Silver Line Way rank equally); selecting a STATION
// seeds just that stop, so its area-siblings start one hop back.
//
// Weights live in data/ranking.json (schema tonight.ranking/1) and
// fall back to DEFAULT_WEIGHTS below. Factors with no data yet
// (favorites beyond events, Lit) are wired through optional hooks so
// the weights exist before the data does.
// ============================================================
window.TonightRanking = (() => {
  const DEFAULT_WEIGHTS = {
    // -- proximity: score = clamp(selected − perStop·hops, floor..selected)
    selected: 10,        // at the selected station / any station of the selected area
    perStop: 5,          // penalty per station passed (adjacent = +5, two away = 0, …)
    transferStops: 2,    // extra hops charged per line change (two-seat rides read farther)
    proximityFloor: -15, // far events stop sinking here, so favorites/Lit can still lift them
    offMap: 0,           // events whose stop/square isn't on the traced map (e.g. Inman Square)
    // -- everything else
    sponsored: 8,        // kept BELOW `selected` so a paid post can't outrank the square you chose
    favoriteEvent: 5,
    favoriteVenue: 5,
    favoriteArtist: 5,
    litMax: 15,          // scaled by the hook's 0..1 lit level
    jitter: 2,           // daily-seeded shuffle — stable all night, fresh tomorrow, never alphabetical
  };

  const keyOf = (c, r) => c + "," + r;

  // ---- map index: stations, areas, and a hop-weighted graph -------------
  // Same coordinate-keyed dedupe as the app's MetroMap graph (a shared (c,r)
  // across branches is one node = a free interchange), but edges here are
  // weighted in hops-entering-a-station, not cells — ranking counts stops.
  function buildIndex(transit) {
    const nodes = new Map();       // key → {c, r, name, station}
    const adj = new Map();         // key → [{to, line}]
    const areaOfName = {};         // station name → area name (from node `square`)
    if (!transit || !Array.isArray(transit.lines)) return null;
    transit.lines.forEach(ln => (ln.branches || []).forEach(br => {
      const ns = br.nodes || [];
      for (let i = 0; i < ns.length; i++) {
        const n = ns[i], k = keyOf(n.c, n.r);
        let nd = nodes.get(k);
        if (!nd) { nd = { c: n.c, r: n.r, name: "", station: false }; nodes.set(k, nd); adj.set(k, []); }
        if (n.name) nd.name = n.name;   // branch-start convention: "" never overwrites a real name
        if (n.station) nd.station = true;
        if (n.name && n.square) areaOfName[n.name] = n.square;
        if (i > 0) {
          const pk = keyOf(ns[i - 1].c, ns[i - 1].r);
          adj.get(pk).push({ to: k, line: ln.line });
          adj.get(k).push({ to: pk, line: ln.line });
        }
      }
    }));
    const nameToKeys = new Map();  // station name → [keys] (an interchange has one key; a name reused on branches may have several)
    nodes.forEach((nd, k) => {
      if (!nd.station || !nd.name) return;
      if (!nameToKeys.has(nd.name)) nameToKeys.set(nd.name, []);
      nameToKeys.get(nd.name).push(k);
    });
    const areas = new Map();       // area name → [keys of member stations]
    const areaStations = {};       // area name → [member station names]
    for (const [name, area] of Object.entries(areaOfName)) {
      const keys = nameToKeys.get(name);
      if (!keys) continue;
      if (!areas.has(area)) { areas.set(area, []); areaStations[area] = []; }
      areas.get(area).push(...keys);
      areaStations[area].push(name);
    }
    return { nodes, adj, nameToKeys, areas, areaOf: areaOfName, areaStations };
  }

  // A selection name resolves to source node keys: a station name wins (so
  // "Davis" the station beats any hypothetical area of the same name), then
  // an area name (all member stations seed at distance 0). Null = off-map
  // selection (e.g. Inman Square) — scoring falls back to exact string match.
  function resolveSources(index, name) {
    return index.nameToKeys.get(name) || index.areas.get(name) || null;
  }

  // Multi-source Dijkstra in hop units. State is (node, line ridden in on) so
  // a line change costs `transferStops` extra hops. Entering a station node
  // costs 1; passing waypoints is free. NOTE: `line` is the color field, so
  // all future Bus routes read as one line — thread a route-identity field
  // here before drawing buses (same caveat as the app's trip router).
  function distancesFrom(index, sourceKeys, transferStops) {
    const dist = new Map();        // state id → d
    const best = new Map();        // node key → cheapest d over all states
    const pq = [];
    for (const k of sourceKeys) {
      const id = k + "|";
      dist.set(id, 0);
      pq.push({ id, key: k, line: null, d: 0 });
    }
    while (pq.length) {
      let mi = 0;
      for (let i = 1; i < pq.length; i++) if (pq[i].d < pq[mi].d) mi = i;
      const cur = pq.splice(mi, 1)[0];
      if (cur.d > (dist.get(cur.id) ?? Infinity)) continue;
      if (cur.d < (best.get(cur.key) ?? Infinity)) best.set(cur.key, cur.d);
      for (const e of (index.adj.get(cur.key) || [])) {
        const hop = index.nodes.get(e.to).station ? 1 : 0;
        const pen = cur.line && cur.line !== e.line ? transferStops : 0;
        const nd = cur.d + hop + pen;
        const nid = e.to + "|" + e.line;
        if (nd < (dist.get(nid) ?? Infinity)) {
          dist.set(nid, nd);
          pq.push({ id: nid, key: e.to, line: e.line, d: nd });
        }
      }
    }
    return best;
  }

  // Where an event anchors on the map: its own stop when the map knows it,
  // else its square as a station name, else its square as an area (any member
  // station counts). Null = off-map.
  function anchorKeys(index, e) {
    if (e.transit_stop && index.nameToKeys.has(e.transit_stop)) return index.nameToKeys.get(e.transit_stop);
    if (e.square) {
      if (index.nameToKeys.has(e.square)) return index.nameToKeys.get(e.square);
      if (index.areas.has(e.square)) return index.areas.get(e.square);
    }
    return null;
  }

  function anchorDist(index, dmap, e) {
    const keys = anchorKeys(index, e);
    if (!keys) return null;
    let d = Infinity;               // stays Infinity if unreachable → clamps to the floor
    for (const k of keys) {
      const v = dmap.get(k);
      if (v != null && v < d) d = v;
    }
    return d;
  }

  // FNV-1a → [0,1). Seeded per (day, event id): stable within the night so the
  // list never reshuffles mid-browse, fresh tomorrow, and never alphabetical.
  function hash01(s) {
    let h = 2166136261;
    for (let i = 0; i < s.length; i++) {
      h ^= s.charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
    return (h >>> 0) / 4294967296;
  }

  function scoreEvent(e, ctx) {
    const { W, index, dmap, selection, hooks, daySeed } = ctx;
    const parts = {};
    if (selection) {
      const d = index && dmap ? anchorDist(index, dmap, e) : null;
      let prox = d == null
        ? W.offMap
        : Math.max(W.proximityFloor, W.selected - W.perStop * d);
      // Exact string match always earns the full bonus — covers off-map
      // selections (no Dijkstra sources) and any map/data name drift.
      if (e.square === selection || e.transit_stop === selection) prox = Math.max(prox, W.selected);
      parts.proximity = prox;
    } else {
      parts.proximity = 0;          // "Near me" with no home square: geography is silent
    }
    parts.sponsored = e.sponsored ? W.sponsored : 0;
    parts.favoriteEvent = hooks?.isFavoriteEvent?.(e) ? W.favoriteEvent : 0;
    parts.favoriteVenue = hooks?.isFavoriteVenue?.(e) ? W.favoriteVenue : 0;
    parts.favoriteArtist = hooks?.isFavoriteArtist?.(e) ? W.favoriteArtist : 0;
    parts.lit = W.litMax * (hooks?.litLevel?.(e) || 0);
    parts.jitter = W.jitter * hash01(daySeed + "|" + (e.id ?? e.title ?? ""));
    let total = 0;
    for (const v of Object.values(parts)) total += v;
    return { total, parts };
  }

  // Rank events for display. opts:
  //   index     — buildIndex(transit), or null (no map → geography by string match only)
  //   selection — place name (station, area, or off-map square), or null
  //   weights   — overrides merged over DEFAULT_WEIGHTS (from data/ranking.json)
  //   daySeed   — string that changes daily (the app passes NOW.toDateString())
  //   hooks     — {isFavoriteEvent, isFavoriteVenue, isFavoriteArtist, litLevel(e)→0..1}
  //   tiebreak  — comparator for equal scores (the app breaks ties by start time)
  // Returns [{event, total, parts}] sorted best-first; `parts` is the
  // per-factor breakdown the tuner (and debugging) reads.
  function rank(events, opts = {}) {
    const W = { ...DEFAULT_WEIGHTS, ...(opts.weights || {}) };
    const index = opts.index || null;
    const selection = opts.selection || null;
    const sources = selection && index ? resolveSources(index, selection) : null;
    const dmap = sources ? distancesFrom(index, sources, W.transferStops) : null;
    const ctx = { W, index, dmap, selection, hooks: opts.hooks, daySeed: opts.daySeed || "" };
    const scored = events.map(e => ({ event: e, ...scoreEvent(e, ctx) }));
    const tb = opts.tiebreak || (() => 0);
    scored.sort((a, b) => (b.total - a.total) || tb(a.event, b.event));
    return scored;
  }

  return { DEFAULT_WEIGHTS, buildIndex, resolveSources, distancesFrom, anchorKeys, rank };
})();
