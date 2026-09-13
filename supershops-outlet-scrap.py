import asyncio
import random
import urllib.parse
import difflib
import re
import csv
from playwright.async_api import async_playwright

KNOWN_BRANDS = [
    "Agora",
    "Shwapno",
    "Meena Bazar",
    "Daily Shopping",
    "Unimart",
    "Prince Bazar",
    "Almas Super Shop",
    "Trust Family Super Store"
]

GRID_CENTERS = [
    ("Dhaka North", 23.8500, 90.3800, 13),  #(Uttara, Mirpur, Airport)
    ("Dhaka South", 23.7250, 90.3950, 13),  #(Dhanmondi, Old Dhaka, Motijheel)
    ("Dhaka East", 23.7850, 90.4250, 13),   #(Gulshan, Banani, Badda, Rampura)
    ("Dhaka West", 23.7700, 90.3400, 13),   #(Mohammadpur, Shyamoli, Savar Border)
    ("Narayanganj City", 23.6238, 90.5000, 13),
    ("Gazipur City", 23.9999, 90.4203, 13),
    ("Savar / Ashulia", 23.8583, 90.2667, 13),
    ("Mymensingh City", 24.7471, 90.4203, 13),
    ("Chattogram Metro", 22.3400, 91.8000, 13),
    ("Sylhet City", 24.8949, 91.8687, 13),
    ("Rajshahi City", 24.3745, 88.6042, 13),
    ("Khulna City", 22.8456, 89.5403, 13),
    ("Barishal City", 22.7010, 90.3535, 13),
    ("Rangpur City", 25.7439, 89.2752, 13),
]

EXCLUDED_CATEGORIES = [
    "apartment", "housing", "residential", "condominium", 
    "real estate", "society", "building", "association", "corporate office",
    "warehouse", "shoe store", "jewelry designer", "momo restaurant", 
    "restaurant", "bakery", "candy store", "cafe", "sweets shop", "clothing store",
    "cosmetics store", "children amusement center", "shopping center"
]

PLUS_CODE_REGEX = r'\b[A-Z0-9]{4,5}\+[A-Z0-9]{2,5}\b,?\s*'

def clean_address(raw_address: str) -> str:
    clean = raw_address.replace("", "").replace("\n", " ").strip()
    clean = re.sub(PLUS_CODE_REGEX, "", clean).strip()
    clean = clean.strip(", ")
    return clean if clean else "N/A"

def correct_brand_name(user_input: str) -> str:
    clean_input = user_input.strip()
    matches = difflib.get_close_matches(clean_input, KNOWN_BRANDS, n=1, cutoff=0.4)
    if matches:
        matched_brand = matches[0]
        print(f" Auto-corrected '{user_input}' to '{matched_brand}'")
        return matched_brand
    else:
        print(f" Brand '{user_input}' not in preset list. Searching directly...")
        return clean_input.title()

async def scrape_spatial_grid(target_brand: str):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        seen_composite_keys = set()
        all_results = []
        feed_selector = 'div[role="feed"]'

        for zone_name, lat, lng, zoom in GRID_CENTERS:
            query = urllib.parse.quote(target_brand)
            search_url = f"https://www.google.com/maps/search/{query}/@{lat},{lng},{zoom}z?hl=en"

            print(f"\n📡 Scanning Tile: [{zone_name}]...")
            await page.goto(search_url, timeout=60000)

            try:
                await page.wait_for_selector(feed_selector, timeout=6000)
            except Exception:
                if await page.locator('button[data-item-id="address"]').count() > 0:
                    pass
                else:
                    print(f"   No listings found in {zone_name}. Moving to next tile.")
                    continue

            if await page.locator(feed_selector).count() > 0:
                previous_height = 0
                while True:
                    await page.evaluate(f"document.querySelector('{feed_selector}').scrollTop = document.querySelector('{feed_selector}').scrollHeight")
                    await page.wait_for_timeout(random.randint(1200, 2000))
                    
                    current_height = await page.evaluate(f"document.querySelector('{feed_selector}').scrollHeight")
                    end_visible = await page.locator("text=You've reached the end of the list.").is_visible()
                    
                    if current_height == previous_height or end_visible:
                        break
                    previous_height = current_height

                cards = await page.locator('div[role="article"]').all()
            else:
                cards = [page]

            for card in cards:
                if card != page:
                    try:
                        # Target inner link with force=True to trigger Google Maps panel opening safely
                        link = card.locator('a[href*="/maps/place/"]').first
                        if await link.count() > 0:
                            await link.click(force=True, timeout=3000)
                        else:
                            await card.click(force=True, timeout=3000)
                        await page.wait_for_timeout(1200)
                    except Exception as e:
                        continue

                store_name = ""
                h1_elements = await page.locator('h1').all()
                for h1 in h1_elements:
                    text = (await h1.inner_text()).strip()
                    if text and text.lower() not in ["results", f"results for {target_brand.lower()}", "google maps"]:
                        store_name = text
                        break

                if not store_name:
                    continue

                brand_keyword = target_brand.split()[0].lower()
                if brand_keyword not in store_name.lower():
                    continue

                category = ""
                category_locator = page.locator('button[jsaction*="category"]')
                if await category_locator.count() > 0:
                    category = await category_locator.first.inner_text()

                if any(bad_cat in category.lower() for bad_cat in EXCLUDED_CATEGORIES):
                    continue

                address_locator = page.locator('button[data-item-id="address"]')
                if await address_locator.count() > 0:
                    raw_address = await address_locator.inner_text()
                    address = clean_address(raw_address)
                else:
                    address = "N/A"

                composite_key = f"{store_name.lower().strip()} | {address.lower().strip()}"
                if composite_key in seen_composite_keys or address == "N/A":
                    continue

                seen_composite_keys.add(composite_key)

                store_url = page.url if "/maps/place/" in page.url else "N/A"

                store_data = {
                    "name": store_name,
                    "address": address,
                    "url": store_url
                }
                
                all_results.append(store_data)
                print(f"    [{len(all_results)}] {store_name}")
                print(f"       Address: {address}")
                print(f"       URL: {store_url}")

        await browser.close()
        
        filename = f"{target_brand.lower().replace(' ', '_')}_outlets.csv"
        if all_results:
            with open(filename, mode="w", newline="", encoding="utf-8") as csv_file:
                fieldnames = ["name", "address", "url"]
                writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(all_results)
            
            print("\n" + "="*60)
            print(f" Grid Search Complete!")
            print(f" Successfully exported {len(all_results)} records to '{filename}'")
            print("="*60)
        else:
            print("\ No records found to export.")

if __name__ == "__main__":
    user_input = input("Enter the super shop name: ")
    corrected_brand = correct_brand_name(user_input)
    asyncio.run(scrape_spatial_grid(corrected_brand))