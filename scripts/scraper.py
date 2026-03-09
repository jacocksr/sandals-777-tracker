"""
sandals_777_scraper.py
======================
Fetches the current 7-7-7 deals from sandals.com and saves them to
  data/deals.json   (this week's deals, always overwritten)
  data/history.json (append-only archive of every week ever scraped)

HOW IT WORKS
------------
Sandals' suite-deals page is a JavaScript-rendered Single Page Application
(SPA). A normal HTTP request only gets an empty HTML shell. We use
Playwright, a headless browser automation library, to actually LOAD the page
the way a real browser would, wait until the deal content appears, then
extract the text.

Think of it like a robot sitting in front of an invisible Chrome browser,
waiting for the page to finish loading, reading it, and writing the data
down for us.
"""

import json
import re
import os
from datetime import datetime, timezone
from pathlib import Path

# Playwright lets us drive a real headless browser
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# ── PATHS ──────────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent.parent          # /sandals-tracker/
DATA_DIR   = BASE_DIR / "docs" / "data"
DEALS_FILE = DATA_DIR / "deals.json"
HIST_FILE  = DATA_DIR / "history.json"
DATA_DIR.mkdir(exist_ok=True)

# ── CONSTANTS ──────────────────────────────────────────────────────────────────
SANDALS_777_URL = "https://www.sandals.com/specials/suite-deals/"

# Map resort codes to full names and locations
RESORT_MAP = {
    "SGO": {"name": "Sandals Ochi",                  "location": "Ocho Rios, Jamaica"},
    "SSV": {"name": "Sandals Saint Vincent",          "location": "St. Vincent"},
    "SLU": {"name": "Sandals Regency La Toc",         "location": "Castries, Saint Lucia"},
    "SRB": {"name": "Sandals Royal Bahamian",         "location": "Nassau, Bahamas"},
    "SRP": {"name": "Sandals Royal Plantation",       "location": "Ocho Rios, Jamaica"},
    "SNG": {"name": "Sandals Negril",                 "location": "Negril, Jamaica"},
    "SCR": {"name": "Sandals Royal Curacao",          "location": "Willemstad, Curacao"},
    "SBR": {"name": "Sandals Barbados",               "location": "Christ Church, Barbados"},
    "SKJ": {"name": "Sandals South Coast",            "location": "Whitehouse, Jamaica"},
    "SML": {"name": "Sandals Montego Bay",            "location": "Montego Bay, Jamaica"},
    "SDL": {"name": "Sandals Dunns River",            "location": "Ocho Rios, Jamaica"},
    "SSN": {"name": "Sandals Grenada",                "location": "Point Saline, Grenada"},
    "SST": {"name": "Sandals Grande St. Lucian",      "location": "Gros Islet, Saint Lucia"},
    "SAB": {"name": "Sandals Antigua",                "location": "Dickenson Bay, Antigua"},
    "SMB": {"name": "Sandals Emerald Bay",            "location": "Exuma, Bahamas"},
    "SPR": {"name": "Sandals Royal Barbados",         "location": "Christ Church, Barbados"},
}

# Color palette for each resort code (used by the frontend)
RESORT_COLORS = {
    "SGO": "#1a5c6a", "SSV": "#3a5878", "SLU": "#5a4878",
    "SRB": "#2a6858", "SRP": "#785848", "SNG": "#4a7848",
    "SCR": "#1a6878", "SBR": "#3a7868", "SKJ": "#6a4858",
    "SML": "#487858", "SDL": "#284878", "SSN": "#784838",
    "SST": "#2a5868", "SAB": "#5a6848", "SMB": "#384868",
    "SPR": "#685838",
}


# ── SCRAPER ────────────────────────────────────────────────────────────────────

def scrape_777_deals() -> list[dict]:
    """
    Launch a headless Chromium browser, load the Sandals 777 page,
    wait for deal cards to appear, then parse them.
    Returns a list of deal dicts.
    """
    deals = []

    with sync_playwright() as p:
        # Launch headless Chromium (invisible browser)
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 900},
        )

        print(f"[scraper] Loading {SANDALS_777_URL} ...")
        try:
            page.goto(SANDALS_777_URL, wait_until="networkidle", timeout=45_000)
        except PlaywrightTimeoutError:
            # Page sometimes takes long; try anyway with what loaded
            print("[scraper] Timeout waiting for networkidle, proceeding...")

        # ── Strategy 1: look for structured room/suite cards ──────────────────
        # Sandals renders deal items inside elements that typically contain
        # the room code and discount. We try several CSS selectors that have
        # historically matched their markup. If none work, we fall back to
        # full-page text parsing.

        CARD_SELECTORS = [
            "[class*='suite-deal']",
            "[class*='SuiteDeal']",
            "[class*='deal-card']",
            "[class*='qualifying']",
            "[data-room-code]",
        ]

        cards_found = []
        for sel in CARD_SELECTORS:
            try:
                page.wait_for_selector(sel, timeout=6_000)
                cards_found = page.query_selector_all(sel)
                if cards_found:
                    print(f"[scraper] Found {len(cards_found)} cards with selector '{sel}'")
                    break
            except PlaywrightTimeoutError:
                continue

        if cards_found:
            deals = _parse_card_elements(page, cards_found)
        else:
            # ── Strategy 2: full-page text extraction ─────────────────────────
            print("[scraper] No card elements found — falling back to text parse")
            full_text = page.inner_text("body")
            deals = _parse_page_text(full_text)

        browser.close()

    print(f"[scraper] Extracted {len(deals)} deals")
    return deals


def _parse_card_elements(page, cards) -> list[dict]:
    """Parse deal data from structured DOM card elements."""
    deals = []
    for i, card in enumerate(cards[:7]):   # max 7 per the promotion rules
        try:
            text = card.inner_text()
            deal = _extract_deal_fields(text, i + 1)
            if deal:
                deals.append(deal)
        except Exception as e:
            print(f"[scraper] Error parsing card {i}: {e}")
    return deals


def _parse_page_text(text: str) -> list[dict]:
    """
    Fallback: scan raw page text for resort codes and room info.
    Sandals always lists the 7 deals with their 3-letter resort codes.
    """
    deals = []
    # Find lines that contain known resort codes
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    current_deal = {}
    deal_num = 0

    for line in lines:
        # Check if line contains a resort code pattern like "SGO:" or "SGO –"
        code_match = re.match(r'\b([A-Z]{3})\s*[:\–\-]?\s*(.*)', line)
        if code_match:
            code = code_match.group(1)
            if code in RESORT_MAP:
                if current_deal:
                    deals.append(current_deal)
                deal_num += 1
                current_deal = {
                    "id": deal_num,
                    "resortCode": code,
                    "resort": RESORT_MAP[code]["name"],
                    "location": RESORT_MAP[code]["location"],
                    "imgColor": RESORT_COLORS.get(code, "#1a5c6a"),
                    "roomCode": "",
                    "roomName": code_match.group(2).strip(),
                    "discount": "7%+ off",
                    "travelWindow": "",
                    "priceFrom": None,
                    "priceWas": None,
                }
                continue

        # Try to capture room code (short uppercase + possible letters)
        room_match = re.match(r'^([A-Z]{2,6})\s*[–\-]\s*(.+)$', line)
        if room_match and current_deal and not current_deal.get("roomCode"):
            current_deal["roomCode"] = room_match.group(1)
            current_deal["roomName"] = room_match.group(2)

        # Travel window
        if "travel" in line.lower() and ("–" in line or "-" in line) and current_deal:
            current_deal["travelWindow"] = line

        # Price info
        price_match = re.search(r'\$\s*([\d,]+)', line)
        if price_match and current_deal:
            price = int(price_match.group(1).replace(",", ""))
            if not current_deal["priceFrom"]:
                current_deal["priceFrom"] = price
            elif not current_deal["priceWas"]:
                current_deal["priceWas"] = price

    if current_deal and current_deal not in deals:
        deals.append(current_deal)

    return deals[:7]  # cap at 7


def _extract_deal_fields(text: str, deal_num: int) -> dict | None:
    """Extract structured fields from a single card's text blob."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    resort_code = None
    room_code   = None
    room_name   = None
    travel_window = ""
    price_from  = None
    price_was   = None

    for line in lines:
        # Detect resort code
        for code in RESORT_MAP:
            if code in line:
                resort_code = code
                break

        # Detect room code (2-6 uppercase letters often appear alone on a line)
        if re.fullmatch(r'[A-Z]{2,6}', line) and not room_code:
            room_code = line

        # Detect travel window
        if re.search(r'\d{4}', line) and ("–" in line or "-" in line) and not travel_window:
            travel_window = line.strip()

        # Detect prices
        price_match = re.findall(r'\$\s*([\d,]+)', line)
        for p in price_match:
            val = int(p.replace(",", ""))
            if val > 50:  # ignore tiny numbers
                if not price_from:
                    price_from = val
                elif not price_was and val != price_from:
                    price_was = val

    if not resort_code:
        return None

    # Room name: find the longest non-code line
    room_name = max(
        (ln for ln in lines if len(ln) > 15 and not re.fullmatch(r'[A-Z\s\d\$%,\.–\-]+', ln)),
        key=len,
        default=lines[0] if lines else "Suite"
    )

    return {
        "id": deal_num,
        "resortCode": resort_code,
        "resort": RESORT_MAP[resort_code]["name"],
        "location": RESORT_MAP[resort_code]["location"],
        "imgColor": RESORT_COLORS.get(resort_code, "#1a5c6a"),
        "roomCode": room_code or "–",
        "roomName": room_name,
        "discount": "7%+ off",
        "travelWindow": travel_window,
        "priceFrom": price_from,
        "priceWas": price_was,
    }


# ── PERSISTENCE ────────────────────────────────────────────────────────────────

def get_week_label() -> str:
    """Return a human-readable label for the current deal week (Wed–Tue)."""
    now = datetime.now(timezone.utc)
    # Find the most recent Wednesday
    days_since_wed = (now.weekday() - 2) % 7
    week_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    # subtract days to get to Wednesday
    from datetime import timedelta
    week_start = week_start - timedelta(days=days_since_wed)
    week_end   = week_start + timedelta(days=6)
    fmt = "%b %-d"
    return f"{week_start.strftime(fmt)} – {week_end.strftime(fmt)}, {week_end.year}"


def save_deals(deals: list[dict]) -> None:
    """Write current week's deals to deals.json."""
    payload = {
        "weekLabel":   get_week_label(),
        "fetchedAt":   datetime.now(timezone.utc).isoformat(),
        "dealCount":   len(deals),
        "deals":       deals,
    }
    DEALS_FILE.write_text(json.dumps(payload, indent=2))
    print(f"[scraper] Saved {len(deals)} deals to {DEALS_FILE}")


def append_history(deals: list[dict]) -> None:
    """Append this week's snapshot to history.json (never overwrites old data)."""
    week_label = get_week_label()

    # Load existing history or start fresh
    if HIST_FILE.exists():
        history = json.loads(HIST_FILE.read_text())
    else:
        history = []

    # Don't duplicate — skip if this exact week is already recorded
    existing_weeks = {entry["weekLabel"] for entry in history}
    if week_label in existing_weeks:
        print(f"[scraper] Week '{week_label}' already in history — skipping append")
        return

    history.append({
        "weekLabel": week_label,
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
        "deals": deals,
    })

    HIST_FILE.write_text(json.dumps(history, indent=2))
    print(f"[scraper] History now has {len(history)} weeks recorded")


# ── MAIN ───────────────────────────────────────────────────────────────────────

def run():
    print("=" * 60)
    print(f"  Sandals 7·7·7 Scraper  —  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    deals = scrape_777_deals()

    if not deals:
        print("[scraper] ⚠️  No deals extracted. The page structure may have changed.")
        print("[scraper]    Check SANDALS_777_URL and update selectors if needed.")
        return

    save_deals(deals)
    append_history(deals)
    print("[scraper] ✅ Done!")


if __name__ == "__main__":
    run()
