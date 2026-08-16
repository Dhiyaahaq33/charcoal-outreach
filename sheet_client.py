"""Baca & tulis balik tab CLIENT di Google Sheet, pola sama seperti sheets_export.py di
bandar-broksum: service account JSON utuh di GOOGLE_SERVICE_ACCOUNT_JSON (bukan file terpisah),
sheet-nya harus di-share ke email service account itu (role Editor) dulu.

Kolom LAST_ROUND (0-3) dan LAST_SENT_AT (ISO timestamp) ditambahkan otomatis di ujung kanan kalau
belum ada - bot pakai ini buat tau udah sampai offer ke berapa tanpa parse ulang kolom
FIRST/SECOND/THIRD WHATSAPP/EMAIL yang formatnya masih manual/merged di sheet aslinya.
"""

import json
import logging

from config import GOOGLE_SERVICE_ACCOUNT_JSON, GOOGLE_SHEET_ID, CLIENT_SHEET_TAB

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
]

EXTRA_COLUMNS = ["LAST_ROUND", "LAST_SENT_AT"]

log = logging.getLogger(__name__)


def _client():
    import gspread
    from google.oauth2.service_account import Credentials

    info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
    creds = Credentials.from_service_account_info(info, scopes=_SCOPES)
    return gspread.authorize(creds)


def get_worksheet():
    gc = _client()
    sh = gc.open_by_key(GOOGLE_SHEET_ID)
    return sh.worksheet(CLIENT_SHEET_TAB)


def ensure_extra_columns(ws):
    """Tambah header LAST_ROUND/LAST_SENT_AT di kolom kosong pertama kalau belum ada. Return dict
    {nama_kolom: index_1based}."""
    header = ws.row_values(1)
    col_index = {}
    next_col = len(header) + 1
    changed = False
    for name in EXTRA_COLUMNS:
        if name in header:
            col_index[name] = header.index(name) + 1
        else:
            ws.update_cell(1, next_col, name)
            col_index[name] = next_col
            next_col += 1
            changed = True
    if changed:
        log.info(f"[sheet] kolom baru ditambahkan: {col_index}")
    return col_index


def load_rows(ws):
    """Return list of dict per baris client (header row jadi key), plus '_row_number' (1-based,
    termasuk header, jadi baris pertama data = 2)."""
    records = ws.get_all_records()
    rows = []
    for i, rec in enumerate(records, start=2):
        rec["_row_number"] = i
        rows.append(rec)
    return rows


def mark_offer_sent(ws, col_index, row_number, round_number, channel, when_iso):
    """Tulis balik: kolom [FIRST/SECOND/THIRD][WHATSAPP/EMAIL] = DONE, LAST_ROUND = round_number,
    LAST_SENT_AT = when_iso. Nama kolom round di sheet asli pakai header duplikat (WHATSAPP/EMAIL
    muncul 3x untuk FIRST/SECOND/THIRD) - gspread get_all_records akan collapse nama duplikat, jadi
    update kolom round pakai offset kolom manual berdasarkan urutan header mentah, bukan lewat dict
    hasil get_all_records."""
    header = ws.row_values(1)
    round_offset = {1: 0, 2: 2, 3: 4}[round_number]  # tiap round = 2 kolom (WHATSAPP, EMAIL)
    try:
        first_whatsapp_col = header.index("WHATSAPP") + 1
    except ValueError:
        raise RuntimeError("Kolom 'WHATSAPP' gak ketemu di header sheet - cek struktur CLIENT tab")

    channel_sub_offset = 0 if channel == "whatsapp" else 1
    target_col = first_whatsapp_col + round_offset + channel_sub_offset

    ws.update_cell(row_number, target_col, "DONE")
    ws.update_cell(row_number, col_index["LAST_ROUND"], round_number)
    ws.update_cell(row_number, col_index["LAST_SENT_AT"], when_iso)
