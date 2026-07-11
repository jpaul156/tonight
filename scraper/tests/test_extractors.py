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


def test_aeg_events_basic():
    # Minimal .entry.sinclair block matching The Sinclair's AEG/AXS template.
    html = """
    <div class="entry sinclair clearfix">
      <div class="thumb">
        <a href="https://www.sinclaircambridge.com/events/detail/1317869">
          <img src="https://images.axs.com/buck-meek.jpg"/></a>
      </div>
      <div class="info">
        <div class="title">
          <h5 class="presentedBy"></h5>
          <h3 class="carousel_item_title_small">
            <a href="https://www.sinclaircambridge.com/events/detail/1317869">Buck Meek</a></h3>
          <h4 class="supporting">Kisser</h4>
        </div>
        <div class="date-time-container">
          <span class="date"><span class="fa fa-calendar-o"></span>Wed, Jul 8, 2026</span>
          <span class="time"><span class="fa fa-clock-o"></span>Doors&#9;7:00 PM</span>
          <span class="age">All Ages</span>
        </div>
      </div>
      <div class="buttons">
        <a class="btn-tickets tickets status_1" href="https://www.axs.com/events/1317869/buck-meek">Buy Tickets</a>
      </div>
    </div>
    """
    events = sc.extract_aeg_events(html, "https://www.sinclaircambridge.com")
    assert len(events) == 1
    e = events[0]
    # Deterministic headliner only — NOT merged with the support act. This is the
    # whole point: the LLM used to jitter between "Buck Meek" and "Buck Meek -
    # Kisser", churning the title-derived id.
    assert e["title"] == "Buck Meek"
    assert e["start"] == "2026-07-08T19:00:00"
    assert e["description"] == "Kisser"
    assert e["image_url"] == "https://images.axs.com/buck-meek.jpg"
    assert e["ticket_url"] == "https://www.axs.com/events/1317869/buck-meek"
    # Stable per-event permalink drives the id (survives title/time edits).
    assert e["source_url"] == "https://www.sinclaircambridge.com/events/detail/1317869"


def test_events_manager_basic_and_dedup():
    # Two .em-event blocks for the SAME event (the plugin renders each event in
    # multiple layouts) plus one distinct event. Expect 2 events, not 3.
    block = """
    <div class="em-event em-item" data-href="https://artsatthearmory.org/events/widowspeak/">
      <div class="em-item-image"><div class="em-item-image-wrapper">
        <img src="https://artsatthearmory.org/wp/widowspeak.webp"/></div></div>
      <div class="em-item-info">
        <h3 class="em-item-title"><a href="https://artsatthearmory.org/events/widowspeak/">Widowspeak with Neu Blume</a></h3>
        <div class="em-event-meta em-item-meta">
          <div class="em-item-meta-line em-event-date em-event-meta-datetime"><span class="em-icon"></span>Fri. Jul. 03, 2026</div>
          <div class="em-item-meta-line em-event-time em-event-meta-datetime"><span class="em-icon"></span>7:00 pm - 10:00 pm</div>
        </div>
      </div>
    </div>"""
    other = block.replace("widowspeak", "swing").replace("Widowspeak with Neu Blume", "West Coast Swing").replace("Jul. 03", "Jul. 06")
    html = f"<div class='em-list'>{block}{block}</div><div class='em-grid'>{other}</div>"
    events = sc.extract_events_manager(html, "https://artsatthearmory.org")
    assert len(events) == 2                       # the duplicate render collapsed
    e = next(x for x in events if "Widowspeak" in x["title"])
    assert e["title"] == "Widowspeak with Neu Blume"
    assert e["start"] == "2026-07-03T19:00:00"
    assert e["end"] == "2026-07-03T22:00:00"      # both start and end parsed
    assert e["image_url"] == "https://artsatthearmory.org/wp/widowspeak.webp"
    assert e["source_url"] == "https://artsatthearmory.org/events/widowspeak/"


def test_crystal_events_basic():
    html = """
    <article class="grid-item event-grid-item post-3304 event">
      <div class="event-grid-header">
        <img class="wp-post-image" data-src="https://www.crystalballroomboston.com/wp/gash.jpg"/>
      </div>
      <h2 class="entry-title">GASH – Villain’s Ball</h2>
      <div class="entry-footer">
        <div class="event-meta">Sat, Jul 11, 2026 Show 8:00 pm Doors 7:00 pm 21+</div>
        <a class="event-link" href="https://www.crystalballroomboston.com/events/gash-villains-ball/">Details</a>
        <a href="https://www.ticketmaster.com/event/010064C1E0E4DF5D">Purchase Tickets</a>
      </div>
    </article>
    """
    events = sc.extract_crystal_events(html, "https://www.crystalballroomboston.com")
    assert len(events) == 1
    e = events[0]
    assert e["title"] == "GASH – Villain’s Ball"
    assert e["start"] == "2026-07-11T20:00:00"     # Show time, not Doors
    assert e["source_url"] == "https://www.crystalballroomboston.com/events/gash-villains-ball/"
    assert "ticketmaster" in e["ticket_url"]
    assert e["image_url"] == "https://www.crystalballroomboston.com/wp/gash.jpg"


def test_sally_events_multi_show_section_and_prices():
    # A section with two shows joined by "followed by ...", plus a "* * *" one.
    html = """
    <section>Sunday July 5 500pm Cambridge-Somerville All-Stars Free show ! followed by ... Sunday July 5 930pm Dub Apocalypse No cover !!</section>
    <section>Saturday July 4 730pm * * * Stan Martin Band $10</section>
    <section>Wednesday July 1 730pm Fandango! with Chris Cote No cover !!</section>
    <section>16</section>
    """
    events = sc.extract_sally_events(html, "https://www.sallyobriensbar.com")
    by = {e["title"]: e for e in events}
    assert len(events) == 4                                  # stray "16" skipped
    assert by["Cambridge-Somerville All-Stars"]["start"] == "2026-07-05T17:00:00"
    assert by["Cambridge-Somerville All-Stars"]["cost"] == "Free"
    assert by["Dub Apocalypse"]["start"] == "2026-07-05T21:30:00"   # second show split out
    assert by["Stan Martin Band"]["cost"] == "$10"          # "* * *" separator stripped
    assert by["Fandango! with Chris Cote"]["cost"] == "Free"  # trailing "!" in act kept


def test_aeg_datetime_parses_explicit_year():
    assert sc.parse_aeg_datetime("Tue, Jul 7, 2026", "Doors 7:00 PM") == "2026-07-07T19:00:00"
    # Full month name and no weekday still parse.
    assert sc.parse_aeg_datetime("July 7, 2026", "8:30 PM") == "2026-07-07T20:30:00"
    # Unparseable time falls back to midnight (event still lands on the day).
    assert sc.parse_aeg_datetime("Tue, Jul 7, 2026", "time TBA") == "2026-07-07T00:00:00"
    assert sc.parse_aeg_datetime("no date here", "7:00 PM") is None


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


def test_dice_events_basic():
    # Minimal DICE api/v2 shape: UTC instant + type tag + per-event permalink.
    feed = {"data": [{
        "name": "Wicked 80&#39;s ft. DJ Panda",
        "date": "2026-07-02T23:00:00Z",          # -> 19:00 EDT
        "date_end": "2026-07-03T03:00:00Z",
        "status": "on-sale",
        "type_tags": ["music:dj"],
        "url": "https://link.dice.fm/abc123",
        "raw_description": "A night of new wave.",
        "event_images": {"landscape": "https://dice-media/land.jpg",
                          "portrait": "https://dice-media/port.jpg"},
    }]}
    events = sc.extract_dice_events(json.dumps(feed), "https://dice")
    assert len(events) == 1
    e = events[0]
    assert e["title"] == "Wicked 80's ft. DJ Panda"     # HTML entity unescaped
    assert e["start"] == "2026-07-02T19:00"             # UTC Z -> naive EDT
    assert e["end"] == "2026-07-02T23:00"
    assert e["category"] == "music"                     # type tag prefix
    assert e["image_url"] == "https://dice-media/land.jpg"   # landscape preferred
    assert e["source_url"] == e["ticket_url"] == "https://link.dice.fm/abc123"


def test_dice_drops_cancelled_and_defaults_category():
    feed = {"data": [
        {"name": "Cancelled Show", "date": "2026-07-10T23:00:00Z",
         "status": "cancelled", "type_tags": ["music:live"]},   # dropped
        {"name": "Untagged Show", "date": "2026-07-11T23:00:00Z",
         "status": "on-sale"},                                  # default category
    ]}
    events = sc.extract_dice_events(json.dumps(feed), "https://dice")
    titles = {e["title"]: e["category"] for e in events}
    assert titles == {"Untagged Show": "music"}                 # music venue default


def test_dice_bad_json_returns_empty():
    assert sc.extract_dice_events("not json", "https://x") == []


# --- Google Calendar ICS (Village Social) ------------------------------------

# CRLF line endings + a folded DESCRIPTION line (leading space continues it),
# a timed UTC show, an all-day annotation, and a plain-text description.
_ICS = (
    "BEGIN:VCALENDAR\r\n"
    "VERSION:2.0\r\n"
    "BEGIN:VEVENT\r\n"
    "DTSTART:20260719T000000Z\r\n"          # midnight UTC Jul 19 = 8pm EDT Jul 18
    "DTEND:20260719T020000Z\r\n"
    "SUMMARY:Peter Janson\r\n"
    "DESCRIPTION:<div dir=\"auto\">Solo jazz\r\n"
    "  guitarist</div>\r\n"                  # folded continuation + HTML
    "URL:https://example.com/janson\r\n"
    "END:VEVENT\r\n"
    "BEGIN:VEVENT\r\n"
    "DTSTART;VALUE=DATE:20260717\r\n"        # all-day annotation — skipped
    "DTEND;VALUE=DATE:20260718\r\n"
    "SUMMARY:Private Event\r\n"
    "END:VEVENT\r\n"
    "BEGIN:VEVENT\r\n"
    "DTSTART:20261114T010000Z\r\n"           # Nov = EST (-5): 1am UTC = 8pm EST Nov 13
    "SUMMARY:Eva James\r\n"
    "DESCRIPTION:no html here\r\n"           # bare text, no BeautifulSoup needed
    "END:VEVENT\r\n"
    "END:VCALENDAR\r\n"
)


def test_gcal_ics_converts_utc_skips_allday_and_unfolds():
    events = sc.extract_gcal_ics(_ICS, "https://x")
    by = {e["title"]: e for e in events}
    assert set(by) == {"Peter Janson", "Eva James"}      # all-day marker skipped
    # UTC → Eastern (EDT in July), and folded/HTML description flattened.
    j = by["Peter Janson"]
    assert j["start"] == "2026-07-18T20:00:00"
    assert j["end"] == "2026-07-18T22:00:00"
    assert j["description"] == "Solo jazz guitarist"
    assert j["source_url"] == "https://example.com/janson"
    # DST handled by zoneinfo: November is EST (-5), not the summer -4.
    assert by["Eva James"]["start"] == "2026-11-13T20:00:00"
    assert by["Eva James"]["description"] == "no html here"


def test_gcal_ics_empty_feed_returns_empty():
    assert sc.extract_gcal_ics("BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n", "https://x") == []
