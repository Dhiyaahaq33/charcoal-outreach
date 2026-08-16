"""Google Maps *shared list* scraper - ported from gmaps-leads-scraper/gmaps_list_scraper.py,
refactored into an importable function (scrape_lists()) instead of CLI-only. Requires actual
Google Maps shared list URLs (e.g. a saved list "Charcoal Suppliers UAE") - can't discover
listings on its own without one, since Maps has no public search API for this.

Selectors are Google Maps' current (2026) DOM class names - unstable, may break if Google changes
their frontend. If this returns 0 rows for a list that has entries, check GMAPS_ITEM_SELECTOR
against the live page (right-click an entry > Inspect) and update below.
"""

import logging
import random
import re
import time

logger = logging.getLogger(__name__)

ITEM_SELECTOR = "div.BsJqK"
COORD_RE_AT = re.compile(r"/@(-?\d+\.\d+),(-?\d+\.\d+)")
COORD_RE_3D4D = re.compile(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)")


def _force_en(url):
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}hl=en"


_SCROLL_JS = """() => {
    const items = document.querySelectorAll('div.BsJqK');
    if (!items.length) return false;
    let el = items[items.length - 1];
    while (el && el !== document.body) {
        const style = getComputedStyle(el);
        if (/(auto|scroll)/.test(style.overflowY) && el.scrollHeight > el.clientHeight) {
            el.scrollTop = el.scrollHeight;
            return true;
        }
        el = el.parentElement;
    }
    return false;
}"""


def _accept_consent(page):
    for text in ("Accept all", "I agree", "Reject all", "Terima semua"):
        try:
            btn = page.get_by_role("button", name=text, exact=False)
            if btn.count() and btn.first.is_visible(timeout=1000):
                btn.first.click()
                page.wait_for_timeout(500)
                return
        except Exception:
            pass


def _open_list(page, list_url):
    page.goto(_force_en(list_url), wait_until="domcontentloaded", timeout=30000)
    _accept_consent(page)
    page.wait_for_selector(ITEM_SELECTOR, timeout=20000)


def _scroll_to_load_all(page):
    stagnant_rounds = 0
    last_count = -1
    while stagnant_rounds < 5:
        count = page.locator(ITEM_SELECTOR).count()
        if count == last_count:
            stagnant_rounds += 1
        else:
            stagnant_rounds = 0
        last_count = count
        page.evaluate(_SCROLL_JS)
        page.wait_for_timeout(700)
    return last_count


def _collect_place_urls(page, list_url):
    from playwright.sync_api import TimeoutError as PWTimeout

    _open_list(page, list_url)
    total = _scroll_to_load_all(page)
    logger.info(f"[gmaps] found {total} places in list {list_url}")

    urls = []
    for i in range(total):
        items = page.locator(ITEM_SELECTOR)
        if items.count() <= i:
            _scroll_to_load_all(page)
            items = page.locator(ITEM_SELECTOR)
        if items.count() <= i:
            urls.append(None)
            continue

        prev_url = page.url
        try:
            items.nth(i).click(timeout=5000)
            page.wait_for_function(
                "(prev) => window.location.href !== prev", arg=prev_url, timeout=10000,
            )
            urls.append(page.url)
        except Exception:
            urls.append(None)

        try:
            page.go_back(wait_until="domcontentloaded", timeout=15000)
            page.wait_for_selector(ITEM_SELECTOR, timeout=15000)
        except PWTimeout:
            _open_list(page, list_url)
        _scroll_to_load_all(page)
        time.sleep(random.uniform(0.4, 0.9))

    return urls


def _text_or_none(page, selector):
    try:
        loc = page.locator(selector).first
        if loc.count() and loc.is_visible(timeout=800):
            return loc.inner_text(timeout=800).strip()
    except Exception:
        pass
    return None


def _scrape_place_url(page, url):
    from playwright.sync_api import TimeoutError as PWTimeout

    row = {
        "name": None, "category": None, "rating": None, "review_count": None,
        "address": None, "phone": None, "website": None, "maps_url": url,
    }
    if not url:
        return row
    try:
        page.goto(_force_en(url), wait_until="domcontentloaded", timeout=20000)
        page.wait_for_selector("h1.DUwDvf", timeout=15000)
        page.wait_for_timeout(300)
    except PWTimeout:
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

    row["maps_url"] = page.url
    return row


def scrape_lists(list_urls):
    """list_urls: list of Google Maps shared-list URLs. Returns list of dicts
    (name, category, rating, review_count, address, phone, website, maps_url, source_list_url)."""
    if not list_urls:
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

        for list_url in list_urls:
            try:
                urls = _collect_place_urls(page, list_url)
                for url in urls:
                    row = _scrape_place_url(page, url)
                    row["source_list_url"] = list_url
                    if row["name"]:
                        all_rows.append(row)
                    time.sleep(random.uniform(0.8, 1.6))
            except Exception as e:
                logger.error(f"[gmaps] list failed {list_url}: {e}")

        browser.close()

    logger.info(f"[gmaps] scraped {len(all_rows)} places from {len(list_urls)} list(s)")
    return all_rows
