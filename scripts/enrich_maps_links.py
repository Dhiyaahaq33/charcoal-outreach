"""Re-scrape Google Maps satu-per-satu buat ngisi Contact Person (link Maps) DAN Product Interest
(alasan match + cek relevansi) untuk lead hasil scraping LAMA yang kolomnya masih kosong - per
user request setelah ketauan versi kode lama gak nyimpen maps_url/kategori sama sekali begitu
company punya website sendiri (datanya beneran hilang, gak ada di sheet mana pun buat direkonstruksi
tanpa scraping ulang).

User juga eksplisit minta dicek relevansinya: "pastikan nnti lu pas offer mereka semua yg di sheet
itu nyambung dari product kita ke company mereka, soalnya tdi gw liat ada company yg jualan
kosmetik" - jadi selain isi 2 kolom itu, tiap kategori Maps yang ketemu dicocokin ke daftar
kata kunci relevan/gak relevan buat produk charcoal (BBQ, shisha, restoran, wholesale/trading,
dll vs kosmetik, fashion, elektronik, dll). Kalau JELAS gak relevan, kolom FINAL diisi "NO" biar
main.py otomatis skip company itu dari outreach selamanya (_FINAL_NEGATIVE check yang udah ada) -
gak perlu nunggu review manual dulu buat berhentiin kontak ke lead yang jelas salah sasaran.
Kalau ambigu (kategori gak match daftar mana pun), FAIL-OPEN - tetap dianggap boleh di-offer,
biar gak salah skip lead yang sebenarnya relevan tapi kategorinya gak lazim.

Sengaja CUMA nyentuh baris setelah ORIGINAL_DATA_END_ROW (>673) - 671 client awal itu data
kurasi manual, kolom Contact Person-nya beneran nama orang kontak asli, BUKAN slot buat link Maps.

Playwright per-lookup lambat (search + kunjungi place page buat ambil kategori = 2 navigasi/
company), jadi dibatasi MAX_PER_RUN per eksekusi. Idempotent: baris yang Product Interest DAN
Contact Person udah dua-duanya keisi otomatis kelewatan run berikutnya, jadi cukup dijadwalin
ulang beberapa kali buat nyelesain semua baris secara bertahap.

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
from discovery.relevance import classify_relevance

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

MAX_PER_RUN = 20


def _find_maps_profile(page, company, country):
    """Cari 1 company spesifik di Maps, return link profilnya (atau None kalau gak ketemu/gak
    yakin). Maps kadang nampilin list hasil (ambil yang PALING ATAS), kadang langsung redirect ke
    satu tempat dominan (dipercaya HANYA kalau page.url beneran jadi /maps/place/...)."""
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

    try:
        if "/maps/place/" in page.url:
            return page.url
    except Exception:
        pass
    return None


def _visit_and_get_category(page, maps_url):
    try:
        page.goto(_force_en(maps_url), wait_until="domcontentloaded", timeout=20000)
        page.wait_for_selector("h1.DUwDvf", timeout=12000)
    except Exception:
        return None
    return _text_or_none(page, "button.DkEaL")


def run():
    ws = get_worksheet()
    header = ws.row_values(HEADER_ROW)
    last_col = _col_letter(len(header))
    contact_col = header.index("Contact Person") + 1
    product_col = header.index("Product Interest") + 1
    final_col = header.index("FINAL") + 1 if "FINAL" in header else None

    rows = load_rows(ws)
    candidates = [
        r for r in rows
        if r["_row_number"] > ORIGINAL_DATA_END_ROW
        and r.get("Company", "").strip()
        and (not r.get("Contact Person", "").strip() or not r.get("Product Interest", "").strip())
    ]
    log.info(f"[enrich-maps] {len(candidates)} baris kandidat (Contact Person dan/atau Product "
             f"Interest kosong), proses maks {MAX_PER_RUN} run ini.")
    # Random sample, BUKAN selalu N teratas - kalau selalu ambil baris yang sama dari urutan
    # sheet, query yang SAMA PERSIS ("{company} {country}") berulang identik tiap 30 menit selama
    # berjam-jam (kejadian nyata: 0/80 sukses berturut-turut ~10 jam) - kemungkinan itu sinyal
    # scraping paling jelas buat Google. Random sample nyebar beban ke seluruh backlog biar query
    # yang sama gak keulang sesering itu.
    if len(candidates) > MAX_PER_RUN:
        candidates = random.sample(candidates, MAX_PER_RUN)
    else:
        random.shuffle(candidates)
    if not candidates:
        log.info("[enrich-maps] gak ada baris yang perlu diproses.")
        return

    from playwright.sync_api import sync_playwright

    updates = []
    contact_found = 0
    product_found = 0
    flagged_irrelevant = 0

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
            existing_contact = r.get("Contact Person", "").strip()
            need_product = not r.get("Product Interest", "").strip()

            # SELALU lewat pencarian dulu ("/maps/search/..."), JANGAN pernah goto() langsung ke
            # URL /maps/place/ mentah - itu kesimpulan dari perbandingan langsung 18 Aug 2026:
            # lead-discovery.yml (SELALU search dulu baru masuk ke place) tetap normal (203 tempat
            # ke-scrape sukses), sementara run enrich-maps yang baris-barisnya udah punya Contact
            # Person (jadi lompat langsung ke /place/ tanpa pencarian) konsisten 0/80 berturut-turut
            # selama berjam-jam. Kemungkinan besar itu pola traffic yang beda (100% direct deep-link
            # tanpa interleaving search) yang kena deteksi bot Google lebih keras. Biayanya 1
            # navigasi ekstra per kandidat, tapi worth it drpd 0% sukses.
            searched_url = _find_maps_profile(page, company, country)
            if searched_url and "/maps/place/" in searched_url and not (
                "/maps/place/" in existing_contact
            ):
                updates.append({"range": f"{_col_letter(contact_col)}{r['_row_number']}",
                                 "values": [[searched_url]]})
                contact_found += 1

            maps_url = existing_contact if "/maps/place/" in existing_contact else searched_url

            category = None
            if need_product and maps_url and "/maps/place/" in maps_url:
                category = _visit_and_get_category(page, maps_url)

            if need_product:
                if category:
                    relevant, bad_kw = classify_relevance(category, company)
                    if relevant:
                        reason = f'Kategori Maps: "{category}" (di-verifikasi ulang via Maps).'
                    else:
                        reason = (f'Kategori Maps: "{category}" - KEMUNGKINAN GAK RELEVAN sama '
                                  f'produk charcoal (terdeteksi "{bad_kw}"), FINAL di-set NO.')
                        if final_col:
                            updates.append({"range": f"{_col_letter(final_col)}{r['_row_number']}",
                                             "values": [["NO"]]})
                            flagged_irrelevant += 1
                    updates.append({"range": f"{_col_letter(product_col)}{r['_row_number']}",
                                     "values": [[reason]]})
                    product_found += 1
                    log.info(f"[enrich-maps] {company} ({country}) -> kategori: \"{category}\""
                             f"{' [DITANDAI NO]' if not relevant else ''}")
                else:
                    log.info(f"[enrich-maps] {company} ({country}) -> kategori gak kebaca, "
                             f"Product Interest dilewatin run ini.")

            time.sleep(random.uniform(3.0, 6.0))

        browser.close()

    if updates:
        for i in range(0, len(updates), 100):
            ws.batch_update(updates[i:i + 100], value_input_option="RAW")
            if i + 100 < len(updates):
                time.sleep(2)

    log.info(f"[enrich-maps] selesai - {contact_found} Contact Person baru, {product_found} "
             f"Product Interest baru ({flagged_irrelevant} ditandai FINAL=NO karena gak relevan), "
             f"dari {len(candidates)} baris diproses.")


if __name__ == "__main__":
    run()
