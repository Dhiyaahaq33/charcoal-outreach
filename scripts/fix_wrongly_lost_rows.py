"""Cari & reset baris yang SALAH ditandai hitam + FINAL=LOST oleh mark_row_unreachable() gara-gara
rule deteksi landline yang LAMA (phonenumbers-based) - sekarang diganti rule tanda-kurung
(has_office_format(), lihat commit d73a532). Baris yang phonenumbers dulu SALAH nganggep landline
padahal nomornya gak ditulis pakai tanda kurung (jadi harusnya WA-capable di rule baru), DAN gak
punya email juga, kelanjur ditandai LOST permanen - itu false positive yang perlu di-undo.

Identifikasi 2 lapis biar gak nyentuh LOST manual asli dari data kurasi lama (yang gak ada
hubungannya sama bug ini):
  1. FINAL == "LOST"
  2. Background baris HITAM (ciri khas satu-satunya dari mark_row_unreachable() - fitur baru sesi
     ini, gak pernah dipakai buat data lama) - dicek via raw Sheets API (gspread gak expose format
     lewat get_all_values()).
Baru dari situ, cek ulang pakai rule BARU: kalau raw_number ADA dan has_office_format() FALSE
(gak ada tanda kurung) DAN email masih kosong -> ini false positive, reset FINAL & warna balik ke
default, biar main.py re-evaluate dari awal run berikutnya.

Run manual: python scripts/fix_wrongly_lost_rows.py
"""

import json
import logging
import sys

sys.path.insert(0, ".")
from config import GOOGLE_SERVICE_ACCOUNT_JSON, GOOGLE_SHEET_ID, CLIENT_SHEET_TAB
from sheet_client import get_worksheet, HEADER_ROW, ORIGINAL_DATA_END_ROW, _col_letter, _retry_on_429
from send_whatsapp import extract_number, has_office_format

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def _authed_session():
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2.service_account import Credentials

    info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
    creds = Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return AuthorizedSession(creds)


def _is_black_background(session, row_number):
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{GOOGLE_SHEET_ID}"
    params = {
        "ranges": f"{CLIENT_SHEET_TAB}!A{row_number}:A{row_number}",
        "fields": "sheets.data.rowData.values.userEnteredFormat.backgroundColor",
    }
    resp = session.get(url, params=params, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    try:
        bg = data["sheets"][0]["data"][0]["rowData"][0]["values"][0]["userEnteredFormat"]["backgroundColor"]
    except (KeyError, IndexError):
        return False
    r = bg.get("red", 1)
    g = bg.get("green", 1)
    b = bg.get("blue", 1)
    return r < 0.1 and g < 0.1 and b < 0.1


def run():
    ws = get_worksheet()
    header = ws.row_values(HEADER_ROW)
    ncols = len(header)
    last_col = _col_letter(ncols)
    final_col = header.index("FINAL") + 1

    all_values = ws.get_all_values()

    lost_candidates = []
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
            lost_candidates.append(i)

    log.info(f"[fix-lost] {len(lost_candidates)} baris FINAL=LOST yang SEHARUSNYA WA-capable di "
             f"rule baru (kandidat awal, belum dicek warna).")
    if not lost_candidates:
        return

    session = _authed_session()
    to_reset = []
    for row_number in lost_candidates:
        if _is_black_background(session, row_number):
            to_reset.append(row_number)

    log.info(f"[fix-lost] {len(to_reset)} dari kandidat itu beneran dicat HITAM (ciri khas "
             f"mark_row_unreachable()) - ini yang di-reset. Sisanya ({len(lost_candidates) - len(to_reset)}) "
             f"dibiarin (kemungkinan LOST manual asli, bukan dari bug ini).")

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

    log.info(f"[fix-lost] selesai - {len(to_reset)} baris di-reset (FINAL dikosongin, warna balik "
             f"normal), bakal di-evaluate ulang main.py run berikutnya.")


if __name__ == "__main__":
    run()
