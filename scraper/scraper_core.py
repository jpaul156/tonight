# scraper_core.py
# Shared scraping engine. Each venue config in venues.py drives this
# without needing venue-specific code.

import json
import re
import time
import hashlib
import requests
from bs4 import BeautifulSoup
import anthropic
from datetime import datetime, timezone, timedelta
from html import unescape as html_unescape

# Lazy client so importing this module (e.g. from the test suite) doesn't
# require ANTHROPIC_API_KEY — it's only needed when an LLM pass actually runs.
_client = None


def get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client

VALID_CATEGORIES = [
    "music", "trivia", "comedy", "film", "market",
    "karaoke", "community", "sports", "fitness", "food", "other"
]

# Strategies whose Pass 1 extraction goes through the LLM. Everything else
# parses a structured feed directly. Used by the health report to show which
# venues still cost tokens (and are more fragile to prompt/format drift).
LLM_STRATEGIES = {"html_page", "html_full_text", "shopify_products"}

# Front-end filter chips (must match SQUARES in js/app.js). Only used to
# validate an event-location square extracted for venues that opt into
# per-event addresses (event_address: True). An invalid/unknown value falls
# back to the venue's own square.
SQUARES = [
    "Davis", "Porter", "Harvard", "Central", "Kendall", "Downtown Crossing",
    "Assembly", "Lechmere", "Union Square", "Maverick",
]

BASE_URL_PATTERN = re.compile(r"^https?://[^/]+")


# ============================================================
# Cache — persisted to scraper_cache.json between runs
# ============================================================

def load_cache(path="scraper_cache.json"):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_cache(cache, path="scraper_cache.json"):
    with open(path, "w") as f:
        json.dump(cache, f, indent=2)


def content_hash(html):
    return hashlib.md5(html.encode()).hexdigest()


# ============================================================
# HTTP — conditional fetching with ETag / Last-Modified / hash
# ============================================================

def fetch_page(url, cache=None, retries=2, extra_headers=None):
    """
    Fetch a page. If cache is provided:
    - Sends If-None-Match / If-Modified-Since headers when available.
    - Returns (html, changed) where changed=False means skip LLM.
    If cache is None, behaves like the old fetch_page and returns html only.

    extra_headers: per-venue static request headers (e.g. an API key). Merged
    over the default UA; used by feed-backed venues whose collection_url is an
    authenticated JSON endpoint (see fetch_headers in venues.py, e.g. Deep Cuts'
    DICE partner API).
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }
    if extra_headers:
        headers.update(extra_headers)

    cached = (cache or {}).get(url, {})
    if cached.get("etag"):
        headers["If-None-Match"] = cached["etag"]
    if cached.get("last_modified"):
        headers["If-Modified-Since"] = cached["last_modified"]

    for attempt in range(retries + 1):
        try:
            r = requests.get(url, headers=headers, timeout=12)

            # 304 = server confirmed nothing changed
            if r.status_code == 304:
                if cache is not None:
                    cache[url]["last_fetched"] = datetime.now(timezone.utc).isoformat()
                return (None, False) if cache is not None else None

            r.raise_for_status()
            html = r.text

            if cache is not None:
                new_hash = content_hash(html)
                old_hash = cached.get("content_hash")

                # Update cache entry
                cache[url] = {
                    "etag": r.headers.get("ETag"),
                    "last_modified": r.headers.get("Last-Modified"),
                    "content_hash": new_hash,
                    "last_fetched": datetime.now(timezone.utc).isoformat(),
                    "last_changed": (
                        datetime.now(timezone.utc).isoformat()
                        if new_hash != old_hash
                        else cached.get("last_changed")
                    ),
                }

                # Hash match = content identical even though server sent 200
                if old_hash and new_hash == old_hash:
                    return html, False

                return html, True

            return html  # no-cache mode

        except Exception as e:
            if attempt == retries:
                raise
            print(f"    Retry {attempt + 1} after error: {e}")
            time.sleep(2)


# ============================================================
# HTML extraction strategies
# ============================================================

def parse_burren_date(date_str, time_str):
    """
    Convert "MONDAY JUNE 8" + "8:30pm:" into an ISO 8601 datetime string.
    Handles ranges like "3-6pm:" by using the start time.
    Handles multi-time strings like "10:30am, 12:30pm, ..." by using the first.

    Year is inferred from the current date: if the event month is earlier than
    the current month it wraps to next year (handles Dec→Jan rollovers).
    """
    import re
    from datetime import datetime as dt
    MONTHS = {"JANUARY":1,"FEBRUARY":2,"MARCH":3,"APRIL":4,"MAY":5,"JUNE":6,
              "JULY":7,"AUGUST":8,"SEPTEMBER":9,"OCTOBER":10,"NOVEMBER":11,"DECEMBER":12}

    # Extract month and day from date string
    date_upper = date_str.upper()
    month_num = None
    day_num = None
    for month, num in MONTHS.items():
        if month in date_upper:
            month_num = num
            m = re.search(rf"{month}\s+(\d+)", date_upper)
            if m:
                day_num = int(m.group(1))
            break
    if not month_num or not day_num:
        return None

    # Infer year: if event month is before current month, the event is next year
    now = datetime.now(timezone.utc)
    year = now.year if month_num >= now.month else now.year + 1

    # Extract first time from time string (handles ranges, multi-times, trailing colon)
    time_clean = re.split(r"[,&]", time_str)[0].strip().rstrip(":")
    # Handle range "3-6pm" -> "3pm"
    time_clean = re.sub(r"(\d+)-\d+(am|pm)", r"\1\2", time_clean, flags=re.I)
    try:
        t = dt.strptime(time_clean.strip().upper(), "%I:%M%p")
    except ValueError:
        try:
            t = dt.strptime(time_clean.strip().upper(), "%I%p")
        except ValueError:
            return None

    return f"{year}-{month_num:02d}-{day_num:02d}T{t.hour:02d}:{t.minute:02d}:00"


def extract_burren_tables(html, base_url):
    """
    The Burren uses an old-school table layout where each event is a <tr>
    with two <td>s: left has room/time/band/description, right has an <img>.
    Returns a list of parsed event dicts directly — no LLM needed for
    date/time/image/ticket since the HTML structure is fully machine-readable.
    """
    soup = BeautifulSoup(html, "html.parser")
    current_date = None
    events = []

    for tr in soup.find_all("tr"):
        cells = tr.find_all("td", recursive=False)

        # Date header: single cell containing a day name
        if len(cells) == 1:
            text = cells[0].get_text(strip=True)
            if any(day in text.upper() for day in
                   ["MONDAY","TUESDAY","WEDNESDAY","THURSDAY","FRIDAY","SATURDAY","SUNDAY"]):
                current_date = text.strip()
            continue

        # Event row: 2+ cells, left = details, right = image
        if len(cells) >= 2 and current_date:
            detail_cell = None
            image_url = None

            for cell in cells:
                if cell.find(class_="BAND") or cell.find(class_="Time"):
                    detail_cell = cell
                img = cell.find("img")
                if img and img.get("src") and ("images/" in img["src"] or img["src"].startswith("http")):
                    src = img["src"].strip()
                    # Skip UI/navigation images — only want actual event photos
                    EXCLUDED = {"moreinfo.gif", "header1.gif", "line.gif",
                                "tab_home.gif", "tab_music.gif", "tab_food.gif",
                                "tab_more.gif", "tab_fb.gif", "tab_twitter.gif",
                                "tab_instagram.gif"}
                    filename = src.split("/")[-1].lower()
                    if filename in EXCLUDED:
                        continue
                    image_url = src if src.startswith("http") else base_url.rstrip("/") + "/" + src.lstrip("/")

            if not detail_cell:
                continue

            room_el  = detail_cell.find(class_="Room")
            time_el  = detail_cell.find(class_="Time")
            band_el  = detail_cell.find(class_="BAND")
            desc_el  = detail_cell.find(class_="Text")

            ticket_url = None
            cost = None
            for a in detail_cell.find_all("a", href=True):
                if "24hourmusic.com" in a["href"] or "ticket" in a["href"].lower():
                    ticket_url = a["href"]
                    break

            description = desc_el.get_text(strip=True) if desc_el else None
            # Infer cost from description text
            if description:
                desc_lower = description.lower()
                if "free show" in desc_lower or "free admission" in desc_lower or \
                   description.upper().startswith("FREE"):
                    cost = "Free"

            time_str = time_el.get_text(strip=True) if time_el else ""
            start = parse_burren_date(current_date, time_str)

            if band_el and start:
                events.append({
                    "title":       band_el.get_text(strip=True),
                    "start":       start,
                    "end":         None,
                    "location":    room_el.get_text(strip=True) if room_el else None,
                    "cost":        cost,
                    "source_url":  None,
                    "performer":   None,  # title is the performer name for Burren
                    "description": description,
                    "image_url":   image_url,
                    "ticket_url":  ticket_url,
                    "is_recurring": any(kw in band_el.get_text(strip=True).upper()
                                        for kw in ["SESSION","TRIVIA","COMEDY NIGHT",
                                                   "OLD TIMEY","DJANGO CADRE","GRAIN THIEF",
                                                   "TORN AND FRAYED"]),
                    "recurrence_note": None,
                })

    print(f"  Parsed {len(events)} events from table structure (no LLM needed)")
    return events  # returns list of dicts, not a text string


def extract_mideast_events(html, base_url):
    """
    The Middle East complex (mideastclub.com) is a WordPress site whose home
    page embeds a TicketWeb plugin that server-renders every upcoming show as a
    `.event-list .row` card. Each card is fully machine-readable — a dedicated
    class per field — so we parse directly, no LLM for extraction:

      .tw-event-date   "6.30"  (month.day, no year)
      .tw-event-time   "Show: 5:00PM"
      .tw-name a       title (+ href = ticketweb ticket URL)
      .tw-venue-name   "@ Middle East - Upstairs"  (the room)
      .tw-price        "$24.18"  (optional)
      img.event-img    poster image (ticketweb CDN)

    The room string is returned as `location`; venues.py routes it to the right
    sub-venue (Upstairs / Downstairs / Corner / Zuzu / Sonia) via
    location_keywords. Category is left to the Pass 3 classifier.

    The five rooms are peers, not a headquarters with satellites, so an
    unrecognized room must NOT silently fall back to the config's primary
    (Downstairs) and masquerade as a real Downstairs show. We warn on any room
    string that matches none of the known keywords so a new/renamed TicketWeb
    room is caught instead of quietly misrouted. Keep KNOWN_ROOM_KEYWORDS in
    sync with location_keywords in venues.py.
    """
    KNOWN_ROOM_KEYWORDS = ("downstairs", "upstairs", "corner", "zuzu", "sonia")

    soup = BeautifulSoup(html, "html.parser")
    lst = soup.find(class_="event-list")
    if not lst:
        print("  WARNING: no .event-list found — page structure may have changed")
        return []

    events = []
    for row in lst.select(".row"):
        name_el = row.find(class_="tw-name")
        date_el = row.find(class_="tw-event-date")
        if not (name_el and date_el):
            continue

        title = name_el.get_text(strip=True)
        time_el  = row.find(class_="tw-event-time")
        start = parse_mideast_datetime(
            date_el.get_text(strip=True),
            time_el.get_text(strip=True) if time_el else "",
        )
        if not start:
            continue

        room_el  = row.find(class_="tw-venue-name")
        location = room_el.get_text(strip=True).lstrip("@").strip() if room_el else None
        if not location or not any(kw in location.lower() for kw in KNOWN_ROOM_KEYWORDS):
            print(f"  WARNING: unrecognized room {location!r} for '{title}' — "
                  f"will fall back to the primary venue; add it to "
                  f"location_keywords + KNOWN_ROOM_KEYWORDS")

        price_el = row.find(class_="tw-price")
        cost = price_el.get_text(strip=True) if price_el else None

        img = row.find("img", class_="event-img")
        image_url = img.get("src").strip() if img and img.get("src") else None

        tix = row.find("a", class_="tw-buy-tix-btn")
        ticket_url = tix.get("href") if tix and tix.get("href") else None

        title_upper = title.upper()
        is_recurring = any(kw in title_upper for kw in
                           ["KARAOKE", "TRIVIA", "OPEN MIC", "NETWORK WEDNESDAYS"])

        events.append({
            "title":       title,
            "start":       start,
            "end":         None,
            "location":    location,
            "cost":        cost,
            "source_url":  None,
            "performer":   None,
            "description": None,
            "image_url":   image_url,
            "ticket_url":  ticket_url,
            "is_recurring": is_recurring,
            "recurrence_note": None,
        })

    print(f"  Parsed {len(events)} events from TicketWeb cards (no LLM needed)")
    return events


def parse_mideast_datetime(month_day, time_str):
    """
    Combine the Middle East card's "6.30" (month.day, no year) and
    "Show: 5:00PM" into a naive ISO 8601 string ("2026-06-30T17:00:00").

    Year is inferred as the current year, rolling forward when the resulting
    date is well in the past (handles the Dec->Jan wrap). Times are kept naive
    Eastern wall-clock, matching every other venue here.
    """
    m = re.match(r"\s*(\d{1,2})\.(\d{1,2})\s*$", month_day or "")
    if not m:
        return None
    month, day = int(m.group(1)), int(m.group(2))

    t = re.sub(r"(?i)(show|doors)\s*:", "", time_str or "").strip()
    tm = None
    for fmt in ("%I:%M%p", "%I%p", "%I:%M %p"):
        try:
            tm = datetime.strptime(t, fmt)
            break
        except ValueError:
            continue
    if tm is None:
        return None

    now = datetime.now(timezone.utc)
    try:
        dt = datetime(now.year, month, day, tm.hour, tm.minute)
    except ValueError:
        return None
    if dt.replace(tzinfo=timezone.utc) < now - timedelta(days=60):
        dt = dt.replace(year=now.year + 1)
    return dt.strftime("%Y-%m-%dT%H:%M:00")


def extract_aeg_events(html, base_url):
    """AEG Presents / AXS venue template (e.g. The Sinclair). Every show is a
    server-rendered `.entry.sinclair` block with a dedicated class per field, so
    we parse directly — no LLM. This matters beyond cost: the LLM Pass 1 rendered
    the title non-deterministically ("52 Church" vs "52 Church - The Glitter
    Boys" vs "The Glitter Boys"), and since the event id is title-derived AND is
    the shareable URL, every re-render minted a new id → duplicate ghosts + dead
    links. A static parser takes `.carousel_item_title_small` verbatim every run,
    so the title — and the id — are stable.

      .carousel_item_title_small a  headliner (+ href = detail permalink)
      .presentedBy                  promoter tag ("NPR Presents"), often empty
      .supporting                   support acts ("ft ...", "Kisser")
      .date                         "Tue, Jul 7, 2026"
      .time                         "Doors  7:00 PM"
      .thumb img                    poster image (AXS CDN)
      a.btn-tickets                 AXS ticket URL

    Each block carries a stable /events/detail/<id> permalink, returned as
    source_url so make_event_id keys off it (survives title/time edits). The page
    shows only the next ~15-20 shows at once; the runner's merge accumulates the
    fuller calendar across daily runs.
    """
    soup = BeautifulSoup(html, "html.parser")
    entries = soup.select(".entry.sinclair")
    if not entries:
        print("  WARNING: no .entry.sinclair blocks found — page structure may have changed")
        return []

    events = []
    for e in entries:
        title_el = e.select_one(".carousel_item_title_small")
        date_el = e.select_one(".date")
        time_el = e.select_one(".time")
        if not (title_el and date_el):
            continue
        title = title_el.get_text(" ", strip=True)
        start = parse_aeg_datetime(
            date_el.get_text(" ", strip=True),
            time_el.get_text(" ", strip=True) if time_el else "",
        )
        if not (title and start):
            continue

        link = title_el.find("a", href=True) or e.select_one(".thumb a[href]")
        source_url = link["href"].strip() if link else None

        presented = (e.select_one(".presentedBy").get_text(" ", strip=True)
                     if e.select_one(".presentedBy") else "")
        support = (e.select_one(".supporting").get_text(" ", strip=True)
                   if e.select_one(".supporting") else "")
        description = " · ".join(p for p in [presented, support] if p) or None

        img = e.select_one(".thumb img")
        image_url = img.get("src").strip() if img and img.get("src") else None

        tix = e.select_one("a.btn-tickets[href]")
        ticket_url = tix["href"].strip() if tix else None

        events.append({
            "title":       title,
            "start":       start,
            "end":         None,
            "location":    None,
            "cost":        None,
            "source_url":  source_url,
            "performer":   title,   # the headliner is the act
            "description": description,
            "image_url":   image_url,
            "ticket_url":  ticket_url,
            "is_recurring": False,
            "recurrence_note": None,
        })

    print(f"  Parsed {len(events)} events from AEG entry blocks (no LLM needed)")
    return events


def extract_events_manager(html, base_url):
    """WordPress "Events Manager" plugin template (e.g. Arts at the Armory). Each
    show is a server-rendered `.em-event.em-item` block with a dedicated class per
    field, so we parse directly — no LLM, which keeps the title (and the
    title-derived id) deterministic instead of jittering run to run.

      .em-item-title a   title (+ href = event permalink; also on data-href)
      .em-event-date     "Fri. Jul. 03, 2026"
      .em-event-time     "7:00 pm - 10:00 pm"   (start - end)
      .em-item-image img poster

    Each block's permalink is a stable per-event/instance URL (recurring classes
    get date-stamped slugs like .../west-coast-swing-training-2026-07-06/), so
    make_event_id keys off it and ids survive title edits + shared links hold.
    """
    soup = BeautifulSoup(html, "html.parser")
    items = soup.select(".em-event.em-item")
    if not items:
        print("  WARNING: no .em-event.em-item blocks found — page structure may have changed")
        return []

    events = []
    seen = set()  # the plugin renders each event in several layouts (list/grid)
    for it in items:
        title_el = it.select_one(".em-item-title")
        date_el = it.select_one(".em-event-date")
        if not (title_el and date_el):
            continue
        title = title_el.get_text(" ", strip=True)
        # "Fri. Jul. 03, 2026" — the abbreviations carry periods; drop them so
        # parse_aeg_datetime's "<Mon> <day>, <year>" regex matches.
        date_txt = date_el.get_text(" ", strip=True).replace(".", " ")

        time_el = it.select_one(".em-event-time")
        time_txt = time_el.get_text(" ", strip=True) if time_el else ""
        parts = re.split(r"\s*[-–—]\s*", time_txt, maxsplit=1)
        start = parse_aeg_datetime(date_txt, parts[0] if parts else "")
        end = parse_aeg_datetime(date_txt, parts[1]) if len(parts) > 1 else None
        if not (title and start):
            continue

        link = title_el.find("a", href=True)
        source_url = (link["href"].strip() if link else None) or it.get("data-href")

        # The same event is emitted once per layout on the page; collapse the
        # copies. Genuinely distinct same-slot events differ in title or url, so
        # keying on all three keeps them.
        key = (source_url, start, title)
        if key in seen:
            continue
        seen.add(key)

        img = it.select_one(".em-item-image img")
        image_url = img.get("src").strip() if img and img.get("src") else None

        events.append({
            "title":       title,
            "start":       start,
            "end":         end,
            "location":    None,
            "cost":        None,
            "source_url":  source_url,
            "performer":   None,
            "description": None,
            "image_url":   image_url,
            "ticket_url":  None,
            "is_recurring": False,
            "recurrence_note": None,
        })

    print(f"  Parsed {len(events)} events from Events Manager blocks (no LLM needed)")
    return events


def parse_aeg_datetime(date_str, time_str):
    """Combine an AEG listing's "Tue, Jul 7, 2026" and "Doors 7:00 PM" into a
    naive Eastern ISO string ("2026-07-07T19:00:00"). The year is explicit here,
    so no roll-forward inference is needed. If the time can't be parsed the show
    still lands on the right day at midnight rather than being dropped."""
    # Strip the leading weekday, then read "<Mon> <day>, <year>".
    m = re.search(r"([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{4})", date_str or "")
    if not m:
        return None
    try:
        d = datetime.strptime(f"{m.group(1)[:3]} {int(m.group(2))} {m.group(3)}",
                              "%b %d %Y")
    except ValueError:
        return None
    hour = minute = 0
    tm = re.search(r"(\d{1,2}):(\d{2})\s*([AaPp][Mm])", time_str or "")
    if tm:
        try:
            t = datetime.strptime(
                f"{tm.group(1)}:{tm.group(2)} {tm.group(3).upper()}", "%I:%M %p")
            hour, minute = t.hour, t.minute
        except ValueError:
            pass
    return d.replace(hour=hour, minute=minute).strftime("%Y-%m-%dT%H:%M:00")


def extract_crystal_events(html, base_url):
    """Crystal Ballroom — custom WordPress theme, server-rendered
    `article.event-grid-item` cards. Parsed directly, no LLM (which used to
    re-title shows non-deterministically, e.g. "SOLYA" vs "SOLYA *NEW DATE*",
    churning the title-derived id).

      .entry-title   title
      .event-meta    "Sat, Jul 11, 2026 Show 8:00 pm Doors 7:00 pm 21+"
      first /events/ link   event permalink (stable id source)
      ticketing link        ticket url
      img[data-src]         poster (lazy-loaded)
    """
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("article.event-grid-item")
    if not cards:
        print("  WARNING: no article.event-grid-item found — page structure may have changed")
        return []

    events = []
    for c in cards:
        title_el = c.select_one(".entry-title")
        meta_el = c.select_one(".event-meta")
        if not (title_el and meta_el):
            continue
        title = title_el.get_text(" ", strip=True)
        meta = meta_el.get_text(" ", strip=True)
        # parse_aeg_datetime reads the "<Mon> <day>, <year>" date and the first
        # time in the string — which is the Show time (it precedes Doors here).
        start = parse_aeg_datetime(meta, meta)
        if not (title and start):
            continue

        permalink = ticket_url = None
        for a in c.select("a[href]"):
            href = a["href"].strip()
            if "/events/" in href and not permalink:
                permalink = href
            elif re.search(r"ticketmaster|dice\.fm|etix|axs|eventbrite|seetickets|prekindle",
                           href, re.I) and not ticket_url:
                ticket_url = href

        img = c.select_one("img")
        image_url = (img.get("data-src") or img.get("src")).strip() if img and (img.get("data-src") or img.get("src")) else None

        events.append({
            "title":       title,
            "start":       start,
            "end":         None,
            "location":    None,
            "cost":        None,
            "source_url":  permalink,
            "performer":   None,
            "description": None,
            "image_url":   image_url,
            "ticket_url":  ticket_url,
            "is_recurring": False,
            "recurrence_note": None,
        })

    print(f"  Parsed {len(events)} events from Crystal event cards (no LLM needed)")
    return events


# Sally O'Brien's lists shows as hand-formatted prose inside <section> blocks,
# e.g. "Wednesday July 1 730pm Fandango! with Chris Cote No cover !!" — one line
# per show, sometimes two shows in a section joined by "followed by ...". The
# format is regular enough to parse deterministically, which stops the LLM from
# re-rendering "Fandango!" vs "Fandango! with Chris Cote" and churning the id.
_SALLY_EVENT_RE = re.compile(
    r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\s+"
    r"(?P<mon>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+"
    r"(?P<day>\d{1,2})\s+(?P<t>\d{3,4})\s*pm", re.I)
_SALLY_PRICE_RE = re.compile(
    r"(\$\d+|free\s*show|no[\s-]?cover(?:\s+residency)?)\s*!*\s*$", re.I)


def extract_sally_events(html, base_url):
    """Parse Sally O'Brien's prose calendar (see note above). Each <section> may
    hold one or two shows; we anchor on the date/time pattern, take the text up
    to the next anchor as the band + price, and strip a trailing price phrase."""
    soup = BeautifulSoup(html, "html.parser")
    events = []
    for sec in soup.find_all("section"):
        text = re.sub(r"\s+", " ", sec.get_text(" ", strip=True)).strip()
        matches = list(_SALLY_EVENT_RE.finditer(text))
        for i, m in enumerate(matches):
            tail_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            tail = text[m.end():tail_end]
            # drop the "followed by ..." connector that precedes a second show
            tail = re.sub(r"(?i)\bfollowed by\b.*$", "", tail).strip()

            cost = None
            band = tail
            pm = _SALLY_PRICE_RE.search(tail)
            if pm:
                raw = pm.group(1).lower()
                cost = pm.group(1) if raw.startswith("$") else "Free"
                band = tail[:pm.start()]
            # Trim "* * *" separators and surrounding punctuation, but keep a
            # trailing "!" that belongs to the act ("Fandango!", "Hayride!").
            band = band.strip(" .*-")
            if not band:
                continue

            start = parse_sally_datetime(m.group("mon"), int(m.group("day")), m.group("t"))
            if not start:
                continue
            events.append({
                "title":       band,
                "start":       start,
                "end":         None,
                "location":    None,
                "cost":        cost,
                "source_url":  None,
                "performer":   band,
                "description": None,
                "image_url":   None,
                "ticket_url":  None,
                "is_recurring": "residency" in tail.lower(),
                "recurrence_note": None,
            })

    print(f"  Parsed {len(events)} events from Sally O'Brien's calendar (no LLM needed)")
    return events


def parse_sally_datetime(month_name, day, hhmm):
    """Combine Sally's "July", 1, "730" (compact pm time, no year) into a naive
    Eastern ISO string. Every listing is an afternoon/evening pm show, so the
    hour is taken as pm. Year is inferred as current, rolling forward when the
    date is well in the past (Dec->Jan wrap), matching parse_mideast_datetime."""
    try:
        mon = datetime.strptime(month_name[:3].title(), "%b").month
    except ValueError:
        return None
    digits = re.sub(r"\D", "", hhmm or "")
    if len(digits) < 3:
        return None
    hour, minute = int(digits[:-2]), int(digits[-2:])
    if hour != 12:
        hour += 12   # pm
    now = datetime.now(timezone.utc)
    try:
        dt = datetime(now.year, mon, day, hour, minute)
    except ValueError:
        return None
    if dt.replace(tzinfo=timezone.utc) < now - timedelta(days=60):
        dt = dt.replace(year=now.year + 1)
    return dt.strftime("%Y-%m-%dT%H:%M:00")


def parse_wix_datetime(date_str, time_str):
    """
    Combine Wix's pre-formatted strings, e.g. "June 6, 2026" + "2:00 PM",
    into a naive ISO 8601 string ("2026-06-06T14:00:00").

    We deliberately parse the *Formatted strings rather than the UTC startDate.
    Wix renders these in the event's configured timezone, which on this site is
    misconfigured to America/Denver even though the venue is in Boston. The
    formatted time is what the venue advertises and what patrons show up for, so
    it is the correct wall-clock time to store — and it matches every other
    venue here, which keep naive Eastern times. Converting the UTC startDate
    would shift every event by the Denver/Eastern offset.
    """
    if not date_str or not time_str:
        return None
    from datetime import datetime as dt
    try:
        d = dt.strptime(f"{date_str.strip()} {time_str.strip()}", "%B %d, %Y %I:%M %p")
    except ValueError:
        return None
    return d.strftime("%Y-%m-%dT%H:%M:00")


def extract_wix_events(html, base_url):
    """
    Wix Events sites (e.g. The Tall Ship) server-render the full event list as
    JSON inside the page's appsWarmupData blob. We parse it directly — the
    structure is fully machine-readable, so no LLM is needed for extraction
    (categories are still classified in Pass 3). Returns a list of event dicts.

    Events with status 2 (ended) are skipped so we don't import past events.
    """
    anchor = '"events":{"events":'
    i = html.find(anchor)
    if i == -1:
        print("  WARNING: no Wix events JSON found on page")
        return []
    try:
        arr, _ = json.JSONDecoder().raw_decode(html[i + len(anchor):])
    except ValueError as err:
        print(f"  WARNING: could not decode Wix events JSON: {err}")
        return []

    events = []
    for e in arr:
        if e.get("status") == 2:  # ended
            continue
        sc = e.get("scheduling", {})
        start = parse_wix_datetime(sc.get("startDateFormatted"), sc.get("startTimeFormatted"))
        if not start:
            continue
        end = parse_wix_datetime(sc.get("endDateFormatted"), sc.get("endTimeFormatted"))
        slug = e.get("slug")
        source_url = f"{base_url}/event-details/{slug}" if slug else None
        description = (e.get("description") or "").strip() or None
        image_url = (e.get("mainImage") or {}).get("url")

        events.append({
            "title":       e.get("title"),
            "start":       start,
            "end":         end,
            "location":    None,  # location.name is just the street address
            "cost":        None,  # not present in the list JSON
            "source_url":  source_url,
            "performer":   None,
            "description": description,
            "image_url":   image_url,
            "ticket_url":  None,
            "is_recurring": False,
            "recurrence_note": None,
        })

    print(f"  Parsed {len(events)} events from Wix JSON (no LLM needed)")
    return events


def _ics_to_eastern(val):
    """Convert an ICS DTSTART/DTEND value to a naive America/New_York ISO
    string. Handles UTC (trailing Z) and floating/TZID-qualified local times.
    Google Calendar emits timed values in UTC (trailing Z); we convert to
    Eastern wall-clock to match every other venue's naive local times. Uses
    zoneinfo so DST is handled correctly (EDT in summer, EST in winter) —
    unlike the run_scraper hardcoded −4 offset."""
    from zoneinfo import ZoneInfo
    val = val.strip()
    try:
        if val.endswith("Z"):
            dt = datetime.strptime(val, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            return dt.astimezone(ZoneInfo("America/New_York")).strftime("%Y-%m-%dT%H:%M:00")
        return datetime.strptime(val, "%Y%m%dT%H%M%S").strftime("%Y-%m-%dT%H:%M:00")
    except ValueError:
        return None


def extract_gcal_ics(ics_text, base_url):
    """Parse a public Google Calendar ICS feed.

    Village Social Club's on-site calendar is a JS-only BentoBox widget (the
    static page carries no event data), but the widget embeds a *public* Google
    Calendar iframe. We point collection_url straight at that calendar's
    /ical/.../basic.ics feed and parse it directly — no LLM, no Playwright.

    Only timed events are real shows. All-day (VALUE=DATE) entries on this
    calendar are annotations ("no live music", holiday "Private Event"
    markers), so we skip them — leaving the actual booked acts."""
    # RFC 5545 line unfolding: a CRLF followed by a space/tab continues the
    # prior line. Normalize then join folded continuations.
    text = re.sub(r"\r?\n[ \t]", "", ics_text.replace("\r\n", "\n"))

    def ics_unescape(v):
        return (v.replace("\\n", "\n").replace("\\,", ",")
                 .replace("\\;", ";").replace("\\\\", "\\")).strip()

    events = []
    for block in re.findall(r"BEGIN:VEVENT\n(.*?)\nEND:VEVENT", text, re.S):
        fields = {}
        for line in block.split("\n"):
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            fields.setdefault(key.split(";", 1)[0], (key, val))

        if "DTSTART" not in fields:
            continue
        dt_key, dt_val = fields["DTSTART"]
        # All-day markers (VALUE=DATE, no time component) are annotations, skip.
        if "VALUE=DATE" in dt_key or "T" not in dt_val:
            continue
        start = _ics_to_eastern(dt_val)
        if not start:
            continue
        end = _ics_to_eastern(fields["DTEND"][1]) if "DTEND" in fields else None

        title = ics_unescape(fields.get("SUMMARY", ("", ""))[1])
        if not title:
            continue
        raw_desc = ics_unescape(fields.get("DESCRIPTION", ("", ""))[1])
        # Descriptions sometimes carry HTML — strip to plain text, but only run
        # the parser when there's actually a tag (a bare URL/plain text trips
        # BeautifulSoup's MarkupResemblesLocator warning).
        description = raw_desc or None
        if raw_desc and "<" in raw_desc:
            description = BeautifulSoup(raw_desc, "html.parser").get_text(" ", strip=True) or None
        source_url = (fields.get("URL", ("", ""))[1] or "").strip() or None

        events.append({
            "title":       title,
            "start":       start,
            "end":         end,
            "location":    None,
            "cost":        None,
            "source_url":  source_url,
            "performer":   None,
            "description": description,
            "image_url":   None,
            "ticket_url":  None,
            "is_recurring": False,
            "recurrence_note": None,
        })

    print(f"  Parsed {len(events)} timed events from Google Calendar ICS (no LLM needed)")
    return events


def _seatengine_cost(offers):
    """First offer's price → display string ('$20', 'Free', or None)."""
    if not offers:
        return None
    o = offers[0] if isinstance(offers, list) else offers
    price = o.get("price")
    if price in (None, ""):
        return None
    try:
        val = float(price)
    except (TypeError, ValueError):
        return None
    if val == 0:
        return "Free"
    # drop trailing .00 so $20.00 reads as $20
    return f"${val:.2f}".rstrip("0").rstrip(".")


def extract_seatengine(html, base_url):
    """
    SeatEngine box-office sites (comedy clubs like The Comedy Studio) embed the
    full schedule as a JSON-LD EventVenue with an events[] array of schema.org
    Event objects — title, start/end (ISO, local offset), description, image,
    price (offers), performer, and a checkout URL. Fully machine-readable, so no
    LLM is needed for extraction (categories are still classified in Pass 3).

    Note: parse the venue's SeatEngine site (the *-seatengine-sites.com host),
    not the club's own /events page — the latter is a React shell whose JSON-LD
    carries the venue but zero events.
    """
    soup = BeautifulSoup(html, "html.parser")
    venue = None
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (ValueError, TypeError):
            continue
        if isinstance(data, dict) and data.get("@type") == "EventVenue":
            venue = data
            break
    if not venue:
        print("  WARNING: no SeatEngine EventVenue JSON-LD found on page")
        return []

    events = []
    for e in venue.get("events", []):
        status = (e.get("eventStatus") or "")
        if "Cancelled" in status or "Postponed" in status:
            continue
        start = (e.get("startDate") or "")[:16]  # 'YYYY-MM-DDThh:mm' local wall time
        if len(start) < 16:
            continue
        end = (e.get("endDate") or "")[:16] or None

        # Description is HTML and ends with a boilerplate "The Bar" footer on
        # every event — strip tags and cut the footer so cards stay clean.
        desc = None
        if e.get("description"):
            text = BeautifulSoup(e["description"], "html.parser").get_text("\n").strip()
            text = re.split(r"\n?\s*The Bar\s*\n", text)[0].strip()
            desc = text or None

        offers = e.get("offers") or []
        ticket_url = (offers[0].get("url") if offers else None)
        performer = None
        perf = e.get("performer")
        if isinstance(perf, list) and perf:
            performer = perf[0].get("name")
        elif isinstance(perf, dict):
            performer = perf.get("name")

        events.append({
            "title":       e.get("name"),
            "start":       start,
            "end":         end,
            "location":    None,
            "cost":        _seatengine_cost(offers),
            "source_url":  ticket_url,
            "performer":   performer,
            "description": desc,
            "image_url":   e.get("image"),
            "ticket_url":  ticket_url,
            "is_recurring": False,
            "recurrence_note": None,
        })

    print(f"  Parsed {len(events)} events from SeatEngine JSON-LD (no LLM needed)")
    return events


def _jsonld_price(offers):
    """schema.org offers → display cost string ('$25', '$25 – 75', 'Free', None)."""
    if not offers:
        return None
    o = offers[0] if isinstance(offers, list) else offers
    price = o.get("price") or o.get("lowPrice")
    if price in (None, ""):
        return None
    price = str(price).strip()
    if price in ("0", "0.0", "0.00"):
        return "Free"
    return price if price.startswith("$") else f"${price}"


def extract_jsonld_events(html, base_url):
    """
    Generic schema.org Event extractor for pages that server-render their
    schedule as JSON-LD (e.g. The Rockwell, a WordPress/The Events Calendar
    site). Reads every Event object found in any <script type="application/
    ld+json"> block — directly, no LLM. Handles a bare array, a single object,
    or an @graph wrapper.

    Parse the JSON without pre-unescaping: the blocks are valid JSON whose
    string values may legitimately contain &lt;/&gt;; we unescape per field
    afterward (title) or strip with BeautifulSoup (description).
    """
    soup = BeautifulSoup(html, "html.parser")
    raw = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (ValueError, TypeError):
            continue
        candidates = data if isinstance(data, list) else [data]
        for c in candidates:
            if not isinstance(c, dict):
                continue
            if isinstance(c.get("@graph"), list):
                candidates.extend(c["@graph"])
            if c.get("@type") == "Event":
                raw.append(c)

    events = []
    seen = set()
    for e in raw:
        start = (e.get("startDate") or "")[:16]
        if len(start) < 16:
            continue
        title = html_unescape(e.get("name") or "").strip() or None
        key = (title, start)
        if key in seen:
            continue
        seen.add(key)
        desc = None
        if e.get("description"):
            desc = BeautifulSoup(html_unescape(e["description"]), "html.parser").get_text(" ").strip() or None
        img = e.get("image")
        if isinstance(img, list):
            img = img[0] if img else None
        if isinstance(img, dict):
            img = img.get("url")
        events.append({
            "title":       title,
            "start":       start,
            "end":         (e.get("endDate") or "")[:16] or None,
            "location":    None,
            "cost":        _jsonld_price(e.get("offers")),
            "source_url":  e.get("url"),
            "performer":   None,
            "description": desc,
            "image_url":   img,
            "ticket_url":  e.get("url"),
            "is_recurring": False,
            "recurrence_note": None,
        })

    print(f"  Parsed {len(events)} events from JSON-LD (no LLM needed)")
    return events


def extract_squarespace_events(text, base_url):
    """
    Squarespace events collections (e.g. McCarthy's & Toad's /music calendar)
    are JavaScript-rendered, so the page HTML is nearly empty — but the full
    schedule is served as JSON at the collection URL + '?format=json'. Point the
    venue's collection_url at that JSON endpoint; we parse 'upcoming' directly
    (title, start/end, image, description), no LLM needed.

    startDate/endDate are epoch-millisecond UTC instants; we convert to Boston
    local with the project's fixed EDT (-4) assumption (see run_scraper.py).
    """
    try:
        data = json.loads(text)
    except ValueError:
        print("  WARNING: Squarespace JSON did not parse (is collection_url the ?format=json endpoint?)")
        return []

    root = re.match(r"https?://[^/]+", base_url)
    root = root.group(0) if root else ""
    ET = timezone(timedelta(hours=-4))

    def ms_to_local(ms):
        if not isinstance(ms, (int, float)):
            return None
        return datetime.fromtimestamp(ms / 1000, timezone.utc).astimezone(ET).strftime("%Y-%m-%dT%H:%M")

    def real_image(url):
        # Squarespace serves a system placeholder (a slash-like grey tile) for
        # events with no uploaded photo, at static1.squarespace.com/static/...
        # Only genuine uploads live on the image CDN (images.squarespace-cdn.com
        # or a /content/v1/ path). Anything else is the placeholder → drop it so
        # the front end shows no image rather than the broken slash tile.
        if not url:
            return None
        return url if ("images.squarespace-cdn.com" in url or "/content/v1/" in url) else None

    events = []
    for it in data.get("upcoming", []):
        start = ms_to_local(it.get("startDate"))
        if not start:
            continue
        full = it.get("fullUrl") or ""
        source_url = (root + full) if full.startswith("/") else (full or None)
        description = None
        if it.get("body"):
            description = BeautifulSoup(it["body"], "html.parser").get_text(" ").strip() or None
        title = html_unescape(it.get("title") or "").strip() or None
        # Some Squarespace calendars (McCarthy's & Toad) run multiple stages in
        # one complex and encode the stage as a title prefix ("Toad: ...",
        # "Upstairs - ..."). Surface it into `location` so location_keywords can
        # route each event to the right stage (same mechanism as the Middle East
        # rooms). Squarespace's own location is an unset NYC default — ignore it.
        stage_m = re.match(r"\s*(McCarthys|Toad|Upstairs)\b", title or "", re.I)
        location = stage_m.group(1) if stage_m else None
        events.append({
            "title":       title,
            "start":       start,
            "end":         ms_to_local(it.get("endDate")),
            "location":    location,
            "cost":        None,  # not in the feed
            "source_url":  source_url,
            "performer":   None,
            "description": description,
            "image_url":   real_image(it.get("assetUrl")),
            "ticket_url":  None,
            "is_recurring": False,
            "recurrence_note": None,
        })

    print(f"  Parsed {len(events)} events from Squarespace JSON (no LLM needed)")
    return events


# Aeronaut's feed carries its own event category. Map it to our taxonomy so we
# never spend an LLM call classifying (see extract_aeronaut_events). Categories
# not listed here fall through to "other". "closed" / "modified hours" are
# operational notices, not events — dropped in the extractor, not mapped here.
AERONAUT_CATEGORY_MAP = {
    "music":     "music",
    "trivia":    "trivia",
    "community": "community",
    "meetup":    "community",
    "bike":      "community",
    "party":     "community",
    "ticketed":  "other",   # mixed bag (lectures, tile club, drag) — no content signal
}


def extract_aeronaut_events(text, base_url):
    """
    Aeronaut Brewing's public calendar (WordPress/Elementor page) is JS-injected
    from a static JSON feed on their CDN. Point collection_url at that feed
    (https://d3izki9aezxlkr.cloudfront.net/public_events.json) and we parse it
    directly — no LLM for extraction OR categorization, since each item carries
    its own category (mapped via AERONAUT_CATEGORY_MAP).

    The feed covers only the Somerville taproom today but includes a venue_slug
    per item; we filter to somerville so an Allston split later won't leak in.
    Operational notices ("closed", "modified hours") are dropped.
    """
    try:
        data = json.loads(text)
    except ValueError:
        print("  WARNING: Aeronaut JSON did not parse (is collection_url the CDN feed?)")
        return []

    DROP = {"closed", "modified hours"}
    events = []
    for it in data:
        if it.get("venue_slug") != "somerville":
            continue
        cat = (it.get("category") or "").strip().lower()
        if cat in DROP:
            continue
        date = (it.get("date") or "").strip()
        start_t = (it.get("start") or "").strip()
        if not date or not start_t:
            continue
        end_t = (it.get("end") or "").strip()
        ext = (it.get("extlink") or "").strip() or None
        tickets = (it.get("tickets") or "").strip() or None
        events.append({
            "title":       html_unescape(it.get("name") or "").strip() or None,
            "start":       f"{date}T{start_t}",
            "end":         f"{date}T{end_t}" if end_t else None,
            "location":    None,
            "cost":        None,  # not in the feed
            "source_url":  ext or tickets,
            "performer":   None,
            "description": (it.get("description") or "").strip() or None,
            "image_url":   it.get("img_url") or None,
            "ticket_url":  tickets,
            "category":    AERONAUT_CATEGORY_MAP.get(cat, "other"),
            "is_recurring": False,
            "recurrence_note": None,
        })

    print(f"  Parsed {len(events)} events from Aeronaut CDN feed (no LLM needed)")
    return events


# DICE tags its events with a type ("music:dj", "comedy:standup"). Map the tag
# prefix to our taxonomy so a DICE-fed venue skips the LLM classifier entirely
# (same free-category pattern as Aeronaut). Deep Cuts is a music room, so an
# untagged/unmapped event defaults to "music" rather than "other".
DICE_TYPE_MAP = {
    "music":     "music",
    "comedy":    "comedy",
    "film":      "film",
    "food":      "food",
    "sport":     "sports",
    "sports":    "sports",
}
DICE_DEFAULT_CATEGORY = "music"


def extract_dice_events(text, base_url):
    """
    Parse a DICE partner-API events feed (schema api/v2). Point the venue's
    collection_url at the DICE endpoint and supply the widget's partner key via
    `fetch_headers` (x-api-key) in venues.py — we then parse the JSON directly,
    no LLM for extraction OR categorization (type tags map via DICE_TYPE_MAP).

    The key + promoter filter are lifted from the venue's public DICE widget
    config (DiceEventListWidget.create({...}) on its site). Because the feed IS
    the collection_url, change-detection tracks the lineup: a new/removed show
    changes the JSON hash, so the daily cache-based scrape refreshes without
    --force. If DICE rotates the partner key the feed 401/404s and the venue
    reads as broken on the health dashboard — re-lift the key from the widget.

    Cancelled/postponed shows are dropped (the widget hides them too). `date`
    is a UTC instant; we convert to naive Boston wall time with the project's
    fixed EDT (-4) assumption, matching the other extractors.
    """
    try:
        data = json.loads(text)
    except ValueError:
        print("  WARNING: DICE feed did not parse (is collection_url the partner API?)")
        return []

    ET = timezone(timedelta(hours=-4))

    def to_local(iso):
        # DICE emits e.g. '2026-07-02T23:00:00Z'
        if not iso:
            return None
        try:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        except ValueError:
            return None
        return dt.astimezone(ET).strftime("%Y-%m-%dT%H:%M")

    def category_for(ev):
        for tag in (ev.get("type_tags") or []):
            prefix = str(tag).split(":", 1)[0].strip().lower()
            if prefix in DICE_TYPE_MAP:
                return DICE_TYPE_MAP[prefix]
        return DICE_DEFAULT_CATEGORY

    DROP_STATUS = {"cancelled", "canceled", "postponed"}
    events = []
    for ev in data.get("data", []):
        if (ev.get("status") or "").strip().lower() in DROP_STATUS:
            continue
        start = to_local(ev.get("date"))
        if not start:
            continue
        title = html_unescape(ev.get("name") or "").strip() or None
        if not title:
            continue

        # event_images.landscape is the card art; fall back to portrait.
        imgs = ev.get("event_images") or {}
        image_url = (imgs.get("landscape") or imgs.get("portrait")) if isinstance(imgs, dict) else None

        # raw_description is plain text; description may carry HTML.
        desc = ev.get("raw_description") or ev.get("description") or ""
        if desc and "<" in desc:
            desc = BeautifulSoup(desc, "html.parser").get_text(" ").strip()
        desc = desc.strip() or None

        # The per-event DICE link is a stable permalink → keys make_event_id
        # (id survives title/time edits) and doubles as the ticket link.
        url = (ev.get("url") or ev.get("external_url") or "").strip() or None

        events.append({
            "title":       title,
            "start":       start,
            "end":         to_local(ev.get("date_end")),
            "location":    None,
            "cost":        None,  # DICE prices are per-ticket-type; skip
            "source_url":  url,
            "performer":   None,
            "description": desc,
            "image_url":   image_url,
            "ticket_url":  url,
            "category":    category_for(ev),
            "is_recurring": False,
            "recurrence_note": None,
        })

    print(f"  Parsed {len(events)} events from DICE feed (no LLM needed)")
    return events


def extract_tablelist_events(text, base_url):
    """
    Parse a Tablelist venue-events feed (api.tablelist.com /v1/venues/<id>/events).
    Point the venue's collection_url at that endpoint with `sort=-dateStart` +
    `limit` and supply the widget's public API key via `fetch_headers` (api-key)
    in venues.py — we then parse the JSON directly, no LLM. This is the same feed
    the venue's embedded event-carousel widget reads (Scorpion Bar Boston's
    Squarespace page loads it client-side, so the events aren't in the HTML).

    The venue id + api-key are lifted from the venue's own page: the venue id is
    the `data-venue-id` on the `<div data-tl-widget="event-carousel-widget">`, and
    the key is `TL_API_KEY` inside the widget app bundle (venues.tablelistpro.com
    /app.js). If Tablelist rotates the key the feed 401s and the venue reads as
    broken on the health dashboard — re-lift both from the widget.

    `dateStart`/`dateEnd` are UTC instants carrying the real local door/close time
    (e.g. 10pm–3am); we convert to naive Boston wall time with the project's fixed
    EDT (-4) assumption, matching the other extractors. `date` is a separate
    "night of" marquee field the widget shows — we ignore it and trust dateStart.
    We sort descending in the URL so the static endpoint always surfaces the
    upcoming shows without a dynamic date param, then drop anything older than the
    active window here so the archive isn't flooded with past club nights.
    """
    try:
        data = json.loads(text)
    except ValueError:
        print("  WARNING: Tablelist feed did not parse (is collection_url the api.tablelist.com endpoint?)")
        return []

    ET = timezone(timedelta(hours=-4))

    def to_local(iso):
        if not iso:
            return None
        try:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return None
        return dt.astimezone(ET).strftime("%Y-%m-%dT%H:%M")

    # Keep the active window (tonight + future + just-ended); drop older nights.
    # Matches ARCHIVE_LOOKBACK's spirit so we don't archive months of past shows.
    cutoff = datetime.now(ET) - timedelta(hours=36)

    events = []
    for ev in data.get("data", []):
        if ev.get("deleted"):
            continue
        # Only shows actually published to Tablelist (the widget hides the rest).
        publish = ev.get("publish") or {}
        if isinstance(publish, dict) and publish.get("tablelist") is False:
            continue

        iso_start = ev.get("dateStart")
        if not iso_start:
            continue
        try:
            start_dt = datetime.fromisoformat(iso_start.replace("Z", "+00:00")).astimezone(ET)
        except (ValueError, AttributeError):
            continue
        if start_dt < cutoff:
            continue
        start = start_dt.strftime("%Y-%m-%dT%H:%M")

        title = html_unescape(ev.get("name") or "").strip() or None
        if not title:
            continue
        # Some venues suffix the marquee act with the venue name ("Avello | The
        # Grand Boston"); strip a trailing "| <venueName>" so the card shows just
        # the act. Scorpion's feed has no suffix, so this is a no-op there.
        vname = (ev.get("venueName") or "").strip()
        if vname and title.endswith(vname):
            head = title[: -len(vname)].rstrip()
            if head.endswith("|") or head.endswith("-"):
                stripped = head[:-1].strip()
                if stripped:
                    title = stripped

        # End only if it's genuinely after start (some rows carry a stray equal
        # or earlier dateEnd).
        end = None
        end_dt_iso = ev.get("dateEnd")
        if end_dt_iso:
            try:
                end_dt = datetime.fromisoformat(end_dt_iso.replace("Z", "+00:00")).astimezone(ET)
                if end_dt > start_dt:
                    end = end_dt.strftime("%Y-%m-%dT%H:%M")
            except (ValueError, AttributeError):
                pass

        img = ev.get("primaryImage") or {}
        image_url = None
        if isinstance(img, dict):
            image_url = img.get("large") or img.get("original") or img.get("medium")

        desc = (ev.get("description") or "").strip()
        if desc and "<" in desc:
            desc = BeautifulSoup(desc, "html.parser").get_text(" ").strip()
        desc = desc or None

        # Public per-event permalink → keys make_event_id (stable across title/
        # time edits) and doubles as the ticket link.
        seo = (ev.get("seoPathname") or "").strip()
        eid = (ev.get("id") or ev.get("_id") or "").strip()
        url = (f"https://www.tablelist.com/e/{seo}" if seo
               else f"https://www.tablelist.com/events/{eid}" if eid
               else None)

        events.append({
            "title":       title,
            "start":       start,
            "end":         end,
            "location":    None,
            "cost":        None,  # Tablelist prices are per-table/ticket; skip
            "source_url":  url,
            "performer":   None,
            "description": desc,
            "image_url":   image_url,
            "ticket_url":  url,
            "category":    "music",  # DJ / nightlife feed — all music
            "is_recurring": False,
            "recurrence_note": None,
        })

    print(f"  Parsed {len(events)} events from Tablelist feed (no LLM needed)")
    return events


def extract_shopify_products(html, base_url):
    """
    For Shopify/Tailwind sites with no semantic class names.
    Finds all /products/ anchor tags and returns text chunks
    prefixed with their URL.
    """
    soup = BeautifulSoup(html, "html.parser")
    product_links = soup.find_all(
        "a", href=lambda h: h and "/products/" in h
    )

    seen = set()
    chunks = []
    for link in product_links:
        href = link.get("href", "").split("?")[0]
        if href in seen:
            continue
        seen.add(href)

        parent = link.parent
        for _ in range(4):
            if parent and len(parent.get_text(strip=True)) > len(link.get_text(strip=True)) + 10:
                break
            if parent and parent.parent:
                parent = parent.parent
            else:
                break

        text = parent.get_text(separator=" ", strip=True) if parent else link.get_text(strip=True)
        if href.startswith("/"):
            href = base_url + href

        # Pull image from within the link element itself. get_text() above
        # discards all HTML so without this the image URL is lost entirely.
        # Shopify CDN URLs are protocol-relative (//...) and carry size params
        # (?v=...&width=N) — normalize to https and strip the query string.
        image_line = ""
        img = link.find("img", src=True)
        if img:
            src = img["src"].split("?")[0]
            if src.startswith("//"):
                src = "https:" + src
            image_line = f"IMAGE: {src}\n"

        chunks.append(f"URL: {href}\n{image_line}{text}")

    print(f"  Found {len(chunks)} product links")
    return "\n\n---\n\n".join(chunks[:30])


def extract_html_page(html, venue_cfg, extra_pages=None):
    """
    For standard HTML event calendar pages.
    Strategy controlled by venue_cfg['scrape_strategy']:
    - 'html_page': collect detail-page links with surrounding context
    - 'html_full_text': send full stripped body text (for JS-paginated sites
      where all event data is in the HTML but deduplication would lose instances)
    extra_pages: list of additional HTML strings (paginated results) to merge in.
    """
    all_html_sources = [html] + (extra_pages or [])
    base_url = BASE_URL_PATTERN.match(venue_cfg["collection_url"]).group(0)
    url_fragment = venue_cfg.get("url_contains") or ""

    # Full-text mode: strip noise and return body text from all pages combined.
    # Used when the collection page is hard-paginated by JS and event times
    # are only on the collection page (not on detail pages).
    if venue_cfg.get("scrape_strategy") == "html_full_text":
        all_text_parts = []
        for source_html in all_html_sources:
            soup = BeautifulSoup(source_html, "html.parser")
            for tag in soup(["script", "style", "nav"]):
                tag.decompose()
            # Strip site-level header/footer but preserve those inside <article>
            # (some sites put event titles in <header class="entry-header"> and
            # dates/times in <footer class="entry-footer"> within each article).
            for tag in soup.find_all(["header", "footer"]):
                if not tag.find_parent("article"):
                    tag.decompose()
            # Preserve event page links in the text so the LLM can set
            # source_url on each event. Without this, get_text() strips all
            # hrefs and every event falls back to the collection URL, which
            # prevents detail-page fetching (Pass 2) and therefore images.
            if url_fragment:
                for a in soup.find_all("a", href=lambda h: h and url_fragment in h):
                    href = a.get("href", "")
                    if not href.startswith("http"):
                        href = base_url + href
                    a.insert_before(f"[EVENT_URL: {href}] ")
            all_text_parts.append(soup.get_text(separator="\n", strip=True))
        combined = "\n\n---PAGE BREAK---\n\n".join(all_text_parts)
        max_chars = venue_cfg.get("max_text_chars", 20000)
        print(f"  Using full page text ({len(combined):,} chars)")
        return combined[:max_chars]

    # Link-collection mode: find event detail links and return URL-prefixed chunks
    if venue_cfg.get("detail_pages") and url_fragment:
        seen = set()
        chunks = []
        for source_html in all_html_sources:
            source_soup = BeautifulSoup(source_html, "html.parser")
            links = source_soup.find_all("a", href=lambda h: h and url_fragment in h)
            for link in links:
                href = link.get("href", "").split("?")[0]
                if href in seen:
                    continue
                seen.add(href)
                parent = link.parent
                for _ in range(3):
                    if parent and len(parent.get_text(strip=True)) > 30:
                        break
                    if parent and parent.parent:
                        parent = parent.parent
                    else:
                        break
                text = parent.get_text(separator=" ", strip=True) if parent else link.get_text(strip=True)
                full_url = href if href.startswith("http") else base_url + href
                chunks.append(f"URL: {full_url}\n{text}")
        if chunks:
            print(f"  Found {len(chunks)} event links")
            return "\n\n---\n\n".join(chunks[:60])

    # Fallback: full page text from first page only
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    max_chars = venue_cfg.get("max_text_chars", 20000)
    print(f"  Using full page text ({len(text):,} chars)")
    return text[:max_chars]


# ============================================================
# LLM calls
# ============================================================

def clean_json(raw, report=None):
    """Normalize an LLM JSON response into parseable text. Stripping code fences
    or a prefix is routine and NOT a data-loss signal; only the truncation
    salvage branch (closing off a response cut mid-array) drops trailing events.
    When `report` is passed, that — and only that — case sets report["truncated"]
    so the health dashboard flags real loss instead of every fenced response.
    """
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        inner = lines[1:] if lines[0].startswith("```") else lines
        if inner and inner[-1].strip() == "```":
            inner = inner[:-1]
        text = "\n".join(inner).strip()

    # Fence-stripped text that parses cleanly is complete — not truncated.
    try:
        json.loads(text)
        return text
    except json.JSONDecodeError:
        pass

    # Recovery: the response was truncated mid-event. Find the last complete
    # object boundary (closing '}') and close the array — trailing events lost.
    last_close = text.rfind("}")
    if last_close != -1:
        candidate = text[:last_close + 1].rstrip().rstrip(",") + "\n]"
        try:
            json.loads(candidate)
            print(f"  WARNING: JSON was truncated — recovered {candidate.count('{') - candidate.count('}')} partial events")
            if report is not None:
                report["truncated"] = True
                report["note"] = ("extraction hit the token limit and was "
                                  "truncated — trailing events are missing")
            return candidate
        except json.JSONDecodeError:
            pass

    return text  # return as-is and let the caller handle the error


def llm_extract_events(text_chunk, venue_cfg):
    extra_instructions = venue_cfg.get("prompt_notes", "")
    strategy = venue_cfg.get("scrape_strategy", "html_page")
    current_year = datetime.now(timezone.utc).year

    if strategy == "burren_tables":
        prompt = f"""Below is structured event data extracted from The Burren's music calendar.
Each block has DATE, ROOM, TIME, TITLE, and optionally DESCRIPTION, IMAGE_URL, TICKET_URL.

Convert each block into a JSON array entry with:
- title (string — the TITLE field)
- start (ISO 8601 datetime — combine DATE and TIME, assume year {current_year})
- end (null — end times are not listed)
- location (string — the ROOM field)
- cost (string — infer from description if mentioned e.g. "FREE SHOW", else null)
- source_url (null)
- performer (string — artist name from TITLE if it's a named act, else null)
- description (string — the DESCRIPTION field, or null)
- image_url (string — the IMAGE_URL field exactly as given, or null)
- ticket_url (string — the TICKET_URL field exactly as given, or null)
- is_recurring (boolean — true for weekly sessions, trivia nights, comedy nights)
- recurrence_note (string — e.g. "Weekly on Mondays", or null)

Return ONLY the JSON array. No fences, no explanation. Start with [ end with ].

Data:
{text_chunk}"""
    else:
        # Per-event address extraction is opt-in (event_address: True) so we
        # only spend tokens on it for venues that actually host events off-site
        # (street festivals, partner spaces). Most venues never do.
        event_addr_fields = ""
        if venue_cfg.get("event_address"):
            event_addr_fields = (
                '- event_address (string — the event\'s full street address EXACTLY as shown '
                'on its card, e.g. "401 Bremen St., East Boston" or '
                '"Boston Symphony Hall - 301 Mass Ave, Boston, MA". Return null if no address '
                'is shown for the event.)\n'
                f'- event_square (string — only if event_address is given, the closest '
                f'neighborhood from this list: {", ".join(SQUARES)}. Choose one only if the '
                'address clearly falls in it; otherwise null.)\n'
            )

        prompt = f"""Below is content from the events page for {venue_cfg['name']} ({venue_cfg['collection_url']}).

Extract every upcoming IN-PERSON event and return a JSON array.
SKIP any event explicitly labeled as "live stream", "livestream", or "online only".
For each event include:
- title (string)
- start (ISO 8601 datetime, e.g. "{current_year}-06-14T19:00:00" — assume year {current_year} if not stated)
- end (ISO 8601 datetime or null)
- location (string — physical location or room name if stated, otherwise null)
{event_addr_fields}- cost (string — e.g. "Free", "$15", "$35 / Members $33", or null)
- source_url (string — the URL: line before this event's text if present, else null)
- performer (string — artist, band, or host name if explicitly stated, else null)
- description (string — 1-2 sentence summary max, or null)
- image_url (string — copy the IMAGE: line exactly if present, else null)
- ticket_url (string or null)
- is_recurring (boolean)
- recurrence_note (string or null)
{extra_instructions}
Return ONLY the JSON array. No fences, no explanation. Start with [ end with ].

Content:
{text_chunk}"""

    # High-volume calendars (e.g. The Sinclair) overflow a 6000-token response
    # and get truncated — trailing events are silently lost (the health report
    # flags this as report["truncated"]). Default higher and let a busy venue
    # raise it further via max_output_tokens in its config.
    msg = get_client().messages.create(
        model="claude-haiku-4-5",
        max_tokens=venue_cfg.get("max_output_tokens", 8000),
        messages=[{"role": "user", "content": prompt}]
    )
    return msg.content[0].text


def llm_extract_detail(url, html):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    og_image = None
    og = soup.find("meta", property="og:image:secure_url") or \
         soup.find("meta", property="og:image")
    if og:
        og_image = og.get("content")
        # WordPress generates thumbnails with a "-WIDTHxHEIGHT" suffix before
        # the extension (e.g. Open-Mic-360x380.jpg). Strip it to get the
        # full-size original.
        if og_image:
            og_image = re.sub(r"-\d+x\d+(\.\w+)$", r"\1", og_image)

    body = soup.get_text(separator="\n", strip=True)[:4000]

    prompt = f"""From this event page at {url}, extract:
- description (string — 1-2 sentence summary of the artist or event. If there is a long artist bio, summarize it in 1-2 sentences. Do NOT copy streaming/ticketing boilerplate. Return null if nothing useful.)
- cost (string — e.g. "Free", "$15", "$35 / Members $33", or null)
- ticket_url (string — external ticketing link if present, else null)
- performer (string — artist or band name if stated, else null)

Return ONLY a JSON object. No fences.

Text:
{body}"""

    msg = get_client().messages.create(
        model="claude-haiku-4-5",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}]
    )
    detail = {}
    try:
        detail = json.loads(clean_json(msg.content[0].text))
    except Exception:
        pass
    detail["image_url"] = og_image
    return detail


def llm_classify_categories(raw_events, venue_cfg=None):
    if not raw_events:
        return {}
    titles = [{"index": i, "title": e.get("title", "")} for i, e in enumerate(raw_events)]
    # A single-purpose venue (e.g. a comedy club) can set default_category so
    # generically-titled shows ("Certified Fresh", "Comedy Gold") still bucket
    # correctly instead of falling to "other".
    default = (venue_cfg or {}).get("default_category")
    hint = (f"\nAll of these events are at {venue_cfg.get('name')}, a {default} venue — "
            f"when a title is ambiguous, prefer \"{default}\".\n") if default else ""
    prompt = f"""Classify each event title into exactly one category:
{", ".join(VALID_CATEGORIES)}
{hint}

Definitions:
- music: live band, DJ, concert, open mic, ambient/lo-fi session, folk, jazz, etc.
- trivia: trivia night, quiz, bar league, Jeopardy
- comedy: stand-up, improv, comedy show
- film: movie screening, film club
- market: vendor fair, book fair, craft fair, pop-up shop, night market
- karaoke: karaoke night
- community: book club, workshop, craft class, author talk, charity event, knitting/fiber arts
- sports: game screening, World Cup, Super Bowl, watch party
- fitness: yoga, run club, workout class
- food: food truck pop-up, tasting event (NOT brewery tour — that is "community")
- other: anything else

Return ONLY a JSON array with "index" and "category" per item. No fences.

Events:
{json.dumps(titles, indent=2)}"""

    # ~25 tokens/event in the response; budget generously so high-volume venues
    # (a 150-show comedy calendar) don't get truncated and silently fall back.
    msg = get_client().messages.create(
        model="claude-haiku-4-5",
        max_tokens=max(1000, len(titles) * 30),
        messages=[{"role": "user", "content": prompt}]
    )
    try:
        items = json.loads(clean_json(msg.content[0].text))
        return {item["index"]: item["category"] for item in items}
    except Exception:
        return {}


# ============================================================
# Venue routing
# ============================================================

def resolve_venue_id(location_str, description_str, venue_cfg):
    keywords = venue_cfg.get("location_keywords", {})
    if not keywords:
        return venue_cfg["id"]
    for text in [location_str or "", description_str or ""]:
        lower = text.lower()
        for kw, vid in keywords.items():
            if kw in lower:
                return vid
    return venue_cfg["id"]


def should_split_venues(location_str, description_str, venue_cfg):
    if not venue_cfg.get("extra_venues"):
        return False
    combined = ((location_str or "") + " " + (description_str or "")).lower()
    both_signals = ["both taproom", "both location", "all location", "every location",
                    "both our", "at either"]
    return any(s in combined for s in both_signals)


def get_all_venue_ids(venue_cfg):
    ids = [venue_cfg["id"]]
    for sv in venue_cfg.get("extra_venues", []):
        ids.append(sv["id"])
    return ids


def venue_fields(vid, venue_cfg):
    # NOTE: the venue's physical address is intentionally NOT stamped here.
    # It lives in data/venues.json (display config) and is joined to the event
    # at render time via venue_id. The event's own "address" field is reserved
    # for cases where the event happens somewhere other than the venue (e.g. a
    # street festival) — see build_events. "square" here is the venue default;
    # build_events may override it with the event location's square.
    if vid == venue_cfg["id"]:
        return {
            "venue_id": vid,
            "venue": venue_cfg["name"],
            "venue_is_local": venue_cfg["is_local"],
            "square": venue_cfg["square"],
            "transit_line": venue_cfg["transit_line"],
            "transit_stop": venue_cfg["transit_stop"],
            "walk_minutes": venue_cfg["walk_minutes"],
        }
    for sv in venue_cfg.get("extra_venues", []):
        if sv["id"] == vid:
            return {
                "venue_id": vid,
                "venue": sv["name"],
                "venue_is_local": sv["is_local"],
                "square": sv.get("square", venue_cfg["square"]),
                "transit_line": sv.get("transit_line", venue_cfg["transit_line"]),
                "transit_stop": sv.get("transit_stop", venue_cfg["transit_stop"]),
                "walk_minutes": sv.get("walk_minutes", venue_cfg["walk_minutes"]),
            }
    return {}


# ============================================================
# Event location (address different from the venue's own)
# ============================================================

def _norm_addr(s):
    """Lowercase, strip everything but alphanumerics — for loose address
    comparison that ignores punctuation/spacing differences."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def event_specific_address(raw_event, venue_cfg):
    """Return the event's own address ONLY when the venue opts in
    (event_address: True) AND the scraped address differs from the venue's
    home address. Otherwise None — meaning "this event is at the venue", and
    the front end falls back to the venue address from data/venues.json.

    The comparison is substring-based so "282 Meridian St." and
    "282 Meridian St., East Boston" are treated as the same place, while
    "401 Bremen St." or "Boston Symphony Hall" are recognized as elsewhere.
    """
    if not venue_cfg.get("event_address"):
        return None
    addr = (raw_event.get("event_address") or "").strip()
    if not addr:
        return None
    e, v = _norm_addr(addr), _norm_addr(venue_cfg.get("address"))
    if not e or not v or e in v or v in e:
        return None
    return addr


# ============================================================
# Event assembly
# ============================================================

def _title_slug(title):
    return "".join(c if c.isalnum() else "-" for c in (title or "").lower()).strip("-")


def _start_token(start):
    """Compact, stable token derived from an event's start datetime — the basis
    for a title-free event id. `YYYYMMDD`, plus `THHMM` when the start carries a
    time (ISO `YYYY-MM-DDTHH:MM...`). Empty string when start is missing, so
    make_event_id knows there's no stable slot to key on."""
    s = (start or "").strip()
    if not s:
        return ""
    token = s[:10].replace("-", "")
    if "T" in s and len(s) >= 16:
        token += "T" + s[11:16].replace(":", "")
    return token


def make_event_id(vid, start, title=None, source_url=None, disambiguate=False):
    """Stable per-event id. This id IS the event's shareable identity — the
    front end uses it as `location.hash`, the share URL and the .ics `UID` — so
    it must derive from stable identity, never the volatile title (a title edit
    would otherwise mint a new id == a broken bookmark). Precedence:

      1. a genuine per-event permalink (`source_url`), hashed — survives title
         AND time edits. build_events passes it only when the URL is unique in
         the batch and isn't the shared calendar page.
      2. otherwise `venue_id + start`. Splitting rooms into distinct venue_ids
         (Middle East, Burren) yields one event per (venue_id, start), so this is
         unique WITHOUT the title — a rename no longer changes the id/URL.
      3. the title only as a last-resort tiebreaker (`disambiguate=True`), for
         genuine same-slot collisions like Aeronaut's parallel programming.
         build_events sets this only for the (venue_id, start) slots that
         actually collide, so unrelated title jitter never triggers it.

    Degrades to the title slug when start is missing — with no stable slot to
    key on, that's all we have, and it keeps distinct start-less events apart."""
    if source_url:
        h = hashlib.md5(source_url.encode()).hexdigest()[:10]
        return f"{vid}-{h}"
    token = _start_token(start)
    if not token:
        slug = _title_slug(title)[:30]
        return f"{vid}-{slug}" if slug else vid
    base = f"{vid}-{token}"
    if disambiguate:
        slug = _title_slug(title)[:20]
        if slug:
            base = f"{base}-{slug}"
    return base


def is_private_event(title, description):
    """True when an event is a private/closed-to-the-public booking that the
    main feed should hide. Deliberately narrow: the title says "private event"
    (e.g. the Lilypad's "** Private Event **") or the description explicitly
    states the venue is closed to the public. A passing mention of private-event
    booking in a footer ("Book the Lilypad for your next private event") does NOT
    trigger this — that phrasing lacks both signals.
    """
    if "private event" in (title or "").lower():
        return True
    if "closed to the public" in (description or "").lower():
        return True
    return False


def build_events(raw_events, category_map, detail_map, venue_cfg):
    results = []
    # A source_url is a usable per-event permalink only when it's unique within
    # this venue's batch and isn't the shared collection/calendar page. Venues
    # like the Burren stamp the same calendar URL on every event (useless as a
    # key); Toad/McCarthy's give each show its own URL (a stable key). Count
    # occurrences up front so make_event_id can prefer the permalink when safe.
    from collections import Counter
    _url_counts = Counter(
        (e.get("source_url") or "").strip()
        for e in raw_events if (e.get("source_url") or "").strip()
    )
    for i, e in enumerate(raw_events):
        location_str = e.get("location") or ""
        source_url = e.get("source_url") or venue_cfg["collection_url"]
        detail = detail_map.get(source_url, {})

        description = detail.get("description") or e.get("description")
        image_url = detail.get("image_url") or e.get("image_url")
        ticket_url = detail.get("ticket_url") or e.get("ticket_url")
        cost = detail.get("cost") or e.get("cost")
        performer = detail.get("performer") or e.get("performer")

        if should_split_venues(location_str, description, venue_cfg):
            venue_ids = get_all_venue_ids(venue_cfg)
        else:
            venue_ids = [resolve_venue_id(location_str, description, venue_cfg)]

        # Fall back to the venue's default_category (e.g. a comedy club) rather
        # than "other" when the classifier didn't label this event.
        fallback = venue_cfg.get("default_category") or "other"
        # Prefer a category the extractor already resolved from a structured feed
        # (e.g. aeronaut_events); otherwise use the LLM classifier's result.
        category = e.get("category") or category_map.get(i, fallback)
        if category not in VALID_CATEGORIES:
            category = fallback if fallback in VALID_CATEGORIES else "other"

        # An event whose address differs from the venue's home address (e.g. a
        # street festival). None for the common case of "at the venue", where
        # the front end joins to the venue address via venue_id. The square
        # follows the event location when we recognize it, so the front-end
        # filter buckets the event where it actually happens, not where the
        # organizing venue sits.
        addr = event_specific_address(e, venue_cfg)
        event_square = None
        if addr:
            sq = (e.get("event_square") or "").strip()
            if sq in SQUARES:
                event_square = sq

        # Private/closed-to-the-public bookings (e.g. the Lilypad's
        # "** Private Event **") aren't attendable, so the front end hides them
        # from the main feed. We flag rather than drop so a venue view can still
        # show "closed tonight". Detection is deliberately narrow — the title
        # phrase or an explicit "closed to the public" line — so an event that
        # merely mentions private bookings in a footer isn't caught.
        private = is_private_event(e.get("title"), description)

        for vid in venue_ids:
            fields = venue_fields(vid, venue_cfg)
            # Apply image_map for venues with known static image URLs
            # keyed by event title (used when images aren't in the HTML)
            resolved_image = image_url
            if not resolved_image:
                image_map = venue_cfg.get("image_map", {})
                title = e.get("title", "")
                # Try exact match first, then check if any key is in the title
                resolved_image = image_map.get(title)
                if not resolved_image:
                    for key, url in image_map.items():
                        if key in title:
                            resolved_image = url
                            break

            # Prefer the permalink as the id basis when this event has a real,
            # unique per-event URL; otherwise fall back to the title-slug key.
            raw_url = (e.get("source_url") or "").strip()
            permalink = raw_url if (
                raw_url and raw_url != venue_cfg["collection_url"]
                and _url_counts[raw_url] == 1
            ) else None
            results.append({
                "id": None,        # assigned in the collision pass below
                "_permalink": permalink,   # scratch, popped before return
                "title": e.get("title"),
                **fields,
                "address": addr,
                "square": event_square or fields["square"],
                "start": e.get("start"),
                "end": e.get("end"),
                "category": category,
                "cost": cost,
                "performer": performer,
                "performer_is_local": None,
                "sponsored": False,
                "sponsor": None,
                "description": description,
                "image_url": resolved_image,
                "ticket_url": ticket_url,
                "is_recurring": e.get("is_recurring", False),
                "recurrence_note": e.get("recurrence_note"),
                "private": private,
                "source_url": source_url,
                "last_scraped": datetime.now(timezone.utc).isoformat(),
            })

    # Assign ids after all rows exist, so we can spot genuine (venue_id, start)
    # collisions among the permalink-less events and append a title tiebreaker
    # to ONLY those. Everyone else keeps a clean title-free id, so a title edit
    # never changes the id (== the event's shareable URL / .ics UID).
    slot_counts = Counter(
        (r["venue_id"], _start_token(r["start"]))
        for r in results if not r["_permalink"]
    )
    for r in results:
        permalink = r.pop("_permalink")
        disambiguate = (not permalink
                        and slot_counts[(r["venue_id"], _start_token(r["start"]))] > 1)
        r["id"] = make_event_id(r["venue_id"], r["start"], r["title"],
                                source_url=permalink, disambiguate=disambiguate)
    return results


# ============================================================
# Main scrape function — called by the runner
# ============================================================

def scrape_venue(venue_cfg, cache, verbose=True, force=False, report=None):
    # `report` (optional mutable dict) collects health signals that don't
    # survive into events.json — a truncated/failed extraction, a warning note —
    # so the runner can write them to scrape_health.json for the dashboard.
    if report is None:
        report = {}
    name = venue_cfg["name"]
    collection_url = venue_cfg["collection_url"]
    base_url = BASE_URL_PATTERN.match(collection_url).group(0)

    if verbose:
        print(f"\n{'='*60}")
        print(f"Scraping: {name}")
        print(f"  {collection_url}")

    # --- Fetch collection page (conditional) ---
    fetch_headers = venue_cfg.get("fetch_headers")
    if force:
        # Bypass cache entirely — fetch fresh without conditional headers
        html = fetch_page(collection_url, cache=None, extra_headers=fetch_headers)
        changed = True
        # Still update the cache entry with the fresh content
        if cache is not None:
            new_hash = content_hash(html)
            cache[collection_url] = {
                **cache.get(collection_url, {}),
                "content_hash": new_hash,
                "last_fetched": datetime.now(timezone.utc).isoformat(),
                "last_changed": datetime.now(timezone.utc).isoformat(),
            }
    else:
        html, changed = fetch_page(collection_url, cache=cache, extra_headers=fetch_headers)

    if not changed:
        print(f"  CACHE HIT — collection page unchanged, skipping LLM passes")
        print(f"  (run with --force to scrape anyway)")
        return None

    if verbose:
        print(f"  Got {len(html):,} bytes (page changed)")

    # --- Fetch extra pages for paginated collections ---
    extra_pages = []
    max_extra_pages = venue_cfg.get("max_pages", 1) - 1
    if max_extra_pages > 0:
        for page_num in range(2, max_extra_pages + 2):
            page_url = f"{collection_url}?paged={page_num}"
            try:
                page_html, _ = fetch_page(page_url, cache=cache)
                if not page_html:
                    break
                # Stop if this page has no new event links
                soup_check = BeautifulSoup(page_html, "html.parser")
                url_frag = venue_cfg.get("url_contains", "")
                if url_frag and not soup_check.find("a", href=lambda h: h and url_frag in h):
                    break
                extra_pages.append(page_html)
                if verbose:
                    print(f"  Fetched page {page_num}")
                time.sleep(0.5)
            except Exception:
                break

    # --- Extract events ---
    strategy = venue_cfg.get("scrape_strategy", "html_page")

    if strategy == "burren_tables":
        # Direct HTML parse — no LLM needed for extraction
        raw_events = extract_burren_tables(html, base_url)
        if verbose:
            print(f"  Pass 1: {len(raw_events)} events (parsed directly, no LLM)")
    elif strategy == "wix_events":
        # Direct JSON parse from Wix appsWarmupData — no LLM needed
        raw_events = extract_wix_events(html, base_url)
        if verbose:
            print(f"  Pass 1: {len(raw_events)} events (parsed directly, no LLM)")
    elif strategy == "gcal_ics":
        # Direct parse of a public Google Calendar ICS feed (Village Social) —
        # no LLM, no Playwright. collection_url is the .../basic.ics feed.
        raw_events = extract_gcal_ics(html, base_url)
        if verbose:
            print(f"  Pass 1: {len(raw_events)} events (parsed directly, no LLM)")
    elif strategy == "seatengine":
        # Direct JSON-LD parse from a SeatEngine box-office site — no LLM needed
        raw_events = extract_seatengine(html, base_url)
        if verbose:
            print(f"  Pass 1: {len(raw_events)} events (parsed directly, no LLM)")
    elif strategy == "squarespace_events":
        # Direct parse of a Squarespace events collection (?format=json) — no LLM
        raw_events = extract_squarespace_events(html, base_url)
        if verbose:
            print(f"  Pass 1: {len(raw_events)} events (parsed directly, no LLM)")
    elif strategy == "jsonld_events":
        # Generic schema.org Event JSON-LD parse — no LLM
        raw_events = extract_jsonld_events(html, base_url)
        if verbose:
            print(f"  Pass 1: {len(raw_events)} events (parsed directly, no LLM)")
    elif strategy == "aeronaut_events":
        # Direct parse of Aeronaut's CDN JSON feed — no LLM, native categories
        raw_events = extract_aeronaut_events(html, base_url)
        if verbose:
            print(f"  Pass 1: {len(raw_events)} events (parsed directly, no LLM)")
    elif strategy == "dice_events":
        # Direct parse of a DICE partner-API feed (Deep Cuts) — no LLM, native
        # categories from DICE type tags.
        raw_events = extract_dice_events(html, base_url)
        if verbose:
            print(f"  Pass 1: {len(raw_events)} events (parsed directly, no LLM)")
    elif strategy == "tablelist_events":
        # Direct parse of a Tablelist venue-events API feed (Scorpion Bar) — no
        # LLM; the DJ/nightlife feed is all "music".
        raw_events = extract_tablelist_events(html, base_url)
        if verbose:
            print(f"  Pass 1: {len(raw_events)} events (parsed directly, no LLM)")
    elif strategy == "mideast_events":
        # Direct parse of the Middle East's TicketWeb event cards — no LLM.
        # Room-per-card routes to sub-venues via location_keywords.
        raw_events = extract_mideast_events(html, base_url)
        if verbose:
            print(f"  Pass 1: {len(raw_events)} events (parsed directly, no LLM)")
    elif strategy == "aeg_events":
        # Direct parse of an AEG Presents / AXS venue template (The Sinclair) —
        # no LLM, deterministic titles, stable permalink ids.
        raw_events = extract_aeg_events(html, base_url)
        if verbose:
            print(f"  Pass 1: {len(raw_events)} events (parsed directly, no LLM)")
    elif strategy == "em_events":
        # Direct parse of a WordPress Events Manager template (Arts at the
        # Armory) — no LLM, deterministic titles, stable permalink ids.
        raw_events = extract_events_manager(html, base_url)
        if verbose:
            print(f"  Pass 1: {len(raw_events)} events (parsed directly, no LLM)")
    elif strategy == "crystal_events":
        # Direct parse of Crystal Ballroom's WordPress event cards — no LLM,
        # deterministic titles, stable permalink ids.
        raw_events = extract_crystal_events(html, base_url)
        if verbose:
            print(f"  Pass 1: {len(raw_events)} events (parsed directly, no LLM)")
    elif strategy == "sally_events":
        # Direct parse of Sally O'Brien's prose calendar — no LLM, deterministic
        # titles (no permalinks, so ids stay title-based but stable run to run).
        raw_events = extract_sally_events(html, base_url)
        if verbose:
            print(f"  Pass 1: {len(raw_events)} events (parsed directly, no LLM)")
    else:
        # Text extraction + LLM
        if strategy == "shopify_products":
            text_chunk = extract_shopify_products(html, base_url)
        else:
            text_chunk = extract_html_page(html, venue_cfg, extra_pages=extra_pages)

        if verbose:
            print(f"  Sending {len(text_chunk):,} chars to Pass 1")

        raw_json = llm_extract_events(text_chunk, venue_cfg)
        # clean_json sets report["truncated"] only when it salvages a genuinely
        # truncated array (trailing events lost) — not for routine fence/prefix
        # stripping, which is complete data.
        cleaned = clean_json(raw_json, report=report)
        try:
            raw_events = json.loads(cleaned)
        except Exception as err:
            print(f"  ERROR: Pass 1 JSON parse failed: {err}")
            print(cleaned[:300])
            report["error"] = f"Pass 1 JSON parse failed: {err}"
            return []

        if verbose:
            print(f"  Pass 1: found {len(raw_events)} events")

    # --- Pass 2: detail pages (conditional per URL) ---
    detail_map = {}
    if venue_cfg.get("detail_pages"):
        # In html_full_text mode, source_urls come from what the LLM extracted.
        # In link-collection mode, they come from the HTML links.
        # Either way, deduplicate and fetch.
        source_urls = list({
            e["source_url"] for e in raw_events
            if e.get("source_url") and e["source_url"].startswith("http")
               and e["source_url"] != collection_url
        })
        if verbose:
            print(f"  Pass 2: checking {len(source_urls)} detail pages...")

        skipped = 0
        fetched = 0
        for url in source_urls:
            try:
                if force:
                    detail_html = fetch_page(url, cache=None)
                    detail_changed = True
                else:
                    detail_html, detail_changed = fetch_page(url, cache=cache)
                if not detail_changed:
                    # Page unchanged — but we still need its data from
                    # the last successful scrape. Return empty dict here;
                    # the runner's merge logic will preserve the old event.
                    detail_map[url] = {}
                    skipped += 1
                    if verbose:
                        print(f"    SKIP (unchanged) {url}")
                else:
                    detail_map[url] = llm_extract_detail(url, detail_html)
                    fetched += 1
                    if verbose:
                        print(f"    FETCH {url}")
                time.sleep(0.3)
            except Exception as ex:
                print(f"    FAILED {url}: {ex}")
                detail_map[url] = {}

        if verbose:
            print(f"  Pass 2: fetched {fetched}, skipped {skipped} unchanged")

    # --- Pass 3: classify categories ---
    # Skip entirely when the extractor already assigned every event a category
    # from a structured feed (e.g. aeronaut_events) — no LLM call needed.
    if raw_events and all(e.get("category") for e in raw_events):
        if verbose:
            print(f"  Pass 3: skipped (categories from feed)")
        category_map = {}
    else:
        if verbose:
            print(f"  Pass 3: classifying categories...")
        category_map = llm_classify_categories(raw_events, venue_cfg)
    if verbose:
        for i, cat in category_map.items():
            title = raw_events[i].get("title", "?")[:40]
            print(f"    [{i:02d}] {title:<40} -> {cat}")

    # --- Assemble ---
    events = build_events(raw_events, category_map, detail_map, venue_cfg)
    if verbose:
        print(f"  Done: {len(events)} events assembled")

    return events
