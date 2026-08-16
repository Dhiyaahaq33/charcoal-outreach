"""Given a lead's website, fetch a few likely pages and extract an email + best-guess contact
name. Ported/adapted from pt-ekspor-arang-agent's enrichment_agent._scrape_site() pattern, extended
here to actually pull contact info (the old agent only validated emails already present, never
extracted new ones from the site).

Best-effort only - most business sites don't publish a named contact on the homepage. Missing
Contact Person is left blank (user said this is optional; Email is the one field they actually
want filled when possible).
"""

import logging
import re

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; CahayaWoodcharLeadBot/1.0)"}
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_SKIP_EMAIL_DOMAINS = ("example.com", "sentry.io", "wixpress.com", "godaddy.com")
_CONTACT_NAME_RE = re.compile(
    r"\b(?:Mr\.?|Ms\.?|Mrs\.?)\s+([A-Z][a-zA-Z'-]+(?:\s+[A-Z][a-zA-Z'-]+){0,2})"
)
_CONTACT_PATHS = ("", "/contact", "/contact-us", "/about", "/about-us")
# Common false-positive matches for _CONTACT_NAME_RE (business/product words that happen to
# follow "Mr./Ms." somewhere in page text, e.g. "Ms. Charcoal" from an unrelated nav/heading -
# not an actual person's name). Reject candidates that are just one of these words.
_NOT_A_NAME = {
    "charcoal", "company", "trading", "group", "international", "export", "import",
    "wholesale", "supplier", "distributor", "products", "quality", "service", "services",
}


def _fetch(url, timeout=10):
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout, allow_redirects=True)
        if resp.status_code >= 400:
            return None
        return resp.text
    except Exception as e:
        logger.debug(f"[enrichment] fetch failed {url}: {e}")
        return None


def _extract_emails(html):
    text = html
    # also decode mailto: links, which regex on raw HTML already catches inside href=""
    found = set(_EMAIL_RE.findall(text))
    return {
        e for e in found
        if not any(skip in e.lower() for skip in _SKIP_EMAIL_DOMAINS)
        and not e.lower().endswith((".png", ".jpg", ".gif", ".svg", ".webp"))
    }


def _extract_contact_name(soup_text):
    m = _CONTACT_NAME_RE.search(soup_text)
    if not m:
        return ""
    candidate = m.group(1)
    if candidate.strip().lower() in _NOT_A_NAME:
        return ""
    return candidate


def enrich_from_website(website):
    """Return {"email": str, "contact_person": str} - either may be empty string if not found."""
    if not website:
        return {"email": "", "contact_person": ""}

    base = website if website.startswith("http") else f"https://{website}"
    base = base.rstrip("/")

    for path in _CONTACT_PATHS:
        html = _fetch(base + path)
        if not html:
            continue
        emails = _extract_emails(html)
        if emails:
            soup = BeautifulSoup(html, "lxml")
            text = soup.get_text(" ", strip=True)
            contact = _extract_contact_name(text)
            return {"email": sorted(emails)[0], "contact_person": contact}

    return {"email": "", "contact_person": ""}
