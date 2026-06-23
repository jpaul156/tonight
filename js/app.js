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

const SQUARES = ["Davis", "Porter", "Harvard", "Central", "Kendall", "Lechmere", "Union Square", "Maverick", "Wonderland"];
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

init();

async function init() {
  setDate();
  buildFilterChips();
  let deals;
  [allEvents, venueData, deals] = await Promise.all([loadEvents(), loadVenues(), loadDeals()]);
  allEvents = allEvents.concat(deals);
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
  const squareRow = document.getElementById("square-filters");
  const categoryRow = document.getElementById("category-filters");

  addChip(squareRow, "Near me", "all", "square");
  SQUARES.forEach(sq => addChip(squareRow, sq, sq, "square"));

  addChip(categoryRow, "All", "all", "category");
  CATEGORIES.forEach(cat => addChip(categoryRow, capitalize(cat), cat, "category"));
}

function addChip(row, label, value, group) {
  const btn = document.createElement("button");
  btn.className = "chip" + (value === "all" ? " active" : "");
  btn.textContent = label;
  btn.dataset.value = value;
  btn.addEventListener("click", () => {
    row.querySelectorAll(".chip").forEach(c => c.classList.remove("active"));
    btn.classList.add("active");
    if (group === "square") activeSquare = value;
    if (group === "category") activeCategory = value;
    render();
  });
  row.appendChild(btn);
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

  const sortFn = (a, b) =>
    activeSquare === "all"
      ? a.walk_minutes - b.walk_minutes || startMs(a) - startMs(b)
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
