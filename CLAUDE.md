# Tonight — Claude Code guide

## Running the scraper

Always run from the **repo root**, not from inside `scraper/`:

```
python3 scraper/run_scraper.py                  # all venues
python3 scraper/run_scraper.py burren           # one venue by ID fragment
python3 scraper/run_scraper.py lamplighter --force  # bypass cache
```

Output goes to `data/events.json`. Cache is `scraper_cache.json` at root (gitignored).

**After editing venue config** (`scraper/venues.py` or `data/venues.json`), always use `--force` — otherwise the HTTP cache skips re-scraping and existing events keep stale values.

## Local preview

```
python3 -m http.server 8000
```

Then open `http://localhost:8000`. Opening `index.html` directly won't work — `fetch()` is blocked on `file://`.

## Two venue config files — intentionally separate

- `scraper/venues.py` — scraping config (URLs, strategies, selectors, routing). Drives the scraper only.
- `data/venues.json` — display config (walk times, phone, notes, logo). Read by the front end. The scraper never writes it.

Both must be kept in sync for shared fields (transit_line, transit_stop, walk_minutes, square).

## Event address vs venue address

An event's `address` field is the *event's actual location*, set **only** when the event happens somewhere other than the venue (e.g. a street festival). When it's `null`, the event is at the venue and the front end inherits the venue address from `data/venues.json` via `venue_id` (`venueFor()` → `e.address || vd.address`). The scraper never stamps the venue address onto events anymore.

Per-event address extraction is opt-in: set `event_address: True` on a venue in `scraper/venues.py` only if that source sometimes hosts events off-site. It costs extra LLM extraction, so most venues should leave it off. When set, the scraper also records the event-location `square` (validated against the front-end chip list) so the filter buckets the event where it actually happens.

## Transit color

`transit_color` does not exist anywhere in the data. Color is derived from `transit_line` at render time via `LINE_COLORS` in `js/app.js`. Never add a `transit_color` field — the point is that a known line cannot render the wrong color.

Supported line names: `Red`, `Orange`, `Green`, `Blue`, `Silver`, `Bus`, `Commuter Rail`, `Ferry`.

## The 4am rollover — two runtimes, one rule

The front end's `getNow()` in `js/app.js` is the sole authority on what counts as "tonight." The scraper's `cutoff_datetime()` in `run_scraper.py` is intentionally loose (36h lookback) — it only archives old events so the active list doesn't grow forever. Do not make the scraper cutoff precise; see NOTES.md for the bug this prevented.

## Known limitations

- `venue_id` is stamped on newly scraped events; the front end joins to `data/venues.json` via `venueFor()`, falling back to `id` string parsing for older events scraped before stamping. Re-scrape a venue with `--force` to migrate its events.
- EDT/UTC-4 is hardcoded in `run_scraper.py` — off by one hour in winter (EST). Low priority until the app has winter users.
- Club Passim captures ~7 events per scrape due to JS pagination. Playwright needed for the full calendar.

## Transit map — tool files

The transit navigation layer lives in three standalone HTML files at the repo root (no build step, open via `python3 -m http.server 8000`):

- **`transit-layer-editor.html`** — draw MBTA-style lines on a 140×140 tile grid matching the Tiled terrain map. Export `transit-layer.json` (schema `tonight.transit/1`) and `transit-layer.png`.
- **`transit-animation-preview.html`** — load `transit-layer.json`, auto-load `transit-layer.png` as base image, pick origin/destination, animate a train with Dijkstra routing + transfer penalty.
- **`sample-transit.json`** — 70×70 stylized MBTA sample (Red/Orange/Green/Blue) used as fallback when `transit-layer.json` isn't served.

### Data files

- **`transit-layer.json`** — the real traced MBTA network (140×140 grid). Station names are filled in. User maintains this; update via the editor and re-export.
- **`prototype/station_list.csv`** — authoritative station list (renamed from `stations.csv`). Format: `Line/Branch, Station Name, Include, Alt Square Name`. Includes Armory Street (Green B consolidation). Source of truth for the label tool's bulk-fill and autocomplete.

### Key design rules

- **Color is always derived from the line name** via `LINE_COLORS` in `js/app.js`. Never store `transit_color` anywhere — same rule as the event/venue data.
- **`transit-layer.json` schema:** nodes are `{c, r, station, name, square?}`. `square` maps to the app's filter chip. Interchanges are detected automatically by shared `(c,r)` coordinates across branches/lines — no explicit interchange field.
- **Branch-start naming convention:** when a branch begins at a node that already exists on the main branch (e.g. JFK/UMass on Red Braintree/Ashmont, Kenmore on Green sub-branches), the branch-start node is left with `name: ""`. The graph builder picks up the name from whichever copy has it. Never use `" "` (a space) as a placeholder — that is truthy in JS and will overwrite a valid name from a sibling branch.
- **Routing:** Dijkstra over `(node, came-from, line)` state tuples. Transfer penalty `TRANSFER_PENALTY=6` (fake cell distance) applies on line changes AND same-line heading reversals >90° (branch junctions like JFK/UMass). Never convert this penalty to display time.
- **Animation:** arc-length interpolation (cells/sec, not fixed duration). 0.95s dwell only at line transfers and >90° branch reversals — not at plain stations. Train morphs color and rotates the short way during dwell.
- **Grid alignment:** tile count (140×140), not pixel size, is the contract between editor, Tiled terrain map, and app. CELL=16 world px in both tools.

### Pending transit work

- Generate `station_list.csv` from MBTA GTFS `stops.txt` (V3 API: `https://api-v3.mbta.com/stops`) to stay current with service changes. Add stable GTFS `id` field to each station node.
- Use `status` field (`open` / `temporary_closed` / `closed`) instead of deleting stations for closures like Symphony renovation.
- **Square coverage on the in-app metro map:** the overlay filters by station *name* (an event's `square` joins to a grid node's `name`). Most current events match a station, but any `square` value with no matching named node in `transit-layer.json` is unreachable on the map — it can't be tapped to filter. Audit `eventSquares` against the grid's node names and backfill missing stations (or add an explicit `square` field) so every filterable square has a home on the map.

## Deployment

GitHub Pages serves the repo root. Push to `main` → live within ~1 minute. The scraper runs automatically via GitHub Actions (`scrape.yml`) daily at 6am ET and commits updated `events.json` directly to `main`.

**Before pushing local scraper runs:** pull first (`git pull --rebase`) to avoid conflicts with the Action's commit. If `events.json` conflicts, use the scraper's `merge_events` function to reconcile both versions by event ID.
