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

# Sheet asli punya 2 baris header: baris 1 = label grup yang di-merge (mis. "[merged] FIRST"),
# baris 2 = header kolom asli ("No, Company, Country, ..."). Semua kode di sini harus baca/tulis
# header di baris 2, BUKAN baris 1 - kalau baca baris 1, header.index("WHATSAPP") bakal ValueError
# karena "WHATSAPP" cuma ada di baris 2. Dikonfirmasi manual lewat gspread langsung ke sheet asli.
HEADER_ROW = 2

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
    header = ws.row_values(HEADER_ROW)
    col_index = {}
    next_col = len(header) + 1
    changed = False
    for name in EXTRA_COLUMNS:
        if name in header:
            col_index[name] = header.index(name) + 1
        else:
            ws.update_cell(HEADER_ROW, next_col, name)
            col_index[name] = next_col
            next_col += 1
            changed = True
    if changed:
        log.info(f"[sheet] kolom baru ditambahkan: {col_index}")
    return col_index


def load_rows(ws):
    """Return list of dict per baris client (header row jadi key), plus '_row_number' (1-based,
    termasuk header, jadi baris pertama data = 2). Pakai get_all_values() manual (bukan
    get_all_records()) karena header row di sheet asli punya banyak kolom kosong/duplikat
    (WHATSAPP/EMAIL muncul 3x untuk FIRST/SECOND/THIRD) - get_all_records() gspread error kalau
    ada header kosong duplikat. Kolom kosong di-skip, duplikat nama diambil kemunculan PERTAMA
    saja (cukup buat field yang dipakai bot: Company/Country/Phone/WhatsApp/Email/FCBK/dst, yang
    semuanya unik)."""
    all_values = ws.get_all_values()
    header = all_values[HEADER_ROW - 1]
    rows = []
    for i, raw_row in enumerate(all_values[HEADER_ROW:], start=HEADER_ROW + 1):
        if not any(cell.strip() for cell in raw_row):
            continue  # baris kosong total, skip
        rec = {}
        for col_name, value in zip(header, raw_row):
            if not col_name or col_name in rec:
                continue
            rec[col_name] = value
        rec["_row_number"] = i
        rows.append(rec)
    return rows


def mark_offer_sent(ws, col_index, row_number, round_number, channel, when_iso):
    """Tulis balik: kolom [FIRST/SECOND/THIRD][WHATSAPP/EMAIL] = DONE, LAST_ROUND = round_number,
    LAST_SENT_AT = when_iso. Kalau round_number == 3 (offer terakhir), kolom FINAL (label grup di
    atasnya "FCBK" - nama kolom asli di header row 2 adalah "FINAL", bukan "FCBK") ikut diisi
    PENDING, KECUALI udah ada nilai NO/LOST di situ (final negatif gak boleh ke-overwrite jadi
    PENDING). Nama kolom round di sheet asli pakai header duplikat (WHATSAPP/EMAIL muncul 3x untuk
    FIRST/SECOND/THIRD) - gspread get_all_records akan collapse nama duplikat, jadi update kolom
    round pakai offset kolom manual berdasarkan urutan header mentah, bukan lewat dict hasil
    get_all_records."""
    header = ws.row_values(HEADER_ROW)
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

    if round_number == 3 and "FINAL" in header:
        final_col = header.index("FINAL") + 1
        current = ws.cell(row_number, final_col).value or ""
        if current.strip().upper() not in ("NO", "LOST"):
            ws.update_cell(row_number, final_col, "PENDING")


def _col_letter(n):
    """1-based column count -> A1 column letter (26='Z', 27='AA', ...)."""
    letters = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def append_new_leads(ws, leads):
    """Append newly-discovered leads (from discovery/) as new rows at the end of the sheet, with
    ONE blank divider row in between (colored red) so scraped batches are visually separated from
    the original/prior data - each call adds its own divider, so multiple discovery runs stack as
    distinct red-separated blocks. "No" is auto-incremented from the current max. Only the first 9
    columns (No..Email) are filled - everything else (Day/Hour/STATUS/rounds/FINAL/LAST_ROUND/etc)
    stays blank, computed live by main.py on the next run same as any other row.

    Writes via an explicit ws.update() range (not append_rows) - append_rows auto-detects the
    "first empty row" by cell VALUES, which would land inside the blank divider row itself (empty
    cells still count as empty even with background color set), destroying the separation."""
    if not leads:
        return 0

    header = ws.row_values(HEADER_ROW)
    ncols = len(header)
    all_values = ws.get_all_values()
    last_row = len(all_values)
    existing_nos = [
        int(row[0]) for row in all_values[HEADER_ROW:]
        if row and row[0].strip().isdigit()
    ]
    next_no = (max(existing_nos) + 1) if existing_nos else 1

    divider_row = last_row + 1
    data_start_row = divider_row + 1

    rows_to_write = []
    for lead in leads:
        row = [""] * ncols
        row[0] = str(next_no)
        row[1] = lead.get("company", "")
        row[2] = lead.get("country", "")
        row[3] = lead.get("role", "")
        row[4] = lead.get("product_interest", "")
        row[5] = lead.get("contact_person", "")
        row[6] = lead.get("phone", "")
        row[7] = lead.get("whatsapp", "")
        row[8] = lead.get("email", "")
        rows_to_write.append(row)
        next_no += 1

    data_end_row = data_start_row + len(rows_to_write) - 1
    last_col = _col_letter(ncols)

    if data_end_row > ws.row_count:
        ws.add_rows(data_end_row - ws.row_count)

    ws.format(f"A{divider_row}:{last_col}{divider_row}", {
        "backgroundColor": {"red": 1.0, "green": 0.0, "blue": 0.0}
    })
    # RAW, not USER_ENTERED - phone numbers like "0" or "5xx-xxx-xxxx" can get parsed as an
    # arithmetic expression by Sheets under USER_ENTERED, producing #ERROR! (seen live in
    # testing). Every field here is plain text/digits, never a formula, so RAW is correct.
    ws.update(range_name=f"A{data_start_row}:{last_col}{data_end_row}", values=rows_to_write,
              value_input_option="RAW")

    log.info(f"[sheet] {len(rows_to_write)} lead baru ditambahkan ke CLIENT tab "
             f"(baris {data_start_row}-{data_end_row}, divider merah di baris {divider_row}).")
    return len(rows_to_write)
