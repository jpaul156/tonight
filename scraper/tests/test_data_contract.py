"""Contract tests over the committed data files and the partition logic.
These catch drift that unit tests can't: a venue present in one config but not
the other, an event missing a required field, or the archive cutoff misfiling
an event."""
import json
from datetime import datetime, timezone, timedelta

import pytest

from conftest import repo_path
from venues import VENUE_BY_ID
import run_scraper as rs

SHARED_FIELDS = ["square", "transit_line", "transit_stop", "walk_minutes",
                 "address", "name", "is_local"]


@pytest.fixture(scope="module")
def venues_json():
    with open(repo_path("data", "venues.json")) as f:
        return json.load(f)


# ---- venues.py <-> data/venues.json sync ----

def test_every_scraper_venue_has_display_config(venues_json):
    """Each scraper venue id (incl. sibling extra_venues) must have a display
    entry in data/venues.json, or its events render with no address/logo."""
    missing = [vid for vid in VENUE_BY_ID if vid not in venues_json]
    assert not missing, f"venues.json missing display config for: {missing}"


def test_shared_fields_match(venues_json):
    """The fields both files carry must agree (CLAUDE.md: the two configs are
    intentionally separate but shared fields must stay in sync)."""
    mismatches = []
    for vid, cfg in VENUE_BY_ID.items():
        disp = venues_json.get(vid, {})
        for f in SHARED_FIELDS:
            if f in cfg and f in disp and cfg[f] != disp[f]:
                mismatches.append(f"{vid}.{f}: venues.py={cfg[f]!r} venues.json={disp[f]!r}")
    assert not mismatches, "shared field drift:\n" + "\n".join(mismatches)


# ---- events.json shape ----

REQUIRED_EVENT_FIELDS = ["id", "title", "venue", "square", "category", "start"]


def test_events_json_shape():
    with open(repo_path("data", "events.json")) as f:
        data = json.load(f)
    assert set(data) >= {"generated_at", "events", "past_events"}
    from scraper_core import VALID_CATEGORIES
    for e in data["events"]:
        for field in REQUIRED_EVENT_FIELDS:
            assert e.get(field) not in (None, ""), f"{e.get('id')} missing {field}"
        assert e["category"] in VALID_CATEGORIES, f"{e['id']} bad category {e['category']}"
        # start must parse
        datetime.fromisoformat(e["start"])


# ---- partition tiering ----

def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def test_partition_tiers():
    now = datetime.now(timezone.utc)
    events = [
        {"id": "future", "start": _iso(now + timedelta(days=3))},
        {"id": "tonight", "start": _iso(now - timedelta(hours=2))},
        {"id": "recent", "start": _iso(now - timedelta(days=3))},   # 36h..7d
        {"id": "old", "start": _iso(now - timedelta(days=30))},
        {"id": "no_time"},
    ]
    active, recent, archived = rs.partition_events(events)
    ids = lambda lst: {e["id"] for e in lst}
    assert ids(active) == {"future", "tonight", "no_time"}
    assert ids(recent) == {"recent"}
    assert ids(archived) == {"old"}


def test_partition_prefers_end_over_start():
    now = datetime.now(timezone.utc)
    # Started long ago but ends in the future (multi-day) -> stays active.
    e = {"id": "festival", "start": _iso(now - timedelta(days=30)),
         "end": _iso(now + timedelta(days=1))}
    active, recent, archived = rs.partition_events([e])
    assert {x["id"] for x in active} == {"festival"}
