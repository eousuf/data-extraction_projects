import json
import os
import re
import time
from urllib.parse import quote_plus
from typing import Optional, Dict, List, Tuple
import pandas as pd
from playwright.sync_api import sync_playwright

CSV_PATH = "top-50 restaurants.csv"
SAMPLE_CSV_PATH = "dummy-restaurants.sample.csv"
DEFAULT_RESTAURANTS = ["KFC", "BFC", "Pizza Hut", "Burger King", "Domino's Pizza"]

BANGLADESH_BOUNDS = {
    "min_lat": 20.57,
    "max_lat": 26.63,
    "min_lng": 88.01,
    "max_lng": 92.67
}

FOOD_KEYWORDS = {
    "restaurant", "food", "cafe", "café", "coffee", "bistro", "bakery", "diner", "lunch",
    "eatery", "kitchen", "kebab", "kabab", "pizza", "burger", "biriyani", "biryani",
    "grill", "tea", "snack", "sweets", "catering", "dining", "seafood", "chicken",
    "steak", "caterer", "fast food", "ramen", "sushi", "lounge", "bfc", "kfc", "hut"
}

def clean_text(text: Optional[str]) -> Optional[str]:
    if not text:                                        #Normalize address
        return None
    cleaned = re.sub(r'[\uE000-\uF8FF]', '', text)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    cleaned = re.sub(r'^[,\s\-\•\·]+', '', cleaned).strip()
    return cleaned if cleaned else None

def parse_review_count(raw_str: Optional[str]) -> Optional[int]:
    if not raw_str:                                     #Review check
        return None
    raw_str = raw_str.upper().replace(',', '').strip()
    match = re.search(r'([\d\.]+)\s*([KM])?', raw_str)
    if match:
        num_str, suffix = match.group(1), match.group(2)
        try:
            val = float(num_str)
            if suffix == 'K':
                val *= 1000
            elif suffix == 'M':
                val *= 1000000
            return int(val)
        except ValueError:
            return None
    return None

def extract_reviews_from_text(text: Optional[str]) -> int:  #extracts total review count integer from multi-line card text
    if not text:
        return 0
    m1 = re.search(r'\(([\d\.,]+[KM]?)\)', text)
    if m1:
        val = parse_review_count(m1.group(1))
        if val is not None:
            return val

    m2 = re.search(r'([\d\.,]+[KM]?)\s*reviews?', text, re.IGNORECASE)
    if m2:
        val = parse_review_count(m2.group(1))
        if val is not None:
            return val

    m3 = re.search(r'[\d\.]+\s*★\s*\(?([\d\.,]+[KM]?)\)?', text)
    if m3:
        val = parse_review_count(m3.group(1))
        if val is not None:
            return val

    return 0

def extract_rating_from_text(text: Optional[str]) -> Optional[float]:
    """
    Extracts the star rating (e.g. 4.5) from a search-result card's text.
    NOTE: card layout puts the rating immediately before the review-count
    parenthetical or the star glyph, so we anchor on those patterns first
    before falling back to a bare '4.5'-style token, to avoid accidentally
    picking up an unrelated number (address, price level, etc).
    """
    if not text:
        return None

    m1 = re.search(r'([1-5]\.\d)\s*\(', text)
    if m1:
        return float(m1.group(1))

    m2 = re.search(r'([1-5]\.\d)\s*★', text)
    if m2:
        return float(m2.group(1))

    m3 = re.search(r'\b([1-5]\.\d)\b', text)
    if m3:
        return float(m3.group(1))

    return None

def normalize_name(s: str) -> str:         #Accurate token matching
    if not s:
        return ""
    s = s.lower().replace("'", "").replace("’", "")
    return re.sub(r'[^a-z0-9\s]', ' ', s)

def is_name_match(search_name: str, candidate_title: str) -> bool:
    if not search_name or not candidate_title:
        return False

    s_norm = normalize_name(search_name)
    c_norm = normalize_name(candidate_title)

    if c_norm.strip() in ["results", "search results", "places"]:
        return False

    s_words = [w for w in s_norm.split() if w]
    c_words = set(c_norm.split())

    if not s_words:
        return False

    return all(w in c_words for w in s_words)

def extract_coords(url: Optional[str]) -> Optional[Tuple[float, float]]:    #Pulls (lat, lng) out of a Google Maps URL. Checks for both '@lat,lng' and '!3dlat!4dlng' formats.
    if not url:
        return None
        
    # 1. Try standard @lat,lng format
    m1 = re.search(r'@(-?\d+\.\d+),(-?\d+\.\d+)', url)
    if m1:
        return float(m1.group(1)), float(m1.group(2))
        
    # 2. Try Google Maps data parameter format (!3d<lat>!4d<lng>)
    m2 = re.search(r'!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)', url)
    if m2:
        return float(m2.group(1)), float(m2.group(2))
        
    return None

def coords_in_bangladesh(lat: float, lng: float) -> bool:
    return (BANGLADESH_BOUNDS["min_lat"] <= lat <= BANGLADESH_BOUNDS["max_lat"] and
            BANGLADESH_BOUNDS["min_lng"] <= lng <= BANGLADESH_BOUNDS["max_lng"])

def is_in_bangladesh(url: Optional[str], address: Optional[str]) -> bool:
    """Validates if coordinates or address belong to Bangladesh."""
    if not url and not address:
        return True

    # 1. Check if the URL provides coordinates within the boundary box
    coords = extract_coords(url)
    if coords:
        return coords_in_bangladesh(*coords)

    # 2. Fallback: Check if the exact country name is in the address string
    addr_lower = (address or "").lower()
    return "bangladesh" in addr_lower

def load_target_restaurants() -> List[str]: #Load target list from main CSV, fallback to sample CSV, or default array.
    if os.path.exists(CSV_PATH):
        print(f"Loading targets from '{CSV_PATH}'...")
        return pd.read_csv(CSV_PATH)["name"].tolist()
    elif os.path.exists(SAMPLE_CSV_PATH):
        print(f"Notice: '{CSV_PATH}' not found. Loading targets from '{SAMPLE_CSV_PATH}'...")
        return pd.read_csv(SAMPLE_CSV_PATH)["name"].tolist()
    else:
        print(f"Notice: No CSV file found. Using default fallback list.")
        return DEFAULT_RESTAURANTS

def select_best_candidate(candidates: List[Dict]) -> Optional[Dict]:
    """
    Picks the best branch among name-matched search-result candidates.
    Selection rule: prefer candidates that fall within the Bangladesh boundary; 
    among those, prefer highest rating, then highest review count as the tiebreaker.
    """
    if not candidates:
        return None

    known_in_bd = [c for c in candidates if c["in_bd"] is True]
    pool = known_in_bd if known_in_bd else candidates

    def score(c):
        rating = c["rating"] if c["rating"] is not None else -1.0
        reviews = c["reviews"] if c["reviews"] is not None else -1
        return (rating, reviews)

    return max(pool, key=score)

def run_scraper():
    restaurant_names = load_target_restaurants()
    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            locale="en-US",
            geolocation={"latitude": 23.8103, "longitude": 90.4125},
            permissions=["geolocation"],
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        for index, raw_name in enumerate(restaurant_names, 1):
            search_query = f"{raw_name.strip()}, Bangladesh"
            print(f"\n[{index}/{len(restaurant_names)}] Searching: {search_query}")

            record = {
                "search_name": raw_name,
                "place_name": None,
                "rating": None,
                "reviews_count": None,
                "address": None,
                "phone": None,
                "website": None,
                "about_metadata": "{}"
            }

            try:
                encoded_query = quote_plus(search_query)
                search_url = f"https://www.google.com/maps/search/{encoded_query}?hl=en"
                page.goto(search_url, wait_until="domcontentloaded", timeout=30000)

                consent_btn = page.locator("button:has-text('Accept all'), button:has-text('I agree')").first
                if consent_btn.is_visible(timeout=1500):
                    consent_btn.click()

                place_link_selector = "a[href*='/maps/place/']"
                try:
                    page.locator(place_link_selector).first.wait_for(state="attached", timeout=8000)
                except Exception:
                    print(f"  [debug] no {place_link_selector} link attached within 8s")

                page.wait_for_timeout(1000)
                try:
                    page.mouse.wheel(0, 2000)
                    page.wait_for_timeout(600)
                except Exception:
                    pass

                anchors = page.locator(place_link_selector)
                anchor_count = anchors.count()
                print(f"  [debug] {anchor_count} place link(s) detected on page")

                already_on_place_page = anchor_count == 0 and "/maps/place/" in page.url
                candidates = []
                matched_count = 0
                seen_hrefs = set()

                if already_on_place_page:
                    print(f"  [debug] no place links found but current URL is already a place page - "
                          f"treating it as the sole candidate (url: {page.url})")
                else:
                    for i in range(min(anchor_count, 20)):
                        anchor = anchors.nth(i)
                        try:
                            href = anchor.get_attribute("href")
                        except Exception:
                            href = None

                        if not href or href in seen_hrefs:
                            continue
                        seen_hrefs.add(href)

                        aria_label = clean_text(anchor.get_attribute("aria-label")) or ""

                        anchor_text = ""
                        try:
                            anchor_text = anchor.inner_text() or ""
                        except Exception:
                            anchor_text = ""

                        try:
                            card_text = anchor.evaluate(
                                """el => {
                                    let node = el;
                                    for (let i = 0; i < 8 && node; i++) {
                                        const text = node.innerText || '';
                                        if (/[1-5]\\.\\d/.test(text) && text.length > 0 && text.length < 800) {
                                            return text;
                                        }
                                        node = node.parentElement;
                                    }
                                    return el.innerText || '';
                                }"""
                            ) or ""
                        except Exception:
                            card_text = anchor_text

                        candidate_title = aria_label or clean_text(anchor_text) or ""
                        search_text_for_stats = card_text or aria_label or anchor_text

                        is_match = is_name_match(raw_name, candidate_title)
                        if is_match:
                            matched_count += 1
                            rev_count = extract_reviews_from_text(search_text_for_stats)
                            rating_val = extract_rating_from_text(search_text_for_stats)
                            coords = extract_coords(href)
                            in_bd = coords_in_bangladesh(*coords) if coords else None

                            candidates.append({
                                "index": i,
                                "title": candidate_title,
                                "rating": rating_val,
                                "reviews": rev_count,
                                "href": href,
                                "in_bd": in_bd,
                            })

                    print(f"  [debug] {matched_count} of {len(seen_hrefs)} unique link(s) name-matched '{raw_name}'")

                if already_on_place_page:
                    pass
                else:
                    best = select_best_candidate(candidates)

                    if best is not None and best.get("href"):
                        print(f"  [debug] selected candidate: title='{best['title']}' "
                            f"rating={best['rating']} reviews={best['reviews']} in_bd={best['in_bd']}")
                        
                        page.goto(best["href"], wait_until="domcontentloaded", timeout=30000)
                        page.wait_for_timeout(2000)
                    else:
                        print(f"  -> Skipping: No matching search result found for '{raw_name}'.")
                        results.append(record)
                        continue

                h1_text = ""
                header_selectors = [
                    "h1.fontHeadlineLarge",
                    "h1.DUwfx",
                    "h1[class*='fontHeadline']",
                    "h1",
                    "div.DUwfx",
                    ".fontTitleLarge"
                ]

                for _ in range(12):
                    for sel in header_selectors:
                        el = page.locator(sel).first
                        if el.is_visible():
                            val = clean_text(el.inner_text())
                            if val and val.lower() not in ["results", "search results", "places"]:
                                h1_text = val
                                break
                    if h1_text:
                        break
                    page.wait_for_timeout(500)

                if not h1_text:
                    print(f"  -> Skipping: Loaded venue heading is missing or invalid.")
                    results.append(record)
                    continue

                record["place_name"] = h1_text

                if not is_name_match(raw_name, record["place_name"]):
                    print(f"  -> Skipping: Loaded venue '{record['place_name']}' does not match '{raw_name}'.")
                    results.append(record)
                    continue

                rating_el = page.locator("div.F7L83c, span.ceA1da, div.fontBodyMedium span[aria-hidden='true']").first
                if rating_el.is_visible(timeout=1500):
                    val = clean_text(rating_el.inner_text() or rating_el.get_attribute("aria-label"))
                    match = re.search(r'([1-5]\.\d)', val or '')
                    if match:
                        record["rating"] = match.group(1)

                reviews_el = page.locator("button[aria-label*='reviews'], span[aria-label*='reviews']").first
                if reviews_el.is_visible(timeout=1500):
                    aria_val = reviews_el.get_attribute("aria-label") or reviews_el.inner_text()
                    record["reviews_count"] = parse_review_count(aria_val)

                address_el = page.locator("button[data-item-id='address']").first
                if address_el.is_visible(timeout=1500):
                    record["address"] = clean_text(address_el.inner_text())

                if not is_in_bangladesh(page.url, record["address"]):
                    print(f"  -> Skipping: Location '{record['place_name']}' is outside Bangladesh.")
                    results.append(record)
                    continue

                phone_el = page.locator("button[data-item-id*='phone']").first
                if phone_el.is_visible(timeout=1500):
                    record["phone"] = clean_text(phone_el.inner_text())

                website_el = page.locator("a[data-item-id='authority']").first
                if website_el.is_visible(timeout=1500):
                    record["website"] = website_el.get_attribute("href")

                about_tab = page.locator("button[role='tab']:has-text('About')").first
                if about_tab.is_visible(timeout=2000):
                    about_tab.click()
                    page.wait_for_timeout(1000)

                    panel_selectors = [
                        "div[role='tabpanel']",
                        "div.m6QErb[role='region']",
                        "div.m6QErb",
                    ]
                    panel = None
                    for sel in panel_selectors:
                        candidate_panel = page.locator(sel).first
                        if candidate_panel.count() > 0 and candidate_panel.is_visible():
                            panel = candidate_panel
                            break

                    about_dict = {}

                    if panel:
                        section_selectors = ["div.iP2WAd", "div.g27P1d", "div:has(> h2)"]
                        max_scroll_steps = 15
                        stale_streak = 0
                        prev_category_count = -1

                        for _step in range(max_scroll_steps):
                            sections = []
                            for sel in section_selectors:
                                found = panel.locator(sel).all()
                                if found:
                                    sections = found
                                    break

                            for section in sections:
                                header_text = None
                                for hsel in ["h2", "div.fontTitleMedium"]:
                                    h_el = section.locator(hsel).first
                                    if h_el.count() > 0 and h_el.is_visible():
                                        header_text = clean_text(h_el.inner_text())
                                        if header_text:
                                            break

                                if not header_text or header_text.lower() in ["about", "overview"]:
                                    continue

                                clean_items = list(about_dict.get(header_text, []))

                                item_els = section.locator("li[aria-label], span[aria-label]").all()
                                for el in item_els:
                                    label = clean_text(el.get_attribute("aria-label"))
                                    if label and label != header_text and label not in clean_items:
                                        clean_items.append(label)

                                if not clean_items:
                                    items = section.locator("li, span, div.fontBodyMedium").all_inner_texts()
                                    for item_text in items:
                                        c_item = clean_text(item_text)
                                        if c_item and c_item != header_text and len(c_item) < 60 and c_item not in clean_items:
                                            clean_items.append(c_item)

                                if clean_items:
                                    about_dict[header_text] = clean_items

                            if len(about_dict) == prev_category_count:
                                stale_streak += 1
                            else:
                                stale_streak = 0
                            prev_category_count = len(about_dict)

                            if stale_streak >= 3:
                                break

                            panel.evaluate("el => el.scrollBy(0, 400)")
                            page.wait_for_timeout(300)

                    record["about_metadata"] = json.dumps(about_dict, ensure_ascii=False)
                    print(f"  [debug] about section: {len(about_dict)} categor(y/ies) captured "
                          f"after {_step + 1 if panel else 0} scroll step(s): {list(about_dict.keys())}")

            except Exception as e:
                print(f"Error processing {raw_name}: {e}")

            results.append(record)
            time.sleep(1)

        browser.close()

    df_output = pd.DataFrame(results)
    df_output.to_csv("scraped_restaurants_metadata.csv", index=False, encoding="utf-8-sig")

    with open("scraped_restaurants_metadata.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print("\nExtraction complete. Files saved: scraped_restaurants_metadata.csv & scraped_restaurants_metadata.json")

if __name__ == "__main__":
    run_scraper()