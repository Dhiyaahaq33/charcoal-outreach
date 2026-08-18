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
from datetime import datetime, timezone

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
    "BBQ equipment supplier",
]

# TRUE global coverage per user request ("nyari di semua negara bisa termasuk indonesia") -
# every country pycountry knows about (~249, incl. territories), not just the curated ~71-country
# list used for existing-client timezone/DO-DONT logic. COUNTRY_NAME_OVERRIDES keeps spelling
# consistent with the sheet's convention (e.g. "Korea, Republic of" -> "South Korea") so dedup
# against existing rows still matches correctly.
TARGET_COUNTRIES = sorted({
    COUNTRY_NAME_OVERRIDES.get(c.name, c.name) for c in pycountry.countries
})

# Istilah lokal "arang/charcoal" per negara - banyak bisnis di Google Maps cuma punya kategori/
# nama dalam bahasa lokal, gak pernah diterjemahin ke Inggris, jadi query BUYER_QUERIES (semua
# Inggris) bisa kelewat mereka. Dipakai sebagai query BERDIRI SENDIRI per negara (bukan
# dikombinasi ulang dengan 14 keyword Inggris - istilah lokalnya udah cukup spesifik sendiri),
# nambah ke _all_combos() di bawah. Cuma negara-negara yang bahasanya jelas dominan & charcoal
# trade-nya relevan yang dicover - belum lengkap semua 249 negara, tapi jauh lebih baik daripada
# Inggris doang.
LOCAL_TERMS = {
    "Turkey": ["mangal kömürü", "odun kömürü"],
    "Saudi Arabia": ["تاجر فحم", "فحم"],
    "United Arab Emirates": ["تاجر فحم", "فحم"],
    "Kuwait": ["فحم"],
    "Qatar": ["فحم"],
    "Bahrain": ["فحم"],
    "Oman": ["فحم"],
    "Iraq": ["فحم"],
    "Jordan": ["فحم"],
    "Lebanon": ["فحم"],
    "Egypt": ["فحم"],
    "Palestine": ["فحم"],
    "Syria": ["فحم"],
    "Morocco": ["فحم"],
    "Algeria": ["فحم"],
    "Tunisia": ["فحم"],
    "Libya": ["فحم"],
    "France": ["charbon de bois"],
    "Belgium": ["charbon de bois"],
    "Switzerland": ["charbon de bois", "Holzkohle"],
    "Spain": ["carbón vegetal"],
    "Mexico": ["carbón vegetal"],
    "Argentina": ["carbón vegetal"],
    "Chile": ["carbón vegetal"],
    "Colombia": ["carbón vegetal"],
    "Peru": ["carbón vegetal"],
    "Brazil": ["carvão vegetal"],
    "Portugal": ["carvão vegetal"],
    "Angola": ["carvão vegetal"],
    "Mozambique": ["carvão vegetal"],
    "Germany": ["Holzkohle"],
    "Austria": ["Holzkohle"],
    "Indonesia": ["arang kayu", "arang briket"],
    "Malaysia": ["arang kayu"],
    "China": ["木炭"],
    "Taiwan": ["木炭"],
    "Japan": ["木炭"],
    "South Korea": ["숯"],
    "Russia": ["древесный уголь"],
    "Ukraine": ["деревне вугілля"],
    "Thailand": ["ถ่าน"],
    "Viet Nam": ["than củi"],
    "Vietnam": ["than củi"],
    "Italy": ["carbonella", "carbone di legna"],
    "Netherlands": ["houtskool"],
    "India": ["कोयला"],
    "Pakistan": ["کوئلہ"],
    "Bangladesh": ["কাঠকয়লা"],
    "Iran": ["زغال چوب"],

    # --- Perluasan 17 Aug 2026: sisa ~185 negara (dari 249 total) per user request "tambahin
    # bahasa lokal buat 200 negara sisanya juga". Negara yang bahasanya SAMA dengan yang udah ada
    # di atas (Spanyol/Prancis/Arab/Portugis/Belanda/Mandarin/Italia/Melayu/Persia) tinggal reuse
    # istilah yang sama. Bahasa BARU pakai terjemahan terbaik yang bisa dipastikan (best-effort -
    # sama kayak entri-entri di atas, belum diverifikasi native speaker, tapi jauh lebih baik
    # daripada Inggris doang buat listing yang namanya/kategorinya cuma ada dalam bahasa lokal).
    # Negara yang DILEWATIN sengaja: wilayah gak berpenghuni/nyaris gak ada aktivitas bisnis
    # (Antarctica, Bouvet Island, Heard Island and McDonald Islands, French Southern Territories,
    # British Indian Ocean Territory, South Georgia and the South Sandwich Islands, Pitcairn,
    # Tokelau, Niue, Norfolk Island) dan negara yang bahasa resminya udah Inggris (BUYER_QUERIES
    # udah nyakup penuh, nambah istilah lokal di situ cuma redundan) - dua kelompok ini tetap
    # kecover lewat kombinasi BUYER_QUERIES + negara di _all_combos(), cuma gak punya entri di sini.

    # Spanyol (reuse "carbón vegetal")
    "Costa Rica": ["carbón vegetal"],
    "Cuba": ["carbón vegetal"],
    "Dominican Republic": ["carbón vegetal"],
    "Ecuador": ["carbón vegetal"],
    "El Salvador": ["carbón vegetal"],
    "Guatemala": ["carbón vegetal"],
    "Honduras": ["carbón vegetal"],
    "Nicaragua": ["carbón vegetal"],
    "Panama": ["carbón vegetal"],
    "Paraguay": ["carbón vegetal"],
    "Uruguay": ["carbón vegetal"],
    "Venezuela": ["carbón vegetal"],
    "Equatorial Guinea": ["carbón vegetal"],
    "Bolivia": ["carbón vegetal"],
    "Puerto Rico": ["carbón vegetal"],

    # Prancis (reuse "charbon de bois")
    "Benin": ["charbon de bois"],
    "Burkina Faso": ["charbon de bois"],
    "Cameroon": ["charbon de bois"],
    "Central African Republic": ["charbon de bois"],
    "Chad": ["charbon de bois"],
    "Comoros": ["charbon de bois"],
    "Congo": ["charbon de bois"],
    "Congo, The Democratic Republic of the": ["charbon de bois"],
    "Côte d'Ivoire": ["charbon de bois"],
    "Djibouti": ["charbon de bois"],
    "Gabon": ["charbon de bois"],
    "Guinea": ["charbon de bois"],
    "Madagascar": ["charbon de bois"],
    "Mali": ["charbon de bois"],
    "Monaco": ["charbon de bois"],
    "Niger": ["charbon de bois"],
    "Rwanda": ["charbon de bois"],
    "Senegal": ["charbon de bois"],
    "Seychelles": ["charbon de bois"],
    "Togo": ["charbon de bois"],
    "Vanuatu": ["charbon de bois"],
    "French Guiana": ["charbon de bois"],
    "French Polynesia": ["charbon de bois"],
    "Guadeloupe": ["charbon de bois"],
    "Martinique": ["charbon de bois"],
    "Mayotte": ["charbon de bois"],
    "Réunion": ["charbon de bois"],
    "Saint Barthélemy": ["charbon de bois"],
    "Saint Martin (French part)": ["charbon de bois"],
    "Saint Pierre and Miquelon": ["charbon de bois"],
    "Wallis and Futuna": ["charbon de bois"],
    "Burundi": ["charbon de bois"],
    "Canada": ["charbon de bois"],
    "Mauritius": ["charbon de bois"],
    "Luxembourg": ["charbon de bois"],
    "Andorra": ["charbon de bois"],

    # Portugis (reuse "carvão vegetal")
    "Cabo Verde": ["carvão vegetal"],
    "Guinea-Bissau": ["carvão vegetal"],
    "Sao Tome and Principe": ["carvão vegetal"],
    "Timor-Leste": ["carvão vegetal"],

    # Arab (reuse "فحم")
    "Yemen": ["فحم"],
    "Western Sahara": ["فحم"],
    "Sudan": ["فحم"],
    "South Sudan": ["فحم"],
    "Mauritania": ["فحم"],
    "Eritrea": ["فحم"],

    # Belanda (reuse "houtskool")
    "Aruba": ["houtskool"],
    "Bonaire, Sint Eustatius and Saba": ["houtskool"],
    "Curaçao": ["houtskool"],
    "Sint Maarten (Dutch part)": ["houtskool"],
    "Suriname": ["houtskool"],
    "South Africa": ["houtskool"],  # Afrikaans, kata sama dengan Belanda
    "Namibia": ["houtskool"],

    # Mandarin (reuse "木炭")
    "Hong Kong": ["木炭"],
    "Macao": ["木炭"],
    "Singapore": ["木炭"],

    # Italia (reuse)
    "San Marino": ["carbonella"],
    "Holy See (Vatican City State)": ["carbonella"],

    # Melayu (reuse "arang kayu")
    "Brunei Darussalam": ["arang kayu"],

    # Persia (reuse "زغال چوب")
    "Afghanistan": ["زغال چوب"],

    # Swedia (reuse "träkol")
    "Åland Islands": ["träkol"],

    # Norwegia (reuse "trekull")
    "Svalbard and Jan Mayen": ["trekull"],

    # Swahili (reuse "mkaa")
    "Tanzania": ["mkaa"],
    "Uganda": ["mkaa"],

    # --- Bahasa baru (satu negara/grup kecil per bahasa) ---
    "Albania": ["qymyr druri"],                    # Albania
    "Armenia": ["փայտածուխ"],                       # Armenia
    "Azerbaijan": ["odun kömürü"],                  # Azerbaijan (mirip Turki)
    "Belarus": ["драўняны вугаль"],                 # Belarusia
    "Bosnia and Herzegovina": ["drveni ugalj"],     # Bosnia
    "Bulgaria": ["дървени въглища"],                # Bulgaria
    "Croatia": ["drveni ugljen"],                   # Kroasia
    "Cyprus": ["κάρβουνο ξύλου"],                   # Yunani (mayoritas)
    "Czechia": ["dřevěné uhlí"],                    # Ceko
    "Denmark": ["trækul"],                          # Denmark
    "Estonia": ["puusüsi"],                         # Estonia
    "Ethiopia": ["ከሰል"],                            # Amharik
    "Finland": ["puuhiili"],                        # Finlandia
    "Georgia": ["ხის ნახშირი"],                     # Georgia
    "Greece": ["κάρβουνο ξύλου"],                   # Yunani
    "Haiti": ["charbon de bois"],                   # Prancis (bahasa resmi bareng Kreol Haiti)
    "Hungary": ["faszén"],                          # Hungaria
    "Iceland": ["viðarkol"],                        # Islandia
    "Israel": ["פחם עץ"],                           # Ibrani
    "Kazakhstan": ["ағаш көмірі"],                  # Kazakh
    "Kenya": ["mkaa"],                              # Swahili
    "Kyrgyzstan": ["жыгач көмүр"],                  # Kirgistan
    "Laos": ["ຖ່ານ"],                                # Lao
    "Latvia": ["kokogle"],                          # Latvia
    "Lithuania": ["medžio anglis"],                 # Lituania
    "Cambodia": ["ធ្យូង"],                            # Khmer
    "Mongolia": ["модны нүүрс"],                    # Mongolia
    "Montenegro": ["drveni ugalj"],                 # Montenegro
    "Myanmar": ["မီးသွေး"],                          # Myanmar/Burma
    "Nepal": ["कोइला"],                              # Nepal
    "Nigeria": ["gawayi"],                          # Hausa (salah satu bahasa besar Nigeria)
    "North Macedonia": ["дрвен јаглен"],             # Makedonia Utara
    "Norway": ["trekull"],                          # Norwegia
    "Philippines": ["uling"],                       # Filipino/Tagalog
    "Poland": ["węgiel drzewny"],                   # Polandia
    "Romania": ["cărbune de lemn"],                 # Rumania
    "Serbia": ["дрвени угаљ"],                      # Serbia
    "Slovakia": ["drevené uhlie"],                  # Slovakia
    "Slovenia": ["oglje"],                          # Slovenia
    "Somalia": ["dhuxul"],                          # Somalia
    "Sri Lanka": ["අඟුරු"],                          # Sinhala
    "Sweden": ["träkol"],                           # Swedia
    "Tajikistan": ["ангишти чӯбӣ"],                 # Tajikistan
    "Turkmenistan": ["agaç kömür"],                 # Turkmenistan
    "Uzbekistan": ["yog'och ko'mir"],               # Uzbekistan
    "Fiji": ["कोयला"],                              # Hindi (populasi Indo-Fiji besar)
}

MAX_COMBOS_PER_RUN = 60
MAX_RESULTS_PER_COMBO = 8


def _all_combos():
    english = [(q, c) for q in BUYER_QUERIES for c in TARGET_COUNTRIES]
    local = [(term, country) for country, terms in LOCAL_TERMS.items() for term in terms]
    return english + local


def _todays_combos():
    """Deterministic rotation by 30-minute UTC slot (matches the cron cadence) - each run picks a
    genuinely different slice, so the full sweep actually progresses every run instead of
    re-scraping the same combos all day. Was keyed by date-only originally, which meant every run
    within the same day picked the IDENTICAL slice - harmless at 1 run/day, but once cron moved to
    every 30 min (per user request "terus menerus cari tanpa henti", enabled by the repo going
    public for unlimited Actions minutes) that would've wasted every run after the first re-doing
    zero new coverage. Manually re-running within the same 30-min slot still returns the same
    slice (deterministic, avoids skipping/duplicating work unpredictably), same guarantee as
    before just at finer granularity."""
    combos = _all_combos()
    slot_index = int(datetime.now(timezone.utc).timestamp() // 1800)  # 1800s = 30 menit
    start = (slot_index * MAX_COMBOS_PER_RUN) % len(combos)
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
