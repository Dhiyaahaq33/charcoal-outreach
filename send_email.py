"""Kirim email per-klien lewat Gmail SMTP + App Password (bukan OAuth - lebih simpel, gratis, gak
butuh daftar apa-apa selain generate App Password dari akun Gmail sendiri di
myaccount.google.com/apppasswords, butuh 2FA aktif dulu). Jalan 100% dari cloud runner, gak butuh
device/akun tetap login di device manapun.

PENTING: satu koneksi+login SMTP dipakai ULANG buat semua email dalam satu run (open_smtp_session()
sekali di main(), lalu send_email(server, ...) berkali-kali) - BUKAN connect+login baru per email.
Awalnya kode ini connect+login per panggilan, dan setelah ratusan email dalam sehari itu beneran
kena rate limit Gmail ("454 Too many login attempts, please try again later") - kejadian nyata di
produksi 17 Aug 2026, bukan spekulasi. Reuse koneksi drastis ngurangin jumlah login attempt (1 per
run, bukan 1 per email).

GMAIL_ADDRESS/GMAIL_APP_PASSWORD kosong atau SMTP error apa pun -> return False/None (dianggap
gagal), BUKAN exception yang bikin run mati.
"""

import logging
import smtplib
from email.mime.text import MIMEText

from config import GMAIL_ADDRESS, GMAIL_APP_PASSWORD

log = logging.getLogger(__name__)

_SMTP_HOST = "smtp.gmail.com"
_SMTP_PORT = 587


def open_smtp_session():
    """Buka & login SEKALI, dipakai ulang buat semua kirim email dalam satu run. Return objek
    smtplib.SMTP yang udah authenticated, atau None kalau kredensial kosong/login gagal (caller
    skip semua kirim email run ini kalau None, sama seperti GMAIL_ADDRESS/PASSWORD kosong)."""
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        log.info("[email] GMAIL_ADDRESS/GMAIL_APP_PASSWORD kosong, skip semua kirim email run ini.")
        return None
    try:
        server = smtplib.SMTP(_SMTP_HOST, _SMTP_PORT, timeout=30)
        server.starttls()
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        return server
    except Exception as e:
        log.warning(f"[email] gagal buka sesi SMTP: {e}")
        return None


def close_smtp_session(server):
    if server is None:
        return
    try:
        server.quit()
    except Exception:
        pass


def send_email(server, to_address, subject, body):
    """server: hasil open_smtp_session() (bisa None kalau session gagal dibuka - langsung return
    False, gak coba connect baru per-email lagi)."""
    if server is None:
        return False
    if not to_address:
        log.info("[email] to_address kosong, skip.")
        return False

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = to_address

    try:
        server.sendmail(GMAIL_ADDRESS, [to_address], msg.as_string())
        return True
    except Exception as e:
        log.warning(f"[email] gagal kirim ke {to_address}: {e}")
        return False
