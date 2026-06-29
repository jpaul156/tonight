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
    {
        "id": "burren",
        "name": "The Burren",
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
        "location_keywords": {},
        "extra_venues": [],
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
        "collection_url": "https://www.sallyobriensbar.com/music/",
        "scrape_strategy": "html_full_text",
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
        "scrape_strategy": "html_full_text",
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
        "scrape_strategy": "html_full_text",
        "detail_pages": False,
        "url_contains": None,
        "location_keywords": {},
        "extra_venues": [],
    },

]

# Quick lookup by venue ID (used by the runner to resolve sibling venues)
VENUE_BY_ID = {v["id"]: v for v in VENUES}
for v in VENUES:
    for sv in v.get("extra_venues", []):
        VENUE_BY_ID[sv["id"]] = {**v, **sv, "extra_venues": [], "location_keywords": {}}
