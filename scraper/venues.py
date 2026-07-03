# venues.py
# One entry per scrapeable venue. Add new venues here — the runner
# picks them up automatically.
#
# Required fields for every venue:
#   id            unique slug, used in event IDs
#   name          display name shown in the app
#   address       street address
#   square        neighborhood label matching the front-end filter chips
#   transit_line  MBTA line/mode name ("Red", "Green", "Bus",
#                 "Commuter Rail", "Ferry", etc.) — the badge color is
#                 derived from this name in the front end (LINE_COLORS),
#                 so no hex is stored here.
#   transit_stop  station name shown in the badge
#   walk_minutes  approximate walk from the T stop
#   is_local      True for independent/locally-owned venues
#   collection_url the events/calendar page to scrape
#   scrape_strategy one of: "shopify_products", "html_page"
#
# Optional fields:
#   detail_pages  True if we should fetch individual event pages for
#                 richer data (image, description, cost, ticket_url).
#                 Set False for venues where a single calendar page
#                 has everything we need.
#   url_contains  string filter — only follow detail links whose URL
#                 contains this string (e.g. "/products/"). Ignored
#                 if detail_pages is False.
#   extra_venues  list of sibling venue dicts that share the same
#                 collection page but are physically separate locations
#                 (e.g. Lamplighter Broadway + CX).
#   location_keywords  dict mapping location string fragments to
#                 venue IDs, used to route events to the right
#                 physical location when a single collection page
#                 covers multiple venues.
#   max_output_tokens  override for the Pass-1 LLM response budget (default
#                 8000). Raise it for a high-volume calendar that the health
#                 dashboard flags as "truncated" (trailing events lost).
#   expected_empty True if this venue is known to yield 0 events right now
#                 (a stale calendar, or a JS-only site awaiting Playwright).
#                 The health dashboard treats 0 events as a calm "idle" state
#                 instead of an error for these, so real breakage stands out.
#   event_address True if this venue sometimes hosts events at a DIFFERENT
#                 address than its own (e.g. street festivals at partner
#                 spaces). Opt-in because it costs extra LLM extraction —
#                 only set it for sources known to do this. When set, the
#                 scraper records the per-event address (and its square, for
#                 filtering) on events whose address differs from the venue's;
#                 events at the venue keep address=None and inherit the venue
#                 address from data/venues.json at render time.

VENUES = [

    # ----------------------------------------------------------
    # Lamplighter Brewing — Broadway (primary) + CX (sibling)
    # ----------------------------------------------------------
    {
        "id": "lamplighter-broadway",
        "name": "Lamplighter Brewing - Broadway",
        "address": "284 Broadway, Cambridge, MA",
        "square": "Central",
        "transit_line": "Red",
        "transit_stop": "Central",
        "walk_minutes": 8,
        "is_local": True,
        "collection_url": "https://lamplighterbrewing.com/collections/events",
        "scrape_strategy": "shopify_products",
        "detail_pages": True,
        "url_contains": "/products/",
        "location_keywords": {
            "cx": "lamplighter-cx",
            "western": "lamplighter-cx",
            "525": "lamplighter-cx",
            "broadway": "lamplighter-broadway",
            "284": "lamplighter-broadway",
        },
        "extra_venues": [
            {
                "id": "lamplighter-cx",
                "name": "Lamplighter Brewing - CX",
                "address": "525 Western Ave, Cambridge, MA",
                "square": "Lechmere",
                "transit_line": "Green",
                "transit_stop": "Lechmere",
                "walk_minutes": 2,
                "is_local": True,
            }
        ],
    },

    # ----------------------------------------------------------
    # The Burren — Davis Square
    # ----------------------------------------------------------
    # The Burren has two performance rooms — the ticketed Back Room and the
    # free trad/acoustic Front Room — and the music table tags every event with
    # its room ("THE BACK ROOM" / "THE FRONT ROOM" in a class="Room" cell, read
    # by extract_burren_tables into each event's `location`). We split them into
    # peer stages the same way as the Middle East complex: the owning entry holds
    # the collection page + strategy and is the no-match fallback (the Back Room,
    # the main ticketed room), and location_keywords routes each event to the
    # right stage. Keep these fields in sync with data/venues.json.
    {
        "id": "burren-back-room",
        "name": "The Burren - Back Room",
        "address": "247 Elm St, Somerville, MA",
        "square": "Davis",
        "transit_line": "Red",
        "transit_stop": "Davis",
        "walk_minutes": 4,
        "is_local": True,
        "collection_url": "https://www.burren.com/music.html",
        "scrape_strategy": "burren_tables",
        "detail_pages": False,
        "url_contains": None,
        "location_keywords": {
            "back room": "burren-back-room",
            "front room": "burren-front-room",
        },
        "extra_venues": [
            {
                "id": "burren-front-room",
                "name": "The Burren - Front Room",
                "address": "247 Elm St, Somerville, MA",
                "square": "Davis",
                "transit_line": "Red",
                "transit_stop": "Davis",
                "walk_minutes": 4,
                "is_local": True,
            },
        ],
    },

    {
        "id": "passim",
        "name": "Club Passim",
        "address": "47 Palmer St, Cambridge, MA",
        "square": "Harvard",
        "transit_line": "Red",
        "transit_stop": "Harvard",
        "walk_minutes": 4,
        "is_local": True,
        "collection_url": "https://www.passim.org/live-music/",
        # html_full_text: send full stripped body to LLM so it sees all
        # show instances (e.g. two Gail Ann Dorsey shows at 5pm and 8pm).
        # Detail pages supply image + description keyed by source_url.
        # "See More" is JS-driven so pagination won't help; we accept
        # ~7 visible events per scrape and accumulate over time via merging.
        "scrape_strategy": "html_full_text",
        "detail_pages": True,
        "url_contains": "/live-music/events/",
        "max_pages": 1,
        "prompt_notes": "- If the same artist appears twice on the same date with different show times, create two separate event entries with different start times.\n- The cost may include a member price (e.g. '$35 / Members $33') — preserve the full string.\n- The text contains [EVENT_URL: https://...] markers immediately before each event listing. Set source_url to the EVENT_URL that appears closest before that event's artist name.",
        "location_keywords": {},
        "extra_venues": [],
    },

    # ----------------------------------------------------------
    # The Tall Ship Boston — East Boston waterfront (Wix Events)
    # ----------------------------------------------------------
    {
        "id": "tallship",
        "name": "The Tall Ship Boston",
        "address": "1 E Pier Dr, East Boston, MA",
        "square": "Maverick",
        "transit_line": "Blue",
        "transit_stop": "Maverick",
        "walk_minutes": 7,
        "is_local": True,
        "collection_url": "https://www.tallshipboston.com/events",
        # wix_events: the full event list is server-rendered as JSON in the
        # page's appsWarmupData blob, so we parse it directly (no LLM Pass 1).
        # Title, image, description and times all come from the JSON.
        # See parse_wix_datetime for the timezone handling.
        #
        # detail_pages skipped for now: detail URLs exist at
        # /event-details/<slug> and return 200, but pricing isn't in the list
        # JSON so ~30 extra fetches/run would only gain cost data. Enable later
        # if cost matters or richer descriptions are wanted.
        "scrape_strategy": "wix_events",
        "detail_pages": False,
        "url_contains": None,
        "location_keywords": {},
        "extra_venues": [],
    },

    # ----------------------------------------------------------
    # Veronica Robles Cultural Center — East Boston
    # ----------------------------------------------------------
    {
        "id": "vrcc",
        "name": "Veronica Robles Cultural Center",
        "address": "282 Meridian St., East Boston, MA",
        "square": "Maverick",
        "transit_line": "Blue",
        "transit_stop": "Maverick",
        "walk_minutes": 5,
        "is_local": True,
        "collection_url": "https://veronicaroblesculturalcenter.org/events-east-boston/",
        # html_full_text: an Elementor (WordPress) page with no stable per-event
        # container class and heavy per-card variation (TBD dates, end time only
        # in the description, address in different spots, inconsistent/dead
        # buttons). Only ~10 events on the page, so we send the whole stripped
        # body to the LLM rather than parsing structure. Detail "buttons" are
        # unreliable (external links, "More information soon"), so no Pass 2.
        "scrape_strategy": "html_full_text",
        "detail_pages": False,
        "url_contains": None,
        # Several events are off-site (Bremen St, Border St, Symphony Hall) while
        # the center is at 282 Meridian St — exactly what event_address is for.
        "event_address": True,
        "prompt_notes": (
            "- Each event card lists, in order: the title, then an address line, then a "
            "description, then the date, then a time, then a button label. The address "
            "and date/time belong to the event whose title appears just before them.\n"
            "- Skip any event whose date or time is shown as 'TBD' or otherwise "
            "unspecified — do not invent a date.\n"
            "- Some events show only a start time in the time field but state the full "
            "range in the description (e.g. '2:00–5:00 p.m.'). Use the description's "
            "end time as the event end when it is given there.\n"
            "- Ignore button labels such as 'More information', 'More information soon', "
            "'More information here', and 'Details coming soon' — they are navigation, not "
            "event data, and several are non-functional."
        ),
        "location_keywords": {},
        "extra_venues": [],
    },

    # ----------------------------------------------------------
    # Sheet2 batch (added 2026-06-29). All html_full_text + LLM:
    # event text is server-rendered, no inline JSON-LD Event data.
    # See scraper/NEW_VENUES.md for the per-venue parse assessment.
    # detail_pages left False on the first pass — turn on per venue
    # only if a calendar lacks image/description we want.
    # ----------------------------------------------------------
    {
        "id": "sally-obriens",
        "name": "Sally O'Brien's",
        "address": "335 Somerville Ave, Somerville, MA",
        "square": "Union Square",
        "transit_line": "Green",
        "transit_stop": "Union Square",
        "walk_minutes": 3,
        "is_local": True,
        # Hand-formatted prose calendar (one show per line inside <section>
        # blocks, e.g. "Wednesday July 1 730pm Fandango! with Chris Cote No cover
        # !!"). Parsed directly (sally_events), no LLM: the LLM re-rendered
        # "Fandango!" vs "Fandango! with Chris Cote", churning the title-derived
        # id. No permalinks here, so ids stay title-based — but a deterministic
        # parser reads the same title every run, so they no longer churn.
        "collection_url": "https://www.sallyobriensbar.com/music/",
        "scrape_strategy": "sally_events",
        "detail_pages": False,
        "url_contains": None,
        "location_keywords": {},
        "extra_venues": [],
    },
    {
        "id": "arts-armory",
        "name": "Arts at the Armory",
        "address": "191 Highland Ave, Somerville, MA",
        "square": "Davis",
        "transit_line": "Green",
        "transit_stop": "Magoun",
        "walk_minutes": 10,
        "is_local": True,
        "collection_url": "https://artsatthearmory.org/upcoming-events/",
        # WordPress Events Manager plugin — fully server-rendered .em-event.em-item
        # blocks. Parsed directly (em_events), no LLM: the old html_full_text path
        # re-titled shows non-deterministically, churning the title-derived id and
        # piling up duplicate ghosts. Each block carries a per-instance permalink,
        # so ids are stable across re-scrapes.
        "scrape_strategy": "em_events",
        "detail_pages": False,
        "url_contains": None,
        "location_keywords": {},
        "extra_venues": [],
    },
    {
        "id": "plough-stars",
        "name": "The Plough and Stars",
        "address": "912 Massachusetts Ave, Cambridge, MA",
        "square": "Central",
        "transit_line": "Red",
        "transit_stop": "Central",
        "walk_minutes": 8,
        "is_local": True,
        "collection_url": "https://calendar.ploughandstars.com/events/calendar",
        "scrape_strategy": "html_full_text",
        "detail_pages": False,
        "url_contains": None,
        "location_keywords": {},
        "extra_venues": [],
    },
    {
        "id": "sinclair",
        "name": "The Sinclair",
        "address": "52 Church St, Cambridge, MA",
        "square": "Harvard",
        "transit_line": "Red",
        "transit_stop": "Harvard",
        "walk_minutes": 3,
        "is_local": False,
        "collection_url": "https://www.sinclaircambridge.com/events",
        # AEG Presents / AXS venue template — fully server-rendered
        # `.entry.sinclair` blocks. Parsed directly (aeg_events), no LLM: the
        # previous html_full_text path re-titled shows non-deterministically each
        # run ("52 Church" vs "52 Church - The Glitter Boys"), churning the
        # title-derived id and piling up duplicate ghosts. Each block has a
        # /events/detail/<id> permalink, so ids are now stable across re-scrapes.
        "scrape_strategy": "aeg_events",
        "detail_pages": False,
        "url_contains": None,
        "location_keywords": {},
        "extra_venues": [],
    },

    {
        "id": "comedy-studio",
        "name": "The Comedy Studio",
        "address": "5 John F. Kennedy St, Cambridge, MA",
        "square": "Harvard",
        "transit_line": "Red",
        "transit_stop": "Harvard",
        "walk_minutes": 2,
        "is_local": True,
        # The club's own /events page is a React shell; the real schedule lives
        # on its SeatEngine box-office site as JSON-LD (EventVenue.events[]).
        # Parsed directly via the seatengine strategy — no LLM. The v-<uuid> host
        # is this venue's stable SeatEngine site id.
        "collection_url": "https://v-cf2b1561-bf36-40b8-8380-9c2a3bd0e4e3.seatengine-sites.com",
        "scrape_strategy": "seatengine",
        "default_category": "comedy",  # a comedy club — bias ambiguous titles to comedy
        "detail_pages": False,
        "url_contains": None,
        "location_keywords": {},
        "extra_venues": [],
    },

    # McCarthy's complex — three peer stages under one Squarespace calendar,
    # each encoded as a title prefix ("McCarthys: ...", "Toad: ...",
    # "Upstairs: ..."). Same multi-stage pattern as the Middle East rooms: one
    # entry owns the collection page + strategy and is the no-match fallback
    # (McCarthy's — the Irish-session room), extras are peer stages. The
    # squarespace_events extractor lifts the stage prefix into `location` so
    # location_keywords routes each event. Keep in sync with data/venues.json.
    {
        "id": "mccarthys",
        "name": "McCarthy's",
        "address": "1912 Massachusetts Ave, Cambridge, MA",
        "square": "Porter",
        "transit_line": "Red",
        "transit_stop": "Porter",
        "walk_minutes": 6,
        "is_local": True,
        # Squarespace JS calendar — its /calendar page renders no event text, but
        # the events collection serves the full schedule (incl. images) as JSON.
        # Point collection_url at the ?format=json endpoint; parsed directly.
        "collection_url": "https://www.mccarthystoad.com/music?format=json",
        "scrape_strategy": "squarespace_events",
        "detail_pages": False,
        "url_contains": None,
        "location_keywords": {
            "mccarthys": "mccarthys",
            "toad": "toad",
            "upstairs": "mccarthys-upstairs",
        },
        "extra_venues": [
            {
                "id": "toad",
                "name": "Toad",
                "address": "1912 Massachusetts Ave, Cambridge, MA",
                "square": "Porter",
                "transit_line": "Red",
                "transit_stop": "Porter",
                "walk_minutes": 6,
                "is_local": True,
            },
            {
                "id": "mccarthys-upstairs",
                "name": "McCarthy's - Upstairs",
                "address": "1912 Massachusetts Ave, Cambridge, MA",
                "square": "Porter",
                "transit_line": "Red",
                "transit_stop": "Porter",
                "walk_minutes": 6,
                "is_local": True,
            },
        ],
    },

    {
        "id": "rockwell",
        "name": "The Rockwell",
        "address": "255 Elm St, Somerville, MA",
        "square": "Davis",
        "transit_line": "Red",
        "transit_stop": "Davis",
        "walk_minutes": 2,
        "is_local": True,
        # WordPress/The Events Calendar site that server-renders the full
        # schedule as schema.org Event JSON-LD — parsed directly, no LLM.
        "collection_url": "https://therockwell.org/calendar/",
        "scrape_strategy": "jsonld_events",
        "detail_pages": False,
        "url_contains": None,
        "location_keywords": {},
        "extra_venues": [],
    },

    {
        "id": "lilypad",
        "name": "The Lilypad",
        "address": "1353 Cambridge St, Cambridge, MA",
        "square": "Inman Square",
        "transit_line": "Bus",
        "transit_stop": "Inman Square",
        "walk_minutes": 1,
        "is_local": True,
        # Squarespace events collection lives at /home (per sitemap) — jazz and
        # avant-garde shows, often several a night. Parsed from ?format=json.
        "collection_url": "https://www.lilypadinman.com/home?format=json",
        "scrape_strategy": "squarespace_events",
        "detail_pages": False,
        "url_contains": None,
        "location_keywords": {},
        "extra_venues": [],
    },

    {
        "id": "bow-market",
        "name": "Bow Market",
        "address": "1 Bow Market Way, Somerville, MA",
        "square": "Union Square",
        "transit_line": "Green",
        "transit_stop": "Union Square",
        "walk_minutes": 3,
        "is_local": True,
        # Squarespace events collection at /upcomingevents (per sitemap). NOTE:
        # as of 2026-06 this collection is stale — nothing posted after mid-June,
        # so it currently yields 0 upcoming. Config is correct and will populate
        # automatically if Bow Market resumes posting here. (Multi-tenant market;
        # treated as one venue per the project decision.)
        "collection_url": "https://www.bowmarketsomerville.com/upcomingevents?format=json",
        "scrape_strategy": "squarespace_events",
        "expected_empty": True,  # collection stale since mid-June 2026 — see note above
        "detail_pages": False,
        "url_contains": None,
        "location_keywords": {},
        "extra_venues": [],
    },

    # ----------------------------------------------------------
    # Midway Cafe — Jamaica Plain (Green Street, Orange)
    # ----------------------------------------------------------
    {
        "id": "midway-cafe",
        "name": "Midway Cafe",
        "address": "3496 Washington St, Jamaica Plain, MA",
        "square": "Green Street",
        "transit_line": "Orange",
        "transit_stop": "Green Street",
        "walk_minutes": 12,
        "is_local": True,
        # Calendar at /our/calendar is JS-rendered — strips to ~300 chars with
        # no event data. Facebook is their primary schedule but has no structured
        # feed. Needs Playwright. Config is correct; will work once Playwright
        # support is added.
        "collection_url": "https://midwaycafe.com/our/calendar",
        "scrape_strategy": "html_full_text",
        "expected_empty": True,  # JS-rendered calendar — awaits Playwright support
        "detail_pages": False,
        "url_contains": None,
        "location_keywords": {},
        "extra_venues": [],
    },

    # ----------------------------------------------------------
    # Dorchester Brewing Co. — Dorchester (Andrew, Red)
    # ----------------------------------------------------------
    {
        "id": "dorchester-brewing",
        "name": "Dorchester Brewing Co.",
        "address": "1250 Massachusetts Ave, Dorchester, MA",
        "square": "Andrew",  # must match the metro-map station name, not "Andrew Square"
        "transit_line": "Red",
        "transit_stop": "Andrew",
        "walk_minutes": 12,
        "is_local": True,
        # WordPress site. /events-calendar/ is JS-rendered (body strips to ~400
        # chars). /events/ is the tile view and server-renders full event HTML.
        "collection_url": "https://www.dorchesterbrewing.com/events/",
        "scrape_strategy": "html_full_text",
        "detail_pages": False,
        "url_contains": None,
        "prompt_notes": (
            "- Skip any listing whose title contains 'Private Event' or 'Private Party'."
        ),
        "location_keywords": {},
        "extra_venues": [],
    },

    # ----------------------------------------------------------
    # The Lizard Lounge — Cambridge (Porter, Red)
    # ----------------------------------------------------------
    {
        "id": "lizard-lounge",
        "name": "The Lizard Lounge",
        "address": "1667 Massachusetts Ave, Cambridge, MA",
        "square": "Porter",
        "transit_line": "Red",
        "transit_stop": "Porter",
        "walk_minutes": 8,
        "is_local": True,
        # WordPress + The Events Calendar plugin. JSON-LD Event schema embedded
        # in the page — parse directly, no LLM needed.
        "collection_url": "https://lizardloungeclub.com/calendar/",
        "scrape_strategy": "jsonld_events",
        "detail_pages": False,
        "url_contains": None,
        "location_keywords": {},
        "extra_venues": [],
    },

    # ----------------------------------------------------------
    # Idle Hands Craft Ales — Malden Center (Orange)
    # ----------------------------------------------------------
    {
        "id": "idle-hands",
        "name": "Idle Hands Craft Ales",
        "address": "35 Medford St, Malden, MA",
        "square": "Malden Center",
        "transit_line": "Orange",
        "transit_stop": "Malden Center",
        "walk_minutes": 10,
        "is_local": True,
        # Squarespace events collection confirmed via ?format=json (returns
        # "upcoming" array with title, startDate, endDate, image, etc.).
        "collection_url": "https://www.idlehandscraftales.com/events?format=json",
        "scrape_strategy": "squarespace_events",
        "detail_pages": False,
        "url_contains": None,
        "location_keywords": {},
        "extra_venues": [],
    },

    # ----------------------------------------------------------
    # Faces Brewing Co. — Malden Center (Orange)
    # ----------------------------------------------------------
    {
        "id": "faces-brewing",
        "name": "Faces Brewing Co.",
        "address": "107 Ferry St, Malden, MA",
        "square": "Malden Center",
        "transit_line": "Orange",
        "transit_stop": "Malden Center",
        "walk_minutes": 12,
        "is_local": True,
        # Squarespace site, but ?format=json items embed date as freetext in
        # excerpt ("8 pm - July 8th, 2026") with no startDate/endDate fields —
        # incompatible with squarespace_events. Use html_full_text instead;
        # the /events page server-renders all event cards.
        "collection_url": "https://www.facesbrewing.com/events",
        "scrape_strategy": "html_full_text",
        "detail_pages": False,
        "url_contains": None,
        "location_keywords": {},
        "extra_venues": [],
    },

    # ----------------------------------------------------------
    # Medford Brewing Company — Medford Square (Bus)
    # ----------------------------------------------------------
    {
        "id": "medford-brewing",
        "name": "Medford Brewing Company",
        "address": "30 Harvard Ave, Medford, MA",
        "square": "Medford Square",
        "transit_line": "Bus",
        "transit_stop": "Medford Square",
        "walk_minutes": 5,
        "is_local": True,
        # WordPress + The Events Calendar plugin. JSON-LD Event schema on the
        # events page — same pattern as The Rockwell.
        "collection_url": "https://medfordbrew.com/events/",
        "scrape_strategy": "jsonld_events",
        "detail_pages": False,
        "url_contains": None,
        "location_keywords": {},
        "extra_venues": [],
    },

    # ----------------------------------------------------------
    # Deep Cuts — Medford Square (Bus)
    # ----------------------------------------------------------
    {
        "id": "deep-cuts",
        "name": "Deep Cuts",
        "address": "21 Main St, Medford, MA",
        "square": "Medford Square",
        "transit_line": "Bus",
        "transit_stop": "Medford Square",
        "walk_minutes": 3,
        "is_local": True,
        # Events page is fully JS-rendered — html_full_text gets 0 chars.
        # No structured alternative (Bandsintown/Eventbrite are aggregators,
        # not a direct feed). Needs Playwright. Disabled with a stub URL until
        # Playwright support is added; swap collection_url back to /events then.
        "collection_url": "https://www.deepcuts.rocks/events",
        "scrape_strategy": "html_full_text",
        "expected_empty": True,  # fully JS-rendered — awaits Playwright support
        "detail_pages": False,
        "url_contains": None,
        "location_keywords": {},
        "extra_venues": [],
    },

    # ----------------------------------------------------------
    # Village Social Club — Brookline Village (Green D)
    # ----------------------------------------------------------
    {
        "id": "village-social",
        "name": "Village Social Club",
        "address": "27 Harvard St, Brookline, MA",
        "square": "Brookline Village",
        "transit_line": "Green",
        "transit_stop": "Brookline Village",
        "walk_minutes": 3,
        "is_local": True,
        # BentoBox CMS — calendar page at /event-calendar/. May be JS-rendered;
        # if html_full_text yields nothing, Playwright will be needed.
        "collection_url": "https://www.villagesocialclub.com/event-calendar/",
        "scrape_strategy": "html_full_text",
        "detail_pages": False,
        "url_contains": None,
        "prompt_notes": (
            "- Skip any listing whose title is 'Private Event' or 'Private Party' "
            "or contains the word 'Private'."
        ),
        "location_keywords": {},
        "extra_venues": [],
    },

    # ----------------------------------------------------------
    # Somerville Theatre — Davis Square (Red)
    # ----------------------------------------------------------
    {
        "id": "somerville-theatre",
        "name": "Somerville Theatre",
        "address": "55 Davis Square, Somerville, MA",
        "square": "Davis",  # must match the metro-map station name, not "Davis Square"
        "transit_line": "Red",
        "transit_stop": "Davis",
        "walk_minutes": 2,
        "is_local": True,
        # WP Theatre Manager plugin renders events server-side — no JS needed.
        # /events = live music/theater/comedy only (no films). /calendar and
        # /schedule are film listings; hold for the cinema feature design.
        # Crystal Ballroom is a separate venue in the same building with its
        # own website and event calendar — see crystal-ballroom below.
        "collection_url": "https://www.somervilletheatre.com/events/",
        "scrape_strategy": "html_full_text",
        "detail_pages": False,
        "url_contains": None,
        "prompt_notes": (
            "- Events are music, comedy, theater, and lectures only — no film screenings."
        ),
        "location_keywords": {},
        "extra_venues": [],
    },

    # ----------------------------------------------------------
    # Crystal Ballroom — Davis Square (Red)
    # ----------------------------------------------------------
    {
        "id": "crystal-ballroom",
        "name": "Crystal Ballroom",
        "address": "55 Davis Square, Somerville, MA",
        "square": "Davis",  # must match the metro-map station name, not "Davis Square"
        "transit_line": "Red",
        "transit_stop": "Davis",
        "walk_minutes": 2,
        "is_local": True,
        # Separate venue from Somerville Theatre despite sharing the building.
        # Custom WordPress theme — server-rendered article.event-grid-item cards
        # (.entry-title + .event-meta + /events/ permalink). Parsed directly
        # (crystal_events), no LLM: the old html_full_text path re-titled shows
        # ("SOLYA" vs "SOLYA *NEW DATE*"), churning the title-derived id. Each
        # card has a stable /events/<slug>/ permalink, so ids hold across scrapes.
        "collection_url": "https://www.crystalballroomboston.com/events/",
        "scrape_strategy": "crystal_events",
        "detail_pages": False,
        "url_contains": None,
        "location_keywords": {},
        "extra_venues": [],
    },

    # ----------------------------------------------------------
    # Hamilton Restaurant & Bar — Coolidge Corner (Green C)
    # ----------------------------------------------------------
    {
        "id": "hamilton-brookline",
        "name": "Hamilton Restaurant & Bar",
        "address": "1 Longwood Ave, Brookline, MA",
        "square": "Coolidge Corner",
        "transit_line": "Green",
        "transit_stop": "Coolidge Corner",
        "walk_minutes": 3,
        "is_local": True,
        # SpotApps CMS events page. Currently hosts one recurring event:
        # Geeks Who Drink Trivia, every Monday at 7:30pm. html_full_text
        # to pick up any additional events that get added.
        "collection_url": "https://hamiltonbrookline.com/brookline-coolidge-corner-hamilton-restaurant-and-bar-events",
        "scrape_strategy": "html_full_text",
        "detail_pages": False,
        "url_contains": None,
        "location_keywords": {},
        "extra_venues": [],
    },

    # ----------------------------------------------------------
    # Aeronaut Brewing Company — Union Square (Green)
    # ----------------------------------------------------------
    {
        "id": "aeronaut",
        "name": "Aeronaut Brewing Company",
        "address": "14 Tyler St, Somerville, MA",
        "square": "Union Square",
        "transit_line": "Green",
        "transit_stop": "Union Square",
        "walk_minutes": 8,
        "is_local": True,
        # The public /events/ page (WordPress/Elementor, Cloudflare-fronted) is
        # a JS-injected teaser; the real calendar loads from a static CDN feed.
        # Point collection_url straight at that feed and parse it directly —
        # no LLM for extraction or categorization (native category per item).
        # The feed is Somerville-only today but carries venue_slug; the parser
        # filters to somerville so a future Allston split can't leak in.
        "collection_url": "https://d3izki9aezxlkr.cloudfront.net/public_events.json",
        "scrape_strategy": "aeronaut_events",
        "detail_pages": False,
        "url_contains": None,
        "location_keywords": {},
        "extra_venues": [],
    },

    # ----------------------------------------------------------
    # The Middle East complex — Central Square (Red)
    # ----------------------------------------------------------
    # One WordPress home page (mideastclub.com) embeds a TicketWeb plugin that
    # server-renders every show across all five rooms, each card tagged with its
    # room ("@ Middle East - Upstairs", "@ Sonia", ...). Parsed directly by the
    # mideast_events strategy (no LLM for extraction); location_keywords routes
    # each event to the right physical room (same routing mechanism as
    # Lamplighter — though these five are peer stages in one complex, not
    # separate locations of one company). The five rooms are peers; the config
    # format just requires ONE entry to own the collection page + strategy and
    # act as the no-match fallback, and Downstairs holds that role arbitrarily.
    # A room label that matches no keyword is NOT silently accepted as a
    # Downstairs show — extract_mideast_events warns so a new/renamed TicketWeb
    # room is caught. All five are in/around Central Square on the Red line.
    # Keep these fields in sync with data/venues.json.
    {
        "id": "mideast-downstairs",
        "name": "The Middle East - Downstairs",
        "address": "472 Massachusetts Ave, Cambridge, MA",
        "square": "Central",
        "transit_line": "Red",
        "transit_stop": "Central",
        "walk_minutes": 3,
        "is_local": True,
        "collection_url": "https://www.mideastclub.com",
        "scrape_strategy": "mideast_events",
        "detail_pages": False,
        "url_contains": None,
        "location_keywords": {
            "downstairs": "mideast-downstairs",
            "upstairs": "mideast-upstairs",
            "corner": "mideast-corner",
            "zuzu": "mideast-zuzu",
            "sonia": "mideast-sonia",
        },
        "extra_venues": [
            {
                "id": "mideast-upstairs",
                "name": "The Middle East - Upstairs",
                "address": "472 Massachusetts Ave, Cambridge, MA",
                "square": "Central",
                "transit_line": "Red",
                "transit_stop": "Central",
                "walk_minutes": 3,
                "is_local": True,
            },
            {
                "id": "mideast-corner",
                "name": "The Middle East - Corner",
                "address": "480 Massachusetts Ave, Cambridge, MA",
                "square": "Central",
                "transit_line": "Red",
                "transit_stop": "Central",
                "walk_minutes": 3,
                "is_local": True,
            },
            {
                "id": "mideast-zuzu",
                "name": "ZuZu",
                "address": "474 Massachusetts Ave, Cambridge, MA",
                "square": "Central",
                "transit_line": "Red",
                "transit_stop": "Central",
                "walk_minutes": 3,
                "is_local": True,
            },
            {
                "id": "mideast-sonia",
                "name": "Sonia",
                "address": "10 Brookline St, Cambridge, MA",
                "square": "Central",
                "transit_line": "Red",
                "transit_stop": "Central",
                "walk_minutes": 4,
                "is_local": True,
            },
        ],
    },

]

# Quick lookup by venue ID (used by the runner to resolve sibling venues)
VENUE_BY_ID = {v["id"]: v for v in VENUES}
for v in VENUES:
    for sv in v.get("extra_venues", []):
        VENUE_BY_ID[sv["id"]] = {**v, **sv, "extra_venues": [], "location_keywords": {}}
