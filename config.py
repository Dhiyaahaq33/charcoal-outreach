"""Load semua konfigurasi dari environment variable (.env lokal saat dev, GitHub Secrets saat CI).
Semua kredensial opsional secara individual - main.py yang decide fallback mana yang jalan."""

import os

from dotenv import load_dotenv

load_dotenv()

FONNTE_TOKEN = os.environ.get("FONNTE_TOKEN", "").strip()

GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS", "").strip()
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "").strip()

GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "").strip()
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
CLIENT_SHEET_TAB = os.environ.get("CLIENT_SHEET_TAB", "CLIENT").strip()

DRY_RUN = os.environ.get("DRY_RUN", "true").strip().lower() in ("1", "true", "yes")

MAX_ROUNDS = 3
OPEN_HOUR_START = 9   # 09:00 waktu lokal client
OPEN_HOUR_END = 17    # 17:00 waktu lokal client
