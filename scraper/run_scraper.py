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
from datetime import datetime, timezone, timedelta

from venues import VENUES
from scraper_core import scrape_venue, load_cache, save_cache

OUTPUT_FILE = "data/events.json"
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


def cutoff_datetime():
    """
    'Tonight' rolls over at 4am — events ending before 4am today
    are considered past. Events with no end time use start time.
    Past events are preserved under 'past_events' key, never deleted.
    """
    now = datetime.now(timezone.utc)
    # 4am EDT = 8am UTC (Boston timezone approximation)
    cutoff = now.replace(hour=8, minute=0, second=0, microsecond=0)
    local_hour = (now.hour - 4) % 24
    if local_hour < 4:
        cutoff -= timedelta(days=1)
    return cutoff


def sort_events(events):
    return sorted(events, key=lambda e: e.get("start") or "9999")


def split_past_future(events):
    """Split events into active (tonight + future) and past."""
    cutoff = cutoff_datetime()
    active, past = [], []
    for e in events:
        # Use end time if available, otherwise start time
        time_str = e.get("end") or e.get("start")
        if not time_str:
            active.append(e)
            continue
        try:
            # Parse naive datetime as UTC for comparison
            t = datetime.fromisoformat(time_str)
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            if t < cutoff:
                past.append(e)
            else:
                active.append(e)
        except ValueError:
            active.append(e)
    return active, past


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

    # Load cache and existing events
    cache = load_cache(CACHE_FILE)
    existing_map = load_existing_events(OUTPUT_FILE)
    print(f"\nCache: {len(cache)} URLs tracked")
    print(f"Events: {len(existing_map)} existing")

    all_new_events = []
    scraped_venue_names = []
    skipped_venues = []
    errors = []

    for venue_cfg in venues_to_run:
        try:
            events = scrape_venue(venue_cfg, cache=cache, verbose=True, force=force)
            if events is None:
                # None = cache hit, collection page unchanged
                skipped_venues.append(venue_cfg["name"])
            else:
                all_new_events.extend(events)
                scraped_venue_names.append(venue_cfg["name"])
        except Exception as err:
            print(f"\n  ERROR scraping {venue_cfg['name']}: {err}")
            errors.append((venue_cfg["name"], str(err)))
        finally:
            # Always save cache after each venue so progress isn't lost
            save_cache(cache, CACHE_FILE)

    # Merge and write output
    merged = merge_events(existing_map, all_new_events)
    active, past = split_past_future(merged)
    active_sorted = sort_events(active)
    past_sorted = sort_events(past)

    # Wrap in a generated_at envelope so the front end can check freshness
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "events": active_sorted,
        "past_events": past_sorted,
    }

    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2)

    if scraped_venue_names:
        print_summary(active_sorted, scraped_venue_names)

    print(f"\nWrote {len(active_sorted)} active + {len(past_sorted)} past events to {OUTPUT_FILE}")
    if all_new_events:
        print(f"  {len(all_new_events)} new/updated events from this run")
    if skipped_venues:
        print(f"  Skipped (no change): {', '.join(skipped_venues)}")

    # Show cache stats
    unchanged = sum(1 for v in cache.values() if v.get("last_changed") != v.get("last_fetched"))
    print(f"\nCache: {len(cache)} URLs tracked, {unchanged} unchanged on this run")

    if errors:
        print(f"\nErrors ({len(errors)}):")
        for name, err in errors:
            print(f"  {name}: {err}")
        sys.exit(1)


if __name__ == "__main__":
    main()
