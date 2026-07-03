#!/usr/bin/env python3
# run_scraper.py
# Scrapes all venues in venues.py and writes a combined events.json.
# Usage:
#   python3 run_scraper.py                 # scrape all venues
#   python3 run_scraper.py lamplighter     # scrape one venue by ID fragment
#   python3 run_scraper.py burren passim   # scrape specific venues

import json
import sys
import os
import time
from datetime import datetime, timezone, timedelta

from venues import VENUES
from scraper_core import (
    scrape_venue, load_cache, save_cache, get_all_venue_ids,
    LLM_STRATEGIES,
)

OUTPUT_FILE = "data/events.json"
ARCHIVE_FILE = "data/archive.json"
HEALTH_FILE = "data/scrape_health.json"
TEST_STATUS_FILE = "data/test_status.json"
TRANSIT_FILE = "transit-layer.json"
CACHE_FILE = "scraper_cache.json"


def load_existing_events(path):
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        existing = json.load(f)
    if isinstance(existing, list):
        return {e["id"]: e for e in existing}
    # Load both active and past events into the merge map
    all_events = existing.get("events", []) + existing.get("past_events", [])
    return {e["id"]: e for e in all_events}


def merge_events(existing_map, new_events):
    """New/updated events overwrite by ID; untouched venues are preserved."""
    merged = dict(existing_map)
    for e in new_events:
        merged[e["id"]] = e
    return list(merged.values())


def collapse_permalink_dupes(events, shared_urls):
    """Collapse events that are provably the same underlying listing: identical
    venue_id + real per-event source_url (not a shared calendar page) + identical
    start. Keeps the most-recently-scraped copy.

    Two jobs: (1) absorb the one-time id-scheme migration, where a permalink
    venue's event carries an old title-slug id in events.json and a new
    permalink-based id from this run — same URL + same start proves they're the
    same show, so the fresh copy wins and the stale ghost (with its stale price)
    is dropped instead of shipping both. (2) A permanent safety net so a stray
    title-id copy can never coexist with the permalink id for one event.

    Keyed on start as well as URL so a recurring series that reuses one URL
    across dates is never merged across days. Events without a usable permalink
    (blank URL, or the venue's shared collection page) pass through untouched —
    this never collapses the Burren's 157-events-one-URL case."""
    from collections import defaultdict
    groups = defaultdict(list)
    out = []
    for e in events:
        u = (e.get("source_url") or "").strip()
        vid = e.get("venue_id")
        if u and vid and u not in shared_urls:
            groups[(vid, u, e.get("start"))].append(e)
        else:
            out.append(e)
    for evs in groups.values():
        out.append(evs[0] if len(evs) == 1
                   else max(evs, key=lambda e: e.get("last_scraped") or ""))
    return out


def _title_tokens(t):
    """Significant word set of a title, for judging whether two titles are
    re-phrasings of one event vs genuinely different acts."""
    import re
    return {w for w in re.sub(r"[^a-z0-9 ]", " ", (t or "").lower()).split() if w}


def _looks_like_retitling(titles):
    """True when a set of same-slot titles look like variants of ONE event rather
    than distinct acts sharing a room. The rename fingerprint: some pair has one
    title's words contained in the other's ("52 Church" ⊆ "52 Church - The
    Glitter Boys"), or a heavy token overlap. A real multi-act bill (Grain Thief
    / Spring Hill Stringband) shares almost no words and stays unflagged — so the
    Burren's front/back-room and Aeronaut's parallel programming don't false-fire."""
    toks = [_title_tokens(t) for t in titles]
    for i in range(len(toks)):
        for j in range(i + 1, len(toks)):
            a, b = toks[i], toks[j]
            if not a or not b:
                continue
            if a <= b or b <= a:
                return True
            if len(a & b) / min(len(a), len(b)) >= 0.6:
                return True
    return False


def build_collisions(active_events):
    """Duplicate events left behind when a title (hence its id) changed but the
    old copy was never superseded — surfaced loudly for the dashboard.

    Gated on BOTH same slot AND title similarity, because a shared venue_id is
    not proof of a duplicate: rooms with their own venue_id (mideast-upstairs vs
    mideast-downstairs) never collide, but some single-venue_id venues genuinely
    run parallel programming (the Burren's two rooms, Aeronaut's taproom). So we
    only flag same-slot events whose titles look like re-phrasings of each other.

      exact   — same venue_id + identical start + variant titles. A rename ghost;
                the copies often disagree on price/title, so one shows stale info.
      overlap — same venue_id + overlapping (not identical) times + variant
                titles. A rename that also nudged the start time. Softer.

    Private events are excluded — the app hides them, and a private booking can
    legitimately share a slot with the public listing it replaced."""
    from collections import defaultdict

    def parse(t):
        try:
            return datetime.fromisoformat(t) if t else None
        except ValueError:
            return None

    byv = defaultdict(list)
    for e in active_events:
        if e.get("private"):
            continue
        vid, start = e.get("venue_id"), e.get("start")
        if vid and start:
            byv[vid].append(e)

    def distinct_by_permalink(group):
        # Two same-slot events are provably different (not a rename ghost) when
        # each carries its own distinct, non-empty per-event source_url — a real
        # permalink venue can't hand the same show two URLs. If any member shares
        # a URL or lacks one, fall back to the title heuristic.
        urls = [(e.get("source_url") or "").strip() for e in group]
        return all(urls) and len(set(urls)) == len(group)

    exact, overlap = [], []
    for vid, evs in byv.items():
        by_start = defaultdict(list)
        for e in evs:
            by_start[e["start"]].append(e)
        for group in by_start.values():
            if len(group) > 1 and not distinct_by_permalink(group) \
                    and _looks_like_retitling([e.get("title") for e in group]):
                exact.append({
                    "venue_id": vid,
                    "venue": group[0].get("venue"),
                    "start": group[0].get("start"),
                    "count": len(group),
                    "events": [{"id": e.get("id"), "title": e.get("title"),
                                "cost": e.get("cost")} for e in group],
                })

        # Overlapping (but not identical) starts — only flagged when the titles
        # also look like a re-titling, so parallel programming stays quiet.
        timed = sorted((e for e in evs if parse(e.get("start"))),
                       key=lambda e: e["start"])
        for a, b in zip(timed, timed[1:]):
            if a["start"] == b["start"]:
                continue
            a_end = parse(a.get("end")) or parse(a.get("start"))
            b_start = parse(b.get("start"))
            if a_end and b_start and b_start < a_end \
                    and not distinct_by_permalink([a, b]) \
                    and _looks_like_retitling([a.get("title"), b.get("title")]):
                overlap.append({
                    "venue_id": vid,
                    "venue": a.get("venue"),
                    "a": {"id": a.get("id"), "title": a.get("title"),
                          "start": a.get("start"), "end": a.get("end")},
                    "b": {"id": b.get("id"), "title": b.get("title"),
                          "start": b.get("start"), "end": b.get("end")},
                })

    exact.sort(key=lambda c: (-c["count"], c["venue_id"] or ""))
    overlap.sort(key=lambda c: c["venue_id"] or "")
    return {"exact": exact, "overlap": overlap}


# How far back the "just ended" active window reaches. Deliberately loose: the
# scraper never decides what counts as "tonight" — the front end re-filters
# every event against its own 4am-rollover clock (getNow in js/app.js). 36h
# comfortably covers the worst case (an event from yesterday evening, viewed at
# 3:59am before the 4am rollover) so nothing the front end might still show is
# ever pushed out of the active list.
ARCHIVE_LOOKBACK = timedelta(hours=36)

# How long a *past* event stays in events.json before moving to archive.json.
# The front end ignores past_events entirely, so this window exists only to (a)
# give the scraper a rolling record for "was live yesterday, gone today"
# detection and (b) keep the shipped events.json bounded. Anything older than
# this is appended to archive.json (which the app never fetches) and dropped
# from events.json. See the dashboard/archive notes in CLAUDE.md.
ARCHIVE_RETENTION = timedelta(days=7)


def _event_time(e):
    """The event's end (or start, if no end) as an aware UTC datetime, or None
    if neither parses. Naive strings are treated as UTC, matching the stored
    floating-local convention used everywhere else here."""
    time_str = e.get("end") or e.get("start")
    if not time_str:
        return None
    try:
        t = datetime.fromisoformat(time_str)
    except ValueError:
        return None
    return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t


def partition_events(events):
    """Split every event into three tiers by age:
      active      — end/start >= now-36h (tonight + future + just-ended)
      recent_past — between 36h and 7 days old (kept in events.json)
      archived    — older than 7 days (moved to archive.json, app never fetches)
    Events with no parseable time are kept active (never archived blindly).
    """
    now = datetime.now(timezone.utc)
    active_cut = now - ARCHIVE_LOOKBACK
    archive_cut = now - ARCHIVE_RETENTION
    active, recent_past, archived = [], [], []
    for e in events:
        t = _event_time(e)
        if t is None:
            active.append(e)
        elif t >= active_cut:
            active.append(e)
        elif t >= archive_cut:
            recent_past.append(e)
        else:
            archived.append(e)
    return active, recent_past, archived


def load_archive(path):
    """Existing archive.json as an {id: event} map (bare list on disk)."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    items = data if isinstance(data, list) else data.get("events", [])
    return {e["id"]: e for e in items}


def sort_events(events):
    return sorted(events, key=lambda e: e.get("start") or "9999")


def load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


# ============================================================
# Health report — feeds app_health.html via data/scrape_health.json
# ============================================================

def map_station_names(path):
    """Every named station in transit-layer.json — the set of squares the app's
    metro map can actually surface as a filter. Events whose `square` isn't in
    here can't be reached from the map (see off_map_squares)."""
    data = load_json(path, None)
    if not data:
        return set()
    names = set()
    for ln in data.get("lines", []):
        for br in ln.get("branches", []):
            for n in br.get("nodes", []):
                if n.get("name"):
                    names.add(n["name"])
                if n.get("square"):
                    names.add(n["square"])
    return names


def build_off_map_squares(active_events, station_names):
    """Squares used by active events that have no matching map station. Flags a
    probable typo when an off-map square contains an on-map station name (the
    'Davis Square' vs 'Davis' class of bug), and marks bus-only squares (all
    events on the Bus line) as expected rather than broken."""
    from collections import defaultdict
    buckets = defaultdict(list)
    for e in active_events:
        sq = e.get("square")
        if sq and sq not in station_names:
            buckets[sq].append(e)
    out = []
    for sq, evs in sorted(buckets.items(), key=lambda kv: -len(kv[1])):
        bus_only = all((e.get("transit_line") == "Bus") for e in evs)
        probable = None
        for name in station_names:
            # e.g. off-map "Davis Square" contains on-map "Davis"
            if name and name != sq and name in sq:
                probable = name
                break
        out.append({
            "square": sq,
            "events": len(evs),
            "bus_only": bus_only,
            "probable_match": probable,
        })
    return out


def build_health(venue_reports, active_events, archived_now_count,
                 duration_s, test_status, station_names, payload):
    from collections import Counter
    by_square = Counter(e.get("square") for e in active_events if e.get("square"))
    no_image = sum(1 for e in active_events if not e.get("image_url"))
    total = len(active_events)

    status_counts = Counter(v["status"] for v in venue_reports)
    return {
        "schema": "tonight.health/1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": round(duration_s, 1),
        "totals": {
            "active_events": total,
            # What a visitor actually downloads on open: events.json is the one
            # payload that grows with the catalog. gzip is what's transferred
            # (GitHub Pages compresses), raw is the parse cost on-device.
            "payload_bytes": payload["raw"],
            "payload_gzip_bytes": payload["gzip"],
            "archived_this_run": archived_now_count,
            "venues_total": len(venue_reports),
            "venues_ok": status_counts.get("ok", 0),
            "venues_idle": status_counts.get("idle", 0),
            "venues_warning": status_counts.get("warning", 0),
            "venues_error": status_counts.get("error", 0),
            "no_image": no_image,
            "no_image_pct": round(100 * no_image / total, 1) if total else 0,
        },
        "by_square": dict(sorted(by_square.items(), key=lambda kv: -kv[1])),
        "off_map_squares": build_off_map_squares(active_events, station_names),
        "collisions": build_collisions(active_events),
        "tests": test_status,
        "venues": venue_reports,
    }


# Rank for sorting the dashboard venue list: loudest first.
STATUS_RANK = {"error": 0, "warning": 1, "idle": 2, "ok": 3}


def venue_status(cfg, outcome, feed_count, prev_feed_count):
    """Derive a venue's health status + note. `outcome` carries this run's
    result: {events, report, errored}. `feed_count` is how many of this venue's
    events are currently in the live feed; `prev_feed_count` is that number at
    the previous run (for the delta and breakage detection).

    The breakage signal keys off this run's *yield*, not the feed count, because
    a venue can break while its already-scraped future events keep the feed
    count non-zero for weeks.
    """
    events = outcome["events"]
    report = outcome["report"]
    expected_empty = cfg.get("expected_empty", False)
    errored = outcome["errored"] or bool(report.get("error"))
    empty = events is not None and len(events) == 0

    # A known-broken venue (stale calendar, or a JS-only page awaiting
    # Playwright) reads as calm "idle" whether its empty page makes the LLM
    # return [] or unparseable junk — we already know it yields nothing, so it
    # must never show up as a loud error alongside genuine breakage.
    if expected_empty and (errored or empty or events is None):
        return "idle", "0 events (known — awaiting fix, see venues.py)"

    if errored:
        return "error", report.get("error") or "scrape raised an exception"

    if events is None:  # cache hit — collection page unchanged, LLM skipped
        return "ok", "unchanged since last run (cache hit)"

    if empty:
        if prev_feed_count > 0:
            return "error", f"yielded 0 events (feed had {prev_feed_count}) — likely broken"
        return "warning", "yields 0 events and never has — check config"

    if report.get("truncated"):
        return "warning", report.get("note", "truncated extraction")

    return "ok", ""


def print_summary(events, venue_names):
    relevant = [
        e for e in events
        if any(n in (e.get("venue") or "") for n in venue_names)
    ]
    print(f"\n{'='*60}")
    print(f"SUMMARY — {len(relevant)} events from this run")
    print(f"{'='*60}")
    for e in relevant:
        has_img  = "img " if e.get("image_url") else "    "
        has_desc = "desc" if e.get("description") else "    "
        cost  = (e.get("cost") or "?")[:18]
        cat   = (e.get("category") or "?")[:10]
        name  = (e.get("venue") or "?").split()[-1]
        title = (e.get("title") or "?")[:35]
        start = (e.get("start") or "??")[:16]
        print(f"  {start} [{cat:<10}] [{has_img}][{has_desc}] {cost:<20} {title} [{name}]")


def main():
    run_start = time.time()
    filters = [a.lower() for a in sys.argv[1:] if not a.startswith("--")]
    force = "--force" in sys.argv
    if filters:
        venues_to_run = [
            v for v in VENUES
            if any(f in v["id"].lower() or f in v["name"].lower() for f in filters)
        ]
        if not venues_to_run:
            print(f"No venues matched: {filters}")
            print(f"Available: {[v['id'] for v in VENUES]}")
            sys.exit(1)
    else:
        venues_to_run = VENUES

    print(f"Running scraper for {len(venues_to_run)} venue(s):{' (FORCED — ignoring cache)' if force else ''}")
    for v in venues_to_run:
        print(f"  - {v['name']}")

    # Load cache, existing events, and the previous health report (for deltas).
    cache = load_cache(CACHE_FILE)
    existing_map = load_existing_events(OUTPUT_FILE)
    prev_health = load_json(HEALTH_FILE, {})
    prev = {v["id"]: v for v in prev_health.get("venues", [])}
    print(f"\nCache: {len(cache)} URLs tracked")
    print(f"Events: {len(existing_map)} existing")

    all_new_events = []
    scraped_venue_names = []
    skipped_venues = []
    errors = []
    outcomes = {}  # venue_id -> {events, report, errored}

    for venue_cfg in venues_to_run:
        report = {}
        events = None
        errored = False
        try:
            events = scrape_venue(venue_cfg, cache=cache, verbose=True,
                                  force=force, report=report)
            if events is None:
                skipped_venues.append(venue_cfg["name"])
            else:
                all_new_events.extend(events)
                scraped_venue_names.append(venue_cfg["name"])
        except Exception as err:
            print(f"\n  ERROR scraping {venue_cfg['name']}: {err}")
            errors.append((venue_cfg["name"], str(err)))
            report["error"] = str(err)
            errored = True
        finally:
            save_cache(cache, CACHE_FILE)
        outcomes[venue_cfg["id"]] = {"events": events, "report": report, "errored": errored}

    # --- Partition into active / recent-past / archived ---
    merged = merge_events(existing_map, all_new_events)
    # Drop provable duplicates (permalink venues: old title-id copy vs new
    # permalink-id copy for the same show). Shared calendar pages are excluded so
    # single-URL venues (the Burren) are never collapsed.
    shared_source_urls = {v["collection_url"] for v in VENUES}
    merged = collapse_permalink_dupes(merged, shared_source_urls)
    active, recent_past, archived_now = partition_events(merged)
    active_sorted = sort_events(active)
    past_sorted = sort_events(recent_past)

    # --- Per-venue health (built after partitioning so event_count reflects the
    # venue's real contribution to the live feed) ---
    from collections import Counter
    feed_counts = Counter(e.get("venue_id") for e in active_sorted)
    venue_reports = []
    now_iso = datetime.now(timezone.utc).isoformat()
    for venue_cfg in venues_to_run:
        outcome = outcomes[venue_cfg["id"]]
        feed_count = sum(feed_counts.get(vid, 0) for vid in get_all_venue_ids(venue_cfg))
        pv = prev.get(venue_cfg["id"], {})
        prev_feed = pv.get("event_count", feed_count)
        status, note = venue_status(venue_cfg, outcome, feed_count, prev_feed)
        strategy = venue_cfg.get("scrape_strategy", "html_page")
        got_fresh = outcome["events"] is not None and len(outcome["events"]) > 0
        venue_reports.append({
            "id": venue_cfg["id"],
            "name": venue_cfg["name"],
            "square": venue_cfg["square"],
            "strategy": strategy,
            "uses_llm": strategy in LLM_STRATEGIES or bool(venue_cfg.get("detail_pages")),
            "status": status,
            "event_count": feed_count,
            "delta": feed_count - prev_feed,
            "note": note,
            "last_success": now_iso if got_fresh else pv.get("last_success"),
        })

    # Include venues that weren't in this run (partial run) so the dashboard
    # still shows their last-known state rather than dropping them.
    run_ids = {v["id"] for v in venues_to_run}
    for pv in prev_health.get("venues", []):
        if pv["id"] not in run_ids:
            venue_reports.append({**pv, "note": "not scraped this run (last-known state)"})

    # Sort loudest-first for the dashboard.
    venue_reports.sort(key=lambda v: (STATUS_RANK.get(v["status"], 9), -v["event_count"]))

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "events": active_sorted,
        "past_events": past_sorted,
    }
    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2)

    # Measure what the front end downloads on open (raw + gzipped transfer size).
    import gzip
    raw_bytes = open(OUTPUT_FILE, "rb").read()
    payload = {"raw": len(raw_bytes), "gzip": len(gzip.compress(raw_bytes))}

    # --- Merge newly-archived events into the growing archive.json ---
    archive_map = load_archive(ARCHIVE_FILE)
    before = len(archive_map)
    for e in archived_now:
        archive_map[e["id"]] = e
    archived_added = len(archive_map) - before
    archive_out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "events": sort_events(list(archive_map.values())),
    }
    with open(ARCHIVE_FILE, "w") as f:
        json.dump(archive_out, f, indent=2)

    # --- Write the health report for the dashboard ---
    station_names = map_station_names(TRANSIT_FILE)
    test_status = load_json(TEST_STATUS_FILE, {"status": "unknown"})
    health = build_health(venue_reports, active_sorted, len(archived_now),
                          time.time() - run_start, test_status, station_names, payload)
    with open(HEALTH_FILE, "w") as f:
        json.dump(health, f, indent=2)

    if scraped_venue_names:
        print_summary(active_sorted, scraped_venue_names)

    print(f"\nWrote {len(active_sorted)} active + {len(past_sorted)} recent-past events to {OUTPUT_FILE}")
    print(f"Archive: {len(archive_map)} total ({archived_added} moved this run) in {ARCHIVE_FILE}")
    print(f"Health: {HEALTH_FILE} "
          f"({health['totals']['venues_error']} error, "
          f"{health['totals']['venues_warning']} warning, "
          f"{health['totals']['venues_ok']} ok)")
    if all_new_events:
        print(f"  {len(all_new_events)} new/updated events from this run")
    if skipped_venues:
        print(f"  Skipped (no change): {', '.join(skipped_venues)}")

    unchanged = sum(1 for v in cache.values() if v.get("last_changed") != v.get("last_fetched"))
    print(f"\nCache: {len(cache)} URLs tracked, {unchanged} unchanged on this run")

    if errors:
        print(f"\nErrors ({len(errors)}):")
        for name, err in errors:
            print(f"  {name}: {err}")
        sys.exit(1)


if __name__ == "__main__":
    main()
