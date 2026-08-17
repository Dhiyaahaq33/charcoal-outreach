"""Given a lead's website, fetch a few likely pages and extract email + phone + best-guess
contact name. Ported/adapted from pt-ekspor-arang-agent's enrichment_agent._scrape_site() pattern,
extended here to actually pull contact info (the old agent only validated emails already present,
never extracted new ones from the site).

Per user request ("usahain ada no telp dan email, klo ga ada cari lagi sampe dapet") - checks
EVERY contact page path and keeps going until both email and phone are found or all paths are
exhausted, instead of stopping at the first page with an email. Still best-effort: most business
sites don't publish a named contact, and if the lead has no website at all there's nothing to
enrich from (Google search - which could find a website independently - is blocked by CAPTCHA from
GitHub Actions IPs, confirmed in discovery/web_scraper.py; only Maps-sourced data is reliable
automated here).
"""

import logging
import re

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; CahayaWoodcharLeadBot/1.0)"}
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_SKIP_EMAIL_DOMAINS = ("example.com", "sentry.io", "wixpress.com", "godaddy.com")
# Nomor telepon internasional - minimal 8 digit (setelah dibuang spasi/tanda), boleh diawali "+".
_PHONE_RE = re.compile(r"\+?[\d][\d\s\-\(\)]{7,18}\d")
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


def _extract_phone(html):
    candidates = _PHONE_RE.findall(html)
    for c in candidates:
        digits = re.sub(r"\D", "", c)
        if 8 <= len(digits) <= 15:
            return c.strip()
    return ""


def enrich_from_website(website, need_email=True, need_phone=True):
    """Return {"email": str, "phone": str, "contact_person": str} - kosong kalau gak ketemu.
    Cek SEMUA path kontak (bukan berhenti di page pertama yang ada email) sampai email DAN phone
    ketemu, atau semua path abis - biar dua-duanya diusahain, bukan cuma email doang."""
    result = {"email": "", "phone": "", "contact_person": ""}
    if not website:
        return result

    base = website if website.startswith("http") else f"https://{website}"
    base = base.rstrip("/")

    for path in _CONTACT_PATHS:
        if (not need_email or result["email"]) and (not need_phone or result["phone"]):
            break  # udah dapet semua yang dibutuhin, gak perlu cek path lagi
        html = _fetch(base + path)
        if not html:
            continue

        if need_email and not result["email"]:
            emails = _extract_emails(html)
            if emails:
                result["email"] = sorted(emails)[0]
                soup = BeautifulSoup(html, "lxml")
                text = soup.get_text(" ", strip=True)
                contact = _extract_contact_name(text)
                if contact:
                    result["contact_person"] = contact

        if need_phone and not result["phone"]:
            phone = _extract_phone(html)
            if phone:
                result["phone"] = phone

    return result
