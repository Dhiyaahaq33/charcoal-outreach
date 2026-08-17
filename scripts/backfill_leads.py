"""One-off/idempotent backfill buat baris CLIENT hasil scraping yang DITAMBAHKAN SEBELUM revisi
Product Interest/Contact Person (commit 86d112f, 17 Aug 2026) - baris-baris itu Contact
Person/Product Interest-nya masih kosong karena scraping-nya jalan sebelum kode revisi di-deploy.

Aman dijalanin berkali-kali (idempotent): cuma nyentuh baris yang kolomnya MASIH KOSONG.
- Contact Person: diisi dari kolom Website KALAU isinya link Google Maps (banyak lead lama nyimpen
  maps_url di situ sebagai fallback waktu Website aslinya kosong - itu satu-satunya info yang
  masih bisa direkonstruksi).
- Product Interest: kategori Maps & query pencarian ASLI yang jadi alasan match gak pernah
  kesimpen ke sheet dulu (baru mulai kesimpen sejak revisi ini) - jadi alasan spesifik buat lead
  lama GAK BISA direkonstruksi ulang. Diisi placeholder yang JUJUR bilang gitu (bukan dikarang
  alasan palsu), sekalian minta user cek manual relevansinya via Company/Website.

Run manual: python scripts/backfill_leads.py
Atau via workflow_dispatch .github/workflows/backfill-leads.yml
"""

import logging
import sys
import time

sys.path.insert(0, ".")
from sheet_client import get_worksheet, ensure_extra_columns, HEADER_ROW, ORIGINAL_DATA_END_ROW, _col_letter

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

_MAPS_HINTS = ("google.com/maps", "maps.app.goo.gl", "g.page", "goo.gl/maps")
_GENERIC_REASON = (
    "Lead lama hasil scraping sebelum revisi Product Interest (17 Aug 2026) - alasan match "
    "spesifik (kategori Maps/query pencarian) gak kesimpen waktu itu, gak bisa direkonstruksi "
    "ulang. Cek Company & Website/kolom ini manual buat verifikasi relevansi produk."
)


def run():
    ws = get_worksheet()
    col_index = ensure_extra_columns(ws)
    header = ws.row_values(HEADER_ROW)
    log.info(f"[backfill] header: {header}")

    contact_col = header.index("Contact Person") + 1
    product_col = header.index("Product Interest") + 1
    website_col = col_index.get("Website") or (header.index("Website") + 1 if "Website" in header else None)

    all_values = ws.get_all_values()
    updates = []
    touched = 0

    for i, row in enumerate(all_values[ORIGINAL_DATA_END_ROW:], start=ORIGINAL_DATA_END_ROW + 1):
        company = row[1].strip() if len(row) > 1 else ""
        if not company:
            continue

        contact = row[contact_col - 1].strip() if len(row) >= contact_col else ""
        product = row[product_col - 1].strip() if len(row) >= product_col else ""
        website = row[website_col - 1].strip() if website_col and len(row) >= website_col else ""

        row_changed = False
        if not contact and website and any(h in website.lower() for h in _MAPS_HINTS):
            updates.append({"range": f"{_col_letter(contact_col)}{i}", "values": [[website]]})
            row_changed = True
        if not product:
            updates.append({"range": f"{_col_letter(product_col)}{i}", "values": [[_GENERIC_REASON]]})
            row_changed = True
        if row_changed:
            touched += 1

    if not updates:
        log.info("[backfill] gak ada baris yang perlu di-backfill (semua udah keisi / gak ada data lama).")
        return

    for i in range(0, len(updates), 100):
        ws.batch_update(updates[i:i + 100], value_input_option="RAW")
        if i + 100 < len(updates):
            time.sleep(2)

    log.info(f"[backfill] selesai - {touched} baris diperbarui ({len(updates)} sel ditulis).")


if __name__ == "__main__":
    run()
