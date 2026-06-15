# NOTES

Rationale for non-obvious decisions. If you change one of these, read the
note first — several encode a subtlety that has already caused a bug once.

## The "4am rollover" lives in two runtimes on purpose

"Tonight" runs until 4am, so a 1am show still belongs to the previous evening.
This rule is enforced in two places, and they are **not** duplicated by
accident — they run in different runtimes and do different jobs:

- **Front end — `getNow()` in `js/app.js`** is the single source of truth for
  "what is tonight." It must compute "now" in the user's browser at page-view
  time, because the site is static and served from a CDN: the scraper cannot
  precompute "tonight" for a page that gets opened at an arbitrary later hour.

- **Scraper — `cutoff_datetime()` in `scraper/run_scraper.py`** only decides
  what gets archived into `past_events` so the active list doesn't grow without
  bound. It does **not** decide what counts as tonight.

Because the front end re-filters every event anyway, the scraper boundary only
needs to be *safe* (never archive something the front end might still show),
not precise. It is deliberately loose — see `ARCHIVE_LOOKBACK` (36h).

### Bug this prevents

The cutoff used to be computed precisely from the *UTC calendar date*. A scrape
run at 00:24 UTC (= 20:24 the previous evening in Boston) read the date as
"tomorrow" and archived all of that night's events as past, so the front end —
still on the correct local date — showed nothing. Lesson: **never derive a
local-day boundary from a UTC date.** Convert to local time first, or, as we do
now, keep the scraper boundary loose enough that the mismatch can't matter.

## Transit badge color is presentation, not data

Events and `data/venues.json` store only `transit_line` (e.g. `"Red"`,
`"Green"`, `"Bus"`, `"Commuter Rail"`, `"Ferry"`). The hex color is derived
from that name at render time via `LINE_COLORS` in `js/app.js` — it is never
stored in the data.

Why: the line→color map is a tiny, stable, well-known set (the MBTA modes). If
the hex were stored per-event it could drift out of sync with the line name —
exactly the mistake made when Lamplighter CX was first added with the Red Line
color on a Green Line stop. Keying color off the line name makes a wrong color
for a known line impossible.

Adding a new mode = add one entry to `LINE_COLORS`. Current colors: Red, Orange,
Green, Blue, Silver, Bus (yellow), Commuter Rail (purple), Ferry (teal).

## Two source-of-truth files for venues, on purpose

- `scraper/venues.py` — scraping config (URLs, strategies, selectors, routing
  keywords). Drives the scraper only.
- `data/venues.json` — display config (walk times, phone, notes, logo). Read by
  the front end. The scraper never writes it.

Note the current limitation: venue-derived display fields (address, square,
transit, walk time) are still **denormalized onto every event** at scrape time,
so editing a venue attribute in `venues.json` does not retroactively update
existing events — they keep the old value until re-scraped. Planned fix: stamp
only `venue_id` on events and join to `venues.json` in the front end. Until
then, a venue edit needs a `--force` re-scrape to fully propagate.

## events.json output path

The scraper writes `data/events.json` (set by `OUTPUT_FILE` in
`run_scraper.py`) and is run from the repo root. There is no second copy — an
older root-level `events.json` was removed once the path was fixed.
