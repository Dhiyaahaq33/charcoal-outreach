"""Bersihin entri Contact Person yang salah ditulis scripts/enrich_maps_links.py run pertama
(17 Aug 2026, sebelum fix deteksi "/maps/place/") - waktu Maps gak nemu match apa pun, kode lama
salah nganggep balik ke URL pencarian sendiri ("https://.../maps/search/{query}?hl=en") sebagai
"link ketemu", padahal itu bukan link profil company sama sekali. Clear balik ke kosong biar baris
itu otomatis di-retry sama enrich_maps_links.py versi yang udah bener (cuma nyimpen kalau match
"/maps/place/") di run-run berikutnya.

Run manual: python scripts/clear_bogus_maps_links.py
"""

import logging
import sys
import time

sys.path.insert(0, ".")
from sheet_client import get_worksheet, HEADER_ROW, ORIGINAL_DATA_END_ROW, _col_letter

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def run():
    ws = get_worksheet()
    header = ws.row_values(HEADER_ROW)
    contact_col = header.index("Contact Person") + 1

    all_values = ws.get_all_values()
    updates = []
    for i, row in enumerate(all_values[ORIGINAL_DATA_END_ROW:], start=ORIGINAL_DATA_END_ROW + 1):
        val = row[contact_col - 1].strip() if len(row) >= contact_col else ""
        if val.startswith("https://www.google.com/maps/search/") and "/maps/place/" not in val:
            updates.append({"range": f"{_col_letter(contact_col)}{i}", "values": [[""]]})

    if not updates:
        log.info("[clear-bogus] gak ada entri bogus yang ketemu.")
        return

    log.info(f"[clear-bogus] menghapus {len(updates)} link bogus (bukan /maps/place/)...")
    for i in range(0, len(updates), 100):
        ws.batch_update(updates[i:i + 100], value_input_option="RAW")
        if i + 100 < len(updates):
            time.sleep(2)
    log.info("[clear-bogus] selesai - baris-baris itu bakal di-retry otomatis run enrich-maps-links berikutnya.")


if __name__ == "__main__":
    run()
