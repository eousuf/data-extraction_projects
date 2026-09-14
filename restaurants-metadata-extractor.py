import json
import os
import re
import time
from urllib.parse import quote_plus
from typing import Optional, Dict, List
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
    """Removes private use unicode icon glyphs (\uE000-\uF8FF) and normalizes whitespace."""
    if not text:
        return None
    cleaned = re.sub(r'[\uE000-\uF8FF]', '', text)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    cleaned = re.sub(r'^[,\s\-\•\·]+', '', cleaned).strip()
    return cleaned if cleaned else None

def parse_review_count(raw_str: Optional[str]) -> Optional[int]:
    """Parses review count values from formats like '747', '(1,250)', or '4.3K'."""
    if not raw_str:
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

def extract_reviews_from_text(text: Optional[str]) -> int:
    """Robustly extracts total review count integer from multi-line card text."""
    if not text:
        return 0
    # Pattern 1: (4,337) or (4.3K)
    m1 = re.search(r'\(([\d\.,]+[KM]?)\)', text)
    if m1:
        val = parse_review_count(m1.group(1))
        if val is not None:
            return val
            
    # Pattern 2: 4,337 reviews or 4.3K reviews
    m2 = re.search(r'([\d\.,]+[KM]?)\s*reviews?', text, re.IGNORECASE)
    if m2:
        val = parse_review_count(m2.group(1))
        if val is not None:
            return val

    # Pattern 3: rating review count combo e.g. 4.2 ★ 4,337
    m3 = re.search(r'[\d\.]+\s*★\s*\(?([\d\.,]+[KM]?)\)?', text)
    if m3:
        val = parse_review_count(m3.group(1))
        if val is not None:
            return val

    return 0

def normalize_name(s: str) -> str:
    """Strips punctuation and apostrophes for accurate token matching."""
    if not s:
        return ""
    s = s.lower().replace("'", "").replace("’", "")
    return re.sub(r'[^a-z0-9\s]', ' ', s)

def is_name_match(search_name: str, candidate_title: str) -> bool:
    """Checks if search_name tokens exist in candidate_title."""
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

def is_food_establishment(category_or_text: str, title_str: str) -> bool:
    """Ensures place belongs to a restaurant/food category."""
    combined = f"{category_or_text or ''} {title_str or ''}".lower()
    return any(keyword in combined for keyword in FOOD_KEYWORDS)

def is_in_bangladesh(url: str, address: Optional[str]) -> bool:
    """Validates if coordinates or address belong to Bangladesh."""
    if not url and not address:
        return True
    coord_match = re.search(r'@(-?\d+\.\d+),(-?\d+\.\d+)', url or '')
    if coord_match:
        lat, lng = float(coord_match.group(1)), float(coord_match.group(2))
        if (BANGLADESH_BOUNDS["min_lat"] <= lat <= BANGLADESH_BOUNDS["max_lat"] and
            BANGLADESH_BOUNDS["min_lng"] <= lng <= BANGLADESH_BOUNDS["max_lng"]):
            return True
        return False
    
    addr_lower = (address or "").lower()
    bd_cities = ["bangladesh", "dhaka", "chittagong", "chattogram", "sylhet", "rajshahi", 
                 "khulna", "barisal", "rangpur", "mymensingh", "comilla", "gazipur", "mirpur",
                 "dhanmondi", "uttara", "gulshan", "banani", "motijheel"]
    return any(city in addr_lower for city in bd_cities)

def load_target_restaurants() -> List[str]:
    """Load target list from main CSV, fallback to sample CSV, or default array."""
    if os.path.exists(CSV_PATH):
        print(f"Loading targets from '{CSV_PATH}'...")
        return pd.read_csv(CSV_PATH)["name"].tolist()
    elif os.path.exists(SAMPLE_CSV_PATH):
        print(f"Notice: '{CSV_PATH}' not found. Loading targets from '{SAMPLE_CSV_PATH}'...")
        return pd.read_csv(SAMPLE_CSV_PATH)["name"].tolist()
    else:
        print(f"Notice: No CSV file found. Using default fallback list.")
        return DEFAULT_RESTAURANTS

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

                # Dismiss consent popup if present
                consent_btn = page.locator("button:has-text('Accept all'), button:has-text('I agree')").first
                if consent_btn.is_visible(timeout=1500):
                    consent_btn.click()

                # Allow Google Maps search UI to settle
                page.wait_for_timeout(3000)

                feed_element = page.locator("div[role='feed']").first
                if feed_element.is_visible(timeout=3000):
                    # Scroll feed to lazy-load top branches
                    for _ in range(4):
                        feed_element.evaluate("el => el.scrollBy(0, 800)")
                        page.wait_for_timeout(400)

                    results_locators = page.locator("div.Nv2pk, a[href*='/maps/place/']")
                    results_count = results_locators.count()

                    best_index = -1
                    max_reviews = -1

                    for i in range(min(results_count, 15)):
                        item = results_locators.nth(i)
                        card_text = item.inner_text()

                        # Extract card title
                        candidate_title = ""
                        title_el = item.locator(".fontHeadlineSmall, div.qBF1Pd, div.fontTitleMedium").first
                        if title_el.is_visible():
                            candidate_title = clean_text(title_el.inner_text()) or ""
                        if not candidate_title:
                            candidate_title = clean_text(item.get_attribute("aria-label")) or ""
                        if not candidate_title and card_text:
                            candidate_title = clean_text(card_text.split('\n')[0]) or ""

                        if not is_name_match(raw_name, candidate_title):
                            continue

                        rev_count = extract_reviews_from_text(card_text)

                        if rev_count >= max_reviews:
                            max_reviews = rev_count
                            best_index = i

                    if best_index != -1:
                        target = results_locators.nth(best_index)
                        link_inside = target.locator("a[href*='/maps/place/']").first
                        if link_inside.is_visible():
                            link_inside.click()
                        else:
                            target.click()
                        page.wait_for_timeout(3000)
                    else:
                        print(f"  -> Skipping: No matching search result found for '{raw_name}'.")
                        results.append(record)
                        continue

                # Wait for detail view H1 title to populate
                h1_text = ""
                for _ in range(10):
                    h1_el = page.locator("h1").first
                    if h1_el.is_visible():
                        val = clean_text(h1_el.inner_text())
                        if val and val.lower() not in ["results", "search results", "places"]:
                            h1_text = val
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

                # Rating Extraction
                rating_el = page.locator("span[aria-label*='star'], div[aria-label*='star'], span.ceA1da, div.F7L83c").first
                if rating_el.is_visible(timeout=1500):
                    aria_val = rating_el.get_attribute("aria-label") or rating_el.inner_text()
                    match = re.search(r'([\d\.]+)', aria_val or '')
                    if match and float(match.group(1)) <= 5.0:
                        record["rating"] = match.group(1)

                # Review Count Extraction
                reviews_el = page.locator("button[aria-label*='reviews'], span[aria-label*='reviews']").first
                if reviews_el.is_visible(timeout=1500):
                    aria_val = reviews_el.get_attribute("aria-label") or reviews_el.inner_text()
                    record["reviews_count"] = parse_review_count(aria_val)

                # Address Extraction
                address_el = page.locator("button[data-item-id='address']").first
                if address_el.is_visible(timeout=1500):
                    record["address"] = clean_text(address_el.inner_text())

                # Geofence Validation
                if not is_in_bangladesh(page.url, record["address"]):
                    print(f"  -> Skipping: Location '{record['place_name']}' is outside Bangladesh.")
                    results.append(record)
                    continue

                # Phone & Website Extraction
                phone_el = page.locator("button[data-item-id*='phone']").first
                if phone_el.is_visible(timeout=1500):
                    record["phone"] = clean_text(phone_el.inner_text())

                website_el = page.locator("a[data-item-id='authority']").first
                if website_el.is_visible(timeout=1500):
                    record["website"] = website_el.get_attribute("href")

                # About Tab Metadata Extraction
                about_tab = page.locator("button[role='tab']:has-text('About')").first
                if about_tab.is_visible(timeout=2000):
                    about_tab.click()
                    page.wait_for_timeout(1000)

                    panel = page.locator("div.m6QErb[role='region']").first
                    if not panel.is_visible():
                        panel = page.locator("div.m6QErb").first

                    if panel.is_visible():
                        for _ in range(3):
                            panel.evaluate("el => el.scrollBy(0, 500)")
                            page.wait_for_timeout(200)

                    about_dict = {}
                    section_headers = page.locator("h2")
                    for i in range(section_headers.count()):
                        header_text = clean_text(section_headers.nth(i).inner_text())
                        if not header_text or header_text.lower() in ["about", "overview"]:
                            continue

                        parent = section_headers.nth(i).locator("xpath=ancestor::div[contains(@class, 'iP2WAd') or contains(@class, 'm6QErb')][1]")
                        items = parent.locator("span, div.fontBodyMedium").all_inner_texts()
                        
                        clean_items = []
                        for item in items:
                            c_item = clean_text(item)
                            if c_item and c_item != header_text and len(c_item) < 60:
                                if c_item not in clean_items:
                                    clean_items.append(c_item)

                        if clean_items:
                            about_dict[header_text] = clean_items

                    record["about_metadata"] = json.dumps(about_dict, ensure_ascii=False)

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