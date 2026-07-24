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

## Feed ranking — geography is a score, then a below-0 filter

`render()` in `js/app.js` applies hard filters (tonight, `!private`, category) and then orders everything with `TonightRanking.rank` (`js/ranking.js`, shared with the future `ranking.html` tuner — keep it free of app globals). Weights are a hand-maintained overlay in `data/ranking.json` (schema `tonight.ranking/1`), merged over the module's `DEFAULT_WEIGHTS`. **When a place is actively selected** (`activeSquare !== "all"`), geography also *filters*: `render()` drops events whose **total** score is below 0 (too far AND neighborhood-unrelated, with no favorite/sponsor/lit boost to rescue them). On "Near me" (no explicit selection, geography seeded from Home Square) nothing is hidden. `rank` itself stays a pure scorer — the cutoff lives in `render()` so the tuner still sees every score.

**Two-level geography — station vs neighborhood.** The station is the transit-layer node `name` (= an event's `transit_stop`); a node's `square` is the neighborhood(s) it sits in (= an event's `square`). `square` is **a string OR a list** — a station↔neighborhood many-to-many (North Station ∈ West End + North End; Seaport ∋ Courthouse/WTC/Silver Line Way). `buildIndex` normalizes string→list (`squaresOf`), so no data migration is needed and the editor rewrites it on next export (same back-compat as `minor`→`tier`). `areaOf` (station→**[neighborhoods]**) and `areaStations` (neighborhood→[stations]) are derived, never hand-maintained. Selecting a **neighborhood** seeds every member station at distance 0; selecting a **station** seeds just that stop. Events never carry neighborhood data — a venue is 1-1 with a station, so neighborhoods live only on map nodes.

**Proximity = max(hop score, neighborhood score).** Two parallel distances, best wins.
- **Hop score** — a multi-source Dijkstra over (node, line) counts 1 per station entered, 0 for waypoints, plus `transferStops` extra per line change. `clamp(selected − perStop·hops, proximityFloor..selected)` — defaults +10 at the selection, +5 adjacent, 0 two away, −5 three away, floored at −10.
- **Neighborhood score** — a BFS over the station↔neighborhood graph from the selection (`neighborhoodDepths`): depth 0 = the selected stop, depth 1 = shares a neighborhood with it, depth 2 = shares one with a depth-1 stop. `neighborhoodBonus[depth]` (default `[10, 5, 2]`, depth ≥ length → no bonus). This is what lets a station that's far *by rail* but linked *by neighborhood* (Boylston ↔ Chinatown via Theater District) rank as near — and it's non-linear, so it can't fold into `perStop`.

Events whose stop/square isn't on the map (Inman, Medford) score `offMap` (**default −10** = the floor, so they drop out of a filtered feed until the bus network reaches them or a bonus lifts them). An exact string match with the selection always earns the full `selected` bonus (also how off-map selections work). Same Bus caveat as the trip router: `line` is the color field, so all future Bus routes read as one line for transfers.

**Other factors:** `sponsored` (deliberately defaulted *below* `selected` so a paid post can't outrank the square the user chose), `favoriteEvent`/`favoriteVenue`, `favoriteArtist` (defaulted **+10 to exactly cancel `proximityFloor` −10**, so a favorite artist playing far away still clears the below-0 cutoff), `litMax` (scaled by a 0..1 hook), and `jitter` — a daily-seeded (`daySeed` + event id) hash so the order is stable all night, fresh tomorrow, and never alphabetical. Venue/artist favorites and Lit are wired through `hooks` but return 0 until profile data exists. On "Near me" the saved Home Square (raw value — profile-less users get no geography) anchors the same scoring. Ties break by start time.

**Map lighting follows areas:** `placeHasEvents(name)` in `js/app.js` (which feeds the metro overlay's `isFilterable`) is true when the station itself OR **any of its neighborhoods** (`areaOf` is now a list) has public events tonight — `eventPlaces` collects both `square` and `transit_stop` values, so an event at Courthouse lights all three Seaport stops. Tapping a station selects the station (siblings deprioritized one hop); area selection currently comes from events' `square` values and, later, neighborhood sprites.

## Stable identity & vanity URLs — uid vs handle

Two-layer identity so a public URL can change without churning the data that points at it. The **uid** is the immutable internal join key; the **handle** is the mutable public slug in `tonight.quest/{handle}`.

- **Venue uid** = its key in `data/venues.json` (e.g. `lamplighter-broadway`). Frozen — it's embedded in every event id (`make_event_id`), so it must never change or be reused.
- **Artist uid** = the `id` field in `data/artists.json` (a frozen name-slug). Every artist carries one; renaming the act changes `name`, never `id`. The fuzzy matcher is unchanged — it just now resolves to a record with a canonical id.
- **`data/handles.json`** (schema `tonight.handles/1`) — the vanity resolver: `handle → { type: venue|artist, uid, canonical }`, plus a `reserved` list of app routes/pages that can't be claimed. **Hand-assigned for now** (no self-serve claiming; that comes later via Firebase as a write overlay). To rename a handle, add the new one as canonical and keep the old with `canonical:false` so links redirect instead of 404 — never repoint or delete a uid. **Square names are not reserved**: squares resolve under their own `/sq/{name}` namespace, so they can't collide with venue/artist handles. Contract tests in `scraper/tests/test_data_contract.py` enforce unique artist ids, handles resolving to real uids, lowercase/non-reserved handles, and one canonical per uid. The front-end resolver (parsing `/{handle}` and `/sq/{name}`) is not built yet.

**Event id is a separate identity axis — derivation, not a handle.** An event id *is* its shareable identity (`location.hash = e.id`, the share URL, and the `.ics` `UID`), so it must derive from stable identity, never the volatile title — but events are auto-minted in bulk, so they get derivation-stability rather than a hand-assigned handle. `make_event_id` precedence: (1) a genuine per-event permalink (`source_url`), hashed; (2) otherwise `venue_id + start` — **title-free**, so a rename no longer mints a new id (splitting rooms into distinct venue_ids like Middle East / Burren gives one event per `(venue_id, start)`); (3) the title only as a last-resort tiebreaker, and `build_events` appends it **only** to the `(venue_id, start)` slots that genuinely collide (e.g. Aeronaut parallel programming). Degrades to the title slug only when `start` is missing. This is paired with venue-authoritative reconciliation (a clean scrape drops future events a venue no longer lists) so the id change self-heals: on each venue's next clean scrape the old title-slug ids are re-minted and the stale ghosts reconciled away — no forced full rescrape needed.

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
- **`transit-layer.json` schema:** nodes are `{c, r, station, name, square?, tier?}`. `square` is the node's neighborhood(s) — **a string or a list of strings** (a station can sit in several, e.g. North Station in West End + North End); readers normalize via `squaresOf`/`isinstance(list)`, and the editor's Neighborhood field takes comma-separated values. Interchanges are detected automatically by shared `(c,r)` coordinates across branches/lines — no explicit interchange field.
- **Station tier (prominence):** `station` stays a boolean (is this a boardable stop). `tier` (1–5) is an orthogonal prominence axis on top of it: **5 = major square** (Harvard/Davis-class), **3 = minor stop** (SL terminal/Washington St, residential Green Line surface stops), **1 = low-priority bus stop**; 2 and 4 are reserved for later. **`tier` absent = 5 (major)**, so nothing needs migration. Legacy files carry the old `minor: true` boolean instead of `tier`; `stationTier()` in `js/app.js` reads it back-compat (`minor`→3, plain→5), and the editor rewrites `minor` to `tier` on its next export. The cutoff is `MAJOR_TIER = 4`: tier ≥ 4 draws a full ring, is labelled, is tappable, and is offered in the Home Square picker; tier < 4 draws a smaller/thinner ring and (rarely having events) falls out of `isFilterable` → automatically unlabeled and non-tappable unless something happens there. The **effective tier of a shared node is the max across its copies** (`nd.tier = Math.max(...)` in `buildGraph`), so a station that's major on one branch and minor on another renders major regardless of node order; the interchange diamond always wins over both. Never make `station` a string enum — it's read as a truthy boolean in ~10 places across the editor and app; tier is the separate number. In the editor, **number keys `0`–`5` set a node's tier** (`0` = waypoint, `1`–`5` = station tier), both for the placement mode and the selected node; export omits `tier` only for the default 5 (keeps major-station diffs empty).
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

- **Suggestion points + swag:** venue suggestions (`/venue_suggestions`) are **verified-account-only** so credit sticks to a durable uid — the plan is points for suggestions that become venues, redeemable for merch (200 glow-in-the-dark Tonight wristbands on hand from the ~2016 attempt at this app; t-shirts TBD). Award on approve in the app-health review flow; needs a points ledger on `users/{uid}` and a tally in the account panel.

- **"Third place" category (name TBD):** For cafes, plazas, and hidden nooks people go to sit/chill/read/study/work — not live events. Like film listings, these should not show up on the main events page by default; needs an opt-in filter similar to the planned cinema `event_type`. Pepita Lo-Fi at Lamplighter belongs here but stays on the main list for now — reclassify when this is addressed.

- **Weekly event verification:** Some recurring events (trivia nights, sessions) get cancelled week-to-week without the calendar being updated (e.g. Grainne O'Malley's was skipped). We need a mechanism for venues to confirm their recurring events are still on — e.g. a venue-facing view where they click a button to verify for the current day/week. Until this exists, treat weekly-only calendars cautiously (Grainne O'Malley's is on hold for this reason).

- **Movies / cinema listings:** Add Apple Cinemas, Coolidge Corner Theatre, and similar to the venue list. Movie showtimes should be hidden from the main event feed by default (since the app prioritizes live events) — likely a separate category or `event_type: "film"` filter that must be opted into. Design the opt-in UX before adding cinema venues.
  - **Somerville Theatre film calendars (not yet scraped):** `/calendar` has repertory/cult cinema in 35mm and 70mm alongside current wide releases (e.g. The Odyssey). `/schedule` is the daily showtimes view of the same content. Both are worth adding once the cinema UX is designed — the mixed blockbuster/repertory content means we'll need a way to filter or label wide releases vs. niche programming. `/events` (live music/theater) is already scraped separately.

## Deployment

GitHub Pages serves the repo root. Push to `main` → live within ~1 minute. The scraper runs automatically via GitHub Actions (`scrape.yml`) daily at 6am ET and commits updated `events.json` directly to `main`.

**Before pushing local scraper runs:** pull first (`git pull --rebase`) to avoid conflicts with the Action's commit. If `events.json` conflicts, use the scraper's `merge_events` function to reconcile both versions by event ID.
