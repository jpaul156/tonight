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


# ---- stable identity: artist ids + handle resolver ----

@pytest.fixture(scope="module")
def artists_json():
    with open(repo_path("data", "artists.json")) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def handles_json():
    with open(repo_path("data", "handles.json")) as f:
        return json.load(f)


def test_every_artist_has_unique_id(artists_json):
    """Each artist carries an immutable 'id' (the join key a /artist/{handle}
    URL resolves to). Ids must be present and unique — a collision would make a
    handle ambiguous."""
    ids = [a.get("id") for a in artists_json["artists"]]
    assert all(ids), "some artist entry is missing an 'id'"
    dupes = [i for i, n in __import__("collections").Counter(ids).items() if n > 1]
    assert not dupes, f"duplicate artist ids: {dupes}"


def test_handles_resolve_to_real_uids(handles_json, venues_json, artists_json):
    """Every handle must point at a uid that actually exists (a venue key or an
    artist id), or the vanity URL would 404."""
    artist_ids = {a["id"] for a in artists_json["artists"]}
    bad = []
    for handle, e in handles_json["handles"].items():
        if e["type"] == "venue" and e["uid"] not in venues_json:
            bad.append((handle, e["uid"], "venue"))
        if e["type"] == "artist" and e["uid"] not in artist_ids:
            bad.append((handle, e["uid"], "artist"))
    assert not bad, f"handles pointing at unknown uids: {bad}"


def test_handles_are_lowercase_and_not_reserved(handles_json):
    reserved = set(handles_json["reserved"])
    problems = [h for h in handles_json["handles"]
                if h != h.lower() or h in reserved]
    assert not problems, f"handles that are non-lowercase or reserved: {problems}"


def test_one_canonical_handle_per_uid(handles_json):
    """A uid may have retired (redirect) handles, but exactly one canonical."""
    from collections import Counter
    canon = Counter((e["type"], e["uid"]) for e in handles_json["handles"].values()
                    if e.get("canonical"))
    dupes = [k for k, n in canon.items() if n > 1]
    assert not dupes, f"more than one canonical handle for: {dupes}"
