"""Private-event detection, event-vs-venue address logic, and venue routing —
small pure functions that encode narrow, deliberate rules (documented in
CLAUDE.md) that a refactor could easily regress."""
import scraper_core as sc


# ---- is_private_event: deliberately narrow ----

def test_private_title():
    assert sc.is_private_event("** Private Event **", None) is True


def test_private_closed_to_public_in_description():
    assert sc.is_private_event("Some Show", "The venue is closed to the public tonight.") is True


def test_footer_mention_is_not_private():
    # A booking-availability footer must NOT trip the flag.
    assert sc.is_private_event("Jazz Night", "Book the Lilypad for your next private party!") is False


def test_normal_event_not_private():
    assert sc.is_private_event("Trivia Night", "Weekly quiz, all welcome.") is False


# ---- event_specific_address: only when it differs from the venue ----

VENUE = {"event_address": True, "address": "282 Meridian St., East Boston, MA"}


def test_same_address_returns_none():
    ev = {"event_address": "282 Meridian St."}
    assert sc.event_specific_address(ev, VENUE) is None


def test_different_address_returned():
    ev = {"event_address": "401 Bremen St., East Boston"}
    assert sc.event_specific_address(ev, VENUE) == "401 Bremen St., East Boston"


def test_no_optin_returns_none():
    ev = {"event_address": "401 Bremen St."}
    assert sc.event_specific_address(ev, {"address": "282 Meridian St."}) is None


# ---- resolve_venue_id: route by location keyword ----

CFG = {
    "id": "mideast-downstairs",
    "location_keywords": {"upstairs": "mideast-upstairs", "sonia": "mideast-sonia"},
}


def test_routes_by_keyword():
    assert sc.resolve_venue_id("@ Middle East - Upstairs", "", CFG) == "mideast-upstairs"


def test_unmatched_falls_back_to_primary():
    assert sc.resolve_venue_id("@ Some New Room", "", CFG) == "mideast-downstairs"


def test_no_keywords_returns_primary():
    assert sc.resolve_venue_id("anywhere", "", {"id": "burren"}) == "burren"


# ---- make_event_id: stable, slugified ----

def test_make_event_id_shape():
    # No permalink -> id is venue_id + start token, TITLE-FREE, so a title edit
    # doesn't mint a new id (== the event's shareable URL / .ics UID).
    eid = sc.make_event_id("burren", "2026-06-15T20:00:00", "The Grafton Street Ramblers!")
    assert eid == "burren-20260615T2000"
    assert " " not in eid and "!" not in eid


def test_make_event_id_title_edit_is_stable():
    """The core fix: same venue + same start, different title -> SAME id."""
    a = sc.make_event_id("burren", "2026-06-15T20:00:00", "Grafton Street Ramblers")
    b = sc.make_event_id("burren", "2026-06-15T20:00:00", "Grafton St. Ramblers (SOLD OUT)")
    assert a == b


def test_make_event_id_disambiguates_only_when_asked():
    """Genuine same-slot collisions (Aeronaut parallel programming) fall back to
    a title tiebreaker, but only when build_events flags it."""
    a = sc.make_event_id("aeronaut", "2026-06-15T20:00:00", "Trivia", disambiguate=True)
    b = sc.make_event_id("aeronaut", "2026-06-15T20:00:00", "Live Jazz", disambiguate=True)
    assert a != b
    assert a.startswith("aeronaut-20260615T2000-")


def test_make_event_id_falls_back_to_title_without_start():
    """No start = no stable slot to key on, so distinct start-less events must
    still stay apart via the title."""
    a = sc.make_event_id("burren", None, "Open Mic")
    b = sc.make_event_id("burren", None, "Quiz Night")
    assert a != b and a.startswith("burren-")


def _mini_venue_cfg():
    return {
        "id": "aeronaut", "name": "Aeronaut", "collection_url": "https://aero/cal",
        "is_local": True, "square": "Union", "transit_line": "Green",
        "transit_stop": "Union Square", "walk_minutes": 5,
    }


def test_build_events_disambiguates_only_the_colliding_slot():
    """End-to-end: two permalink-less events sharing (venue_id, start) get a
    title tiebreaker each; an event alone in its slot stays clean + title-free."""
    raw = [
        {"title": "Trivia", "start": "2026-06-15T20:00:00"},
        {"title": "Live Jazz", "start": "2026-06-15T20:00:00"},  # same slot -> collide
        {"title": "Open Mic", "start": "2026-06-15T22:00:00"},   # alone in its slot
    ]
    out = sc.build_events(raw, {}, {}, _mini_venue_cfg())
    ids = [e["id"] for e in out]
    assert len(set(ids)) == 3
    collided = [i for i in ids if i.startswith("aeronaut-20260615T2000")]
    assert len(collided) == 2 and all("-" in i[len("aeronaut-20260615T2000"):] for i in collided)
    assert "aeronaut-20260615T2200" in ids  # the lone event: no title suffix


def test_make_event_id_permalink_survives_rename():
    # When a real per-event permalink is available the id is derived from it, so
    # a title (or start) edit keeps the SAME id — the fix overwrites in place
    # instead of leaving a duplicate ghost.
    url = "https://toadcambridge.com/event/12345"
    a = sc.make_event_id("toad", "2026-06-15T20:00:00", "The Ramblers", source_url=url)
    b = sc.make_event_id("toad", "2026-06-15T21:00:00", "The Ramblers (SOLD OUT)", source_url=url)
    assert a == b
    # ...but a different show (different URL) still gets a distinct id.
    assert a != sc.make_event_id("toad", "2026-06-15T20:00:00", "The Ramblers",
                                 source_url="https://toadcambridge.com/event/999")
