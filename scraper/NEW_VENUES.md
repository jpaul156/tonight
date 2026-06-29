# New venue scraping assessment

## Sheet3 batch (2026-06-29)

**Added & live:**
| Venue | Square | Strategy | Result |
|---|---|---|---|
| The Rockwell | Davis | `jsonld_events` (new, reusable) | 67 events — server-rendered schema.org Event JSON-LD w/ price ranges + images |
| The Lilypad | Inman Sq | `squarespace_events` | 125 events — jazz/avant-garde; collection at `/home` (found via sitemap) |
| Bow Market | Union Sq | `squarespace_events` | Wired but **0 now** — its `/upcomingevents` collection is stale (nothing after 2026-06-14); self-populates if resumed |

**Not added — documented for later:**
| Venue | Why | Path |
|---|---|---|
| Phoenix Landing | `/events` is recurring weekly programming written as prose ("Wednesdays 7pm Trivia…"), not dated events | Better as curated recurring entries (like `deals.json`) |
| Cantab Lounge | Custom site; the event calendar isn't on the homepage and wasn't located | Find the calendar page/feed |
| Brighton Music Hall | Shopify (Crossroads/AEG umbrella); events not exposed via products.json or JSON-LD | Investigate the shows feed |
| Laugh Boston | **Tixr** platform (calendar.laughboston.com); also out-of-core (Seaport) | Tixr API parser (new) if in scope |
| Improv Asylum | **Tixr** platform; out-of-core (North End) | Same as above |

New reusable strategy this batch: **`jsonld_events`** — parses any page that
server-renders schema.org `Event` JSON-LD (The Events Calendar, etc.).

---

# Sheet2 batch

## Build status (2026-06-29)

**Live now** (added to `venues.py` + `data/venues.json`, scraped with
`html_full_text` + LLM, verified output):

| Venue | Events 1st run | Notes |
|---|---|---|
| Sally O'Brien's | 30 | Clean. Music/other, dates + costs. |
| Arts at the Armory | 41 | Clean. Wide category mix (music/comedy/fitness/film…). |
| The Sinclair | 20 | Clean. Mostly music, good forward range. |
| The Plough and Stars | ~3 active/run | Works, but the calendar shows a short rolling window — accumulates via merge, like passim. |

**Reclassified — turned out JS-rendered, NOT the easy path** (removed from the
active config so they don't burn daily LLM calls returning nothing; need a feed
parser or headless render):

| Venue | Reality | Next step |
|---|---|---|
| ~~The Comedy Studio~~ **DONE** | Not Dice after all — the Dice block was vestigial. Real box office is **SeatEngine**, which ships a JSON-LD `EventVenue.events[]` (151 events w/ price, image, performer). Built `seatengine` strategy (no LLM); 136 active events. Parser is reusable for any SeatEngine comedy club. |
| Porter Square Books | JS calendar; TEC REST API returns **403** | Find the calendar's JSON feed with the right headers, or headless. |
| ~~McCarthy's and Toad~~ **DONE** | Squarespace JS calendar. Events collection lives at `/music?format=json` — 226 upcoming, **every one with an image**. Built `squarespace_events` strategy (no LLM); reusable for Bow Market. |

---

Recon done 2026-06-29 against the 12 venues in `Venue List - Sheet2.csv`.
Method: fetched each event page with a browser UA and inspected the **static
HTML** for (a) inline structured data (JSON-LD `Event`, platform JSON) and
(b) whether event titles/dates render server-side or only after JS.

**Headline:** none of the 12 ship inline JSON-LD `Event` data (the JSON-LD
present is just site/venue metadata). So the split is: *event text is in the
static HTML* → LLM text extraction works today (the `html_full_text` path we
use for **passim**/**vrcc**); *event data is JS-loaded* → we must find the
platform's JSON feed (basic, no LLM, like **wix_events**/**burren_tables**) or
fall back to headless rendering.

Strategy vocabulary referenced below maps to `scraper_core.py`:
- `html_full_text` + LLM — strip body text, Haiku extracts. Easiest to add.
- bespoke structured parser (no LLM) — like `extract_wix_events` /
  `extract_burren_tables`. More work up front, cheaper + sturdier per run.

## Tier 1 — easy, LLM text extraction (copy passim/vrcc)
Event text is server-rendered; point `html_full_text` at the page and go.

| Venue | Page | Notes |
|---|---|---|
| **Sally O'Brien's** | /music/ | Plain HTML list, no platform. Lots of static showtimes. Cleanest LLM target. |
| **Arts at the Armory** | /upcoming-events/ | WordPress + The Events Calendar; very rich static text. *Better:* try the TEC REST API `…/wp-json/tribe/events/v1/events` for a no-LLM parse. |
| **The Comedy Studio** | /events | Static text present, but page is ~1.3 MB — trim to the listing before sending to the LLM. |
| **The Plough and Stars** | calendar.ploughandstars.com | Hosted calendar subdomain; small server-rendered list. LLM works; check for a feed first. |

## Tier 2 — basic parse available (find the feed, no LLM)
JS calendars, but the platform exposes machine-readable event data.

| Venue | Platform | Path to data |
|---|---|---|
| **McCarthy's and Toad** | Squarespace | Static HTML nearly empty (JS). Use the Squarespace events-collection JSON (`?format=json`); the `/calendar` page is just a `calendarView` shell — need the underlying events collection URL. |
| **Porter Square Books** | WordPress + FullCalendar | List text is in static HTML (LLM works), but FullCalendar pulls a JSON feed (admin-ajax/REST) that's cleaner. |
| **The Sinclair** | Carbonhouse (AEG) | Server-rendered, consistent markup (`disco-controller`). A bespoke Carbonhouse parser would be **reusable across many AEG venues**. LLM works as a fast start. |

## Tier 3 — medium, has a routing or format wrinkle
| Venue | Issue |
|---|---|
| **Somerville Theatre / Crystal Ballroom** | WordPress; **two event types** — film showtimes + Ballroom concerts (Ticketmaster). Static showtimes are sparse. LLM on the listing first; verify both types land. |
| **Brattle Theatre** | `/calendar` 404s — need the correct repertory-film schedule URL (homepage links didn't expose it cleanly). Daily film showtimes; LLM once URL is found. |
| **Bow Market** | Squarespace **multi-tenant market** (Comedy Studio @ Bow, Remnant Brewing, Loyal Nine…). Needs per-sub-venue routing like Lamplighter's `extra_venues`/`location_keywords`. |
| **Middle East** | WordPress + FullCalendar via `admin-ajax.php`; **4 rooms** (Up/Down/Corner/Sonia), heavy volume. Find the AJAX feed (basic) and route by room. |

## Tier 4 — hard / blocked
| Venue | Issue |
|---|---|
| **Aeronaut Brewing** | Returns **403** to a plain request and the events live in a JS widget at `#events` (no server-rendered event text). Needs better headers, the widget's API, or headless rendering. Investigate separately. |

## Cross-cutting flags
- **Square coverage:** several sit at **Union Square / Magoun (GLX Green)** —
  squares that are **not yet on the metro map** (`LINES` in `js/app.js`). They'll
  scrape fine but won't be tappable on the map until backfilled (see the
  "square coverage" item in CLAUDE.md → Pending transit work).
- **New display fields:** each venue needs `square`, `transit_line`,
  `transit_stop`, `walk_minutes`, `is_local` in **both** `scraper/venues.py`
  and `data/venues.json`. The CSV's transit guesses cover most of this.
- **New categories:** film, author talks, arts — map to existing `film` /
  `community`; the app's category list is fixed in `js/app.js`.
</content>
