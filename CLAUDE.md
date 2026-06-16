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

## Deployment

GitHub Pages serves the repo root. Push to `main` → live within ~1 minute. The scraper runs automatically via GitHub Actions (`scrape.yml`) daily at 6am ET and commits updated `events.json` directly to `main`.

**Before pushing local scraper runs:** pull first (`git pull --rebase`) to avoid conflicts with the Action's commit. If `events.json` conflicts, use the scraper's `merge_events` function to reconcile both versions by event ID.
