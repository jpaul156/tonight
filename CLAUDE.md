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

Each run also writes `data/scrape_health.json` (dashboard data) and, when the events age out, `data/archive.json`. See "Data lifecycle" and "Health dashboard" below.

## Data lifecycle — three tiers (events.json + archive.json)

`run_scraper.py`'s `partition_events` splits every merged event by age:

- **active** (`events.json` → `events`) — end/start ≥ now−36h. Tonight + future + just-ended. The only tier the front end fetches.
- **recent past** (`events.json` → `past_events`) — 36h–7 days old. Kept only so the scraper can detect "was live yesterday, gone today"; the app ignores it.
- **archived** (`data/archive.json`) — older than 7 days. Appended to a growing archive the app never fetches, then dropped from `events.json` so the shipped payload stays bounded (~9 days). Merged by id, never deleted.

Two cutoffs, deliberately: `ARCHIVE_LOOKBACK` (36h, the active/just-ended line — do NOT make precise, see the 4am-rollover note) and `ARCHIVE_RETENTION` (7 days, the archive line).

## Health dashboard — `app_health.html` + `data/scrape_health.json`

`app_health.html` is an **unlisted** (noindex) static page that reads `data/scrape_health.json` and `data/todo.json`. Calm/serene when all-clear, amber for notes, loud red for errors/broken venues sorted to the top. Each scraper run rewrites `scrape_health.json` (schema `tonight.health/1`): per-venue status (ok/idle/warning/error), event count + delta vs last run, whether it still uses the LLM, plus global totals, by-square counts, no-image %, **off-map squares** (event squares with no matching metro-map station — the `Davis` vs `Davis Square` class of bug), and test status.

- Per-venue signals that don't survive into `events.json` (a truncated extraction, a parse error) come from a `report` dict threaded through `scrape_venue` → `clean_json`. `clean_json` sets `report["truncated"]` **only** on genuine token-limit truncation (trailing events lost), never on routine fence stripping.
- Venues known to yield 0 events (stale calendar or JS-only site awaiting Playwright) set `expected_empty: True` in `venues.py` so they read as calm "idle", not "error".
- `event_count` is a venue's contribution to the live feed (computed after partitioning), so it's meaningful on cache-hits and partial runs; the breakage signal keys off this run's *yield* instead.
- `data/todo.json` (schema `tonight.todo/1`) is the hand-maintained running to-do list surfaced on the dashboard — keep it roughly in sync with the "Pending work" sections here.

## Tests

```
pip install -r requirements-dev.txt
python3 scraper/run_tests.py     # runs pytest + writes data/test_status.json
```

`scraper/tests/` covers the fragile pure functions (date parsers incl. Dec→Jan rollover via freezegun, `clean_json` truncation vs fence stripping, private-event/address/routing rules), the structured extractors (synthetic fixtures — add a saved fixture when a live site changes format), and data contracts (`venues.py`↔`venues.json` sync, `events.json` shape, `partition_events` tiering). `run_tests.py` writes `data/test_status.json`, which feeds the dashboard. Both CI workflows (`tests.yml` on push/PR, and `scrape.yml` before the daily scrape) run it.

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

## Private / closed-to-the-public events

Some feeds list private bookings (e.g. the Lilypad's "** Private Event **", where the venue is closed to the public). `is_private_event()` in `scraper_core.py` flags these with `private: true` on the event — detection is narrow on purpose (title contains "private event", or description says "closed to the public") so an event that merely mentions private-booking availability in a footer isn't caught. The front end **hides `private` events from the main feed and from the metro-map square list** (`render()` and `eventSquares` in `js/app.js`), but keeps them in a venue's "More from this venue" list so a venue view still shows it's booked. We flag rather than drop so that "closed tonight" signal survives. Events scraped before this flag existed simply lack the field — `!e.private` treats missing as not-private (shown), so re-scraping is optional.

## Artist enrichment & image crops — hand-maintained overlays

Two optional front-end-only files decorate events without the scraper ever touching them (same contract as `data/venues.json` — the daily scrape can't clobber them):

- **`data/artists.json`** (schema `tonight.artists/1`) — per-performer `website` + `image_url`. The front end (`artistFor()` in `js/app.js`) matches an event to an artist and, **only when the event has no image of its own**, uses the artist's photo. `eventImage()` is the single source of truth for which image + crop an event shows. The artist website surfaces as a link in the detail overlay. Adding an artist never creates events — it only decorates existing ones.
- **`data/image-crops.json`** — flat map of image URL → CSS `object-position` (e.g. `"50% 20%"`). Keyed by URL so a hand-picked focal point outlives the scraper's daily rewrite of `events.json`. Applied to card + detail art.

**Fuzzy matching (`js/artist-match.js`, shared by app + `curator.html`):** deliberately conservative to avoid false positives. `performerFromTitle()` strips a stage prefix and prefers a quoted act / the part after "with"; `normName()` folds case, apostrophes, `&`, leading articles and a trailing "band". Match precedence, most-to-least specific:
1. **`titles`** — exact event titles force-mapped to an entry (the way to *correct* a wrong auto-match, e.g. a quoted series name like "Banjo Mondays" outranking the real musician).
2. **exact key** — normalized name or any `alt_names`, on the parsed performer then the de-staged title.
3. **token subset** — fires **only for multi-word acts** (all the artist's words appear in the title). Single short names (LDQ, Indigo) match by exact key only.
4. **`match_contains`** — catch-all substrings, for house/generic images (e.g. one shared "Irish Session" photo). Specific artists always win over this.

When a title phrases an act in a way the extractor misses, the fix is an `alt_names` (or `titles`) entry — a one-time edit that improves every future day with no rescrape. The `curator.html` tool writes all of these.

**Dead images degrade gracefully:** a stored `image_url` can rot (a venue deletes its photo, an artist page moves). `img.onerror` in `js/app.js` swaps a failed image for the category icon (`categoryIcon()`) instead of a broken tile — so reusing a venue CDN URL as an artist image is safe, though for keepers prefer downloading + committing a stable copy over hotlinking.

## Transit color

`transit_color` does not exist anywhere in the data. Color is derived from `transit_line` at render time via `LINE_COLORS` in `js/app.js`. Never add a `transit_color` field — the point is that a known line cannot render the wrong color.

Supported line names: `Red`, `Orange`, `Green`, `Blue`, `Silver`, `Bus`, `Commuter Rail`, `Ferry`.

## The 4am rollover — two runtimes, one rule

The front end's `getNow()` in `js/app.js` is the sole authority on what counts as "tonight." The scraper's `cutoff_datetime()` in `run_scraper.py` is intentionally loose (36h lookback) — it only archives old events so the active list doesn't grow forever. Do not make the scraper cutoff precise; see NOTES.md for the bug this prevented.

## Native categories from structured feeds

Some structured feeds carry their own event category (e.g. Aeronaut's CDN JSON feed). When they do, map it to `VALID_CATEGORIES` in the extractor and set `category` on each raw event: `build_events` prefers an extractor-supplied category, and the LLM classify pass (Pass 3) is skipped entirely when *every* event already has one. Prefer this over the LLM classifier whenever the source gives a usable category — it's free and deterministic. See `AERONAUT_CATEGORY_MAP` / `extract_aeronaut_events` in `scraper_core.py` for the pattern.

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
- **`transit-layer.json` schema:** nodes are `{c, r, station, name, square?, minor?}`. `square` maps to the app's filter chip. Interchanges are detected automatically by shared `(c,r)` coordinates across branches/lines — no explicit interchange field.
- **Minor stops:** `station` stays a boolean (is this a boardable stop). `minor: true` is an orthogonal downgrade for low-priority infill stops (Silver Line terminal/Washington St stops, residential Green Line surface stops) — **absent = normal/major**, so no existing data needs migration. Minor stops draw a smaller/thinner ring, and because a minor stop rarely has events they fall out of `isFilterable` → automatically unlabeled and non-tappable unless something happens there. A full-size copy of a shared node wins (`nd.major` beats `nd.minor` in `buildGraph`), and the interchange diamond always wins over both. Never make `station` a string enum — it's read as a truthy boolean in ~10 places across the editor and app. In the editor, **`S` cycles waypoint → station → minor stop** (both for the placement mode and for the selected node); export emits `minor` only when true.
- **Which line(s) a square sits on is derived from `transit-layer.json`, not a hand-maintained table.** `buildStationLineIndex()` in `js/app.js` walks the loaded map (`lines[].branches[].nodes[]`) and maps each station name → its trunk color(s); `stationLines()` is a lookup into that index. This is the single source of truth the pinned square-indicator dot and the metro overlay both read — add a station to the map and its square lights up the right color automatically. (Previously a stale hardcoded `LINES` table predating the Green Line Extension caused Union Square / all GLX stops to fall through to the amber "all" dot.)
- **Branch-start naming convention:** when a branch begins at a node that already exists on the main branch (e.g. JFK/UMass on Red Braintree/Ashmont, Kenmore on Green sub-branches), the branch-start node is left with `name: ""`. The graph builder picks up the name from whichever copy has it. Never use `" "` (a space) as a placeholder — that is truthy in JS and will overwrite a valid name from a sibling branch.
- **Routing:** Dijkstra over `(node, came-from, line)` state tuples. Transfer penalty `TRANSFER_PENALTY=6` (fake cell distance) applies on line changes AND same-line heading reversals >90° (branch junctions like JFK/UMass). Never convert this penalty to display time.
- **Animation:** arc-length interpolation (cells/sec, not fixed duration). 0.95s dwell only at line transfers and >90° branch reversals — not at plain stations. Train morphs color and rotates the short way during dwell.
- **Grid alignment:** tile count (140×140), not pixel size, is the contract between editor, Tiled terrain map, and app. CELL=16 world px in both tools.

### Pending transit work

- Generate `station_list.csv` from MBTA GTFS `stops.txt` (V3 API: `https://api-v3.mbta.com/stops`) to stay current with service changes. Add stable GTFS `id` field to each station node.
- Use `status` field (`open` / `temporary_closed` / `closed`) instead of deleting stations for closures like Symphony renovation.
- **Square coverage on the in-app metro map:** the overlay filters by station *name* (an event's `square` joins to a grid node's `name` in `transit-layer.json`). Most squares map fine (Union Square, Magoun Square, Lechmere are all present). The known gap is **Inman Square** (The Lilypad) — a bus neighborhood with no train station. By design Inman Sq has no map node, so The Lilypad shows in the full "Near me" list but is never tied to a station square (the `square === activeSquare` filter never matches it). This is the intended behavior for bus-only neighborhoods.
- **Frequent Bus Network data (built).** `scraper/refresh_frequent_bus.py` pulls the MBTA-maintained Frequent Bus list from the V3 API (`/routes?filter[type]=3`, keeping `description == "Frequent Bus"`) and writes `data/frequent_bus.json` (schema `tonight.frequentbus/1`). We use MBTA's own designation rather than recomputing headways — the frequent label lives only on the API, and MBTA re-rates the set periodically. Refreshed weekly by `.github/workflows/frequent-bus.yml` (Mondays). Each run **diffs against the committed file** and records `changes` (routes added/dropped, endpoint changes) + `last_change_at`; the **app-health dashboard** (`app_health.html`) surfaces these loudly. It refuses to overwrite on an empty API response (upstream schema guard) and treats a missing file as a cold-start baseline (no spurious "added"). Silver Line (SL*) routes are tagged `silver_line: true` since the app already renders them as rapid transit. The file also carries a `map` block cross-checking routes actually drawn on `transit-layer.json` (line entries with `line` `"Bus"`/`"Silver"`, keyed by the entry's `name` = route short_name) — `missing_from_map` / `drawn_not_frequent` only populate once ≥1 bus route is drawn.
- **Bus routes on the map (not yet drawn / rendered).** The editor already offers `Bus` (yellow) and `Silver` in its palette, so bus lines can be drawn today. But before buses route/animate correctly, `js/app.js` needs:
  - **Routing identity ≠ color.** The graph edges and Dijkstra key transfers off `ln.line` (the color field), so *every* `line: "Bus"` route reads as one line — a transfer between two different bus routes would incur no penalty and no color/label change. Thread a separate route-identity field (e.g. the line entry `name`) through `buildGraph`/`route` for transfer detection, while color still comes from `ln.line`.
  - **Per-mode speed.** Animation uses one global `SPEED = 27` cells/sec. Buses are slower — apply a per-segment factor (~0.3–0.5×) when the segment's mode is Bus.
  - **Higher bus transfer penalty.** `TRANSFER_PENALTY = 6` assumes 5–10-min rail headways; two 15-min buses is a much bigger real wait, so a bus-involving transfer should cost more (keep it as fake cell-distance, never convert to minutes).
  - **Thinner bus strokes + selective display.** Lines are drawn at runtime over the base image (`draw()` in the MetroMap module, fixed `4/view.scale` width) — so bus routes can be drawn thinner and shown selectively (e.g. only routes serving the current square, only frequent ones, or both) by filtering the `data.lines` loop. Nothing is baked into the terrain image.

## Pending product work

- **Weekly event verification:** Some recurring events (trivia nights, sessions) get cancelled week-to-week without the calendar being updated (e.g. Grainne O'Malley's was skipped). We need a mechanism for venues to confirm their recurring events are still on — e.g. a venue-facing view where they click a button to verify for the current day/week. Until this exists, treat weekly-only calendars cautiously (Grainne O'Malley's is on hold for this reason).

- **Movies / cinema listings:** Add Apple Cinemas, Coolidge Corner Theatre, and similar to the venue list. Movie showtimes should be hidden from the main event feed by default (since the app prioritizes live events) — likely a separate category or `event_type: "film"` filter that must be opted into. Design the opt-in UX before adding cinema venues.
  - **Somerville Theatre film calendars (not yet scraped):** `/calendar` has repertory/cult cinema in 35mm and 70mm alongside current wide releases (e.g. The Odyssey). `/schedule` is the daily showtimes view of the same content. Both are worth adding once the cinema UX is designed — the mixed blockbuster/repertory content means we'll need a way to filter or label wide releases vs. niche programming. `/events` (live music/theater) is already scraped separately.

## Deployment

GitHub Pages serves the repo root. Push to `main` → live within ~1 minute. The scraper runs automatically via GitHub Actions (`scrape.yml`) daily at 6am ET and commits updated `events.json` directly to `main`.

**Before pushing local scraper runs:** pull first (`git pull --rebase`) to avoid conflicts with the Action's commit. If `events.json` conflicts, use the scraper's `merge_events` function to reconcile both versions by event ID.
