"""Cari & reset baris yang SALAH ditandai FINAL=LOST oleh mark_row_unreachable() gara-gara rule
deteksi landline yang LAMA (phonenumbers-based) - sekarang diganti rule tanda-kurung
(has_office_format(), lihat commit d73a532). Baris yang phonenumbers dulu SALAH nganggep landline
padahal nomornya gak ditulis pakai tanda kurung (jadi harusnya WA-capable di rule baru), DAN gak
punya email juga, kelanjur ditandai LOST permanen - itu false positive yang perlu di-undo.

Identifikasi TANPA perlu cek warna baris (awalnya nyoba cek background HITAM via raw Sheets API,
tapi ternyata gak reliable - scripts/move_batch_to_top.py yang jalan lebih dulu mindahin NILAI sel
doang lewat ws.update(), formatting/warna GAK ikut pindah bareng, jadi warna hitam "ketinggalan" di
posisi baris lama sementara datanya udah pindah ke baris lain - konfirmasi langsung: baris
"Tradeasia International" yang diketahui FINAL=LOST dari log run 18 Aug ternyata background-nya
udah putih sekarang). Cara yang PASTI: baris hasil scraping (row > ORIGINAL_DATA_END_ROW) CUMA
BISA punya FINAL=LOST dari mark_row_unreachable() - discovery_main.py gak pernah nyetel FINAL
waktu insert lead baru, dan gak ada kode lain yang nyetel LOST buat baris di area ini. Jadi
posisi baris (>673) aja udah cukup buat mastiin ini bukan LOST manual dari data kurasi asli
(671 client awal, di luar range yang disentuh script ini).

Run manual: python scripts/fix_wrongly_lost_rows.py
"""

import logging
import sys
import time

sys.path.insert(0, ".")
from sheet_client import get_worksheet, HEADER_ROW, ORIGINAL_DATA_END_ROW, _col_letter, _retry_on_429
from send_whatsapp import extract_number, has_office_format

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def run():
    ws = get_worksheet()
    header = ws.row_values(HEADER_ROW)
    ncols = len(header)
    last_col = _col_letter(ncols)
    final_col = header.index("FINAL") + 1

    all_values = ws.get_all_values()

    to_reset = []
    for i, row in enumerate(all_values[ORIGINAL_DATA_END_ROW:], start=ORIGINAL_DATA_END_ROW + 1):
        company = row[1].strip() if len(row) > 1 else ""
        if not company:
            continue
        final_val = row[final_col - 1].strip().upper() if len(row) >= final_col else ""
        if final_val != "LOST":
            continue

        phone_field = row[6] if len(row) > 6 else ""       # kolom Phone
        whatsapp_field = row[7] if len(row) > 7 else ""    # kolom WhatsApp
        email_field = row[8].strip() if len(row) > 8 else ""  # kolom Email

        raw_number = extract_number(whatsapp_field, phone_field)
        would_be_wa_now = raw_number and not has_office_format(phone_field, whatsapp_field)

        if would_be_wa_now and not email_field:
            to_reset.append(i)

    log.info(f"[fix-lost] {len(to_reset)} baris FINAL=LOST yang SEHARUSNYA WA-capable di rule "
             f"baru (dan gak ada email) - ini false positive dari rule lama, di-reset.")
    if not to_reset:
        return

    updates = []
    for row_number in to_reset:
        updates.append({"range": f"{_col_letter(final_col)}{row_number}", "values": [[""]]})
    _retry_on_429(lambda u=updates: ws.batch_update(u, value_input_option="RAW"))

    for row_number in to_reset:
        _retry_on_429(
            ws.format, f"A{row_number}:{last_col}{row_number}",
            {
                "backgroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0},
                "textFormat": {"foregroundColor": {"red": 0.0, "green": 0.0, "blue": 0.0}},
            },
        )
        time.sleep(1)

    log.info(f"[fix-lost] selesai - {len(to_reset)} baris di-reset (FINAL dikosongin, warna balik "
             f"normal), bakal di-evaluate ulang main.py run berikutnya.")

    _resync_row_colors(ws, all_values, final_col, ncols, last_col, to_reset)


def _resync_row_colors(ws, all_values, final_col, ncols, last_col, already_reset):
    """Efek samping dari move_batch_to_top.py sebelumnya: itu mindahin NILAI sel doang (ws.update()
    values-only), formatting/warna GAK ikut kepindah bareng datanya - jadi warna hitam bisa
    "ketinggalan" di posisi baris lama sementara datanya udah geser ke baris lain (kejadian nyata:
    baris "Tradeasia International" FINAL=LOST tapi background udah putih). Ini nyamain lagi warna
    tiap baris hasil scraping sesuai status FINAL SAAT INI.

    Efisien: PUTIHKAN SEMUA baris scraping sekaligus dalam SATU request (bukan per-baris - mayoritas
    ribuan baris emang seharusnya putih), baru HITAMKAN ULANG cuma baris yang FINAL=LOST (jumlahnya
    jauh lebih sedikit, itu baru per-baris)."""
    last_row_with_data = len(all_values)
    while last_row_with_data > ORIGINAL_DATA_END_ROW and not any(
        c.strip() for c in all_values[last_row_with_data - 1]
    ):
        last_row_with_data -= 1

    scrape_start = ORIGINAL_DATA_END_ROW + 1  # termasuk baris pembatas merah
    log.info(f"[fix-lost] resync warna: putihkan A{scrape_start}:{last_col}{last_row_with_data} "
             f"dulu (satu request)...")
    _retry_on_429(ws.format, f"A{scrape_start}:{last_col}{last_row_with_data}", {
        "backgroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0},
        "textFormat": {"foregroundColor": {"red": 0.0, "green": 0.0, "blue": 0.0}},
    })
    _retry_on_429(ws.format, f"A{scrape_start}:{last_col}{scrape_start}", {
        "backgroundColor": {"red": 1.0, "green": 0.0, "blue": 0.0}
    })  # pembatas merah balik lagi

    already_reset_set = set(already_reset)
    should_be_black = []
    for i, row in enumerate(all_values[ORIGINAL_DATA_END_ROW:], start=ORIGINAL_DATA_END_ROW + 1):
        company = row[1].strip() if len(row) > 1 else ""
        if not company or i in already_reset_set:
            continue
        final_val = row[final_col - 1].strip().upper() if len(row) >= final_col else ""
        if final_val == "LOST":
            should_be_black.append(i)

    log.info(f"[fix-lost] hitamkan ulang {len(should_be_black)} baris yang beneran FINAL=LOST...")
    for row_number in should_be_black:
        _retry_on_429(
            ws.format, f"A{row_number}:{last_col}{row_number}",
            {
                "backgroundColor": {"red": 0.0, "green": 0.0, "blue": 0.0},
                "textFormat": {"foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0}},
            },
        )
        time.sleep(1)

    log.info("[fix-lost] resync warna selesai.")


if __name__ == "__main__":
    run()
