"""B2B directory + Google search scrapers - ported from pt-ekspor-arang-agent's
tools/scraper_tool.py (deprecated system, same business). No login required, rate-limited.

STATUS (tested 2026-08-17): all four sources currently return 0 leads from a typical cloud/CI IP -
this is NOT a selector bug, it's infrastructure-level bot detection that a plain headless browser
can't bypass for free:
  - TradeIndia: blocked by CloudFront WAF (403 even via real Chromium)
  - ExportHub: Cloudflare "Just a moment..." challenge page
  - Kompass: blocked/empty response
  - Google search (scrape_google): CAPTCHA "unusual traffic" page
Bypassing this reliably needs a paid residential-proxy/anti-detect service, which is out of scope
for a free pipeline. Kept in the codebase (fails gracefully, never crashes the run) in case it
becomes viable from a different network, or a proxy is added later. Google Maps shared-list
scraping (gmaps_scraper.py) is the source that's actually proven to work.
"""

import logging
import random
import time

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_SCRAPER_DELAY_MIN = 2
_SCRAPER_DELAY_MAX = 5

try:
    from fake_useragent import UserAgent
    _ua = UserAgent()

    def _random_ua():
        return _ua.random
except Exception:
    def _random_ua():
        return (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )


def _get_browser_html(url, timeout=20):
    """Fallback fetch via headless Chromium (Playwright) - bypasses basic bot-detection (403/405
    from plain requests) that blocks non-browser User-Agents. Requires `playwright install
    chromium` to have been run."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=_random_ua())
            page.goto(url, timeout=timeout * 1000, wait_until="domcontentloaded")
            html = page.content()
            browser.close()
            return html
    except Exception as e:
        logger.debug(f"[web_scraper] Playwright fallback failed for {url}: {e}")
        return None


def _get(url, timeout=12):
    time.sleep(random.uniform(_SCRAPER_DELAY_MIN, _SCRAPER_DELAY_MAX))
    try:
        resp = requests.get(url, headers={"User-Agent": _random_ua()}, timeout=timeout)
        if resp.status_code in (403, 405):
            logger.info(f"[web_scraper] blocked ({resp.status_code}) on {url}, retrying via headless browser...")
            html = _get_browser_html(url)
            return BeautifulSoup(html, "lxml") if html else None
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")
    except Exception as e:
        logger.warning(f"[web_scraper] scrape failed {url}: {e}")
        return None


def scrape_tradeindia(max_pages=3):
    leads = []
    for page in range(1, max_pages + 1):
        url = f"https://www.tradeindia.com/importers/charcoal/{page}/"
        soup = _get(url)
        if not soup:
            continue
        for card in soup.select(".company-detail, .company-info, .dir-info"):
            name = card.select_one(".company-name, h2, h3, .cname")
            country = card.select_one(".country, .location, .cloc")
            href = card.select_one("a[href*='http']")
            email_a = card.select_one("a[href^='mailto:']")
            if not name:
                continue
            leads.append({
                "company_name": name.get_text(strip=True),
                "country": country.get_text(strip=True) if country else "",
                "website": href["href"] if href and href.get("href") else "",
                "email": email_a["href"].replace("mailto:", "") if email_a else "",
                "source": url,
            })
    logger.info(f"[web_scraper] TradeIndia: {len(leads)} leads")
    return leads


def scrape_exporthub():
    leads = []
    for keyword in ("charcoal", "bbq+charcoal", "wood+charcoal", "industrial+charcoal"):
        url = f"https://www.exporthub.com/buyer-list/?q={keyword}"
        soup = _get(url)
        if not soup:
            continue
        for item in soup.select(".buyer-item, .rfq-item, .company-card"):
            name = item.select_one(".company-name, .buyer-name, h3, h2")
            country = item.select_one(".country, .location, .flag-text")
            if not name:
                continue
            leads.append({
                "company_name": name.get_text(strip=True),
                "country": country.get_text(strip=True) if country else "",
                "website": "",
                "email": "",
                "source": url,
                "industry": keyword.replace("+", " "),
            })
    logger.info(f"[web_scraper] ExportHub: {len(leads)} leads")
    return leads


def scrape_kompass():
    leads = []
    url = "https://us.kompass.com/searchCompany?text=charcoal+importer"
    soup = _get(url)
    if not soup:
        return leads
    for card in soup.select(".company-card, .company-result, .k-result"):
        name = card.select_one(".company-name, h2, h3, .name")
        country = card.select_one(".country, .location")
        site = card.select_one("a.website, a[href*='http']")
        if not name:
            continue
        leads.append({
            "company_name": name.get_text(strip=True),
            "country": country.get_text(strip=True) if country else "",
            "website": site.get("href", "") if site else "",
            "email": "",
            "source": url,
        })
    logger.info(f"[web_scraper] Kompass: {len(leads)} leads")
    return leads


def scrape_google(queries=None):
    if queries is None:
        queries = [
            "charcoal importer company contact email",
            "bbq charcoal wholesale buyer importer",
            "industrial charcoal importer Middle East",
            "charcoal import Japan South Korea buyer",
            "wood charcoal Germany Netherlands importer",
            "charcoal briquette importer Africa",
            "hookah shisha charcoal buyer wholesale",
        ]
    leads = []
    try:
        from googlesearch import search
        _SKIP = {"google", "youtube", "wikipedia", "facebook", "twitter", "linkedin", "instagram"}
        for query in queries:
            for url in search(query, num_results=10, sleep_interval=3):
                if any(s in url for s in _SKIP):
                    continue
                domain = url.split("/")[2].replace("www.", "")
                company = domain.split(".")[0].replace("-", " ").title()
                leads.append({
                    "company_name": company,
                    "website": url,
                    "email": "",
                    "country": "",
                    "source": f"Google: {query}",
                })
            time.sleep(random.uniform(3, 6))
    except Exception as e:
        logger.warning(f"[web_scraper] Google search failed: {e}")
    logger.info(f"[web_scraper] Google search: {len(leads)} leads")
    return leads


def scrape_all():
    combined = []
    for fn in (scrape_tradeindia, scrape_exporthub, scrape_kompass, scrape_google):
        try:
            combined.extend(fn())
        except Exception as e:
            logger.error(f"[web_scraper] {fn.__name__} failed: {e}")
    logger.info(f"[web_scraper] Total raw leads collected: {len(combined)}")
    return combined
