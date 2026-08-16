"""Kirim WA per-klien lewat Fonnte (fonnte.com), device = nomor +62 812-2564-6585 di-pairing sekali
lewat scan QR di dashboard mereka - habis itu pengiriman ditangani server Fonnte, gak butuh HP/PC
kamu nyala terus (jalan virtual di GitHub Actions).

Beda sama notify_whatsapp.py di bandar-broksum: di sana target tetap (notify ke diri sendiri), di
sini target BEDA tiap klien (dari kolom WhatsApp per baris), jadi target jadi parameter, bukan config.

FONNTE_TOKEN kosong atau API error apa pun -> return False (dianggap gagal, caller fallback ke
email), BUKAN exception yang bikin run mati.
"""

import logging
import re

import requests

from config import FONNTE_TOKEN

FONNTE_URL = "https://api.fonnte.com/send"

log = logging.getLogger(__name__)


def extract_number(whatsapp_field, phone_field=""):
    """Kolom WhatsApp di sheet formatnya 'wa.me//6281234567890' atau kosong ('wa.me//').
    Fallback ke kolom Phone kalau WhatsApp kosong/gak valid. Return angka doang (tanpa +), atau
    None kalau gak ada nomor valid sama sekali."""
    for raw in (whatsapp_field, phone_field):
        if not raw:
            continue
        digits = re.sub(r"\D", "", str(raw))
        if len(digits) >= 8:  # nomor telepon valid minimal ~8 digit
            return digits
    return None


def send_whatsapp(target_number, message):
    if not FONNTE_TOKEN:
        log.info("[whatsapp] FONNTE_TOKEN kosong, skip kirim WhatsApp.")
        return False
    if not target_number:
        log.info("[whatsapp] target_number kosong, skip.")
        return False

    try:
        resp = requests.post(
            FONNTE_URL,
            headers={"Authorization": FONNTE_TOKEN},
            data={"target": target_number, "message": message},
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
        if not payload.get("status", True):
            log.warning(f"[whatsapp] Fonnte nolak pesan ke {target_number}: {payload}")
            return False
        return True
    except Exception as e:
        log.warning(f"[whatsapp] gagal kirim ke {target_number}: {e}")
        return False
