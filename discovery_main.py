"""Lead discovery entrypoint - separate from main.py (outreach). Scrapes B2B directories, an
autonomous Google Maps search sweep (no list link needed - see discovery/gmaps_search_scraper.py),
and (if GMAPS_LIST_URLS is set) Google Maps shared lists, dedupes against the live CLIENT sheet,
enriches missing email/contact via each lead's website, and appends genuinely new leads.

Does NOT send any outreach itself - new rows land with Role/Product Interest blank and get picked
up by main.py's normal cron cycle once someone fills in enough context (or as-is, since main.py
only needs Country + a contact channel to start offering).

Run manually: python discovery_main.py
Or via .github/workflows/lead-discovery.yml (scheduled).
"""

import logging

from config import GMAPS_LIST_URLS, DISCOVERY_DRY_RUN
from sheet_client import get_worksheet, ensure_extra_columns, load_rows, append_new_leads
from discovery import web_scraper, dedupe, enrichment
from discovery.relevance import classify_relevance

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

_MAX_ENRICH = 60  # cap website-enrichment HTTP calls per run, keeps runtime/cost bounded


def _match_reason(category, query):
    """Alasan singkat kenapa company ini masuk database - per user request setelah nemu beberapa
    lead scraping yang namanya keliatan gak ada korelasi sama produk sama sekali ("ada beberapa
    company dari namanya seperti ga ada korelasi dengan produk kita sama sekali"). Ditulis dari
    kategori Google Maps tempat itu + query pencarian yang nemuinnya, biar user bisa langsung cek
    manual relevansinya tanpa buka Maps dulu."""
    bits = []
    if category:
        bits.append(f"kategori Maps: \"{category}\"")
    if query:
        bits.append(f"ditemukan lewat pencarian \"{query}\"")
    return " - ".join(bits) or "ditemukan via pencarian Google Maps (kategori tidak terbaca)"


def _normalize_gmaps_lead(row, country_hint=None):
    maps_url = row.get("maps_url") or ""
    return {
        "company_name": row.get("name") or "",
        "country": country_hint or (
            dedupe.country_from_phone(row.get("phone") or "")
            or dedupe.country_from_address(row.get("address") or "")
            or ""
        ),
        "phone": row.get("phone") or "",
        "website": row.get("website") or "",
        # Link Google Maps tempat itu - dipakai sebagai fallback kolom Website kalau lead ini
        # gak punya website sendiri (banyak listing Maps gak ada website tapi tetap punya link
        # profil Maps-nya - lebih baik daripada kolom Website kosong sama sekali).
        "maps_url": maps_url,
        # Per user request: kolom Contact Person diisi link Maps company-nya (bukan tebakan nama
        # orang, yang seringnya kosong/gak akurat dari enrichment website).
        "contact_person": maps_url,
        # Per user request: kolom Product Interest diisi alasan singkat kenapa company ini dipilih
        # masuk database, bukan dikosongin.
        "product_interest": _match_reason(row.get("category") or "", row.get("query") or ""),
        "category": row.get("category") or "",
        "email": "",
        "source": row.get("source_list_url") or row.get("query") or "gmaps",
    }


def run():
    log.info("=== Lead discovery run start ===")

    web_leads = web_scraper.scrape_all()

    log.info("[discovery] running autonomous Google Maps search sweep (today's rotation slice)...")
    from discovery import gmaps_search_scraper
    raw_search = gmaps_search_scraper.search_and_scrape()
    search_leads = [
        _normalize_gmaps_lead(r, country_hint=r.get("country_hint"))
        for r in raw_search if r.get("name")
    ]

    gmaps_list_leads = []
    if GMAPS_LIST_URLS:
        log.info(f"[discovery] scraping {len(GMAPS_LIST_URLS)} Google Maps list(s)...")
        from discovery import gmaps_scraper
        raw_gmaps = gmaps_scraper.scrape_lists(GMAPS_LIST_URLS)
        gmaps_list_leads = [_normalize_gmaps_lead(r) for r in raw_gmaps if r.get("name")]
    else:
        log.info("[discovery] GMAPS_LIST_URLS kosong, skip Google Maps LIST scraping "
                  "(search sweep di atas jalan tanpa perlu ini).")

    all_leads = dedupe.dedupe_batch(web_leads + search_leads + gmaps_list_leads)
    log.info(f"[discovery] {len(all_leads)} lead unik setelah dedup dalam batch ini.")

    ws = get_worksheet()
    col_index = ensure_extra_columns(ws)
    sheet_rows = load_rows(ws)
    existing_names, existing_phones = dedupe.existing_keys(sheet_rows)

    new_leads = [
        lead for lead in all_leads
        if dedupe.is_new_lead(lead, existing_names, existing_phones)
    ]
    log.info(f"[discovery] {len(new_leads)} lead genuinely baru (belum ada di CLIENT sheet).")

    # Filter relevansi ke katalog charcoal SEBELUM masuk sheet sama sekali - per user request
    # setelah nemu lead yang jelas gak nyambung (toko kosmetik) ikut ke-scrape masuk database.
    # Ambigu (kategori kosong/gak match keyword mana pun) tetap diloloskan (fail-open) - mending
    # nyangkut lead yang gak yakin daripada salah buang lead yang sebenernya relevan.
    relevant_leads = []
    dropped = 0
    for lead in new_leads:
        is_relevant, bad_kw = classify_relevance(lead.get("category", ""), lead.get("company_name", ""))
        if is_relevant:
            relevant_leads.append(lead)
        else:
            dropped += 1
            log.info(f"[discovery] skip (gak relevan, terdeteksi \"{bad_kw}\"): "
                     f"{lead.get('company_name', '')}")
    if dropped:
        log.info(f"[discovery] {dropped} lead di-skip karena kategorinya gak nyambung ke produk charcoal.")
    new_leads = relevant_leads

    # Per user request: usahakan tiap lead punya email DAN phone, bukan email doang - kalau
    # salah satu masih kosong, tetap coba enrich (need_email/need_phone nentuin apa yang dicari).
    enrich_count = 0
    for lead in new_leads:
        if enrich_count >= _MAX_ENRICH:
            break
        need_email = not lead.get("email")
        need_phone = not lead.get("phone")
        if not need_email and not need_phone:
            continue
        website = lead.get("website", "") or lead.get("maps_url", "")
        if not website:
            continue
        result = enrichment.enrich_from_website(website, need_email=need_email, need_phone=need_phone)
        enrich_count += 1
        if result["email"]:
            lead["email"] = result["email"]
        if result["phone"] and not lead.get("phone"):
            lead["phone"] = result["phone"]
        # Maps leads udah punya contact_person = link Maps (lihat _normalize_gmaps_lead) - jangan
        # ditimpa tebakan nama dari enrichment. Cuma lead non-Maps (web_scraper, gak punya
        # maps_url) yang boleh kepake nama hasil enrichment di sini.
        if result["contact_person"] and not lead.get("contact_person"):
            lead["contact_person"] = result["contact_person"]
    log.info(f"[discovery] {enrich_count} website di-enrich buat cari email/kontak.")

    to_append = [{
        "company": lead.get("company_name", ""),
        "country": lead.get("country", ""),
        "role": "",
        "product_interest": lead.get("product_interest", ""),
        "contact_person": lead.get("contact_person", ""),
        "phone": lead.get("phone", ""),
        "whatsapp": dedupe.to_whatsapp(lead.get("phone", "")) if lead.get("phone") else "",
        "email": lead.get("email", ""),
        "website": lead.get("website", "") or lead.get("maps_url", ""),
    } for lead in new_leads if lead.get("company_name")]

    with_email = sum(1 for lead in to_append if lead["email"])
    if DISCOVERY_DRY_RUN:
        log.info(f"[DRY_RUN] would append {len(to_append)} rows ({with_email} with email) - "
                  f"sheet NOT modified. Preview:")
        for lead in to_append[:20]:
            log.info(f"  - {lead['company']} | {lead['country']} | email={lead['email'] or '(none)'}")
        if len(to_append) > 20:
            log.info(f"  ... and {len(to_append) - 20} more")
    else:
        added = append_new_leads(ws, col_index, to_append)
        log.info(f"[discovery] {added} baris baru ditambahkan ke sheet ({with_email} dengan email terisi).")
    log.info("=== Lead discovery run selesai ===")


if __name__ == "__main__":
    run()
