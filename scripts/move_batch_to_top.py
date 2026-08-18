"""One-off: pindahin satu block data scraping spesifik (dari company "West Indies Smoke Shop"
sampai "SUPERBAT") ke posisi PALING ATAS blok scraping - tepat setelah baris pembatas merah
(ORIGINAL_DATA_END_ROW+1), BUKAN menimpa baris pembatasnya sendiri. Per user request: block ini
kemungkinan batch scraping PERTAMA yang dulu (sebelum append_new_leads() diubah ke append-di-akhir)
udah kegeser jauh ke bawah gara-gara desain lama nyisip batch baru selalu di posisi yang sama
persis setelah data asli.

Caranya: baca SEMUA baris di blok scraping (setelah pembatas), susun ulang di memory (block target
dipindah ke depan, sisanya tetap urutan semula), tulis balik semua sekaligus pakai ws.update() -
BUKAN insert_rows()/delete_rows() sama sekali, biar gak ada risiko masalah inherit-formatting
kayak insiden bug warna merah sebelumnya (jumlah baris gak berubah, cuma urutan isinya ditukar).

Run manual: python scripts/move_batch_to_top.py
"""

import logging
import sys

sys.path.insert(0, ".")
from sheet_client import get_worksheet, HEADER_ROW, ORIGINAL_DATA_END_ROW, _col_letter, _resync_no_column

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

START_COMPANY = "West Indies Smoke Shop"
END_COMPANY = "SUPERBAT"


def run():
    ws = get_worksheet()
    header = ws.row_values(HEADER_ROW)
    ncols = len(header)
    last_col = _col_letter(ncols)
    company_col_idx = header.index("Company")  # 0-based buat indexing all_values

    all_values = ws.get_all_values()

    # Batas blok scraping: baris pertama setelah pembatas merah (ORIGINAL_DATA_END_ROW+1) sampai
    # baris terakhir yang beneran ada isinya.
    scrape_start = ORIGINAL_DATA_END_ROW + 2  # 1-based, baris data pertama setelah pembatas
    last_row_with_data = len(all_values)
    while last_row_with_data > ORIGINAL_DATA_END_ROW and not any(
        c.strip() for c in all_values[last_row_with_data - 1]
    ):
        last_row_with_data -= 1

    scrape_block = all_values[scrape_start - 1:last_row_with_data]
    log.info(f"[move-batch] blok scraping: baris {scrape_start}-{last_row_with_data} "
             f"({len(scrape_block)} baris).")

    start_idx = end_idx = None
    for i, row in enumerate(scrape_block):
        company = row[company_col_idx].strip() if len(row) > company_col_idx else ""
        if company == START_COMPANY and start_idx is None:
            start_idx = i
        if company == END_COMPANY:
            end_idx = i

    if start_idx is None or end_idx is None or end_idx < start_idx:
        log.error(f"[move-batch] gagal ketemu range yang valid - start_idx={start_idx}, "
                  f"end_idx={end_idx}. Gak ada yang diubah.")
        return

    target_block = scrape_block[start_idx:end_idx + 1]
    remaining = scrape_block[:start_idx] + scrape_block[end_idx + 1:]
    log.info(f"[move-batch] ketemu {len(target_block)} baris ({START_COMPANY} s/d {END_COMPANY}), "
             f"dipindah ke depan blok scraping.")

    new_order = target_block + remaining
    # Samain panjang tiap baris ke ncols (jaga-jaga ada baris pendek dari get_all_values()).
    new_order = [row + [""] * (ncols - len(row)) if len(row) < ncols else row[:ncols]
                 for row in new_order]

    ws.update(range_name=f"A{scrape_start}:{last_col}{last_row_with_data}", values=new_order,
              value_input_option="RAW")
    log.info(f"[move-batch] urutan blok scraping ditulis ulang (baris {scrape_start}-"
             f"{last_row_with_data}).")

    _resync_no_column(ws)
    log.info("[move-batch] selesai, kolom No udah di-resync.")


if __name__ == "__main__":
    run()
