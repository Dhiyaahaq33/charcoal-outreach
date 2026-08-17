"""Re-scrape Google Maps satu-per-satu buat ngisi Contact Person (link Maps) untuk lead hasil
scraping LAMA yang kolomnya masih kosong - per user request setelah ketauan versi kode lama
gak nyimpen maps_url begitu company punya website sendiri (jadi link Maps aslinya beneran hilang,
gak ada di sheet mana pun). "klo ga kesimpen maka di scraping lagi dan taro di sel itu masing2
sesuai profil" - jadi ini bukan sweep kategori kayak gmaps_search_scraper.py, tapi LOOKUP
per-company: cari "{Company} {Country}" di Google Maps, ambil link profil hasil pertama yang
paling relevan, tulis ke Contact Person baris itu.

Sengaja CUMA nyentuh baris setelah ORIGINAL_DATA_END_ROW (>673) - 671 client awal itu data
kurasi manual, kolom Contact Person-nya beneran nama orang kontak asli, BUKAN slot buat link Maps
(konvensi link-Maps-di-Contact-Person cuma berlaku buat lead hasil scraping, bukan data asli).

Playwright per-lookup lambat (~3-6 detik/company: search + tunggu render + verifikasi place page),
jadi dibatasi MAX_PER_RUN per eksekusi biar runtime CI kebentuk & gak digeber ke Google Maps
sekaligus (risiko blokir). Idempotent: baris yang Contact Person-nya udah keisi otomatis
kelewatan run berikutnya, jadi cukup dijadwalin ulang beberapa kali buat nyelesain semua baris
secara bertahap (pola sama kayak gmaps_search_scraper.py punya).

Run manual: python scripts/enrich_maps_links.py
Via workflow_dispatch/schedule: .github/workflows/enrich-maps-links.yml
"""

import logging
import random
import sys
import time

sys.path.insert(0, ".")
from sheet_client import get_worksheet, load_rows, HEADER_ROW, ORIGINAL_DATA_END_ROW, _col_letter
from discovery.gmaps_scraper import _text_or_none, _force_en
from discovery.gmaps_search_scraper import RESULT_LINK_SELECTOR

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

MAX_PER_RUN = 120


def _find_maps_profile(page, company, country):
    """Cari 1 company spesifik di Maps, return link profilnya (atau None kalau gak ketemu/gak
    yakin). Sama pola dual-path-nya gmaps_search_scraper.search_and_scrape(): Maps kadang nampilin
    list hasil (ambil yang PALING ATAS - hasil paling relevan buat nama company spesifik kayak
    gini), kadang langsung redirect ke satu tempat dominan (dipercaya langsung)."""
    query = f"{company} {country}".strip() if country else company
    search_url = f"https://www.google.com/maps/search/{query.replace(' ', '+')}"
    try:
        page.goto(_force_en(search_url), wait_until="domcontentloaded", timeout=25000)
    except Exception:
        return None

    try:
        page.wait_for_selector(f"{RESULT_LINK_SELECTOR}, h1.DUwDvf", timeout=12000)
    except Exception:
        return None

    try:
        links = page.locator(RESULT_LINK_SELECTOR)
        if links.count():
            return links.first.get_attribute("href")
    except Exception:
        pass

    # Gak ada list hasil - Maps mungkin langsung redirect ke satu tempat dominan. TAPI cuma
    # dipercaya kalau page.url beneran berubah jadi URL profil ("/maps/place/...") - kalau masih
    # persis URL pencarian yang kita buka sendiri (search_url), berarti Maps GAK nemu apa-apa dan
    # h1.DUwDvf kebetulan match elemen lain di halaman kosong itu (false positive kejadian nyata:
    # nulis balik query pencarian sebagai "link ketemu" ke 30-an baris di run pertama).
    try:
        if "/maps/place/" in page.url:
            return page.url
    except Exception:
        pass
    return None


def run():
    ws = get_worksheet()
    header = ws.row_values(HEADER_ROW)
    last_col = _col_letter(len(header))
    contact_col = header.index("Contact Person") + 1

    rows = load_rows(ws)
    candidates = [
        r for r in rows
        if r["_row_number"] > ORIGINAL_DATA_END_ROW
        and r.get("Company", "").strip()
        and not r.get("Contact Person", "").strip()
    ]
    log.info(f"[enrich-maps] {len(candidates)} baris kandidat (Contact Person kosong), "
             f"proses maks {MAX_PER_RUN} run ini.")
    candidates = candidates[:MAX_PER_RUN]
    if not candidates:
        log.info("[enrich-maps] gak ada baris yang perlu diproses.")
        return

    from playwright.sync_api import sync_playwright

    updates = []
    found = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
            locale="en-US",
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        page = context.new_page()

        for r in candidates:
            company = r.get("Company", "").strip()
            country = r.get("Country", "").strip()
            maps_url = _find_maps_profile(page, company, country)
            if maps_url:
                updates.append({"range": f"{_col_letter(contact_col)}{r['_row_number']}",
                                 "values": [[maps_url]]})
                found += 1
                log.info(f"[enrich-maps] {company} ({country}) -> {maps_url}")
            else:
                log.info(f"[enrich-maps] {company} ({country}) -> gak ketemu, skip.")
            time.sleep(random.uniform(0.8, 1.6))

        browser.close()

    if updates:
        for i in range(0, len(updates), 100):
            ws.batch_update(updates[i:i + 100], value_input_option="RAW")
            if i + 100 < len(updates):
                time.sleep(2)

    log.info(f"[enrich-maps] selesai - {found}/{len(candidates)} link Maps ketemu & ditulis.")


if __name__ == "__main__":
    run()
