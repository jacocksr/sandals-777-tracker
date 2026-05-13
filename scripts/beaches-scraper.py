"""
beaches_777_scraper.py  —  v1.0
================================
Scrapes Beaches Resorts' 7·7·7 suite deals from:
  https://www.beaches.com/specials/suite-deals/

Beaches has 2 resorts:
  BTC — Beaches Turks & Caicos (Providenciales)
  BNG — Beaches Negril (Jamaica)

Architecture mirrors the Sandals scraper (v3.3):
  - Playwright headless browser to render the React SPA
  - Wait until "Room Code:" appears 7 times in rendered text
  - Parse rendered text blocks
  - Download CDN images locally (Beaches uses the same cdn.sandals.com CDN)
  - Verify booking URLs via HEAD request
  - Write docs/data/beaches-deals.json and docs/data/beaches-history.json
"""

import json, re, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
import requests
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ── PATHS ──────────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent.parent
DATA_DIR   = BASE_DIR / "docs" / "data"
DEALS_FILE  = DATA_DIR / "beaches-deals.json"
HIST_FILE   = DATA_DIR / "beaches-history.json"
IMAGE_DIR   = BASE_DIR / "docs" / "images"
DATA_DIR.mkdir(parents=True, exist_ok=True)
IMAGE_DIR.mkdir(parents=True, exist_ok=True)

BEACHES_URL = "https://www.beaches.com/specials/suite-deals/"

# ── RESORT LOOKUP ──────────────────────────────────────────────────────────────
RESORT_MAP = {
    "BTC": {"name": "Beaches Turks & Caicos", "location": "Providenciales, Turks & Caicos"},
    "BNG": {"name": "Beaches Negril",          "location": "Negril, Jamaica"},
}

RESORT_COLORS = {
    "BTC": "#0077b6",   # deep ocean blue — Turks & Caicos
    "BNG": "#00b4d8",   # bright teal — Negril
}

# Beaches CDN folder slugs (same cdn.sandals.com CDN as Sandals)
RESORT_CDN_SLUG = {
    "BTC": "btc",
    "BNG": "bng",
}

# Booking URL slugs: beaches.com/resorts/{slug}/rooms-suites/{room-code}/
RESORT_BOOKING_SLUG = {
    "BTC": "turks-caicos",
    "BNG": "negril",
}

# Resort name fragments → resort code (order matters)
RESORT_NAME_TO_CODE = {
    "turks":   "BTC",
    "caicos":  "BTC",
    "negril":  "BNG",
    "jamaica": "BNG",   # fallback if resort name only says "Jamaica"
}

SUITE_KEYWORDS = [
    "suite", "villa", "room", "bungalow", "butler",
    "beachfront", "oceanfront", "poolside", "walkout",
    "tranquility", "swim-up", "oversized", "junior",
    "one-bedroom", "two-bedroom", "family", "connecting",
    "club level", "luxury", "grand luxe", "key west",
    "caribbean", "french", "italian", "mediterranean",
    "penthouse", "veranda",
]

SCRAPER_BLOCKLIST = {
    'new room', 'new', 'featured', 'book now', 'view details',
    'read more', 'sold out', 'limited availability', 'per person',
    'per night', 'starting from', 'adults only', 'family friendly',
}

def make_deal(i, resort_code, room_code, room_name, resort_display,
              location, price_from=None, price_child=None):
    info = RESORT_MAP.get(resort_code, {
        "name": resort_display or f"Beaches {resort_code}",
        "location": location or "Caribbean"
    })
    return {
        "id":          i,
        "resortCode":  resort_code,
        "resort":      info["name"],
        "location":    info["location"],
        "imgColor":    RESORT_COLORS.get(resort_code, "#0077b6"),
        "imgUrl":      "",
        "imgPath":     "",
        "imgPaths":    [],
        "roomCode":    room_code,
        "roomName":    room_name,
        "roomView":    "",
        "bedding":     "",
        "discount":    "7%+ off",
        "priceFrom":   price_from,
        "priceChild":  price_child,
        "priceWas":    None,
    }


def download_images(deals: list[dict]) -> None:
    """
    Download up to 4 photos per deal from Beaches/Sandals CDN.
    Stored as: docs/images/B{resortCode}_{roomCode}[_N].jpg
    Uses B prefix to avoid collisions with Sandals images.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.beaches.com/",
        "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
    }
    for deal in deals:
        cdn_urls = deal.pop("_cdn_urls", [])
        if not cdn_urls and deal.get("imgUrl"):
            cdn_urls = [deal["imgUrl"]]
        paths = []
        for idx, url in enumerate(cdn_urls[:4]):
            suffix = "" if idx == 0 else f"_{idx+1}"
            filename = f"B{deal['resortCode']}_{deal['roomCode']}{suffix}.jpg"
            dest = IMAGE_DIR / filename
            if dest.exists() and dest.stat().st_size > 5000:
                paths.append(f"images/{filename}")
                print(f"[images] Already have {filename}")
                continue
            try:
                r = requests.get(url, headers=headers, timeout=15)
                if r.status_code == 200 and len(r.content) > 5000:
                    dest.write_bytes(r.content)
                    paths.append(f"images/{filename}")
                    print(f"[images] Downloaded {filename} ({len(r.content)//1024}KB)")
                else:
                    print(f"[images] Failed {filename}: HTTP {r.status_code}")
            except Exception as e:
                print(f"[images] Error {filename}: {e}")
        deal["imgPath"]  = paths[0] if paths else ""
        deal["imgPaths"] = paths


def get_week_label():
    now = datetime.now(timezone.utc)
    days_since_wed = (now.weekday() - 2) % 7
    start = (now - timedelta(days=days_since_wed)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=6)
    return f"{start.strftime('%b %-d')} – {end.strftime('%b %-d')}, {end.year}"


# ══════════════════════════════════════════════════════════════════════════════
#  BROWSER SCRAPER
# ══════════════════════════════════════════════════════════════════════════════

def scrape_deals() -> list[dict]:
    print(f"[scraper] Loading {BEACHES_URL}")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ]
        )
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
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
            page.goto(BEACHES_URL, wait_until="domcontentloaded", timeout=40_000)
        except PWTimeout:
            print("[scraper] Initial load timed out — continuing")

        # Poll until "Room Code:" appears in rendered text (up to 40s)
        print("[scraper] Waiting for deal cards...")
        body_text = ""
        for attempt in range(40):
            page.mouse.wheel(0, 300)
            time.sleep(1)
            try:
                body_text = page.inner_text("body")
                count = body_text.count("Room Code:")
                if count >= 7:
                    print(f"[scraper] All 7 deal cards found after {attempt+1}s ✓")
                    break
                elif count > 0:
                    print(f"[scraper] {count}/7 cards loaded at {attempt+1}s...")
            except Exception:
                pass

        # Capture the raw HTML source containing the Next.js state data before closing
        print("[scraper] Capturing Next.js state data...")
        html_source = page.content()
        
        browser.close()

    if not body_text:
        print("[scraper] No page text retrieved")
        return []

    rc_count = body_text.count("Room Code:")
    print(f"[scraper] Rendered text: {len(body_text)} chars, {rc_count} 'Room Code:' occurrences")
    
    # Parse deals from the rendered text
    deals = parse_rendered_text(body_text)

    # Extract accurate images from the Next.js HTML source
    print("[scraper] Extracting accurate images from Next.js state data...")
    for deal in deals:
        room_name = deal.get('roomName', '')
        if not room_name:
            continue
            
        # The HTML encodes ampersands as \u0026
        room_search_term = room_name.replace('&', '\\u0026')
        
        # Find where this room is mentioned in the Next.js JSON state
        idx = html_source.find(room_search_term)
        if idx != -1:
            # Look at a window of text before the room name to find the associated images
            window_start = max(0, idx - 1500)
            window_end = min(len(html_source), idx + 1000)
            window = html_source[window_start:window_end]
            
            # Find all CDN jpg URLs in this window
            found_urls = re.findall(r'https://cdn\.sandals\.com/[^"\\]+\.jpg', window)
            
            if found_urls:
                # Deduplicate while preserving order
                unique_urls = list(dict.fromkeys(found_urls))
                
                # Assign up to 4 images to the deal (Uses _cdn_urls to match your download_images logic)
                deal['_cdn_urls'] = unique_urls[:4]
                
                # Set the primary image URL
                deal['imgUrl'] = unique_urls[0]
                print(f"[scraper] Found {len(unique_urls)} images for {room_name[:30]}...")
            else:
                print(f"[scraper] No Next.js images found for {room_name[:30]}")
        else:
            print(f"[scraper] Room name not found in Next.js state: {room_name[:30]}")

    download_images(deals)
    return deals

# ══════════════════════════════════════════════════════════════════════════════
#  PARSER
# ══════════════════════════════════════════════════════════════════════════════

def parse_rendered_text(text: str) -> list[dict]:
    """
    The rendered page text for each deal looks like:

        Beaches Turks & Caicos - Providenciales, Turks & Caicos
        Caribbean Family Butler One Bedroom Suite
        Located in...  Read More
        Room Code: CFB1
        Room View(s): Beachfront, Pool
        Bedding: 2 Double Beds
        Starting from $425 PP/PN

    Split on "Room Code:" and parse each block.
    """
    parts = re.split(r'Room Code:', text, flags=re.IGNORECASE)

    if len(parts) < 2:
        print("[parser] 'Room Code:' not found in rendered text")
        return []

    print(f"[parser] {len(parts)-1} Room Code blocks found")
    deals = []

    for i, part in enumerate(parts[1:], 1):
        if len(deals) >= 7:
            break

        lines = [l.strip() for l in part.splitlines() if l.strip()]
        if not lines:
            continue

        room_code = lines[0].split()[0].strip()

        room_view = ""
        bedding   = ""
        for line in lines[1:5]:
            if line.startswith("Room View"):
                room_view = re.sub(r"^Room View\(s\):\s*", "", line).strip()
            elif line.startswith("Bedding:"):
                bedding = re.sub(r"^Bedding:\s*", "", line).strip()

        split_pos = _find_nth_occurrence(text, "Room Code:", i)
        lookback  = text[max(0, split_pos - 2500) : split_pos]

        resort_display, location, room_name = extract_resort_and_room(lookback)
        resort_code = resolve_resort_code(resort_display)

        price_from  = None
        price_child = None
        
        adult_match = re.search(r'Adult\s+from\s+\$\s*([\d,]+)\s*PP/?PN', part, re.IGNORECASE)
        child_match = re.search(r'Child\s+from\s+\$\s*([\d,]+)\s*PP/?PN', part, re.IGNORECASE)
        
        if adult_match:
            price_from  = int(adult_match.group(1).replace(",", ""))
        if child_match:
            price_child = int(child_match.group(1).replace(",", ""))
        
        # Fallback for any other format
        if price_from is None:
            for _pat in [
                r'[Ss]tarting\s+from\s+\$\s*([\d,]+)',
                r'[Ff]rom\s+\$\s*([\d,]+)',
                r'\$\s*([\d,]+)\s*PP/?PN',
                r'([\d,]+)\s*PP/?PN',
            ]:
                _m = re.search(_pat, part, re.IGNORECASE)
                if _m:
                    try:
                        price_from = int(_m.group(1).replace(",", ""))
                    except (ValueError, IndexError):
                        pass
                    else:
                        break

        print(f"[parser] Deal {i}: {resort_code} | {room_code} | "
              f"{room_name[:55] if room_name else 'NO NAME'} | ${price_from}")

        if room_name and resort_code:
            
            deal = make_deal(
                len(deals) + 1, resort_code, room_code, room_name,
                resort_display, location, price_from, price_child,
            )
            deal["roomView"] = room_view
            deal["bedding"]  = bedding
            deals.append(deal)
        else:
            print(f"[parser]   ↳ Skipped (resort_code='{resort_code}' "
                  f"room_name='{room_name[:30] if room_name else ''}')")

    return deals


def _find_nth_occurrence(text: str, pattern: str, n: int) -> int:
    pos = 0
    for _ in range(n):
        found = text.find(pattern, pos)
        if found == -1:
            return len(text)
        pos = found + 1
    return pos - 1


def extract_resort_and_room(lookback: str) -> tuple:
    lines = [l.strip() for l in lookback.splitlines() if l.strip()]

    resort_display = ""
    location       = ""
    room_name      = ""
    resort_idx     = None

    for j in range(len(lines) - 1, -1, -1):
        line = lines[j]
        # Beaches resort line: contains "beaches" and " - " separator
        if re.search(r'\bbeaches\b', line, re.IGNORECASE) and " - " in line:
            parts = line.split(" - ", 1)
            resort_display = parts[0].strip()
            location       = parts[1].strip() if len(parts) > 1 else ""
            resort_idx     = j
            break

    if resort_idx is not None:
        for offset in [1, 2]:
            if resort_idx + offset < len(lines):
                candidate = lines[resort_idx + offset]
                if len(candidate) > 150:
                    continue
                has_keyword = any(kw in candidate.lower() for kw in SUITE_KEYWORDS)
                is_title = (len(candidate) <= 70 and
                            not re.match(r'^[a-z]', candidate) and
                            '.' not in candidate)
                
                if (has_keyword or is_title) and candidate.lower().strip() not in SCRAPER_BLOCKLIST:
                    room_name = candidate
                    break

    return resort_display, location, room_name


def resolve_resort_code(resort_display: str) -> str:
    name_lower = resort_display.lower()
    for fragment, code in RESORT_NAME_TO_CODE.items():
        if fragment in name_lower:
            return code
    return ""


# ══════════════════════════════════════════════════════════════════════════════
#  PERSISTENCE
# ══════════════════════════════════════════════════════════════════════════════

def make_room_url(resort_code: str, room_code: str) -> str:
    """
    Beaches booking URL pattern:
      beaches.com/resorts/{resort-slug}/rooms-suites/{room-code-lowercase}/
    """
    resort_slug = RESORT_BOOKING_SLUG.get(resort_code, "")
    if not resort_slug or not room_code:
        return "https://www.beaches.com/specials/suite-deals/"
    return f"https://www.beaches.com/resorts/{resort_slug}/rooms-suites/{room_code.lower()}/"


def verify_book_url(url: str, fallback: str) -> str:
    """HEAD-request the booking URL; fall back on 404 or error."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.beaches.com/",
    }
    try:
        r = requests.head(url, headers=headers, timeout=10, allow_redirects=True)
        if r.status_code == 404:
            print(f"[verify] 404 → falling back: {url}")
            return fallback
        print(f"[verify] {r.status_code} OK: {url}")
        return url
    except Exception as e:
        print(f"[verify] Error checking {url}: {e} — keeping URL")
        return url


def save_deals(deals: list[dict]) -> None:
    FALLBACK = "https://www.beaches.com/specials/suite-deals/"
    print("[save] Verifying booking URLs…")
    for deal in deals:
        raw_url = make_room_url(deal["resortCode"], deal["roomCode"])
        deal["bookUrl"] = verify_book_url(raw_url, FALLBACK)
    payload = {
        "weekLabel": get_week_label(),
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
        "dealCount": len(deals),
        "deals":     deals,
    }
    DEALS_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"[save] Wrote {len(deals)} deals → {DEALS_FILE}")


def append_history(deals: list[dict]) -> None:
    week_label = get_week_label()
    history = json.loads(HIST_FILE.read_text()) if HIST_FILE.exists() else []
    for entry in history:
        if entry["weekLabel"] == week_label:
            entry["deals"]     = deals
            entry["fetchedAt"] = datetime.now(timezone.utc).isoformat()
            HIST_FILE.write_text(json.dumps(history, indent=2, ensure_ascii=False))
            print(f"[save] Updated existing week in history ({len(history)} total)")
            return
    history.append({
        "weekLabel": week_label,
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
        "deals":     deals,
    })
    HIST_FILE.write_text(json.dumps(history, indent=2, ensure_ascii=False))
    print(f"[save] History now has {len(history)} weeks")


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def run():
    print("=" * 60)
    print(f"  Beaches 7·7·7 Scraper v1.0  —  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    deals = scrape_deals()

    if not deals:
        print("\n⚠️  No deals extracted. Existing beaches-deals.json NOT overwritten.")
        return

    save_deals(deals)
    append_history(deals)
    print(f"\n✅ Done! Extracted {len(deals)} deals.")


if __name__ == "__main__":
    run()
