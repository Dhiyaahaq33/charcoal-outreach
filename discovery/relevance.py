"""Cek relevansi lead ke katalog PT Cahaya Woodchar (sawdust/coconut shell/BBQ briquette/mix
hardwood/binchotan/halaban charcoal - buat rumah tangga/komersial/industri, BBQ, jajanan kaki
lima, dapur komersial, shisha, panggangan Jepang, restoran/steakhouse kelas atas, katering).

Dipakai di 2 tempat: discovery_main.py (filter SEBELUM lead baru masuk sheet) dan
scripts/enrich_maps_links.py (klasifikasi lead LAMA yang udah kelanjur masuk) - satu sumber
kebenaran biar kriterianya konsisten di dua jalur itu. Dibuat per user request setelah nemu lead
yang jelas gak nyambung (toko kosmetik) ikut ke-scrape masuk database.

Keyword SENGAJA lebar (bukan cuma "charcoal") biar nyakup end-use business (hotel, restoran,
wholesale/trading umum) yang relevan meski namanya gak literally sebut "charcoal". Ambigu (gak
match daftar mana pun) FAIL-OPEN - dianggap tetap relevan, biar gak salah skip lead yang
sebenernya relevan tapi kategorinya gak lazim/gak lengkap.
"""

RELEVANT_KEYWORDS = (
    "charcoal", "coal", "briquette", "bbq", "barbecue", "grill", "shisha", "hookah", "hooka",
    "tobacco", "smoke shop", "vape", "biomass", "firewood", "fuel", "wood", "restaurant",
    "steakhouse", "steak house", "hotel", "catering", "caterer", "wholesale", "import", "export",
    "trading", "distributor", "supplier", "kitchen", "cigar", "grocery", "convenience store",
    "supermarket", "food", "cafe", "resto",
)

IRRELEVANT_KEYWORDS = (
    "cosmetic", "beauty", "makeup", "skincare", "hair salon", "nail salon", "spa", "clothing",
    "apparel", "fashion", "jewelry", "jeweler", "electronics", "software", "insurance",
    "real estate", "bank", "hospital", "dental", "clinic", "school", "university", "gym",
    "fitness", "car dealer", "auto repair", "pharmacy", "furniture store", "toy store",
    "bookstore", "florist", "pet store", "bakery shop",
)


def classify_relevance(category, company_name):
    """Return (is_relevant: bool, matched_keyword: str|None). matched_keyword cuma keisi kalau
    is_relevant=False (kata kunci gak-relevan yang ketangkep, buat ditulis di log/alasan)."""
    text = f"{category or ''} {company_name or ''}".lower()
    if any(k in text for k in RELEVANT_KEYWORDS):
        return True, None
    for k in IRRELEVANT_KEYWORDS:
        if k in text:
            return False, k
    return True, None
