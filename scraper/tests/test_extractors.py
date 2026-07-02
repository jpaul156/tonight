"""Structured (non-LLM) extractors, exercised with hand-built synthetic
fixtures matching each source's real shape. These guard against a refactor
quietly breaking a parser; when a live site changes format, add a saved fixture
of its new HTML/JSON here and assert the expected parse.

The synthetic inputs are intentionally minimal — enough fields for the parser
to succeed — since the goal is to lock in field-mapping and drop/skip rules,
not to reproduce a whole page."""
import json

import scraper_core as sc


def test_jsonld_events_basic():
    html = """
    <html><head>
    <script type="application/ld+json">
    {"@type": "Event", "name": "Hayden &amp; Friends",
     "startDate": "2026-10-02T19:00:00-04:00", "endDate": "2026-10-02T22:00:00-04:00",
     "url": "https://therockwell.org/e/hayden",
     "description": "<p>An evening of folk.</p>",
     "image": ["https://cdn/img.jpg"],
     "offers": {"price": "23", "url": "https://tix"}}
    </script></head></html>
    """
    events = sc.extract_jsonld_events(html, "https://therockwell.org")
    assert len(events) == 1
    e = events[0]
    assert e["title"] == "Hayden & Friends"           # HTML entity unescaped
    assert e["start"] == "2026-10-02T19:00"
    assert e["description"] == "An evening of folk."    # tags stripped
    assert e["image_url"] == "https://cdn/img.jpg"      # first of the list
    assert e["cost"] == "$23"


def test_jsonld_dedups_repeated_event():
    one = ('{"@type":"Event","name":"X","startDate":"2026-10-02T19:00:00",'
           '"url":"u"}')
    html = f'<script type="application/ld+json">[{one},{one}]</script>'
    assert len(sc.extract_jsonld_events(html, "https://x.org")) == 1


def test_squarespace_events_basic():
    # startDate is epoch-ms UTC; 2026-06-15T00:00Z -> 2026-06-14T20:00 EDT.
    doc = {"upcoming": [{
        "title": "Jazz Trio",
        "startDate": 1781827200000,
        "fullUrl": "/events/jazz",
        "body": "<p>Late set.</p>",
        "assetUrl": "https://images.squarespace-cdn.com/x.jpg",
    }]}
    events = sc.extract_squarespace_events(json.dumps(doc), "https://lilypadinman.com")
    assert len(events) == 1
    assert events[0]["title"] == "Jazz Trio"
    assert events[0]["start"].startswith("2026-06-1")
    assert events[0]["image_url"] == "https://images.squarespace-cdn.com/x.jpg"
    assert events[0]["source_url"] == "https://lilypadinman.com/events/jazz"


def test_squarespace_drops_placeholder_image():
    doc = {"upcoming": [{
        "title": "No Art Show", "startDate": 1781827200000,
        "assetUrl": "https://static1.squarespace.com/static/placeholder.png",
    }]}
    events = sc.extract_squarespace_events(json.dumps(doc), "https://x.com")
    assert events[0]["image_url"] is None


def test_aeronaut_filters_and_maps_category():
    feed = [
        {"venue_slug": "somerville", "category": "Music", "name": "Band A",
         "date": "2026-07-04", "start": "20:00:00"},
        {"venue_slug": "somerville", "category": "Closed", "name": "Holiday",
         "date": "2026-07-04", "start": "00:00:00"},          # dropped
        {"venue_slug": "allston", "category": "Music", "name": "Elsewhere",
         "date": "2026-07-04", "start": "20:00:00"},          # wrong venue
        {"venue_slug": "somerville", "category": "Bike", "name": "Group Ride",
         "date": "2026-07-05", "start": "10:00:00"},
    ]
    events = sc.extract_aeronaut_events(json.dumps(feed), "https://aeronaut")
    titles = {e["title"]: e["category"] for e in events}
    assert titles == {"Band A": "music", "Group Ride": "community"}


def test_aeronaut_bad_json_returns_empty():
    assert sc.extract_aeronaut_events("not json", "https://x") == []
