# venues.py
# One entry per scrapeable venue. Add new venues here — the runner
# picks them up automatically.
#
# Required fields for every venue:
#   id            unique slug, used in event IDs
#   name          display name shown in the app
#   address       street address
#   square        neighborhood label matching the front-end filter chips
#   transit_line  MBTA line name ("Red", "Green", etc.)
#   transit_color hex color for the transit badge
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
        "transit_color": "#DA291C",
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
                "square": "Central",
                "transit_line": "Red",
                "transit_color": "#DA291C",
                "transit_stop": "Central",
                "walk_minutes": 12,
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
        "transit_color": "#DA291C",
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
        "transit_color": "#DA291C",
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
        "prompt_notes": "- If the same artist appears twice on the same date with different show times, create two separate event entries with different start times.\n- The cost may include a member price (e.g. '$35 / Members $33') — preserve the full string.\n- The source_url for each event should be the /live-music/events/ link associated with that artist.",
        "location_keywords": {},
        "extra_venues": [],
    },

]

# Quick lookup by venue ID (used by the runner to resolve sibling venues)
VENUE_BY_ID = {v["id"]: v for v in VENUES}
for v in VENUES:
    for sv in v.get("extra_venues", []):
        VENUE_BY_ID[sv["id"]] = {**v, **sv, "extra_venues": [], "location_keywords": {}}
