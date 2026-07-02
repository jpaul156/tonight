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
    eid = sc.make_event_id("burren", "2026-06-15T20:00:00", "The Grafton Street Ramblers!")
    assert eid.startswith("burren-20260615-")
    assert " " not in eid and "!" not in eid
