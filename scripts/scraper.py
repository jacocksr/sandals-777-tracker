"""
sandals_777_scraper.py  —  v2
==============================
Sandals' suite-deals page is a JavaScript SPA that actively detects
headless browsers. This version uses three strategies in sequence:

  Strategy A: Intercept the underlying API call the page makes
              (fastest and most reliable if it works)
  Strategy B: Stealth Playwright with human-like behaviour
  Strategy C: Parse the Sandals blog / travel-agency partner sites
              that re-publish the deals in plain HTML each week

The first strategy that returns 7 (or any) deals wins.
"""

import json, re, time, random
from datetime import datetime, timezone, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
import requests
from bs4 import BeautifulSoup

# ── PATHS ──────────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent.parent
DATA_DIR   = BASE_DIR / "docs" / "data"
DEALS_FILE = DATA_DIR / "deals.json"
HIST_FILE  = DATA_DIR / "history.json"
DATA_DIR.mkdir(parents=True, exist_ok=True)

SANDALS_URL = "https://www.sandals.com/specials/suite-deals/"

# ── RESORT LOOKUP ──────────────────────────────────────────────────────────────
RESORT_MAP = {
    "SGO": {"name": "Sandals Ochi",                 "location": "Ocho Rios, Jamaica"},
    "SSV": {"name": "Sandals Saint Vincent",         "location": "St. Vincent"},
    "SLU": {"name": "Sandals Regency La Toc",        "location": "Castries, Saint Lucia"},
    "SRB": {"name": "Sandals Royal Bahamian",        "location": "Nassau, Bahamas"},
    "SRP": {"name": "Sandals Royal Plantation",      "location": "Ocho Rios, Jamaica"},
    "SNG": {"name": "Sandals Negril",                "location": "Negril, Jamaica"},
    "SCR": {"name": "Sandals Royal Curacao",         "location": "Willemstad, Curacao"},
    "SBR": {"name": "Sandals Barbados",              "location": "Christ Church, Barbados"},
    "SKJ": {"name": "Sandals South Coast",           "location": "Whitehouse, Jamaica"},
    "SML": {"name": "Sandals Montego Bay",           "location": "Montego Bay, Jamaica"},
    "SDL": {"name": "Sandals Dunns River",           "location": "Ocho Rios, Jamaica"},
    "SSN": {"name": "Sandals Grenada",               "location": "Point Saline, Grenada"},
    "SST": {"name": "Sandals Grande St. Lucian",     "location": "Gros Islet, Saint Lucia"},
    "SAB": {"name": "Sandals Grande Antigua",         "location": "St. John's, Antigua"},
    "SMB": {"name": "Sandals Emerald Bay",           "location": "Exuma, Bahamas"},
    "SPR": {"name": "Sandals Royal Barbados",        "location": "Christ Church, Barbados"},
}

RESORT_COLORS = {
    "SGO":"#1a5c6a","SSV":"#3a5878","SLU":"#5a4878","SRB":"#2a6858",
    "SRP":"#785848","SNG":"#4a7848","SCR":"#1a6878","SBR":"#3a7868",
    "SKJ":"#6a4858","SML":"#487858","SDL":"#284878","SSN":"#784838",
    "SST":"#2a5868","SAB":"#5a6848","SMB":"#384868","SPR":"#685838",
}

# ── HELPERS ────────────────────────────────────────────────────────────────────

def make_deal(i, code, room_code, room_name, travel="", price_from=None, price_was=None):
    info = RESORT_MAP.get(code, {"name": f"Sandals {code}", "location": "Caribbean"})
    return {
        "id": i,
        "resortCode": code,
        "resort": info["name"],
        "location": info["location"],
        "imgColor": RESORT_COLORS.get(code, "#1a5c6a"),
        "roomCode": room_code,
        "roomName": room_name,
        "discount": "7%+ off",
        "travelWindow": travel,
        "priceFrom": price_from,
        "priceWas": price_was,
    }


def get_week_label():
    now = datetime.now(timezone.utc)
    days_since_wed = (now.weekday() - 2) % 7
    start = (now - timedelta(days=days_since_wed)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=6)
    return f"{start.strftime('%b %-d')} – {end.strftime('%b %-d')}, {end.year}"


# ══════════════════════════════════════════════════════════════════════════════
#  STRATEGY A  —  Intercept the XHR / fetch calls the SPA makes
#  Sandals' React app calls an internal API to get deal data. If we can
#  capture that network response, we get clean structured JSON directly.
# ══════════════════════════════════════════════════════════════════════════════

def strategy_a_intercept() -> list[dict]:
    """
    Sandals' page fires one request per deal room using URLs like:
      /specials/suite-deals/?categoryCode=VF&_rsc=rbniq
    The _rsc suffix means React Server Component — a streaming text format.
    We capture ALL such responses, then mine them for room data.
    """
    print("[A] Trying network interception (RSC-aware)...")

    # Store (categoryCode, raw_body) pairs
    captured = []

    def handle_response(response):
        url = response.url
        # Target the per-room categoryCode requests specifically
        if "suite-deals" in url and ("categoryCode" in url or "_rsc" in url):
            try:
                body = response.body()
                text = body.decode("utf-8", errors="ignore")
                if len(text) > 100:
                    # Pull out the categoryCode if present
                    m = re.search(r"categoryCode=([A-Z0-9]+)", url)
                    cat = m.group(1) if m else "UNKNOWN"
                    print(f"[A] Captured RSC response: categoryCode={cat} ({len(text)} bytes)")
                    captured.append((cat, text))
            except Exception as e:
                print(f"[A] Error reading response: {e}")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox",
                  "--disable-blink-features=AutomationControlled"]
        )
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 900},
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
        )
        page = ctx.new_page()
        page.on("response", handle_response)

        try:
            page.goto(SANDALS_URL, wait_until="domcontentloaded", timeout=35_000)
            # Scroll to trigger lazy-loaded deal cards
            for _ in range(6):
                page.mouse.wheel(0, 500)
                time.sleep(random.uniform(0.5, 1.0))
            page.wait_for_timeout(6000)
        except PWTimeout:
            print("[A] Page load timed out — using whatever was captured")

        browser.close()

    if not captured:
        print("[A] No RSC responses captured")
        return []

    deals = _parse_rsc_responses(captured)
    print(f"[A] Extracted {len(deals)} deals from {len(captured)} RSC responses")
    return deals


def _parse_rsc_responses(captured: list[tuple]) -> list[dict]:
    """
    React Server Component payloads look like:
      1:{"key":"value","roomName":"...","resortCode":"SGO",...}
      2:["$","div",null,{"children":...}]
    We extract JSON objects from each line and hunt for room/resort fields.
    """
    deals = []
    seen_codes = set()

    for cat_code, text in captured:
        if cat_code == "UNKNOWN":
            continue

        # Split into lines — each line in RSC is a self-contained chunk
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue

            # RSC lines start with  "N:" where N is a number
            # Strip the leading number prefix to get the JSON part
            json_part = re.sub(r"^\d+:", "", line).strip()
            if not json_part.startswith("{") and not json_part.startswith("["):
                continue

            try:
                obj = json.loads(json_part)
            except Exception:
                # Not valid JSON on its own — try to find embedded JSON objects
                # by scanning for {"resortCode": patterns
                matches = re.findall(r'\{[^{}]{20,}\}', json_part)
                for m in matches:
                    try:
                        obj = json.loads(m)
                        deal = _extract_deal_from_obj(obj, cat_code, len(deals)+1)
                        if deal and deal["resortCode"] not in seen_codes:
                            seen_codes.add(deal["resortCode"])
                            deals.append(deal)
                    except Exception:
                        pass
                continue

            deal = _extract_deal_from_obj(obj, cat_code, len(deals)+1)
            if deal and deal["resortCode"] not in seen_codes:
                seen_codes.add(deal["resortCode"])
                deals.append(deal)

            # Also recurse into nested dicts/lists to find embedded room data
            if isinstance(obj, (dict, list)):
                extras = _deep_search_rsc(obj, cat_code, len(deals))
                for d in extras:
                    if d["resortCode"] not in seen_codes:
                        seen_codes.add(d["resortCode"])
                        d["id"] = len(deals) + 1
                        deals.append(d)

        if len(deals) >= 7:
            break

    return deals[:7]


def _extract_deal_from_obj(obj: dict, cat_code: str, idx: int):
    """Try to build a deal from a parsed JSON object."""
    if not isinstance(obj, dict):
        return None

    # Look for resort code in various field names
    resort_code = (obj.get("resortCode") or obj.get("resort_code") or
                   obj.get("propertyCode") or obj.get("property_code") or
                   obj.get("hotelCode") or "")

    # Also check if any known resort code appears anywhere in the stringified obj
    if not resort_code:
        obj_str = json.dumps(obj)
        for code in RESORT_MAP:
            if f'"{code}"' in obj_str or f"'{code}'" in obj_str:
                resort_code = code
                break

    if not resort_code or resort_code not in RESORT_MAP:
        return None

    room_code = (obj.get("roomCode") or obj.get("room_code") or
                 obj.get("categoryCode") or obj.get("code") or cat_code or "")
    room_name = (obj.get("roomName") or obj.get("room_name") or
                 obj.get("roomDescription") or obj.get("name") or
                 obj.get("description") or obj.get("title") or "")
    travel = str(obj.get("travelWindow") or obj.get("travel_window") or
                 obj.get("dates") or obj.get("blackoutDates") or "")
    price_from = obj.get("price") or obj.get("priceFrom") or obj.get("from_price")
    price_was  = obj.get("originalPrice") or obj.get("wasPrice") or obj.get("rack_rate")

    if not room_name:
        return None

    return make_deal(idx, resort_code, room_code, room_name, travel,
                     price_from, price_was)


def _deep_search_rsc(obj, cat_code: str, current_count: int) -> list[dict]:
    """Recursively search nested structures for deal objects."""
    results = []
    if current_count >= 7:
        return results

    if isinstance(obj, dict):
        d = _extract_deal_from_obj(obj, cat_code, current_count + len(results) + 1)
        if d:
            results.append(d)
        for v in obj.values():
            results.extend(_deep_search_rsc(v, cat_code, current_count + len(results)))
    elif isinstance(obj, list):
        for item in obj:
            results.extend(_deep_search_rsc(item, cat_code, current_count + len(results)))

    return results


# ══════════════════════════════════════════════════════════════════════════════
#  STRATEGY D  —  Direct HTTP requests to the categoryCode endpoints
#  The log showed Sandals fires requests like:
#    /specials/suite-deals/?categoryCode=VF&_rsc=rbniq
#  We call these directly with requests (no browser needed).
# ══════════════════════════════════════════════════════════════════════════════

# All room codes Sandals has ever used in the 777 deal.
# Each RSC response is for ONE specific categoryCode — that IS the room code.
KNOWN_CATEGORY_CODES = [
    "LV", "1R", "HSUP", "VF", "1B", "OV1", "WSCL",   # current week (Mar 10 2026)
    "NPV", "HG", "KB", "STB", "OCV", "PLB", "RON",     # recent weeks
    "PCS", "GOV", "SLV", "BWV", "SKYV", "VFP", "HB", "LR",
]

# Map room code → resort code. Built from observed deal history.
# When a new room code appears that isn't here, the scraper will try to
# detect the resort from the page text automatically.
ROOM_TO_RESORT = {
    "LV":   "SAB",  # Grande Antigua
    "1R":   "SRP",  # Royal Plantation
    "HSUP": "SRB",  # Royal Bahamian
    "VF":   "SSV",  # Saint Vincent
    "1B":   "SNG",  # Negril
    "OV1":  "SGO",  # Ochi
    "WSCL": "SCR",  # Royal Curacao
    "NPV":  "SGO",  # Ochi
    "HG":   "SRB",  # Royal Bahamian
    "KB":   "SCR",  # Royal Curacao
    "KIB":  "SCR",  # Royal Curacao
    "STB":  "SGO",  # Ochi
    "OCV":  "SRB",  # Royal Bahamian
    "PLB":  "SCR",  # Royal Curacao
    "RON":  "SNG",  # Negril
    "PCS":  "SBR",  # Barbados
    "GOV":  "SLU",  # Regency La Toc
    "SLV":  "SSV",  # Saint Vincent
    "BWV":  "SNG",  # Negril
    "SKYV": "SLU",  # Regency La Toc
    "VFP":  "SSV",  # Saint Vincent
    "HB":   "SNG",  # Negril
    "LR":   "SRP",  # Royal Plantation
}

RSC_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "text/x-component",
    "RSC": "1",
    "Next-Url": "/specials/suite-deals/",
    "Referer": "https://www.sandals.com/specials/suite-deals/",
}

# Known suite name keywords to help identify real room names vs nav text
SUITE_KEYWORDS = [
    "suite", "villa", "room", "bungalow", "cottage", "loft",
    "butler", "oceanfront", "beachfront", "poolside", "walkout",
    "tranquility", "sanctuary", "rondoval", "swim-up", "oversize",
]

def _get_rsc_token() -> str:
    try:
        r = requests.get(SANDALS_URL,
            headers={**RSC_HEADERS, "Accept": "text/html"}, timeout=15)
        matches = re.findall(r'_rsc=([a-z0-9]+)', r.text)
        if matches:
            print(f"[D] Found RSC token: {matches[0]}")
            return matches[0]
    except Exception as e:
        print(f"[D] Could not fetch RSC token: {e}")
    return "rbniq"

def strategy_d_direct_api() -> list[dict]:
    print("[D] Trying direct RSC API calls...")
    rsc_token = _get_rsc_token()
    captured = []

    for code in KNOWN_CATEGORY_CODES:
        url = f"https://www.sandals.com/specials/suite-deals/?categoryCode={code}&_rsc={rsc_token}"
        try:
            r = requests.get(url, headers=RSC_HEADERS, timeout=15)
            if r.status_code == 200 and len(r.text) > 100:
                print(f"[D] Got categoryCode={code} ({len(r.text)} bytes)")
                captured.append((code, r.text))
        except Exception as e:
            print(f"[D] Failed {code}: {e}")
        time.sleep(0.3)

    if not captured:
        print("[D] No responses received")
        return []

    deals = _parse_rsc_targeted(captured)
    print(f"[D] Extracted {len(deals)} deals")
    return deals


def _parse_rsc_targeted(captured: list[tuple]) -> list[dict]:
    """
    Each RSC response contains the FULL page but with one deal highlighted.
    We know the categoryCode = room code. We find the resort and room name by:
    1. Looking for the room code appearing near "Room Code:" in the text
    2. Extracting the room name from surrounding context
    3. Extracting price from "Starting from $NNN" pattern
    4. Using ROOM_TO_RESORT to assign the correct resort
    """
    deals = []
    seen_room_codes = set()

    for cat_code, text in captured:
        # Skip if we've already found a deal for this room code
        if cat_code in seen_room_codes:
            continue

        # ── Find "Room Code: XXX" in the text ─────────────────────────────────
        # The page renders "Room Code: LV" near the deal card
        rc_match = re.search(
            rf'Room\s*Code[:\s]+({re.escape(cat_code)})\b', text, re.IGNORECASE
        )
        if not rc_match:
            # Room code not found in this response — skip, it's not a 777 deal
            print(f"[D] categoryCode={cat_code}: Room Code not found in response, skipping")
            continue

        print(f"[D] categoryCode={cat_code}: Room Code confirmed in response ✓")

        # ── Extract room name ──────────────────────────────────────────────────
        # Room name appears just before or after the Room Code line.
        # Strategy: find all strings near "Room Code:" that look like suite names
        pos = rc_match.start()
        # Take a window of text around the room code mention (±3000 chars)
        window = text[max(0, pos-3000):pos+500]

        room_name = _extract_room_name_from_window(window, cat_code)

        # ── Extract price ──────────────────────────────────────────────────────
        price_from = None
        price_match = re.search(
            r'[Ss]tarting\s+from\s+\$\s*([\d,]+)', text[max(0,pos-5000):pos+5000]
        )
        if price_match:
            price_from = int(price_match.group(1).replace(",", ""))

        # ── Map to resort ──────────────────────────────────────────────────────
        resort_code = ROOM_TO_RESORT.get(cat_code)
        if not resort_code:
            # Try to detect from text near the room code
            resort_code = _detect_resort_from_window(window)

        if not resort_code:
            print(f"[D] categoryCode={cat_code}: could not determine resort, skipping")
            continue

        if room_name:
            seen_room_codes.add(cat_code)
            deals.append(make_deal(
                len(deals) + 1,
                resort_code,
                cat_code,
                room_name,
                "",          # travel window — hard to extract from RSC reliably
                price_from,
                None
            ))
            print(f"[D]   → {resort_code} | {cat_code} | {room_name[:60]} | ${price_from}")

        if len(deals) >= 7:
            break

    return deals


def _extract_room_name_from_window(window: str, room_code: str) -> str:
    """
    Extract the room name from a text window around the Room Code mention.
    Room names are mixed-case strings containing suite keywords.
    We look for the longest qualifying string in the window.
    """
    # Split into chunks by common delimiters in RSC text
    chunks = re.split(r'["\n\r\t\\]+', window)

    candidates = []
    for chunk in chunks:
        chunk = chunk.strip()
        # Must be long enough to be a room name
        if len(chunk) < 15 or len(chunk) > 200:
            continue
        # Must contain at least one suite keyword
        chunk_lower = chunk.lower()
        if not any(kw in chunk_lower for kw in SUITE_KEYWORDS):
            continue
        # Must not be just navigation/footer text
        if any(bad in chunk_lower for bad in [
            "book online", "check rates", "find a travel", "returning guest",
            "sandals blog", "privacy policy", "terms", "contact us",
            "get $100", "bonus points", "sweepstakes", "learn more",
            "view all", "read more", "room details",
        ]):
            continue
        # Must have mixed case (real room names do; nav items are often ALL CAPS)
        if chunk == chunk.upper():
            continue
        candidates.append(chunk)

    if not candidates:
        return ""

    # Return the longest qualifying candidate (room names tend to be descriptive)
    return max(candidates, key=len)


def _detect_resort_from_window(window: str) -> str:
    """Scan window text for known resort name fragments to identify the resort."""
    resort_hints = {
        "SAB": ["grande antigua", "antigua resort", "dickenson bay"],
        "SGO": ["ochi", "ocho rios"],
        "SRP": ["royal plantation", "plantation"],
        "SRB": ["royal bahamian", "nassau", "west bay"],
        "SSV": ["saint vincent", "buccament"],
        "SNG": ["negril", "longshore"],
        "SCR": ["cura", "santa barbara", "subi"],
        "SBR": ["barbados", "christ church"],
        "SLU": ["la toc", "castries", "regency"],
        "SST": ["grande st. lucian", "gros islet"],
        "SSN": ["grenada"],
        "SAB": ["antigua"],
        "SKJ": ["south coast", "whitehouse"],
    }
    window_lower = window.lower()
    for code, hints in resort_hints.items():
        if any(h in window_lower for h in hints):
            return code
    return ""


# ══════════════════════════════════════════════════════════════════════════════
#  STRATEGY B  —  Stealth browser with full page wait + DOM scraping
#  Use a more patient approach: wait for specific text to appear on the page.
# ══════════════════════════════════════════════════════════════════════════════

def strategy_b_stealth() -> list[dict]:
    print("[B] Trying stealth browser scrape...")
    page_html = ""

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox",
                  "--disable-dev-shm-usage",
                  "--disable-blink-features=AutomationControlled",
                  "--window-size=1440,900"]
        )
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 900},
        )
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
        )
        page = ctx.new_page()

        try:
            page.goto(SANDALS_URL, wait_until="domcontentloaded", timeout=40_000)

            # Wait up to 20s for any of these resort codes to appear in page text
            # If Sandals' JS loads the deals, one of these will appear
            codes = list(RESORT_MAP.keys())
            deadline = time.time() + 20
            while time.time() < deadline:
                content = page.content()
                if any(code in content for code in codes):
                    print("[B] Resort codes found in page content")
                    break
                page.mouse.wheel(0, 300)
                time.sleep(1)

            page_html = page.content()

        except PWTimeout:
            print("[B] Timed out — using whatever loaded")
            try:
                page_html = page.content()
            except Exception:
                pass

        browser.close()

    if not page_html:
        return []

    return _parse_html_content(page_html)


def _parse_html_content(html: str) -> list[dict]:
    """Parse resort codes and room names from raw HTML."""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator="\n")
    return _parse_text_for_deals(text)


def _parse_text_for_deals(text: str) -> list[dict]:
    """
    Scan text for the pattern Sandals uses to present 777 deals:
    resort code → room code → room name → travel dates
    """
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    deals = []
    i = 0

    while i < len(lines) and len(deals) < 7:
        line = lines[i]

        # Look for a known resort code appearing in the line
        found_code = None
        for code in RESORT_MAP:
            if code in line:
                found_code = code
                break

        if found_code:
            # Collect the next ~8 lines as context for this deal
            context = lines[i:i+8]
            context_text = " | ".join(context)

            # Room code: 2-6 uppercase letters standing alone
            room_code = ""
            for cl in context:
                if re.fullmatch(r"[A-Z]{2,6}", cl):
                    room_code = cl
                    break

            # Room name: longest line with mixed case and spaces
            room_name = ""
            for cl in context:
                if (len(cl) > 20
                        and not re.fullmatch(r"[A-Z0-9\s\|\-\–\$\%\,\.]+", cl)
                        and not any(c in cl for c in RESORT_MAP)):
                    room_name = cl
                    break

            # Travel window: contains a year
            travel = ""
            for cl in context:
                if re.search(r"202[5-9]", cl):
                    travel = cl
                    break

            # Price
            prices = re.findall(r"\$\s*([\d,]+)", context_text)
            prices = [int(p.replace(",","")) for p in prices if int(p.replace(",","")) > 50]
            price_from = prices[0] if prices else None
            price_was  = prices[1] if len(prices) > 1 else None

            if room_name or room_code:
                deals.append(make_deal(
                    len(deals)+1, found_code, room_code, room_name or f"{found_code} Suite",
                    travel, price_from, price_was
                ))
            i += 4  # skip past this deal's lines
        else:
            i += 1

    return deals


# ══════════════════════════════════════════════════════════════════════════════
#  STRATEGY C  —  Scrape travel partner sites that publish the deals weekly
#  Sites like Honeymoons Inc., travel blogs, and deal aggregators post the
#  777 deals every Wednesday in plain readable HTML — much easier to parse.
# ══════════════════════════════════════════════════════════════════════════════

PARTNER_SOURCES = [
    # Each entry: (url, description)
    # These are checked in order; first one with deal data wins.
    ("https://www.sandals.com/specials/", "Sandals specials page"),
]

def strategy_c_partners() -> list[dict]:
    """
    Search for travel sites that have published this week's 777 deals.
    We use a web search to find the most current posts.
    """
    print("[C] Trying partner/blog sites...")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    # Try to find this week's deals via search
    today = datetime.now().strftime("%B %d %Y")
    search_queries = [
        f"Sandals 777 suite deals this week {datetime.now().strftime('%B %Y')}",
        "Sandals 7-7-7 weekly deals rooms site:sandals.com OR site:honeymoonsinc.com",
    ]

    for url, desc in PARTNER_SOURCES:
        try:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code == 200:
                deals = _parse_text_for_deals(
                    BeautifulSoup(r.text, "html.parser").get_text(separator="\n")
                )
                if deals:
                    print(f"[C] Got {len(deals)} deals from {desc}")
                    return deals
        except Exception as e:
            print(f"[C] Failed {desc}: {e}")

    print("[C] No deals from partner sites")
    return []


# ══════════════════════════════════════════════════════════════════════════════
#  PERSISTENCE
# ══════════════════════════════════════════════════════════════════════════════

def save_deals(deals: list[dict]) -> None:
    payload = {
        "weekLabel": get_week_label(),
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
        "dealCount": len(deals),
        "deals": deals,
    }
    DEALS_FILE.write_text(json.dumps(payload, indent=2))
    print(f"[save] Wrote {len(deals)} deals → {DEALS_FILE}")


def append_history(deals: list[dict]) -> None:
    week_label = get_week_label()
    history = json.loads(HIST_FILE.read_text()) if HIST_FILE.exists() else []
    if any(e["weekLabel"] == week_label for e in history):
        print(f"[save] Week '{week_label}' already in history — skipping")
        return
    history.append({
        "weekLabel": week_label,
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
        "deals": deals,
    })
    HIST_FILE.write_text(json.dumps(history, indent=2))
    print(f"[save] History now has {len(history)} weeks")


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def run():
    print("=" * 60)
    print(f"  Sandals 7·7·7 Scraper v2  —  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    deals = []

    # Try each strategy in order until one works
    for strategy in [strategy_d_direct_api, strategy_a_intercept, strategy_b_stealth, strategy_c_partners]:
        try:
            deals = strategy()
        except Exception as e:
            print(f"  Strategy {strategy.__name__} crashed: {e}")
            deals = []
        if deals:
            print(f"  ✅ {strategy.__name__} succeeded with {len(deals)} deals")
            break
        print(f"  ↩ Trying next strategy...\n")

    if not deals:
        print("\n⚠️  All strategies failed.")
        print("   The existing deals.json will NOT be overwritten.")
        print("   Manual action required — see README troubleshooting section.")
        return

    save_deals(deals)
    append_history(deals)
    print("\n✅ Done!")


if __name__ == "__main__":
    run()
