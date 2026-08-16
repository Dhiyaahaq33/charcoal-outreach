"""Dedup logic adapted from gmaps-leads-scraper/clean_new_leads.py, but compares against the LIVE
CLIENT sheet (via sheet_client.load_rows()) instead of a local xlsx snapshot."""

import re
import unicodedata

import phonenumbers
import pycountry

COUNTRY_NAME_OVERRIDES = {
    "Korea, Republic of": "South Korea",
    "Russian Federation": "Russia",
    "Taiwan, Province of China": "Taiwan",
    "Iran, Islamic Republic of": "Iran",
    "Syrian Arab Republic": "Syria",
    "Lao People's Democratic Republic": "Laos",
    "Moldova, Republic of": "Moldova",
    "Tanzania, United Republic of": "Tanzania",
    "Bolivia, Plurinational State of": "Bolivia",
    "Venezuela, Bolivarian Republic of": "Venezuela",
    "Palestine, State of": "Palestine",
    "Türkiye": "Turkey",
}


def normalize_name(name):
    if not isinstance(name, str):
        return ""
    text = unicodedata.normalize("NFKD", name).lower()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\b(llc|ltd|l\.l\.c|co|company|trading|general|est|establishment|"
                  r"fze|fzc|sp|tr|w\.l\.l|wll)\b", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_phone(phone):
    if not isinstance(phone, str):
        return ""
    digits = re.sub(r"\D", "", phone)
    return digits[-9:] if len(digits) >= 9 else digits


def country_from_phone(phone):
    if not phone or not phone.strip():
        return None
    candidate = phone.strip()
    if not candidate.startswith("+"):
        candidate = "+" + re.sub(r"\D", "", candidate)
    try:
        parsed = phonenumbers.parse(candidate, None)
        if not phonenumbers.is_valid_number(parsed):
            return None
        region = phonenumbers.region_code_for_number(parsed)
        c = pycountry.countries.get(alpha_2=region) if region else None
        if not c:
            return None
        return COUNTRY_NAME_OVERRIDES.get(c.name, c.name)
    except Exception:
        return None


def country_from_address(address):
    if not address or not address.strip():
        return None
    tail = address.split("-")[-1].strip()
    if not tail:
        return None
    match = pycountry.countries.get(name=tail)
    if not match:
        try:
            results = pycountry.countries.search_fuzzy(tail)
            match = results[0] if results else None
        except LookupError:
            match = None
    return COUNTRY_NAME_OVERRIDES.get(match.name, match.name) if match else None


def to_whatsapp(phone):
    if not phone or not phone.strip():
        return ""
    digits = re.sub(r"\D", "", phone)
    return f"wa.me//{digits}" if digits else ""


def existing_keys(sheet_rows):
    """Build the dedup lookup sets from already-loaded CLIENT sheet rows."""
    names = {normalize_name(r.get("Company", "")) for r in sheet_rows}
    names.discard("")
    phones = set()
    for r in sheet_rows:
        for col in ("Phone", "WhatsApp"):
            p = normalize_phone(r.get(col, ""))
            if p:
                phones.add(p)
    return names, phones


def is_new_lead(lead, existing_names, existing_phones):
    name = normalize_name(lead.get("company_name") or lead.get("name") or "")
    if not name:
        return False
    if name in existing_names:
        return False
    phone = normalize_phone(lead.get("phone") or "")
    if phone and phone in existing_phones:
        return False
    return True


def dedupe_batch(leads):
    """Dedup within a single scrape batch (same lead found by multiple scrapers/lists)."""
    seen_names = set()
    seen_phones = set()
    out = []
    for lead in leads:
        name = normalize_name(lead.get("company_name") or lead.get("name") or "")
        if not name or name in seen_names:
            continue
        phone = normalize_phone(lead.get("phone") or "")
        if phone and phone in seen_phones:
            continue
        seen_names.add(name)
        if phone:
            seen_phones.add(phone)
        out.append(lead)
    return out
