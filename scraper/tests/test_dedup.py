"""Duplicate handling for the rename/cancel failure mode (see CLAUDE.md):

- collapse_permalink_dupes — collapses the one-time id-scheme migration and any
  stray title-id copy for a permalink venue, WITHOUT ever merging a shared
  calendar-page venue (the Burren) or a recurring series across dates.
- build_collisions — the dashboard alarm: same room (venue_id) + same start is a
  rename ghost; overlapping-but-offset sets are a softer heads-up.
"""
from datetime import datetime, timezone

import run_scraper as rs

NOW = datetime(2026, 7, 1, tzinfo=timezone.utc)


def _ev(id, vid, start, url="", end=None, cost=None, title="Show", private=False):
    return {"id": id, "venue_id": vid, "venue": vid, "start": start, "end": end,
            "source_url": url, "cost": cost, "title": title, "private": private,
            "last_scraped": ""}


# ---- collapse_permalink_dupes ----

def test_migration_ghost_collapses_to_freshest():
    # Same room + same permalink + same start = the same show under two id
    # schemes. The fresher copy (later last_scraped, with the corrected price)
    # wins; the stale ghost is dropped.
    url = "https://toad.com/e/1"
    old = {**_ev("toad-20260615-old-slug", "toad", "2026-06-15T20:00:00", url, cost="$10"),
           "last_scraped": "2026-06-14T06:00:00"}
    new = {**_ev("toad-abc123", "toad", "2026-06-15T20:00:00", url, cost="$15"),
           "last_scraped": "2026-06-15T06:00:00"}
    out = rs.collapse_permalink_dupes([old, new], shared_urls=set())
    assert len(out) == 1
    assert out[0]["cost"] == "$15"


def test_shared_calendar_page_never_collapses():
    # The Burren stamps one calendar URL on every event — collapsing by URL would
    # wipe the venue. shared_urls guards against exactly that.
    cal = "https://burren.com/calendar"
    evs = [_ev("burren-1", "burren", "2026-06-15T20:00:00", cal),
           _ev("burren-2", "burren", "2026-06-15T20:00:00", cal)]
    out = rs.collapse_permalink_dupes(evs, shared_urls={cal})
    assert len(out) == 2


def test_recurring_permalink_not_merged_across_dates():
    # A series that reuses one URL across dates must stay distinct per date.
    url = "https://toad.com/series"
    evs = [_ev("a", "toad", "2026-06-15T20:00:00", url),
           _ev("b", "toad", "2026-06-22T20:00:00", url)]
    out = rs.collapse_permalink_dupes(evs, shared_urls=set())
    assert len(out) == 2


def test_blank_url_passes_through():
    evs = [_ev("a", "mideast-upstairs", "2026-06-15T20:00:00", ""),
           _ev("b", "mideast-upstairs", "2026-06-15T21:00:00", "")]
    out = rs.collapse_permalink_dupes(evs, shared_urls=set())
    assert len(out) == 2


# ---- build_collisions ----

def test_exact_collision_same_room_same_start():
    evs = [_ev("a", "mideast-upstairs", "2026-06-15T19:00:00", title="Band A", cost="$12"),
           _ev("b", "mideast-upstairs", "2026-06-15T19:00:00", title="Band A!", cost="$15")]
    c = rs.build_collisions(evs)
    assert len(c["exact"]) == 1
    assert c["exact"][0]["count"] == 2


def test_different_rooms_same_time_not_a_collision():
    # Distinct venue_ids per room is what makes the detector safe.
    evs = [_ev("a", "mideast-upstairs", "2026-06-15T19:00:00"),
           _ev("b", "mideast-downstairs", "2026-06-15T19:00:00")]
    c = rs.build_collisions(evs)
    assert c["exact"] == []


def test_distinct_titles_same_slot_not_flagged():
    # A single-venue_id venue running a genuine multi-act bill / parallel
    # programming shares a slot but with unrelated titles — must NOT be flagged.
    evs = [_ev("a", "burren", "2026-07-01T19:00:00", title="Grain Thief"),
           _ev("b", "burren", "2026-07-01T19:00:00", title="Spring Hill Stringband")]
    c = rs.build_collisions(evs)
    assert c["exact"] == []


def test_title_variant_same_slot_is_flagged():
    # "52 Church" ⊆ "52 Church - The Glitter Boys" → a rename ghost.
    evs = [_ev("a", "sinclair", "2026-07-03T21:30:00", title="52 Church"),
           _ev("b", "sinclair", "2026-07-03T21:30:00", title="52 Church - The Glitter Boys")]
    c = rs.build_collisions(evs)
    assert len(c["exact"]) == 1


def test_distinct_permalinks_override_title_heuristic():
    # Two genuinely different Armory shows at the same slot whose titles happen to
    # share words ("... Show") but have their own permalinks — must NOT be flagged.
    evs = [_ev("a", "arts-armory", "2026-07-25T19:00:00", url="https://x/events/here-for-the-show/", title="HERE FOR THE SHOW"),
           _ev("b", "arts-armory", "2026-07-25T19:00:00", url="https://x/events/the-everything-show/", title="The Everything Show")]
    c = rs.build_collisions(evs)
    assert c["exact"] == []


def test_shared_or_missing_url_still_flags_retitle():
    # No per-event permalink (both blank) + variant titles → still a rename ghost.
    evs = [_ev("a", "sally-obriens", "2026-07-01T19:30:00", url="", title="Fandango!"),
           _ev("b", "sally-obriens", "2026-07-01T19:30:00", url="", title="Fandango! with Chris Cote")]
    c = rs.build_collisions(evs)
    assert len(c["exact"]) == 1


def test_private_event_excluded_from_collisions():
    evs = [_ev("a", "lilypad", "2026-06-15T19:00:00"),
           _ev("b", "lilypad", "2026-06-15T19:00:00", private=True)]
    c = rs.build_collisions(evs)
    assert c["exact"] == []


def test_overlapping_offset_sets_are_soft_overlap():
    evs = [_ev("a", "toad", "2026-06-15T19:00:00", end="2026-06-15T21:00:00"),
           _ev("b", "toad", "2026-06-15T20:00:00", end="2026-06-15T22:00:00")]
    c = rs.build_collisions(evs)
    assert c["exact"] == []
    assert len(c["overlap"]) == 1


# ---- reconcile_events ----

def _outcome(events, errored=False, report=None):
    return {"events": events, "report": report or {}, "errored": errored}


def test_reconcile_drops_unlisted_future_event():
    # A cleanly-scraped venue's fresh set doesn't include the stored copy (renamed
    # or cancelled) -> drop it, record it.
    old = _ev("sinclair-old", "sinclair", "2026-07-05T20:00:00", title="Band OLD")
    new = _ev("sinclair-new", "sinclair", "2026-07-05T20:00:00", title="Band NEW")
    kept, dropped, skipped = rs.reconcile_events(
        [old, new], {"sinclair": _outcome([new])}, [{"id": "sinclair"}], NOW)
    assert {e["id"] for e in kept} == {"sinclair-new"}
    assert [d["id"] for d in dropped] == ["sinclair-old"]
    assert skipped == []


def test_reconcile_leaves_past_events():
    now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    past = _ev("sinclair-past", "sinclair", "2026-07-05T20:00:00")   # before now
    new = _ev("sinclair-new", "sinclair", "2026-07-20T20:00:00")
    kept, dropped, _ = rs.reconcile_events(
        [past, new], {"sinclair": _outcome([new])}, [{"id": "sinclair"}], now)
    assert {e["id"] for e in kept} == {"sinclair-past", "sinclair-new"}
    assert dropped == []


def test_reconcile_skips_partial_feed():
    old = _ev("passim-old", "passim", "2026-07-15T20:00:00")
    new = _ev("passim-new", "passim", "2026-07-16T20:00:00")
    kept, dropped, _ = rs.reconcile_events(
        [old, new], {"passim": _outcome([new])},
        [{"id": "passim", "partial_feed": True}], NOW)
    assert {e["id"] for e in kept} == {"passim-old", "passim-new"}
    assert dropped == []


def test_reconcile_ignores_venues_not_scraped_this_run():
    other = _ev("burren-x", "burren-back-room", "2026-07-15T20:00:00")
    new = _ev("sinclair-new", "sinclair", "2026-07-16T20:00:00")
    kept, dropped, _ = rs.reconcile_events(
        [other, new], {"sinclair": _outcome([new])}, [{"id": "sinclair"}], NOW)
    assert {e["id"] for e in kept} == {"burren-x", "sinclair-new"}
    assert dropped == []


def test_reconcile_mass_drop_guard():
    # 6 stored future events, a clean scrape yields only 1 -> would drop 5/6 (>70%):
    # skip and flag rather than wipe (signature of an under-extracting parser).
    stored = [_ev(f"vrcc-{i}", "vrcc", f"2026-07-1{i}T20:00:00") for i in range(6)]
    new = _ev("vrcc-new", "vrcc", "2026-07-19T20:00:00")
    kept, dropped, skipped = rs.reconcile_events(
        stored + [new], {"vrcc": _outcome([new])}, [{"id": "vrcc"}], NOW)
    assert dropped == []
    assert len(skipped) == 1 and skipped[0]["venue_id"] == "vrcc"
    assert len(kept) == 7


def test_reconcile_gate_rejects_degraded_scrapes():
    assert not rs._reconcile_gate({"id": "x"}, _outcome(None))                       # cache hit
    assert not rs._reconcile_gate({"id": "x"}, _outcome([]))                         # empty yield
    assert not rs._reconcile_gate({"id": "x"}, _outcome([1], errored=True))          # crashed
    assert not rs._reconcile_gate({"id": "x"}, _outcome([1], report={"truncated": True}))
    assert not rs._reconcile_gate({"id": "x", "expected_empty": True}, _outcome([1]))
    assert rs._reconcile_gate({"id": "x"}, _outcome([1]))                            # trustworthy
