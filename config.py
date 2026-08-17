"""Load semua konfigurasi dari environment variable (.env lokal saat dev, GitHub Secrets saat CI).
Semua kredensial opsional secara individual - main.py yang decide fallback mana yang jalan."""

import os

from dotenv import load_dotenv

load_dotenv()

FONNTE_TOKEN = os.environ.get("FONNTE_TOKEN", "").strip()

# Matiin channel WhatsApp sepenuhnya (semua kirim langsung ke Email, gak coba WA sama sekali) -
# dipakai waktu device Fonnte kena disconnect berulang gara-gara WhatsApp mendeteksi pengiriman
# otomatis massal dari satu nomor dan maksa logout linked device sebagai proteksi anti-spam
# mereka. Biar gak nambah percobaan koneksi yang bisa makin memperparah status nomornya.
WHATSAPP_ENABLED = os.environ.get("WHATSAPP_ENABLED", "true").strip().lower() in ("1", "true", "yes")

GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS", "").strip()
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "").strip()

GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "").strip()
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
CLIENT_SHEET_TAB = os.environ.get("CLIENT_SHEET_TAB", "CLIENT").strip()

DRY_RUN = os.environ.get("DRY_RUN", "true").strip().lower() in ("1", "true", "yes")

# Comma-separated Google Maps shared-list URLs (lead discovery only, discovery_main.py) - kosong =
# skip Maps scraping, cuma jalanin web scraper (TradeIndia/ExportHub/Kompass/Google search).
GMAPS_LIST_URLS = [
    u.strip() for u in os.environ.get("GMAPS_LIST_URLS", "").split(",") if u.strip()
]

# Terpisah dari DRY_RUN outreach di atas - discovery_main.py cuma nulis row baru (gak kirim
# apa-apa), tapi tetap defaultnya true biar scraper yang belum diverifikasi selector-nya gak
# ngotorin sheet produksi sebelum di-review.
DISCOVERY_DRY_RUN = os.environ.get("DISCOVERY_DRY_RUN", "true").strip().lower() in ("1", "true", "yes")

MAX_ROUNDS = 3
OPEN_HOUR_START = 9   # 09:00 waktu lokal client
OPEN_HOUR_END = 17    # 17:00 waktu lokal client

# Jarak minimum antara round follow-up ke client yang sama (round 1->2, 2->3). BUKAN 20-menit
# anti-dobel-kirim guard (itu cuma buat run yang tumpang tindih) - ini soal cadence follow-up B2B
# yang wajar, biar gak keliatan spam ke calon buyer.
MIN_DAYS_BETWEEN_ROUNDS = 7

# Batas email/hari (WIB) - dijaga jauh di bawah limit resmi Gmail (500/hari) sekaligus ngurangin
# frekuensi login SMTP harian, biar konsisten aman gak kena rate-limit lagi kayak yang kejadian
# 17 Aug 2026 (kirim 400+ email sehari langsung kena "too many login attempts").
MAX_EMAILS_PER_DAY = 200

# Bot Telegram (telegram_bot.py) buat kontrol kirim WhatsApp via command (mis. "kirim wa ke 50
# klien") - per user request pasca insiden WA banned 17 Aug 2026, WA gak boleh auto-kirim lagi,
# harus standby sampai ada command eksplisit. Bikin bot: chat @BotFather di Telegram > /newbot.
# TELEGRAM_CHAT_ID: chat id user (BUKAN username) - didapat dari getUpdates setelah kirim pesan
# pertama ke bot, atau dari bot semacam @userinfobot.
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
