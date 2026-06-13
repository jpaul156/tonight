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
  community: `<path d="M4 19V5a2 2 0 0 1 2-2h9l5 5v11a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z"/><line x1="8" y1="8" x2="14" y2="8"/><line x1="8" y1="12" x2="16" y2="12"/><line x1="8" y1="16" x2="13" y2="16"/>`
};

const SQUARES = ["Davis", "Porter", "Harvard", "Central", "Kendall", "Union Square"];
const CATEGORIES = ["music", "trivia", "comedy", "film", "market", "karaoke", "community"];

// Stand-in for "now" — once real scraping is in place this becomes new Date()
const NOW = new Date("2026-06-12T17:00:00");

let allEvents = [];
let activeSquare = "all";
let activeCategory = "all";

init();

async function init() {
  setDate();
  buildFilterChips();
  allEvents = await loadEvents();
  render();
  wireDetailOverlay();
  wireCollapsingHeader();
  window.addEventListener("hashchange", handleHash);
  handleHash();
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
    document.getElementById("today-date").style.opacity = String(1 - progress);
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
    return await res.json();
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
// Main feed
// ============================================================

function render() {
  const list = document.getElementById("event-list");
  const empty = document.getElementById("empty-state");
  list.innerHTML = "";

  let events = allEvents
    .filter(e => new Date(e.end) > NOW) // tonight's feed only shows what's still ahead
    .filter(e => {
      const squareMatch = activeSquare === "all" || e.square === activeSquare;
      const categoryMatch = activeCategory === "all" || e.category === activeCategory;
      return squareMatch && categoryMatch;
    });

  events.sort((a, b) =>
    activeSquare === "all"
      ? a.walk_minutes - b.walk_minutes
      : new Date(a.start) - new Date(b.start)
  );

  if (events.length === 0) {
    empty.hidden = false;
    return;
  }
  empty.hidden = true;

  events.forEach(e => list.appendChild(renderCard(e)));
}

function renderCard(e) {
  const article = document.createElement("article");
  article.className = "card";
  article.tabIndex = 0;
  article.setAttribute("role", "button");
  article.addEventListener("click", () => { location.hash = e.id; });
  article.addEventListener("keydown", ev => {
    if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); location.hash = e.id; }
  });

  const art = document.createElement("div");
  art.className = `card-art cat-${e.category}`;
  art.appendChild(buildArt(e));

  const body = document.createElement("div");
  body.className = "card-body";
  body.innerHTML = `
    <div class="card-meta">
      <span class="category-tag">${e.category}</span>
      <span class="cost">${e.cost}</span>
    </div>
    <h2 class="card-title">${e.title}</h2>
    <p class="card-venue">${e.venue}</p>
    <p class="card-time">${formatTimeRange(e.start, e.end)}</p>
    <div class="transit-badge" style="--line-color:${e.transit_color}">
      <span class="transit-dot"></span>
      <span class="transit-text">${e.transit_stop} → ${e.walk_minutes} min</span>
    </div>
  `;

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

  document.getElementById("detail-category").textContent = e.category;
  document.getElementById("detail-cost").textContent = e.cost;
  document.getElementById("detail-title").textContent = e.title;
  document.getElementById("detail-time").textContent = formatFullTimeRange(e.start, e.end);
  document.getElementById("detail-description").textContent = e.description || "";

  const transit = document.getElementById("detail-transit");
  transit.style.setProperty("--line-color", e.transit_color);
  document.getElementById("detail-transit-text").textContent =
    `${e.transit_stop} → ${e.walk_minutes} min`;

  document.getElementById("detail-venue-avatar").textContent = e.venue.charAt(0);
  document.getElementById("detail-venue-name").textContent = e.venue;
  document.getElementById("detail-venue-address").textContent = e.address || "";

  document.getElementById("detail-directions").href =
    `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(e.address || e.venue)}`;

  const ticketBtn = document.getElementById("detail-tickets");
  if (e.ticket_url) {
    ticketBtn.href = e.ticket_url;
    ticketBtn.hidden = false;
  } else {
    ticketBtn.hidden = true;
  }

  renderMoreFrom("more-venue", "more-venue-list", null,
    allEvents.filter(o => o.venue === e.venue && o.id !== e.id && new Date(o.end) > NOW));

  const performerHeading = document.getElementById("more-performer-heading");
  if (e.performer) performerHeading.textContent = `More from ${e.performer}`;
  renderMoreFrom("more-performer", "more-performer-list", null,
    e.performer
      ? allEvents.filter(o => o.performer === e.performer && o.id !== e.id && new Date(o.end) > NOW)
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
  const fmt = d => d.toISOString().replace(/[-:]/g, "").split(".")[0];
  const ics = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "BEGIN:VEVENT",
    `UID:${e.id}@tonight`,
    `DTSTART:${fmt(new Date(e.start))}`,
    `DTEND:${fmt(new Date(e.end))}`,
    `SUMMARY:${e.title}`,
    `LOCATION:${e.venue}, ${e.address || ""}`,
    `DESCRIPTION:${(e.description || "").replace(/\n/g, "\\n")}`,
    "END:VEVENT",
    "END:VCALENDAR"
  ].join("\r\n");

  const blob = new Blob([ics], { type: "text/calendar" });
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

function formatTimeRange(start, end) {
  const opts = { hour: "numeric", minute: "2-digit" };
  const s = new Date(start).toLocaleTimeString("en-US", opts);
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
