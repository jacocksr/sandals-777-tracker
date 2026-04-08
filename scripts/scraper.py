"""
sandals_777_scraper.py  —  v3.3
================================
What we know from testing:
- Sandals' page is a Next.js React SPA
- The RSC network responses are binary streams, not parseable text
- BUT: the browser DOES render the page correctly (confirmed by testing:
  "Resort codes found in page content")
- The rendered page text contains exactly what we see on screen:
    "Room Code: LV", "Starting from $843 PP/PN", room names, resort names

This version loads the page in a real headless browser, waits until
"Room Code:" appears in the rendered text (meaning deal cards loaded),
then parses the text by splitting on "Room Code:" occurrences.

v3.1 changes:
- Added Sandals Halcyon Beach (SHB) to all lookup maps
- Improved image loading: scroll through full page before capturing URLs,
  then wait until at least 7 CDN images are present in the DOM
"""

import json, re, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
import requests
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ── PATHS ──────────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent.parent
DATA_DIR   = BASE_DIR / "docs" / "data"
DEALS_FILE  = DATA_DIR / "deals.json"
HIST_FILE   = DATA_DIR / "history.json"
IMAGE_DIR   = BASE_DIR / "docs" / "images"
DATA_DIR.mkdir(parents=True, exist_ok=True)
IMAGE_DIR.mkdir(parents=True, exist_ok=True)

SANDALS_URL = "https://www.sandals.com/specials/suite-deals/"

# ── RESORT LOOKUP ──────────────────────────────────────────────────────────────
RESORT_MAP = {
    "SGO": {"name": "Sandals Ochi",               "location": "Ocho Rios, Jamaica"},
    "SSV": {"name": "Sandals Saint Vincent",       "location": "Buccament Bay, Saint Vincent"},
    "SLU": {"name": "Sandals Regency La Toc",      "location": "Castries, Saint Lucia"},
    "SHB": {"name": "Sandals Halcyon Beach",       "location": "Castries, Saint Lucia"},  # v3.1
    "SRB": {"name": "Sandals Royal Bahamian",      "location": "Nassau, Bahamas"},
    "SRP": {"name": "Sandals Royal Plantation",    "location": "Ocho Rios, Jamaica"},
    "SNG": {"name": "Sandals Negril",              "location": "Negril, Jamaica"},
    "SCR": {"name": "Sandals Royal Curacao",       "location": "Santa Barbara, Curaçao"},
    "SBR": {"name": "Sandals Barbados",            "location": "Christ Church, Barbados"},
    "SKJ": {"name": "Sandals South Coast",         "location": "Whitehouse, Jamaica"},
    "SML": {"name": "Sandals Montego Bay",         "location": "Montego Bay, Jamaica"},
    "SDL": {"name": "Sandals Dunns River",         "location": "Ocho Rios, Jamaica"},
    "SSN": {"name": "Sandals Grenada",             "location": "Point Saline, Grenada"},
    "SST": {"name": "Sandals Grande St. Lucian",   "location": "Gros Islet, Saint Lucia"},
    "SAB": {"name": "Sandals Grande Antigua",      "location": "St. John's, Antigua"},
    "SMB": {"name": "Sandals Emerald Bay",         "location": "Exuma, Bahamas"},
    "SPR": {"name": "Sandals Royal Barbados",      "location": "Christ Church, Barbados"},
}

RESORT_COLORS = {
    "SGO":"#1a5c6a","SSV":"#3a5878","SLU":"#5a4878","SRB":"#2a6858",
    "SRP":"#785848","SNG":"#4a7848","SCR":"#1a6878","SBR":"#3a7868",
    "SKJ":"#6a4858","SML":"#487858","SDL":"#284878","SSN":"#784838",
    "SST":"#2a5868","SAB":"#5a6848","SMB":"#384868","SPR":"#685838",
    "SHB":"#3a6858",  # v3.1
}

# Maps our resort codes → Sandals CDN folder slugs (confirmed from live scrape logs)
RESORT_CDN_SLUG = {
    "SAB": "sat",   # Grande Antigua
    "SRP": "brp",   # Royal Plantation  (CDN uses 'brp')
    "SRB": "srb",   # Royal Bahamian    (CDN uses 'srb')
    "SSV": "ssv",
    "SNG": "sng",
    "SGO": "sgo",
    "SCR": "scr",
    "SBR": "sbd",   # CDN uses 'sbd' (confirmed from scrape logs)
    "SPR": "spr",
    "SLU": "slu",
    "SST": "sst",
    "SSN": "ssn",
    "SKJ": "skj",
    "SML": "sml",
    "SMB": "smb",
    "SHB": "shc",   # CDN uses 'shc' (confirmed from scrape logs)
}

# Maps our resort codes → sandals.com URL slugs for deep booking links
# Confirmed pattern: sandals.com/{slug}/rooms-suites/{room-code}/
#
# Slug rules observed from live site (v3.3):
#   - "Royal *" resorts keep short slug: royal-plantation, royal-bahamian, etc.
#   - "Negril" keeps short slug: negril
#   - All others need "sandals-" prefix to avoid clashing with destination pages
#   - SGO is special: slug is just "ochi" (not "ochi-beach-resort")
RESORT_BOOKING_SLUG = {
    "SAB": "sandals-grande-antigua",
    "SRP": "royal-plantation",
    "SRB": "royal-bahamian",
    "SSV": "sandals-saint-vincent",
    "SNG": "negril",
    "SGO": "ochi",
    "SCR": "royal-curacao",
    "SBR": "sandals-barbados",
    "SPR": "royal-barbados",
    "SLU": "sandals-regency-la-toc",
    "SST": "sandals-grande-st-lucian",
    "SSN": "sandals-grenada",
    "SKJ": "sandals-south-coast",
    "SML": "sandals-montego-bay",
    "SMB": "sandals-emerald-bay",
    "SHB": "sandals-halcyon-beach",
}

# Resort name fragments → resort code (order matters: more specific first)
RESORT_NAME_TO_CODE = {
    "grande antigua":    "SAB",
    "royal plantation":  "SRP",
    "royal bahamian":    "SRB",
    "royal barbados":    "SPR",
    "royal cura":        "SCR",
    "grande st. lucian": "SST",
    "saint vincent":     "SSV",
    "halcyon":           "SHB",   # v3.1 — must appear before generic "saint lucia" entries
    "regency la toc":    "SLU",
    "south coast":       "SKJ",
    "montego bay":       "SML",
    "emerald bay":       "SMB",
    "dunns river":       "SDL",
    "grenada":           "SSN",
    "barbados":          "SBR",
    "negril":            "SNG",
    "ochi":              "SGO",
}

SUITE_KEYWORDS = [
    "suite", "villa", "room", "bungalow", "loft", "butler",
    "beachfront", "oceanfront", "poolside", "walkout",
    "tranquility", "sanctuary", "swim-up", "oversized", "junior",
    "one-bedroom", "two-story", "club level", "mediterranean",
    "luxury",   # v3.1 — catches "Crystal Lagoon Poolside Luxury" and similar
]


def make_deal(i, resort_code, room_code, room_name, resort_display,
              location, price_from=None):
    info = RESORT_MAP.get(resort_code, {
        "name": resort_display or f"Sandals {resort_code}",
        "location": location or "Caribbean"
    })
    return {
        "id":          i,
        "resortCode":  resort_code,
        "resort":      info["name"],
        "location":    info["location"],
        "imgColor":    RESORT_COLORS.get(resort_code, "#1a5c6a"),
        "imgUrl":      "",   # primary CDN source URL
        "imgPath":     "",   # primary local path (used by site)
        "imgPaths":    [],   # all downloaded photos for carousel
        "roomCode":    room_code,
        "roomName":    room_name,
        "roomView":    "",   # e.g. "Beachfront, Pool, Tropical Garden"
        "bedding":     "",   # e.g. "1 King Bed"
        "discount":    "7%+ off",
        "priceFrom":   price_from,
        "priceWas":    None,
    }


def download_images(deals: list[dict]) -> None:
    """
    Download up to 4 photos per deal from Sandals CDN and save locally.
    Sandals hotlink-protects their CDN, so images must be hosted on GitHub Pages.
    Primary:  docs/images/{resortCode}_{roomCode}.jpg
    Extras:   docs/images/{resortCode}_{roomCode}_2.jpg, _3.jpg, _4.jpg
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.sandals.com/",
        "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
    }
    for deal in deals:
        # Get all CDN URLs for this resort from img_urls_raw stored on deal
        cdn_urls = deal.pop("_cdn_urls", [])
        if not cdn_urls and deal.get("imgUrl"):
            cdn_urls = [deal["imgUrl"]]
        # Download up to 4 images
        paths = []
        for idx, url in enumerate(cdn_urls[:4]):
            suffix = "" if idx == 0 else f"_{idx+1}"
            filename = f"{deal['resortCode']}_{deal['roomCode']}{suffix}.jpg"
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
    print(f"[scraper] Loading {SANDALS_URL}")

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
            page.goto(SANDALS_URL, wait_until="domcontentloaded", timeout=40_000)
        except PWTimeout:
            print("[scraper] Initial load timed out — continuing")

        # Poll until "Room Code:" appears in the rendered text (up to 40s)
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

        # ── v3.1: Scroll through the full page to trigger lazy-loaded images ──
        # Cards below the fold won't load their images until scrolled into view.
        print("[scraper] Scrolling to trigger lazy image loading...")
        for scroll_pos in [500, 1000, 1500, 2000, 2500, 3000, 3500, 4000]:
            page.mouse.wheel(0, scroll_pos)
            time.sleep(0.8)

        # Scroll back to top so the DOM is fully settled
        page.evaluate("window.scrollTo(0, 0)")
        time.sleep(1)

        # Wait up to 10s for at least 7 CDN images to appear in the DOM
        print("[scraper] Waiting for CDN images to load...")
        for wait_attempt in range(10):
            cdn_img_count = page.evaluate("""() =>
                [...document.querySelectorAll('img')]
                .filter(i => i.src && i.src.includes('cdn.sandals.com')).length
            """)
            print(f"[scraper] CDN images in DOM: {cdn_img_count} (attempt {wait_attempt+1})")
            if cdn_img_count >= 7:
                print("[scraper] Sufficient CDN images loaded ✓")
                break
            time.sleep(1)
        else:
            print("[scraper] ⚠️  Fewer than 7 CDN images found — proceeding anyway")

        # Extract image URLs grouped by deal card position
        # We need one image per card, matched to the correct deal in order.
        # Strategy: find all img elements that are children of the same
        # repeating card container, grouped so we can take one per card.
        img_urls_raw = []
        try:
            img_urls_raw = page.evaluate("""() => {
                // Collect all sandals CDN images, deduped, in DOM order
                const seen = new Set();
                const imgs = [];
                document.querySelectorAll('img').forEach(img => {
                    const src = img.src || img.dataset.src || img.dataset.lazy || '';
                    if (src.includes('cdn.sandals.com') &&
                        !src.includes('logo') &&
                        !src.includes('icon') &&
                        !src.includes('card_image') &&
                        !src.includes('footer') &&
                        !src.includes('brands') &&
                        !seen.has(src)) {
                        seen.add(src);
                        imgs.push(src);
                    }
                });
                return imgs;
            }""")
            print(f"[scraper] Found {len(img_urls_raw)} CDN image URLs total")
            for u in img_urls_raw:
                print(f"[scraper] CDN: {u[:100]}")
        except Exception as e:
            print(f"[scraper] Image extraction error: {e}")

        browser.close()

    if not body_text:
        print("[scraper] No page text retrieved")
        return []

    rc_count = body_text.count("Room Code:")
    print(f"[scraper] Rendered text: {len(body_text)} chars, {rc_count} 'Room Code:' occurrences")
    deals = parse_rendered_text(body_text)

    for deal in deals:
        slug = RESORT_CDN_SLUG.get(deal["resortCode"], "").lower()
        matched = [u for u in img_urls_raw if f"/resorts/{slug}/" in u.lower()] if slug else []
        deal["imgUrl"]    = matched[0] if matched else ""
        deal["_cdn_urls"] = matched[:4]   # store all for multi-photo download
        if deal["imgUrl"]:
            print(f"[scraper] Matched {len(matched)} images for {deal['resortCode']} (slug='{slug}')")
        else:
            print(f"[scraper] No image matched for {deal['resortCode']} (slug='{slug}')")

    # Download all images locally to avoid hotlink-protection blocking
    download_images(deals)

    return deals


# ══════════════════════════════════════════════════════════════════════════════
#  PARSER
# ══════════════════════════════════════════════════════════════════════════════

def parse_rendered_text(text: str) -> list[dict]:
    """
    The rendered page text for each deal looks like:

        sandals Grande Antigua - St. John's, Antigua
        Mediterranean One Bedroom Butler Villa with Private Pool Sanctuary
        Located in the Mediterranean Oceanview Village...  Read More
        Room Code: LV
        Room View(s): Beachfront, Pool, Tropical Garden
        Bedding: 1 King Bed
        Starting from $843 PP/PN

    Split on "Room Code:" and parse each block.
    """
    # Split text on every "Room Code:" occurrence
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

        # ── Room code: first word after "Room Code:" ───────────────────────────
        room_code = lines[0].split()[0].strip()

        # ── Room View and Bedding (lines 1 and 2 after room code) ─────────────
        room_view = ""
        bedding   = ""
        for line in lines[1:5]:
            if line.startswith("Room View"):
                room_view = re.sub(r"^Room View\(s\):\s*", "", line).strip()
            elif line.startswith("Bedding:"):
                bedding = re.sub(r"^Bedding:\s*", "", line).strip()

        # ── Look back in the text before this block for resort + room name ──────
        # Find the position of this Room Code: in the original text
        split_pos = _find_nth_occurrence(text, "Room Code:", i)
        lookback  = text[max(0, split_pos - 2500) : split_pos]

        resort_display, location, room_name = extract_resort_and_room(lookback)
        resort_code = resolve_resort_code(resort_display)

        # ── Price ─────────────────────────────────────────────────────────────
        price_from = None
        price_match = re.search(r'[Ss]tarting\s+from\s+\$\s*([\d,]+)', part[:600])
        if price_match:
            price_from = int(price_match.group(1).replace(",", ""))

        print(f"[parser] Deal {i}: {resort_code} | {room_code} | "
              f"{room_name[:55] if room_name else 'NO NAME'} | ${price_from}")

        if room_name and resort_code:
            deal = make_deal(
                len(deals) + 1, resort_code, room_code, room_name,
                resort_display, location, price_from,
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
    """
    Work backwards through the lookback text to find the last
    "sandals [Name] - [Location]" line, then read the line after it
    as the room name.
    """
    lines = [l.strip() for l in lookback.splitlines() if l.strip()]

    resort_display = ""
    location       = ""
    room_name      = ""
    resort_idx     = None

    for j in range(len(lines) - 1, -1, -1):
        line = lines[j]
        # Resort line: contains "sandals" and " - " separator
        if re.search(r'\bsandals\b', line, re.IGNORECASE) and " - " in line:
            parts = line.split(" - ", 1)
            resort_display = parts[0].strip()
            location       = parts[1].strip() if len(parts) > 1 else ""
            resort_idx     = j
            break

    if resort_idx is not None:
        # Room name is always the line immediately after the resort header.
        # Strategy: prefer offset 1 if it looks like a title (short, not a
        # full sentence). Fall back to offset 2 only if offset 1 is too long.
        # Never accept lines over 150 chars (those are marketing blurbs).
        for offset in [1, 2]:
            if resort_idx + offset < len(lines):
                candidate = lines[resort_idx + offset]
                if len(candidate) > 150:
                    continue  # definitely a blurb, skip
                # Accept if it has suite keywords OR is a short title-like line
                # (under 60 chars, no lowercase sentence starters like "These")
                has_keyword = any(kw in candidate.lower() for kw in SUITE_KEYWORDS)
                is_title = (len(candidate) <= 60 and
                            not re.match(r'^[a-z]', candidate) and
                            '.' not in candidate)
                if has_keyword or is_title:
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
    Confirmed URL pattern from live Sandals site:
      sandals.com/{resort-slug}/rooms-suites/{room-code-lowercase}/
    e.g. sandals.com/grande-antigua/rooms-suites/lv/
         sandals.com/royal-plantation/rooms-suites/1r/
    """
    resort_slug = RESORT_BOOKING_SLUG.get(resort_code, "")
    if not resort_slug or not room_code:
        return "https://www.sandals.com/specials/suite-deals/"
    return f"https://www.sandals.com/{resort_slug}/rooms-suites/{room_code.lower()}/"


def verify_book_url(url: str, fallback: str) -> str:
    """
    HEAD-request the generated booking URL.  If Sandals returns a 404 (or we
    get a redirect to a completely different path) fall back to the suite-deals
    landing page so the user always lands somewhere useful.

    We accept 200, 301, 302, 403 (bot-block but page exists), 405 as "alive".
    Only a true 404 (or connection failure) triggers the fallback.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.sandals.com/",
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
        return url          # network error: don't discard, keep as-is


def save_deals(deals: list[dict]) -> None:
    FALLBACK = "https://www.sandals.com/specials/suite-deals/"
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
    # Update existing week entry rather than skip it
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
    print(f"  Sandals 7·7·7 Scraper v3.2  —  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    deals = scrape_deals()

    if not deals:
        print("\n⚠️  No deals extracted. Existing deals.json NOT overwritten.")
        return

    save_deals(deals)
    append_history(deals)
    print(f"\n✅ Done! Extracted {len(deals)} deals.")


if __name__ == "__main__":
    run()
