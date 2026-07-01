// ============================================================
// Artist matching — shared by the app (js/app.js) and the curator
// tool (curator.html). Pure functions, no DOM, no globals mutated
// except the index object the caller passes back in. Attached to
// window.ArtistMatch so both a <script> include and the app can use it.
//
// Matching is deliberately conservative — a wrong band photo is worse
// than none. Exact normalized key first (name or any alt_names), then a
// token-subset pass that fires ONLY for multi-word acts. Single short
// names (LDQ, Indigo) match by exact key only. The escape hatch for a
// title the extractor phrases oddly is to add an alt_names entry.
// ============================================================
(function (global) {
  // Fold a name to a comparison key: lowercase, drop apostrophes, spell out
  // "&", strip leading articles and a trailing "band", collapse whitespace.
  function normName(s) {
    return (s || "")
      .toLowerCase()
      .replace(/[’'`]/g, "")
      .replace(/&/g, " and ")
      .replace(/[^a-z0-9]+/g, " ")
      .replace(/\b(the|a|an)\b/g, " ")
      .replace(/\bband\b/g, " ")
      .trim()
      .replace(/\s+/g, " ");
  }

  // Strip a stage prefix ("Toad: ...", "McCarthys - ...") from a title.
  function stripStage(title) {
    return (title || "").replace(/^\s*(mccarthys|toad|upstairs)\s*[:\-]\s*/i, "");
  }

  // Pull the likely performer out of a title: a quoted act wins, else the part
  // after "with", else the whole (de-staged) title.
  function performerFromTitle(title) {
    const t = stripStage((title || "").replace(/&amp;/g, "&"));
    const quoted = t.match(/[‘’'"“”]([^‘’'"“”]+)[‘’'"“”]/);
    if (quoted) return quoted[1];
    const withMatch = t.match(/\bwith\s+(.+?)(?:\s+and\s+friends.*)?$/i);
    if (withMatch) return withMatch[1];
    return t;
  }

  // Build the lookup index once from the artists array. Beyond name/alt_names,
  // an entry may carry two optional fields:
  //   • titles         — exact event titles that ALWAYS map here (highest
  //                       priority; the way to correct a wrong auto-match)
  //   • match_contains  — substrings that catch-all when nothing else hits
  //                       (lowest priority; house/generic images, e.g. a
  //                       shared "Irish Session" photo)
  function buildIndex(artists) {
    const byKey = new Map();
    const entries = [];
    for (const a of artists || []) {
      const names = [a.name, ...(a.alt_names || [])].filter(Boolean);
      for (const n of names) {
        const key = normName(n);
        if (key && !byKey.has(key)) byKey.set(key, a); // first spelling wins
      }
      entries.push({
        artist: a,
        tokens: normName(a.name).split(" ").filter(Boolean),
        titleKeys: (a.titles || []).map(normName).filter(Boolean),
        contains: (a.match_contains || []).map(normName).filter(Boolean),
      });
    }
    return { byKey, entries };
  }

  // Resolve a title to an artist record (or null), with a `reason` on the
  // return via matchInfo(). Priority, most to least specific:
  //   1. titles          — explicit per-title override
  //   2. exact name/alt   — on the parsed performer, then the de-staged title
  //   3. token subset     — all of a multi-word act's words appear in the title
  //   4. match_contains   — catch-all substring
  function matchInfo(index, title) {
    if (!index || !index.entries.length) return null;
    const fullKey = normName(title);
    for (const entry of index.entries) {
      if (entry.titleKeys.includes(fullKey)) return { artist: entry.artist, reason: "title override" };
    }
    const perf = normName(performerFromTitle(title));
    const whole = normName(stripStage(title));
    if (perf && index.byKey.has(perf)) return { artist: index.byKey.get(perf), reason: "exact name" };
    if (whole && index.byKey.has(whole)) return { artist: index.byKey.get(whole), reason: "exact name" };
    const haystack = new Set(`${perf} ${whole}`.split(" ").filter(Boolean));
    for (const entry of index.entries) {
      if (entry.tokens.length >= 2 && entry.tokens.every(tok => haystack.has(tok))) {
        return { artist: entry.artist, reason: "token match" };
      }
    }
    for (const entry of index.entries) {
      if (entry.contains.some(c => whole.includes(c))) return { artist: entry.artist, reason: "contains rule" };
    }
    return null;
  }

  function match(index, title) {
    const info = matchInfo(index, title);
    return info ? info.artist : null;
  }

  global.ArtistMatch = { normName, stripStage, performerFromTitle, buildIndex, match, matchInfo };
})(typeof window !== "undefined" ? window : this);
