# DATA EXTRACTION FROM GOOGLE MAP

Extracted Bangladesh's Super Shop's **Outlets** and **Metadata** of popular Restaurants from **Google Map**.

---

## Bangladesh Super Shop Outlet Scraper

An asynchronous Python tool using **Playwright** to scrape chain super shop locations (addresses, outlet names, and Google Maps links) across Bangladesh using spatial grid coordinates.

---

## Features

* **Spatial Grid Scanning:** Coordinates searching across 14 geographical grid centers (Dhaka North/South/East/West, Chattogram, Sylhet, etc.) to capture all outlets.
* **Fuzzy Brand Correction:** Automatically corrects typos in brand inputs (e.g., `unemart` ➔ `Unimart`, `mina bajar` ➔ `Meena Bazar`).
* **Address Data Cleaning:** Strips out Plus Codes (e.g., `R9F8+6PP`), control characters, and raw text noise to produce clean addresses.
* **Category & Sub-Vendor Filtering:** Automatically excludes sub-vendors inside larger shops (e.g., cosmetic counters, amusement centers) and irrelevant business categories.
* **Async Engine:** Powered by `asyncio` and Playwright for fast headless/headful scraping with custom fallback clicking.
* **Automated CSV Export:** Saves all deduplicated results into a structured `.csv` file named after the brand.

---

## Bangladesh Popular Restaurants Metadata Scraper

Another Python tool using **Playwright** to scrap metadata of restaurants (rating, number of reviews, phone, website, coordinate, address, service options, accessibility, payment options etc.) from google map. 

---

## Features
**Read Restaurants Names & Search On Google Map:** From a csv file that contains a list of restaurants and search the name of the search bar of google map.
**Selection Criteria:** Select the names from suggestions that only contains food keywords ("restaurant", "food", "cafe" etc). Since a location boundary is set earlier, it'll also check whether the restaurant falls within that boundary or not. Then from that filter, only check the one with highest rating followed by highest number of reviews incase the ratings are tied.
**Extract Metadata:** After the screening, collect the place name, address, location, phone, website and other contents from "About" section of the restaurant card.
**Store Data:** Finally dump those info into both csv and json format.

---

## Requirements

* Python 3.8+
* Playwright
* A list of restaurant in CSV format. (A dummy CSV file is given)

---

## Quick Start

### 1. Clone the repository
```bash
git clone [https://github.com/your-username/bd-supershop-scraper.git](https://github.com/your-username/bd-supershop-scraper.git)
cd bd-supershop-scraper