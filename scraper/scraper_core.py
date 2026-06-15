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
from datetime import datetime, timezone

client = anthropic.Anthropic()

VALID_CATEGORIES = [
    "music", "trivia", "comedy", "film", "market",
    "karaoke", "community", "sports", "fitness", "food", "other"
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

def fetch_page(url, cache=None, retries=2):
    """
    Fetch a page. If cache is provided:
    - Sends If-None-Match / If-Modified-Since headers when available.
    - Returns (html, changed) where changed=False means skip LLM.
    If cache is None, behaves like the old fetch_page and returns html only.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }

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
    Convert "MONDAY JUNE 8" + "8:30pm:" into "2026-06-08T20:30:00".
    Handles ranges like "3-6pm:" by using the start time.
    Handles multi-time strings like "10:30am, 12:30pm, ..." by using the first.
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

    return f"2026-{month_num:02d}-{day_num:02d}T{t.hour:02d}:{t.minute:02d}:00"


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
            for tag in soup(["script", "style", "nav", "footer", "header"]):
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

def clean_json(raw):
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        inner = lines[1:] if lines[0].startswith("```") else lines
        if inner and inner[-1].strip() == "```":
            inner = inner[:-1]
        text = "\n".join(inner).strip()

    # Try parsing as-is first
    try:
        json.loads(text)
        return text
    except json.JSONDecodeError:
        pass

    # Recovery: if the response was truncated mid-event, try to find
    # the last complete object boundary (closing '}') and close the array.
    last_close = text.rfind("}")
    if last_close != -1:
        candidate = text[:last_close + 1].rstrip().rstrip(",") + "\n]"
        try:
            json.loads(candidate)
            print(f"  WARNING: JSON was truncated — recovered {candidate.count('{') - candidate.count('}')} partial events")
            return candidate
        except json.JSONDecodeError:
            pass

    return text  # return as-is and let the caller handle the error


def llm_extract_events(text_chunk, venue_cfg):
    extra_instructions = venue_cfg.get("prompt_notes", "")
    strategy = venue_cfg.get("scrape_strategy", "html_page")

    if strategy == "burren_tables":
        prompt = f"""Below is structured event data extracted from The Burren's music calendar.
Each block has DATE, ROOM, TIME, TITLE, and optionally DESCRIPTION, IMAGE_URL, TICKET_URL.

Convert each block into a JSON array entry with:
- title (string — the TITLE field)
- start (ISO 8601 datetime — combine DATE and TIME, assume year 2026)
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
        prompt = f"""Below is content from the events page for {venue_cfg['name']} ({venue_cfg['collection_url']}).

Extract every upcoming IN-PERSON event and return a JSON array.
SKIP any event explicitly labeled as "live stream", "livestream", or "online only".
For each event include:
- title (string)
- start (ISO 8601 datetime, e.g. "2026-06-14T19:00:00" — assume year 2026 if not stated)
- end (ISO 8601 datetime or null)
- location (string — physical location or room name if stated, otherwise null)
- cost (string — e.g. "Free", "$15", "$35 / Members $33", or null)
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

    msg = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=6000,
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

    msg = client.messages.create(
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


def llm_classify_categories(raw_events):
    if not raw_events:
        return {}
    titles = [{"index": i, "title": e.get("title", "")} for i, e in enumerate(raw_events)]
    prompt = f"""Classify each event title into exactly one category:
{", ".join(VALID_CATEGORIES)}

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

    msg = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1000,
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
    if vid == venue_cfg["id"]:
        return {
            "venue": venue_cfg["name"],
            "venue_is_local": venue_cfg["is_local"],
            "address": venue_cfg["address"],
            "square": venue_cfg["square"],
            "transit_line": venue_cfg["transit_line"],
            "transit_stop": venue_cfg["transit_stop"],
            "walk_minutes": venue_cfg["walk_minutes"],
        }
    for sv in venue_cfg.get("extra_venues", []):
        if sv["id"] == vid:
            return {
                "venue": sv["name"],
                "venue_is_local": sv["is_local"],
                "address": sv["address"],
                "square": sv.get("square", venue_cfg["square"]),
                "transit_line": sv.get("transit_line", venue_cfg["transit_line"]),
                "transit_stop": sv.get("transit_stop", venue_cfg["transit_stop"]),
                "walk_minutes": sv.get("walk_minutes", venue_cfg["walk_minutes"]),
            }
    return {}


# ============================================================
# Event assembly
# ============================================================

def make_event_id(vid, start, title):
    slug = "".join(c if c.isalnum() else "-" for c in title.lower()).strip("-")
    date = (start or "")[:10].replace("-", "")
    return f"{vid}-{date}-{slug[:30]}"


def build_events(raw_events, category_map, detail_map, venue_cfg):
    results = []
    for i, e in enumerate(raw_events):
        location_str = e.get("location") or ""
        source_url = e.get("source_url") or venue_cfg["collection_url"]
        detail = detail_map.get(source_url, {})

        description = detail.get("description") or e.get("description")
        image_url = detail.get("image_url") or e.get("image_url")
        ticket_url = detail.get("ticket_url")
        cost = detail.get("cost") or e.get("cost")
        performer = detail.get("performer") or e.get("performer")

        if should_split_venues(location_str, description, venue_cfg):
            venue_ids = get_all_venue_ids(venue_cfg)
        else:
            venue_ids = [resolve_venue_id(location_str, description, venue_cfg)]

        category = category_map.get(i, "other")
        if category not in VALID_CATEGORIES:
            category = "other"

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

            results.append({
                "id": make_event_id(vid, e.get("start"), e.get("title", "event")),
                "title": e.get("title"),
                **fields,
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
                "source_url": source_url,
                "last_scraped": datetime.now(timezone.utc).isoformat(),
            })
    return results


# ============================================================
# Main scrape function — called by the runner
# ============================================================

def scrape_venue(venue_cfg, cache, verbose=True, force=False):
    name = venue_cfg["name"]
    collection_url = venue_cfg["collection_url"]
    base_url = BASE_URL_PATTERN.match(collection_url).group(0)

    if verbose:
        print(f"\n{'='*60}")
        print(f"Scraping: {name}")
        print(f"  {collection_url}")

    # --- Fetch collection page (conditional) ---
    if force:
        # Bypass cache entirely — fetch fresh without conditional headers
        html = fetch_page(collection_url, cache=None)
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
        html, changed = fetch_page(collection_url, cache=cache)

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
    else:
        # Text extraction + LLM
        if strategy == "shopify_products":
            text_chunk = extract_shopify_products(html, base_url)
        else:
            text_chunk = extract_html_page(html, venue_cfg, extra_pages=extra_pages)

        if verbose:
            print(f"  Sending {len(text_chunk):,} chars to Pass 1")

        raw_json = llm_extract_events(text_chunk, venue_cfg)
        cleaned = clean_json(raw_json)
        try:
            raw_events = json.loads(cleaned)
        except Exception as err:
            print(f"  ERROR: Pass 1 JSON parse failed: {err}")
            print(cleaned[:300])
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
    if verbose:
        print(f"  Pass 3: classifying categories...")
    category_map = llm_classify_categories(raw_events)
    if verbose:
        for i, cat in category_map.items():
            title = raw_events[i].get("title", "?")[:40]
            print(f"    [{i:02d}] {title:<40} -> {cat}")

    # --- Assemble ---
    events = build_events(raw_events, category_map, detail_map, venue_cfg)
    if verbose:
        print(f"  Done: {len(events)} events assembled")

    return events
