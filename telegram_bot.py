"""Telegram command listener - dipanggil tiap beberapa menit lewat GitHub Actions cron
(.github/workflows/telegram-listener.yml). Bikin WhatsApp berhenti auto-kirim dan STANDBY sampai
user kasih command eksplisit lewat Telegram, mis. "kirim pesan ke 50 org klien di wa" -> quota
kirim WA di-set 50, di-consume bertahap oleh main.py tiap siklus cron (~30 menit) selagi masih
ada client yang eligible (jam buka, giliran round, dst) - bukan langsung ditembak semua sekaligus.
Dibuat per user request pasca insiden WhatsApp banned 17 Aug 2026, biar user yang kontrol penuh
kapan dan seberapa banyak WA dikirim.

Command yang dikenali (case-insensitive, bahasa bebas asal ada kata kuncinya):
  - "kirim wa ke 50 klien" / "kirim pesan ke 20 org di wa" -> set quota WA ke angka itu
  - "stop wa" / "berhenti wa" / "pause wa" -> quota WA direset ke 0 (balik standby)
  - "status" / "cek" -> balas sisa quota WA + jumlah email terkirim hari ini

Kenapa polling (getUpdates), bukan webhook: sistem ini gak punya server yang selalu nyala -
semuanya GitHub Actions cron, jalan on-demand terus mati lagi. Webhook Telegram butuh endpoint
HTTPS yang selalu siap nerima request. Polling tiap beberapa menit cukup buat command sesekali
kayak gini (bukan real-time chat). Offset getUpdates terakhir disimpan di sheet CORE DATABASE
(bukan file lokal) karena GitHub Actions gak punya disk persisten antar run.
"""

import logging
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from sheet_client import (
    get_core_database_worksheet, get_wa_quota, set_wa_quota,
    get_telegram_offset, set_telegram_offset, get_daily_email_count,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

_WIB = ZoneInfo("Asia/Jakarta")
_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def _get_updates(last_offset):
    params = {"timeout": 0}
    if last_offset:
        params["offset"] = last_offset + 1
    resp = requests.get(f"{_API}/getUpdates", params=params, timeout=20)
    resp.raise_for_status()
    return resp.json().get("result", [])


def _reply(text):
    try:
        requests.post(f"{_API}/sendMessage",
                       data={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=20)
    except Exception as e:
        log.error(f"[telegram] gagal balas pesan: {e}")


def _parse_command(text):
    """Return (action, value). action: 'set_quota'/'stop'/'status'/None."""
    t = text.lower().strip()
    wa_mentioned = "wa" in t or "whatsapp" in t

    if wa_mentioned and any(k in t for k in ("stop", "berhenti", "pause", "hentikan")):
        return "stop", None

    if any(k in t for k in ("status", "cek", "check")):
        return "status", None

    if wa_mentioned:
        m = re.search(r"\d+", t)
        if m:
            return "set_quota", int(m.group())

    return None, None


def run():
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.info("[telegram] TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID kosong, skip (belum dikonfigurasi).")
        return

    core_ws = get_core_database_worksheet()
    last_offset = get_telegram_offset(core_ws)

    try:
        updates = _get_updates(last_offset)
    except Exception as e:
        log.error(f"[telegram] gagal ambil updates: {e}")
        return

    if not updates:
        log.info("[telegram] gak ada pesan baru.")
        return

    max_update_id = last_offset
    for update in updates:
        max_update_id = max(max_update_id, update.get("update_id", 0))
        msg = update.get("message") or {}
        chat_id = str(msg.get("chat", {}).get("id", ""))
        text = msg.get("text", "")

        if not text or chat_id != str(TELEGRAM_CHAT_ID):
            continue  # abaikan pesan dari chat lain (bukan owner)

        action, value = _parse_command(text)

        if action == "set_quota":
            set_wa_quota(core_ws, value)
            log.info(f"[telegram] quota WA di-set ke {value} dari command: {text!r}")
            _reply(
                f"Oke, quota kirim WA di-set ke {value} klien.\n"
                f"Bakal dikirim BERTAHAP tiap siklus cron (~30 menit) ke klien yang sesuai jam "
                f"buka & giliran round-nya - gak langsung semua sekaligus, biar aman dari deteksi "
                f"spam WhatsApp."
            )
        elif action == "stop":
            set_wa_quota(core_ws, 0)
            log.info(f"[telegram] WA quota direset ke 0 (standby) dari command: {text!r}")
            _reply("Oke, WA disetel balik ke standby (quota 0). Email tetap jalan otomatis seperti biasa.")
        elif action == "status":
            quota = get_wa_quota(core_ws)
            today_wib = datetime.now(_WIB).strftime("%d/%m/%Y")
            email_today = get_daily_email_count(core_ws, today_wib)
            _reply(
                f"Status hari ini ({today_wib} WIB):\n"
                f"- Sisa quota kirim WA: {quota}\n"
                f"- Email terkirim hari ini: {email_today}\n\n"
                f"Kirim contoh: \"kirim wa ke 50 klien\" buat set quota WA baru."
            )
        else:
            log.info(f"[telegram] pesan gak dikenali, diabaikan: {text!r}")
            _reply(
                "Gak ngerti command ini. Contoh yang dikenali:\n"
                "- \"kirim wa ke 50 klien\" -> kirim WA ke 50 klien berikutnya\n"
                "- \"stop wa\" -> WA balik standby\n"
                "- \"status\" -> cek sisa quota & rekap hari ini"
            )

    set_telegram_offset(core_ws, max_update_id)


if __name__ == "__main__":
    run()
