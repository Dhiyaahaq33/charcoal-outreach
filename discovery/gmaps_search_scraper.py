"""Autonomous Google Maps SEARCH scraper - no pre-made list needed. Runs queries like "charcoal
importer in Turkey" directly against Google Maps search, scrolls the results panel, and scrapes
each place found. This is the fully-autonomous counterpart to gmaps_scraper.py (which needs a
pre-made shared-list link) - built per user request: "cari aja semua tempat di dunia yang
potential buyer... gak harus sekarang yang penting bisa jalan virtual nantinya."

Coverage is capped per run (MAX_COMBOS_PER_RUN query x country pairs) to keep GitHub Actions
runtime bounded - Maps search + scroll + per-place scraping is slow (each combo can take 1-3
minutes). Which combos run each day rotates deterministically by day-of-year, so a full sweep of
all countries x queries happens gradually across many daily cron runs instead of overwhelming a
single run. Nothing is silently dropped forever - every combo gets its turn eventually.

Selectors are Google Maps' current (2026) search-results DOM - same brittleness caveat as
gmaps_scraper.py: verify against a live search (F12 > Inspect a result card) if this starts
returning 0 results.
"""

import logging
import random
import re
import time
from datetime import date

import pycountry

from discovery.gmaps_scraper import _text_or_none, _force_en
from discovery.dedupe import COUNTRY_NAME_OVERRIDES

logger = logging.getLogger(__name__)

RESULT_LINK_SELECTOR = "a.hfpxzc"
RESULTS_FEED_SELECTOR = "div[role='feed']"

BUYER_QUERIES = [
    # Trade/wholesale - generic charcoal buyers/resellers
    "charcoal importer",
    "charcoal wholesaler",
    "charcoal distributor",
    # Product-specific - match PT Cahaya Woodchar's actual catalogue (2026 edition: Sawdust,
    # BBQ Briquette, Coconut Shell, Mix Hardwood, Binchotan, Halaban Wood charcoal)
    "hardwood charcoal supplier",
    "coconut charcoal importer",
    "bbq charcoal supplier",
    "briquette charcoal importer",
    "binchotan charcoal supplier",
    # End-use businesses - per user request to go beyond "charcoal traders" and target companies
    # that consume charcoal for their own operations (catalogue explicitly lists these use cases:
    # household/commercial/industrial, BBQ, street food, commercial kitchens, shisha, Japanese
    # grilling, high-end restaurants, steakhouses, catering)
    "shisha charcoal distributor",
    "restaurant charcoal supplier",
    "steakhouse charcoal supplier",
    "hotel charcoal supplier",
    "catering charcoal supplier",
    "biomass fuel importer",
]

# TRUE global coverage per user request ("nyari di semua negara bisa termasuk indonesia") -
# every country pycountry knows about (~249, incl. territories), not just the curated ~71-country
# list used for existing-client timezone/DO-DONT logic. COUNTRY_NAME_OVERRIDES keeps spelling
# consistent with the sheet's convention (e.g. "Korea, Republic of" -> "South Korea") so dedup
# against existing rows still matches correctly.
TARGET_COUNTRIES = sorted({
    COUNTRY_NAME_OVERRIDES.get(c.name, c.name) for c in pycountry.countries
})

MAX_COMBOS_PER_RUN = 60
MAX_RESULTS_PER_COMBO = 8


def _all_combos():
    return [(q, c) for q in BUYER_QUERIES for c in TARGET_COUNTRIES]


def _todays_combos():
    """Deterministic daily rotation - same day always picks the same slice, so re-running
    discovery_main.py manually the same day doesn't skip ahead or repeat work unpredictably."""
    combos = _all_combos()
    day_index = date.today().toordinal()
    start = (day_index * MAX_COMBOS_PER_RUN) % len(combos)
    end = start + MAX_COMBOS_PER_RUN
    if end <= len(combos):
        return combos[start:end]
    return combos[start:] + combos[:end - len(combos)]


def _scroll_feed(page, target_count, max_rounds=15):
    stagnant = 0
    last_count = -1
    for _ in range(max_rounds):
        try:
            count = page.locator(RESULT_LINK_SELECTOR).count()
        except Exception:
            count = 0
        if count >= target_count or count == last_count:
            stagnant += 1
            if stagnant >= 3:
                break
        else:
            stagnant = 0
        last_count = count
        try:
            page.locator(RESULTS_FEED_SELECTOR).first.hover()
            page.mouse.wheel(0, 1200)
        except Exception:
            pass
        page.wait_for_timeout(600)
    return last_count


def _scrape_place(page, url):
    row = {
        "name": None, "category": None, "address": None, "phone": None,
        "website": None, "maps_url": url,
    }
    try:
        page.goto(_force_en(url), wait_until="domcontentloaded", timeout=20000)
        page.wait_for_selector("h1.DUwDvf", timeout=12000)
        page.wait_for_timeout(300)
    except Exception:
        return row

    row["name"] = _text_or_none(page, "h1.DUwDvf")
    row["category"] = _text_or_none(page, "button.DkEaL")
    row["address"] = _text_or_none(page, "button[data-item-id='address'] div.Io6YTe")
    row["phone"] = _text_or_none(page, "button[data-item-id^='phone:tel:'] div.Io6YTe")
    try:
        site_el = page.locator("a[data-item-id='authority']").first
        if site_el.count():
            row["website"] = site_el.get_attribute("href")
    except Exception:
        pass
    return row


def search_and_scrape(combos=None):
    """combos: list of (query, country) tuples. Defaults to today's rotation slice.
    Returns list of scraped place dicts (name/category/address/phone/website/maps_url/query)."""
    combos = combos if combos is not None else _todays_combos()
    if not combos:
        return []

    from playwright.sync_api import sync_playwright

    all_rows = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
            locale="en-US",
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        page = context.new_page()

        for query, country in combos:
            search_term = f"{query} in {country}"
            search_url = f"https://www.google.com/maps/search/{search_term.replace(' ', '+')}"
            urls = []
            country_confident = True
            try:
                page.goto(_force_en(search_url), wait_until="domcontentloaded", timeout=30000)
                page.wait_for_selector(RESULT_LINK_SELECTOR, timeout=15000)
                _scroll_feed(page, MAX_RESULTS_PER_COMBO)
                links = page.locator(RESULT_LINK_SELECTOR)
                count = min(links.count(), MAX_RESULTS_PER_COMBO)
                urls = [links.nth(i).get_attribute("href") for i in range(count)]
            except Exception:
                # No results FEED found - Maps sometimes redirects straight to a single dominant
                # place instead of showing a list (happens when one match clearly outranks the
                # rest, and Maps' local ranking isn't a strict country filter - verified live: a
                # "in Turkey" query once single-redirected to an Indonesian company). Treat the
                # current page as the one-and-only result, but DON'T trust the searched-for
                # country for it - real country detection (phone/address) decides instead.
                if page.locator("h1.DUwDvf").count():
                    urls = [page.url]
                    country_confident = False
                    logger.info(f"[gmaps-search] '{search_term}' - single dominant place, no "
                                f"list (country NOT assumed, will detect from phone/address)")
                else:
                    logger.warning(f"[gmaps-search] '{search_term}' - no results / blocked")
                    continue

            for url in urls:
                if not url:
                    continue
                row = _scrape_place(page, url)
                if row["name"]:
                    row["query"] = search_term
                    if country_confident:
                        row["country_hint"] = country
                    all_rows.append(row)
                time.sleep(random.uniform(0.6, 1.2))

            logger.info(f"[gmaps-search] '{search_term}': {len(urls)} results scraped")

        browser.close()

    logger.info(f"[gmaps-search] {len(all_rows)} places scraped across {len(combos)} search(es) "
                f"({len(_all_combos())} total combos, full sweep completes gradually over time)")
    return all_rows
