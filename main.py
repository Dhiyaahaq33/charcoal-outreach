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
  5b. Nomor kantor/landline (kedeteksi via phonenumbers) gak dicoba WA sama sekali, langsung
      fallback ke email. Kalau gak ada nomor WA-capable MAUPUN email sama sekali, baris ditandai
      hitam + FINAL=LOST (dead-end permanen) dan lanjut ke client lain.
  6. round = LAST_ROUND + 1. WhatsApp TIDAK auto-kirim lagi (WHATSAPP_ENABLED cuma kill-switch
     keseluruhan) - hanya jalan selama masih ada quota aktif yang di-set lewat command Telegram
     ("kirim wa ke 50 klien", lihat telegram_bot.py), quota di-consume tiap kirim sukses. Quota
     abis / belum pernah di-set (standby) -> WA di-skip, fallback Email (Gmail SMTP) langsung -
     kecuali budget MAX_EMAILS_PER_DAY (200) hari ini udah abis, dicoba lagi besok. Kalau
     dua-duanya gagal, di-skip (gak update sheet, dicoba lagi run berikutnya). Tiap WA sukses
     dikirim, ada jeda 4-9 detik acak sebelum lanjut baris berikutnya - biar polanya gak keliatan
     burst/spam ke WhatsApp (lihat _WA_SEND_DELAY_SECONDS).
  7. Tulis balik ke sheet: kolom [round][channel]=DONE, LAST_ROUND, LAST_SENT_AT.

DRY_RUN=true (default) -> hitung semua, log apa yang MAU dikirim ke siapa, tapi gak benar-benar
kirim & gak nulis ke sheet. Pakai ini dulu buat review sebelum live.
"""

import logging
import random
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from config import DRY_RUN, MAX_ROUNDS, MIN_DAYS_BETWEEN_ROUNDS, WHATSAPP_ENABLED, MAX_EMAILS_PER_DAY
from sheet_client import (
    get_worksheet, ensure_extra_columns, load_rows, mark_offer_sent, mark_row_unreachable,
    get_core_database_worksheet, record_daily_contacts, get_daily_email_count,
    get_wa_quota, set_wa_quota,
)
from timezone_rules import is_open_hour_window
from send_whatsapp import send_whatsapp, extract_number, is_mobile_number
from send_email import send_email, open_smtp_session, close_smtp_session
from templates import render_whatsapp, render_email

# Jeda antar kirim WhatsApp beneran (bukan DRY_RUN) - biar gak nembak beruntun dalam hitungan
# detik kayak insiden 17 Aug 2026 yang berujung device Fonnte di-disconnect paksa WhatsApp
# (pola kirim identik & rapat = sinyal spam paling gampang kedeteksi). Delay acak, bukan fixed.
_WA_SEND_DELAY_SECONDS = (4, 9)

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


def process_row(row, col_index, ws, smtp_state, email_budget, wa_quota):
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

    # Nomor kantor/landline gak punya WhatsApp - deteksi via phonenumbers, JANGAN dicoba WA sama
    # sekali (biar gak ke-Fonnte sia-sia), langsung fallback ke email kalau ada. Kalau dua-duanya
    # (WA-capable number MAUPUN email) sama sekali gak ada, baris ini dead-end permanen - tandai
    # hitam + FINAL=LOST dan lanjut ke client lain, per user request.
    raw_number = extract_number(row.get("WhatsApp", ""), row.get("Phone", ""))
    number = raw_number if (raw_number and is_mobile_number(raw_number, country) is not False) else None
    if raw_number and number is None:
        log.info(f"[skip-wa] {company}: nomor {raw_number} kedeteksi landline/kantor, WA gak "
                 f"dicoba, fallback ke email kalau ada.")
    email = row.get("Email", "").strip()

    if not number and not email:
        if not DRY_RUN:
            mark_row_unreachable(ws, row["_row_number"])
        log.info(f"[skip-dead] {company}: gak ada nomor WA-capable maupun email sama sekali, "
                 f"ditandai hitam & FINAL=LOST, lanjut ke client lain.")
        return None

    is_open, detail = is_open_hour_window(country)
    if not is_open:
        log.debug(f"[skip] {company} ({country}): {detail}")
        return None

    log.info(f"[offer] {company} ({country}) round {round_number} - {detail}")

    channel_used = None
    if number and WHATSAPP_ENABLED:
        # WA STANDBY: gak auto-kirim lagi walau eligible - cuma jalan selama masih ada quota yang
        # di-set via command Telegram ("kirim wa ke N klien", lihat telegram_bot.py). Quota abis
        # (0) = WA di-skip diam-diam, fallback ke email seperti biasa. Preview (DRY_RUN) tetap
        # nampilin semua yang MAU dikirim tanpa peduli quota, biar kelihatan potensi penuhnya.
        if not DRY_RUN and wa_quota["remaining"] <= 0:
            log.debug(f"[skip-wa-standby] {company}: WA standby, belum ada quota kirim aktif "
                      f"(nunggu command Telegram) - coba email kalau ada.")
        else:
            message = render_whatsapp(row, round_number)
            if DRY_RUN:
                log.info(f"[DRY_RUN] would send WhatsApp to {number}:\n{message}\n")
                channel_used = "whatsapp"
            elif send_whatsapp(number, message):
                channel_used = "whatsapp"
                wa_quota["remaining"] -= 1

    if not channel_used and email:
        if not DRY_RUN and email_budget["remaining"] <= 0:
            log.debug(f"[skip] {company}: budget MAX_EMAILS_PER_DAY ({MAX_EMAILS_PER_DAY}) "
                      f"hari ini abis, coba lagi besok.")
        else:
            subject, body = render_email(row, round_number)
            if DRY_RUN:
                log.info(f"[DRY_RUN] would send Email to {email} | subject={subject}\n{body}\n")
                channel_used = "email"
            elif send_email(smtp_state, email, subject, body):
                channel_used = "email"
                email_budget["remaining"] -= 1

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

    # Budget MAX_EMAILS_PER_DAY dihitung dari rekap harian yang UDAH ada (bisa udah kepakai
    # sebagian dari run-run sebelumnya hari ini, cron jalan tiap 30 menit) - bukan reset per run.
    # wa_quota juga dari sumber yang sama (CORE DATABASE) - di-set/direset via command Telegram,
    # bukan auto-penuh tiap run (itu justru balik ke perilaku lama yang bikin ke-banned).
    already_sent_today = 0
    core_ws = None
    wa_quota = {"remaining": 0}
    if not DRY_RUN:
        try:
            core_ws = get_core_database_worksheet()
            today_wib_for_budget = datetime.now(_WIB).strftime("%d/%m/%Y")
            already_sent_today = get_daily_email_count(core_ws, today_wib_for_budget)
            wa_quota["remaining"] = get_wa_quota(core_ws)
        except Exception as e:
            log.error(f"[error] gagal baca rekap harian/quota WA dari CORE DATABASE: {e}")
    email_budget = {"remaining": max(0, MAX_EMAILS_PER_DAY - already_sent_today)}
    log.info(f"[budget] email hari ini: {already_sent_today}/{MAX_EMAILS_PER_DAY} udah kepakai, "
             f"sisa {email_budget['remaining']}.")
    log.info(f"[wa-quota] standby - sisa quota kirim WA saat ini: {wa_quota['remaining']} "
             f"(di-set lewat command Telegram).")

    # Satu sesi SMTP dipakai ulang buat semua email run ini, bukan connect+login per email -
    # itu yang bikin Gmail nge-rate-limit login ("454 Too many login attempts") setelah ratusan
    # email dalam sehari. Gak dibuka sama sekali kalau DRY_RUN atau budget udah abis. Dibungkus
    # dict (bukan variabel biasa) karena send_email() bisa reconnect di tengah run kalau koneksi
    # putus (lihat send_email.py) - dict-nya yang kepakai bareng biar reconnect itu nempel ke
    # baris-baris berikutnya juga, bukan cuma satu baris yang lagi diproses.
    smtp_state = {
        "server": None if (DRY_RUN or email_budget["remaining"] <= 0) else open_smtp_session()
    }

    wa_count = 0
    email_count = 0
    try:
        for row in rows:
            try:
                channel = process_row(row, col_index, ws, smtp_state, email_budget, wa_quota)
                if channel == "whatsapp":
                    wa_count += 1
                    if not DRY_RUN:
                        time.sleep(random.uniform(*_WA_SEND_DELAY_SECONDS))
                elif channel == "email":
                    email_count += 1
            except Exception as e:
                log.error(f"[error] gagal proses baris {row.get('_row_number')}: {e}")
    finally:
        close_smtp_session(smtp_state["server"])

    sent_count = wa_count + email_count
    if not DRY_RUN:
        try:
            core_ws = core_ws or get_core_database_worksheet()
            if sent_count:
                record_daily_contacts(core_ws, datetime.now(_WIB).strftime("%d/%m/%Y"),
                                       whatsapp_count=wa_count, email_count=email_count)
            if wa_count:
                set_wa_quota(core_ws, wa_quota["remaining"])
                log.info(f"[wa-quota] {wa_count} WA terkirim run ini, sisa quota: "
                         f"{wa_quota['remaining']}.")
        except Exception as e:
            log.error(f"[error] gagal update rekap harian/quota WA di CORE DATABASE: {e}")

    log.info(f"=== Run selesai ({sent_count} client dihubungi - WA:{wa_count} Email:{email_count}) ===")


if __name__ == "__main__":
    main()
