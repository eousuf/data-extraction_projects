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

---

## Requirements

* Python 3.8+
* Playwright

---

## Quick Start

### 1. Clone the repository
```bash
git clone [https://github.com/your-username/bd-supershop-scraper.git](https://github.com/your-username/bd-supershop-scraper.git)
cd bd-supershop-scraper