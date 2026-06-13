// ============================================================
// Tonight — front end logic
// Loads data/events.json, renders the feed, and wires up the
// square / category filter chips.
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

let allEvents = [];
let activeSquare = "all";
let activeCategory = "all";

init();

async function init() {
  setDate();
  buildFilterChips();
  allEvents = await loadEvents();
  render();
}

function setDate() {
  const el = document.getElementById("today-date");
  const today = new Date();
  el.textContent = today.toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric"
  });
}

async function loadEvents() {
  try {
    const res = await fetch("data/events.json");
    const data = await res.json();
    // Only show events that haven't ended yet, soonest first by default
    return data
      .filter(e => new Date(e.end) > new Date("2026-06-12T17:00:00"))
      .sort((a, b) => new Date(a.start) - new Date(b.start));
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

function render() {
  const list = document.getElementById("event-list");
  const empty = document.getElementById("empty-state");
  list.innerHTML = "";

  let events = allEvents.filter(e => {
    const squareMatch = activeSquare === "all" || e.square === activeSquare;
    const categoryMatch = activeCategory === "all" || e.category === activeCategory;
    return squareMatch && categoryMatch;
  });

  // "Near me": sort by walk time (stand-in for distance from the user).
  // Square filters preserve chronological order within that square.
  if (activeSquare === "all") {
    events = [...events].sort((a, b) => a.walk_minutes - b.walk_minutes);
  }

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

  const art = document.createElement("div");
  art.className = `card-art cat-${e.category}`;
  if (e.image_url) {
    const img = document.createElement("img");
    img.src = e.image_url;
    img.alt = "";
    img.style.width = "100%";
    img.style.height = "100%";
    img.style.objectFit = "cover";
    art.appendChild(img);
  } else {
    art.innerHTML = `<svg viewBox="0 0 24 24">${ICONS[e.category] || ""}</svg>`;
  }

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
      <span class="transit-text">${e.transit_line.toUpperCase()} · ${e.transit_stop.toUpperCase()} · ${e.walk_minutes} MIN WALK</span>
    </div>
  `;

  article.appendChild(art);
  article.appendChild(body);
  return article;
}

function formatTimeRange(start, end) {
  const opts = { hour: "numeric", minute: "2-digit" };
  const s = new Date(start).toLocaleTimeString("en-US", opts);
  const en = new Date(end).toLocaleTimeString("en-US", opts);
  return `${s} – ${en}`;
}

function capitalize(s) {
  return s.charAt(0).toUpperCase() + s.slice(1);
}
