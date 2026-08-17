"""One-off cleanup for two bugs found live in the CLIENT sheet (17 Aug 2026):

1. RED CASCADE BUG: append_new_leads() inserted each new discovery batch at the same fixed
   position (right after original data) using gspread's insert_rows() default
   inherit_from_before=False - that inherits formatting from whatever row is CURRENTLY at the
   insertion point, which is always the PREVIOUS batch's red divider row. Every ~30-min discovery
   run for about a day cascaded that red across nearly the entire scraped block instead of just
   one single divider row. Fixed at the source in sheet_client.append_new_leads() (now uses
   inherit_from_before=True + explicit background reset on data rows) - this script undoes the
   damage already done: reset background/text color to default for every row from
   ORIGINAL_DATA_END_ROW+1 onward, then re-paint ONLY that one row red as the single divider.
   (Rows genuinely dead-end - no contactable channel - will get re-painted black again naturally
   by main.py's mark_row_unreachable() on its next pass; no need to special-case them here.)

2. Placeholder regret: the first backfill (scripts/backfill_leads.py) wrote a repeated boilerplate
   disclaimer into Product Interest for ~628 old rows. User doesn't want that text at all - clear
   it back to blank so old rows just have an honestly-empty Product Interest instead of a wall of
   repeated placeholder text.

Run manual: python scripts/fix_red_cascade_and_placeholder.py
Via workflow_dispatch: .github/workflows/backfill-leads.yml can be reused, or run this directly.
"""

import logging
import sys
import time

sys.path.insert(0, ".")
from sheet_client import get_worksheet, HEADER_ROW, ORIGINAL_DATA_END_ROW, _col_letter

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

_PLACEHOLDER_TEXT = (
    "Lead lama hasil scraping sebelum revisi Product Interest (17 Aug 2026) - alasan match "
    "spesifik (kategori Maps/query pencarian) gak kesimpen waktu itu, gak bisa direkonstruksi "
    "ulang. Cek Company & Website/kolom ini manual buat verifikasi relevansi produk."
)


def run():
    ws = get_worksheet()
    header = ws.row_values(HEADER_ROW)
    ncols = len(header)
    last_col = _col_letter(ncols)
    product_col = header.index("Product Interest") + 1

    all_values = ws.get_all_values()
    last_row_with_data = len(all_values)
    while last_row_with_data > ORIGINAL_DATA_END_ROW and not any(
        c.strip() for c in all_values[last_row_with_data - 1]
    ):
        last_row_with_data -= 1

    divider_row = ORIGINAL_DATA_END_ROW + 1
    log.info(f"[fix] reset background A{divider_row}:{last_col}{last_row_with_data} ke putih...")
    ws.format(f"A{divider_row}:{last_col}{last_row_with_data}", {
        "backgroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0},
        "textFormat": {"foregroundColor": {"red": 0.0, "green": 0.0, "blue": 0.0}},
    })

    log.info(f"[fix] cat ulang SATU baris pembatas di baris {divider_row}...")
    ws.format(f"A{divider_row}:{last_col}{divider_row}", {
        "backgroundColor": {"red": 1.0, "green": 0.0, "blue": 0.0}
    })

    updates = []
    for i, row in enumerate(all_values[ORIGINAL_DATA_END_ROW:], start=ORIGINAL_DATA_END_ROW + 1):
        product = row[product_col - 1].strip() if len(row) >= product_col else ""
        if product == _PLACEHOLDER_TEXT:
            updates.append({"range": f"{_col_letter(product_col)}{i}", "values": [[""]]})

    if updates:
        log.info(f"[fix] menghapus placeholder Product Interest dari {len(updates)} baris...")
        for i in range(0, len(updates), 100):
            ws.batch_update(updates[i:i + 100], value_input_option="RAW")
            if i + 100 < len(updates):
                time.sleep(2)
    else:
        log.info("[fix] gak ada placeholder Product Interest yang perlu dihapus.")

    log.info("[fix] selesai.")


if __name__ == "__main__":
    run()
