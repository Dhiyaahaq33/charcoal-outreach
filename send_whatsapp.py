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

import phonenumbers
import pycountry
import requests
from phonenumbers import NumberParseException, PhoneNumberType

from config import FONNTE_TOKEN

FONNTE_URL = "https://api.fonnte.com/send"

log = logging.getLogger(__name__)

_MOBILE_TYPES = {PhoneNumberType.MOBILE, PhoneNumberType.FIXED_LINE_OR_MOBILE}


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


def _region_from_country_name(country):
    """Cari kode region ISO alpha-2 (mis. 'ID', 'US') dari nama negara di kolom Country - dipakai
    fallback parse phonenumbers kalau nomornya ditulis lokal (gak diawali + / kode negara)."""
    if not country or not country.strip():
        return None
    try:
        match = pycountry.countries.get(name=country.strip())
        if not match:
            results = pycountry.countries.search_fuzzy(country.strip())
            match = results[0] if results else None
        return match.alpha_2 if match else None
    except Exception:
        return None


def is_mobile_number(digits, country=""):
    """Klasifikasi nomor pakai library phonenumbers - True = kemungkinan besar mobile/WA-capable,
    False = KEDETEKSI JELAS landline/nomor kantor (gak punya WhatsApp), None = gak bisa dipastikan
    (nomor VOIP/pager/format gak lengkap/dll - dianggap fail-open, TETAP dicoba WA, bukan diblok
    cuma karena ambigu). Per user request: nomor kantor otomatis di-skip dari WA, fallback email
    kalau ada, biar gak buang-buang percobaan kirim ke nomor yang emang gak punya WhatsApp."""
    if not digits:
        return None
    candidate = digits if digits.startswith("+") else f"+{digits}"
    try:
        parsed = phonenumbers.parse(candidate, None)
    except NumberParseException:
        parsed = None

    if parsed is None or not phonenumbers.is_valid_number(parsed):
        region = _region_from_country_name(country)
        if not region:
            return None
        try:
            parsed = phonenumbers.parse(digits, region)
        except NumberParseException:
            return None
        if not phonenumbers.is_valid_number(parsed):
            return None

    num_type = phonenumbers.number_type(parsed)
    if num_type == PhoneNumberType.FIXED_LINE:
        return False
    if num_type in _MOBILE_TYPES:
        return True
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
            data={"target": target_number, "message": message, "preview": "true"},
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
