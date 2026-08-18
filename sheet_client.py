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

EXTRA_COLUMNS = ["LAST_ROUND", "LAST_SENT_AT", "Website"]

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


def get_core_database_worksheet():
    gc = _client()
    sh = gc.open_by_key(GOOGLE_SHEET_ID)
    return sh.worksheet("CORE DATABASE")


# Rekap harian "client dihubungi" ditaruh di kolom X/Y (24/25) tab CORE DATABASE - kosong di
# sheet asli (data existing cuma sampai kolom V), jadi aman gak nimpa apa-apa.
_DAILY_RECAP_COL = 24       # X
_DAILY_RECAP_HEADER_ROW = 1
_DAILY_RECAP_DATA_START_ROW = 3


def get_daily_email_count(core_ws, date_wib_str):
    """Baca ulang berapa email yang UDAH sukses terkirim hari ini (dari tabel rekap harian) - buat
    main.py ngitung sisa budget MAX_EMAILS_PER_DAY sebelum mulai run. Return 0 kalau belum ada
    baris buat tanggal itu (hari pertama / tabel belum pernah dibuat)."""
    col = _DAILY_RECAP_COL
    existing_dates = core_ws.col_values(col)[_DAILY_RECAP_DATA_START_ROW - 1:]
    for i, val in enumerate(existing_dates):
        if val.strip() == date_wib_str:
            row = _DAILY_RECAP_DATA_START_ROW + i
            raw = core_ws.cell(row, col + 3).value  # kolom Email
            try:
                return int(raw)
            except (TypeError, ValueError):
                return 0
    return 0


def record_daily_contacts(core_ws, date_wib_str, whatsapp_count=0, email_count=0):
    """Tambahkan/increment jumlah client yang dihubungi pada tanggal_wib_str (format DD/MM/YYYY,
    sesuai konvensi tanggal yang udah dipakai di sheet asli) di tabel rekap harian CORE DATABASE,
    dipecah per channel (WhatsApp/Email) plus kolom Total. Bikin header tabel dulu kalau belum
    ada. Satu baris per tanggal - dipanggil sekali per run dengan jumlah client yang berhasil
    dikontak di run itu (per channel), nambah ke angka hari itu kalau baris tanggalnya udah ada
    (run berikutnya di hari yang sama), atau bikin baris baru kalau ganti hari."""
    total = whatsapp_count + email_count
    if total <= 0:
        return

    col = _DAILY_RECAP_COL
    header_cell = core_ws.cell(_DAILY_RECAP_HEADER_ROW, col).value
    if not header_cell:
        core_ws.update_cell(_DAILY_RECAP_HEADER_ROW, col, "REKAP HARIAN - CLIENT DIHUBUNGI (WIB)")
        core_ws.update_cell(_DAILY_RECAP_HEADER_ROW + 1, col, "Tanggal (WIB)")
        core_ws.update_cell(_DAILY_RECAP_HEADER_ROW + 1, col + 1, "Total")
        core_ws.update_cell(_DAILY_RECAP_HEADER_ROW + 1, col + 2, "WhatsApp")
        core_ws.update_cell(_DAILY_RECAP_HEADER_ROW + 1, col + 3, "Email")

    existing_dates = core_ws.col_values(col)[_DAILY_RECAP_DATA_START_ROW - 1:]
    row_offset = None
    for i, val in enumerate(existing_dates):
        if val.strip() == date_wib_str:
            row_offset = i
            break

    def _int_or_zero(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0

    if row_offset is not None:
        row = _DAILY_RECAP_DATA_START_ROW + row_offset
        cur_total = _int_or_zero(core_ws.cell(row, col + 1).value)
        cur_wa = _int_or_zero(core_ws.cell(row, col + 2).value)
        cur_email = _int_or_zero(core_ws.cell(row, col + 3).value)
        core_ws.update_cell(row, col + 1, cur_total + total)
        core_ws.update_cell(row, col + 2, cur_wa + whatsapp_count)
        core_ws.update_cell(row, col + 3, cur_email + email_count)
    else:
        row = _DAILY_RECAP_DATA_START_ROW + len(existing_dates)
        core_ws.update_cell(row, col, date_wib_str)
        core_ws.update_cell(row, col + 1, total)
        core_ws.update_cell(row, col + 2, whatsapp_count)
        core_ws.update_cell(row, col + 3, email_count)

    log.info(f"[core-db] rekap harian {date_wib_str}: +{total} client dihubungi "
             f"(WA:+{whatsapp_count} Email:+{email_count}).")


# Kolom AD (30) tab CORE DATABASE - jarak sengaja dari tabel rekap harian (X-AA / 24-27) biar gak
# numpuk. Baris 1 = label, baris 2 = quota WA aktif saat ini (di-consume main.py tiap kirim
# sukses, di-set/direset lewat command Telegram - telegram_bot.py), baris 3 = update_id terakhir
# dari Telegram getUpdates yang udah diproses (biar polling gak proses ulang pesan lama - GitHub
# Actions gak punya disk persisten antar run, jadi state ini HARUS disimpan di sheet).
_WA_QUOTA_COL = 30
_WA_QUOTA_LABEL_ROW = 1
_WA_QUOTA_VALUE_ROW = 2
_TELEGRAM_OFFSET_ROW = 3


def get_wa_quota(core_ws):
    """Sisa quota kirim WA yang masih boleh dikirim - default 0 (standby) kalau belum pernah
    di-set. WA main.py gak akan kirim apa pun kalau ini 0, walau WHATSAPP_ENABLED=true."""
    raw = core_ws.cell(_WA_QUOTA_VALUE_ROW, _WA_QUOTA_COL).value
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 0


def set_wa_quota(core_ws, n):
    """Set (bukan tambah) quota kirim WA - dipanggil telegram_bot.py waktu user kasih command
    'kirim wa ke N klien'. Bikin label kolom dulu kalau baris 1 masih kosong (pertama kali)."""
    n = max(0, int(n))
    if not core_ws.cell(_WA_QUOTA_LABEL_ROW, _WA_QUOTA_COL).value:
        core_ws.update_cell(_WA_QUOTA_LABEL_ROW, _WA_QUOTA_COL, "WA SEND QUOTA (command Telegram)")
    core_ws.update_cell(_WA_QUOTA_VALUE_ROW, _WA_QUOTA_COL, n)
    return n


def get_telegram_offset(core_ws):
    raw = core_ws.cell(_TELEGRAM_OFFSET_ROW, _WA_QUOTA_COL).value
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def set_telegram_offset(core_ws, update_id):
    core_ws.update_cell(_TELEGRAM_OFFSET_ROW, _WA_QUOTA_COL, int(update_id))


def mark_row_unreachable(ws, row_number):
    """Tandai baris yang beneran gak ada kontak yang bisa dihubungi sama sekali (nomor WA-capable
    maupun email) - dicat HITAM penuh (teks putih biar kebaca) + kolom FINAL diisi LOST (arti
    aslinya di sheet: kontak client itu memang gak ada sama sekali). Reuse FINAL=LOST biar run
    berikutnya otomatis skip baris ini lewat _FINAL_NEGATIVE check yang udah ada di main.py, gak
    perlu state terpisah buat 'udah pernah ditandai dead-end'."""
    header = ws.row_values(HEADER_ROW)
    ncols = len(header)
    last_col = _col_letter(ncols)
    ws.format(f"A{row_number}:{last_col}{row_number}", {
        "backgroundColor": {"red": 0.0, "green": 0.0, "blue": 0.0},
        "textFormat": {"foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0}},
    })
    if "FINAL" in header:
        final_col = header.index("FINAL") + 1
        ws.update_cell(row_number, final_col, "LOST")
    log.info(f"[sheet] baris {row_number}: gak ada kontak sama sekali, ditandai hitam & FINAL=LOST.")


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


# Baris terakhir dataset asli (671 klien awal, No 1-671, dikonfirmasi manual 17 Aug 2026) - baris
# TETAP, gak akan berubah, jadi di-hardcode BUKAN dideteksi dinamis. Sempat coba deteksi otomatis
# (cari run >=10 baris kosong berturut-turut) tapi itu SALAH begitu data scraping udah nempel
# langsung setelah data asli (cuma 1 baris pemisah, bukan >=10) - heuristiknya malah nyasar nemu
# ujung BAWAH blok scraping sebagai "akhir data asli", bikin batch berikutnya nyisip di tengah
# blok scraping yang udah ada alih-alih tepat setelah data asli. Ketauan lewat test insersi live.
ORIGINAL_DATA_END_ROW = 673


def _resync_no_column(ws):
    """Renumber kolom "No" berurutan (1,2,3,...) buat semua baris yang punya Company, dalam urutan
    baris fisik - dipanggil otomatis tiap kali append_new_leads() nyisip batch baru, karena
    ws.insert_rows() geser baris di bawahnya turun tapi NILAI No lama ikut kebawa apa adanya (jadi
    ada gap besar kalau gak di-resync). Baris kosong (divider/template) dilewatin.

    Retry+backoff di 429 - sheet ini udah ribuan baris dan beberapa workflow (outreach/discovery/
    enrich-maps/telegram) suka nulis ke sheet yang sama nyaris bersamaan, jadi write-quota Sheets
    API (per menit per user) kadang kepakai bareng sampai kena APIError 429 di tengah resync besar
    (kejadian nyata: 1 chunk gagal pas resync ~3900 baris). Delay antar chunk juga dinaikin."""
    import copy
    import time

    all_values = ws.get_all_values()
    batch = []
    counter = 0
    for i, row in enumerate(all_values[HEADER_ROW:], start=HEADER_ROW + 1):
        has_company = len(row) > 1 and row[1].strip() != ""
        if not has_company:
            continue
        counter += 1
        if row[0].strip() != str(counter):
            batch.append({"range": f"A{i}", "values": [[counter]]})

    if not batch:
        return

    for i in range(0, len(batch), 100):
        chunk = batch[i:i + 100]
        for attempt in range(5):
            try:
                # deepcopy WAJIB - gspread.Worksheet.batch_update() memodifikasi dict range di
                # `chunk` IN-PLACE (nambahin prefix "'CLIENT'!" ke tiap range string tiap
                # dipanggil). Reuse `chunk` yang sama di retry bikin prefix numpuk berkali-kali
                # ("'CLIENT'!'CLIENT'!...A1178") dan APIError 400 "Unable to parse range" -
                # kejadian nyata pas retry gara-gara 429 di percobaan pertama.
                ws.batch_update(copy.deepcopy(chunk), value_input_option="RAW")
                break
            except Exception as e:
                if "429" not in str(e) or attempt == 4:
                    raise
                wait = 5 * (attempt + 1)
                log.warning(f"[sheet] kena rate-limit resync No (chunk {i}), retry dalam {wait}s...")
                time.sleep(wait)
        if i + 100 < len(batch):
            time.sleep(4)
    log.info(f"[sheet] kolom No di-resync ({len(batch)} baris diperbarui).")


def append_new_leads(ws, col_index, leads):
    """Tambahkan lead baru (dari discovery/) di PALING BAWAH/AKHIR sheet - per user request
    ("hasil scraping data itu taro di data terakhir di sheet, jgn malah yg lama taro di akhir").
    Desain LAMA nyisip tiap batch baru tepat SETELAH dataset asli (row 674 tetap), yang justru
    bikin batch LAMA makin lama makin ke bawah/akhir tiap ada batch baru masuk - kebalikan dari
    yang diminta. Sekarang: SATU baris pemisah kosong (dicat merah) dibikin SEKALI doang waktu
    batch pertama nempel tepat setelah data asli (row ORIGINAL_DATA_END_ROW+1), abis itu SEMUA
    batch berikutnya tinggal ditambahkan setelah baris terakhir yang udah ada isinya - gak pernah
    nyisip/geser apa pun lagi.

    Ini juga otomatis ngilangin akar masalah bug "warna merah nular" yang pernah kejadian
    (insert_rows() gspread bawa-bawa isu inherit formatting dari baris yang digeser) - append
    biasa (ws.update() di baris kosong baru) gak punya masalah inherit-formatting itu sama sekali.

    "No" auto-increment dari nilai max saat ini (di seluruh sheet, bukan cuma dataset asli).
    col_index: hasil ensure_extra_columns(ws), buat tau posisi kolom LAST_ROUND/LAST_SENT_AT/
    Website. Kolom Website diisi website asli lead (kalau ketemu) atau link Google Maps-nya
    sebagai fallback - biar setiap lead scraping selalu punya link buat verifikasi manual."""
    if not leads:
        return 0

    header = ws.row_values(HEADER_ROW)
    ncols = len(header)
    website_col_idx = col_index.get("Website")  # 1-based, None kalau kolom belum ada

    all_values = ws.get_all_values()
    existing_nos = [
        int(row[0]) for row in all_values[HEADER_ROW:]
        if row and row[0].strip().isdigit()
    ]
    next_no = (max(existing_nos) + 1) if existing_nos else 1

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
        if website_col_idx:
            website = lead.get("website") or lead.get("maps_url") or ""
            row[website_col_idx - 1] = website
        rows_to_write.append(row)
        next_no += 1

    # Baris terakhir yang beneran ada isinya - baris baru selalu nambah PERSIS setelah ini,
    # gak pernah nyisip di tengah. Kalau belum ada data scraping sama sekali (sheet masih persis
    # berakhir di data asli), ini otomatis balik ke ORIGINAL_DATA_END_ROW.
    last_row_with_data = len(all_values)
    while last_row_with_data > ORIGINAL_DATA_END_ROW and not any(
        c.strip() for c in all_values[last_row_with_data - 1]
    ):
        last_row_with_data -= 1

    last_col = _col_letter(ncols)
    divider_row = ORIGINAL_DATA_END_ROW + 1
    is_first_batch_ever = last_row_with_data <= ORIGINAL_DATA_END_ROW

    if is_first_batch_ever:
        # Batch scraping PERTAMA - bikin satu baris pemisah kosong dicat merah, SEKALI SAJA.
        # Baris ini gak akan pernah disentuh/digeser lagi oleh batch-batch berikutnya.
        if divider_row + 1 + len(rows_to_write) > ws.row_count:
            ws.add_rows(divider_row + 1 + len(rows_to_write) - ws.row_count)
        ws.format(f"A{divider_row}:{last_col}{divider_row}", {
            "backgroundColor": {"red": 1.0, "green": 0.0, "blue": 0.0}
        })
        data_start = divider_row + 1
    else:
        data_start = last_row_with_data + 1
        if data_start + len(rows_to_write) - 1 > ws.row_count:
            ws.add_rows(data_start + len(rows_to_write) - 1 - ws.row_count)

    data_end = data_start + len(rows_to_write) - 1

    # RAW, not USER_ENTERED - phone numbers like "0" or "5xx-xxx-xxxx" can get parsed as an
    # arithmetic expression by Sheets under USER_ENTERED, producing #ERROR! (seen live in
    # testing). Every field here is plain text/digits, never a formula, so RAW is correct.
    ws.update(f"A{data_start}:{last_col}{data_end}", rows_to_write, value_input_option="RAW")
    ws.format(f"A{data_start}:{last_col}{data_end}", {
        "backgroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0},
        "textFormat": {"foregroundColor": {"red": 0.0, "green": 0.0, "blue": 0.0}},
    })

    log.info(f"[sheet] {len(rows_to_write)} lead baru ditambahkan di AKHIR CLIENT tab "
             f"(baris {data_start}-{data_end}).")

    _resync_no_column(ws)
    return len(rows_to_write)
