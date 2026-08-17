"""Entrypoint. Jalan tiap 30 menit lewat GitHub Actions cron (lihat .github/workflows/outreach.yml)
- 100% di cloud, gak ada device/PC pribadi yang harus nyala.

Alur per baris di sheet CLIENT:
  1. Skip kalau FCBK udah final negatif (LOST/NO).
  2. Skip kalau LAST_ROUND udah 3 (semua round abis, biarin manual recontact nanti - lihat FCBK
     PENDING di konsep aslinya).
  3. Skip kalau country di luar window Senin-Jumat 09:00-17:00 waktu lokal (timezone_rules.py -
     dihitung ulang tiap run, bukan bergantung kolom DAY/HOUR manual di sheet).
  4. Skip kalau baris ini udah dikirim < 20 menit lalu (guard anti dobel-kirim kalau run tumpang
     tindih - LAST_SENT_AT).
  5. Skip kalau round berikutnya (2 atau 3) belum MIN_DAYS_BETWEEN_ROUNDS hari (default 7) sejak
     round sebelumnya - follow-up cadence B2B wajar, bukan spam ke calon buyer yang sama di hari
     yang sama.
  6. round = LAST_ROUND + 1. Coba WhatsApp dulu (Fonnte); kalau gagal/nomor gak ada, fallback Email
     (Gmail SMTP). Kalau dua-duanya gagal, di-skip (gak update sheet, dicoba lagi run berikutnya).
  7. Tulis balik ke sheet: kolom [round][channel]=DONE, LAST_ROUND, LAST_SENT_AT.

DRY_RUN=true (default) -> hitung semua, log apa yang MAU dikirim ke siapa, tapi gak benar-benar
kirim & gak nulis ke sheet. Pakai ini dulu buat review sebelum live.
"""

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from config import DRY_RUN, MAX_ROUNDS, MIN_DAYS_BETWEEN_ROUNDS, WHATSAPP_ENABLED
from sheet_client import (
    get_worksheet, ensure_extra_columns, load_rows, mark_offer_sent,
    get_core_database_worksheet, record_daily_contacts,
)
from timezone_rules import is_open_hour_window
from send_whatsapp import send_whatsapp, extract_number
from send_email import send_email
from templates import render_whatsapp, render_email

_WIB = ZoneInfo("Asia/Jakarta")  # WIB = Bogor/Jakarta, UTC+7

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

_RESEND_GUARD = timedelta(minutes=20)
_FINAL_NEGATIVE = {"LOST", "NO"}


def _last_round(row):
    val = row.get("LAST_ROUND")
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0


def _recently_sent(row):
    raw = row.get("LAST_SENT_AT")
    if not raw:
        return False
    try:
        sent_at = datetime.fromisoformat(raw)
    except ValueError:
        return False
    return datetime.now(timezone.utc) - sent_at < _RESEND_GUARD


def _too_soon_for_next_round(row, round_number):
    """Round 2/3 harus nunggu minimal MIN_DAYS_BETWEEN_ROUNDS hari sejak LAST_SENT_AT - beda
    dari _recently_sent() (guard 20 menit anti run tumpang tindih). Round 1 selalu boleh langsung
    (belum ada round sebelumnya buat dibandingin). Baris lama hasil backfill yang gak punya
    LAST_SENT_AT (histori manual sebelum bot ada) gak diblokir - gak ada data buat tau kapan
    terakhir dikontak, jadi dianggap aman lanjut daripada nge-block permanen."""
    if round_number <= 1:
        return False
    raw = row.get("LAST_SENT_AT")
    if not raw:
        return False
    try:
        sent_at = datetime.fromisoformat(raw)
    except ValueError:
        return False
    return datetime.now(timezone.utc) - sent_at < timedelta(days=MIN_DAYS_BETWEEN_ROUNDS)


def process_row(row, col_index, ws):
    """Return "whatsapp"/"email" kalau berhasil kirim offer beneran (bukan DRY_RUN), None kalau
    skip/gagal - dipakai main() buat ngitung total client dihubungi run ini per channel (rekap
    harian CORE DATABASE)."""
    company = row.get("Company", "(no name)")
    country = row.get("Country", "")
    # Kolom aslinya namanya "FINAL" di header row 2 - "FCBK" cuma label grup yang di-merge di baris
    # atasnya, bukan nama kolom beneran. Baca "FCBK" di sini bakal selalu kosong (bug lama).
    fcbk = str(row.get("FINAL", "")).strip().upper()

    if fcbk in _FINAL_NEGATIVE:
        return None

    round_number = _last_round(row) + 1
    if round_number > MAX_ROUNDS:
        return None

    if _recently_sent(row):
        log.info(f"[skip] {company}: baru dikirim < {_RESEND_GUARD}, skip (anti dobel-kirim).")
        return None

    if _too_soon_for_next_round(row, round_number):
        log.debug(f"[skip] {company}: round {round_number} belum {MIN_DAYS_BETWEEN_ROUNDS} hari "
                  f"sejak round terakhir dikirim.")
        return None

    is_open, detail = is_open_hour_window(country)
    if not is_open:
        log.debug(f"[skip] {company} ({country}): {detail}")
        return None

    log.info(f"[offer] {company} ({country}) round {round_number} - {detail}")

    number = extract_number(row.get("WhatsApp", ""), row.get("Phone", ""))
    email = row.get("Email", "").strip()

    channel_used = None
    if number and WHATSAPP_ENABLED:
        message = render_whatsapp(row, round_number)
        if DRY_RUN:
            log.info(f"[DRY_RUN] would send WhatsApp to {number}:\n{message}\n")
            channel_used = "whatsapp"
        elif send_whatsapp(number, message):
            channel_used = "whatsapp"

    if not channel_used and email:
        subject, body = render_email(row, round_number)
        if DRY_RUN:
            log.info(f"[DRY_RUN] would send Email to {email} | subject={subject}\n{body}\n")
            channel_used = "email"
        elif send_email(email, subject, body):
            channel_used = "email"

    if not channel_used:
        log.warning(f"[fail] {company}: WhatsApp & Email dua-duanya gagal/gak ada, di-skip run ini.")
        return None

    if DRY_RUN:
        log.info(f"[DRY_RUN] would update sheet row {row['_row_number']}: round={round_number}, "
                  f"channel={channel_used}")
        return None

    mark_offer_sent(
        ws, col_index, row["_row_number"], round_number, channel_used,
        datetime.now(timezone.utc).isoformat(),
    )
    log.info(f"[sent] {company}: round {round_number} via {channel_used}, sheet updated.")
    return channel_used


def main():
    log.info(f"=== Charcoal outreach run start (DRY_RUN={DRY_RUN}) ===")
    ws = get_worksheet()
    col_index = ensure_extra_columns(ws)
    rows = load_rows(ws)
    log.info(f"{len(rows)} baris dimuat dari sheet.")

    wa_count = 0
    email_count = 0
    for row in rows:
        try:
            channel = process_row(row, col_index, ws)
            if channel == "whatsapp":
                wa_count += 1
            elif channel == "email":
                email_count += 1
        except Exception as e:
            log.error(f"[error] gagal proses baris {row.get('_row_number')}: {e}")

    sent_count = wa_count + email_count
    if sent_count and not DRY_RUN:
        today_wib = datetime.now(_WIB).strftime("%d/%m/%Y")
        try:
            core_ws = get_core_database_worksheet()
            record_daily_contacts(core_ws, today_wib, whatsapp_count=wa_count, email_count=email_count)
        except Exception as e:
            log.error(f"[error] gagal update rekap harian CORE DATABASE: {e}")

    log.info(f"=== Run selesai ({sent_count} client dihubungi - WA:{wa_count} Email:{email_count}) ===")


if __name__ == "__main__":
    main()
