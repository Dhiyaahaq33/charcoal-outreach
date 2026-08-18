"""Hapus baris 4228-4566 di CLIENT sheet - diverifikasi manual (scripts/check_range.py) sebagai
sisa baris TEMPLATE lama dari sebelum bot ini ada (No berurutan sampai 1009, kolom Company kosong,
cuma isi placeholder "." / "-" di beberapa kolom lain), BUKAN lead/data asli. Baris 4229-4566 diapit
data scraping asli di kedua sisi (No=4199 tepat sebelum, No=4200 tepat sesudah - konfirmasi baris
ini emang gak nyambung ke urutan data beneran).

SAFETY CHECK built-in: sebelum hapus, script ini verifikasi ULANG bahwa SEMUA baris di range target
punya kolom Company kosong - kalau ketemu SATU AJA baris yang Company-nya keisi, batalin semua
(gak hapus apa pun), biar gak salah potong data asli kalau posisi baris udah berubah sejak dicek.

Run manual: python scripts/delete_empty_template_rows.py
"""

import logging
import sys

sys.path.insert(0, ".")
from sheet_client import get_worksheet, HEADER_ROW, _retry_on_429, _resync_no_column

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DELETE_START_ROW = 4228
DELETE_END_ROW = 4566


def run():
    ws = get_worksheet()
    header = ws.row_values(HEADER_ROW)
    company_col_idx = header.index("Company")  # 0-based

    all_values = ws.get_all_values()
    if DELETE_END_ROW > len(all_values):
        log.error(f"[delete-empty] sheet cuma {len(all_values)} baris, target akhir "
                  f"{DELETE_END_ROW} di luar jangkauan. Dibatalin.")
        return

    target_rows = all_values[DELETE_START_ROW - 1:DELETE_END_ROW]
    non_empty_companies = [
        (DELETE_START_ROW + i, row[company_col_idx])
        for i, row in enumerate(target_rows)
        if len(row) > company_col_idx and row[company_col_idx].strip()
    ]
    if non_empty_companies:
        log.error(f"[delete-empty] SAFETY CHECK GAGAL - ketemu {len(non_empty_companies)} baris "
                  f"yang Company-nya KEISI di range target, dibatalin biar gak salah hapus data "
                  f"asli. Contoh: {non_empty_companies[:5]}")
        return

    log.info(f"[delete-empty] safety check lolos - baris {DELETE_START_ROW}-{DELETE_END_ROW} "
             f"({len(target_rows)} baris) semuanya Company kosong, lanjut hapus.")

    _retry_on_429(ws.delete_rows, DELETE_START_ROW, DELETE_END_ROW)
    log.info(f"[delete-empty] {len(target_rows)} baris kosong/template dihapus.")

    _resync_no_column(ws)
    log.info("[delete-empty] selesai, kolom No udah di-resync.")


if __name__ == "__main__":
    run()
