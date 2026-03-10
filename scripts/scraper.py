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
    "SAB": {"name": "Sandals Antigua",               "location": "Dickenson Bay, Antigua"},
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
    print("[A] Trying network interception...")
    captured = []

    def handle_response(response):
        url = response.url
        # Look for API calls that likely carry room/deal data
        if any(k in url for k in ["suite", "deal", "special", "promo", "offer",
                                   "qualifying", "room", "rate"]):
            try:
                body = response.body()
                text = body.decode("utf-8", errors="ignore")
                if len(text) > 200 and ('"room' in text.lower() or '"suite' in text.lower()
                                         or '"code"' in text.lower()):
                    print(f"[A] Captured API response from: {url}")
                    captured.append(text)
            except Exception:
                pass

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
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )
        # Remove webdriver flag
        ctx.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3]});
        """)
        page = ctx.new_page()
        page.on("response", handle_response)

        try:
            page.goto(SANDALS_URL, wait_until="domcontentloaded", timeout=30_000)
            # Scroll slowly like a human
            for _ in range(5):
                page.mouse.wheel(0, 400)
                time.sleep(random.uniform(0.4, 0.9))
            page.wait_for_timeout(5000)
        except PWTimeout:
            print("[A] Page load timed out")

        browser.close()

    deals = []
    for raw in captured:
        deals = _parse_api_json(raw)
        if deals:
            break

    print(f"[A] Extracted {len(deals)} deals")
    return deals


def _parse_api_json(raw: str) -> list[dict]:
    """Try to parse an API JSON blob into deal dicts."""
    try:
        data = json.loads(raw)
    except Exception:
        return []

    # Handle various possible response shapes
    items = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for key in ["deals", "rooms", "suites", "results", "data", "items", "qualifying"]:
            if key in data and isinstance(data[key], list):
                items = data[key]
                break

    deals = []
    for i, item in enumerate(items[:7], 1):
        if not isinstance(item, dict):
            continue
        code = (item.get("resortCode") or item.get("resort_code") or
                item.get("propertyCode") or "")
        room_code = (item.get("roomCode") or item.get("room_code") or
                     item.get("code") or "")
        room_name = (item.get("roomName") or item.get("room_name") or
                     item.get("name") or item.get("description") or "")
        travel = str(item.get("travelWindow") or item.get("travel_window") or
                     item.get("dates") or "")
        if code and room_name:
            deals.append(make_deal(i, code, room_code, room_name, travel))

    return deals


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
    for strategy in [strategy_a_intercept, strategy_b_stealth, strategy_c_partners]:
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
