"""Kirim email per-klien lewat Gmail SMTP + App Password (bukan OAuth - lebih simpel, gratis, gak
butuh daftar apa-apa selain generate App Password dari akun Gmail sendiri di
myaccount.google.com/apppasswords, butuh 2FA aktif dulu). Jalan 100% dari cloud runner, gak butuh
device/akun tetap login di device manapun.

PENTING: satu koneksi+login SMTP dipakai ULANG buat semua email dalam satu run (open_smtp_session()
sekali di main(), lalu send_email(smtp_state, ...) berkali-kali) - BUKAN connect+login baru per
email. Awalnya kode ini connect+login per panggilan, dan setelah ratusan email dalam sehari itu
beneran kena rate limit Gmail ("454 Too many login attempts, please try again later") - kejadian
nyata di produksi 17 Aug 2026, bukan spekulasi. Reuse koneksi drastis ngurangin jumlah login
attempt (1 per run, bukan 1 per email). send_email() tetap bisa reconnect SEKALI kalau koneksi
yang di-reuse itu putus di tengah jalan (lihat docstring send_email()).

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


def send_email(smtp_state, to_address, subject, body):
    """smtp_state: dict {"server": ...} dari main.py, BUKAN objek server langsung - dibungkus dict
    supaya kalau koneksi putus di tengah run (Gmail motong sesi idle/aneh, kejadian nyata 17 Aug
    2026 dengan error "Connection unexpectedly closed"), fungsi ini bisa reconnect SEKALI dan nulis
    balik server barunya ke smtp_state supaya kepakai buat sisa run - sebelumnya satu koneksi putus
    bikin SEMUA email sisanya di run itu ikut gagal walau kredensialnya sehat-sehat aja."""
    server = smtp_state.get("server")
    if server is None:
        return False
    if not to_address:
        log.info("[email] to_address kosong, skip.")
        return False

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = to_address
    raw = msg.as_string()

    try:
        server.sendmail(GMAIL_ADDRESS, [to_address], raw)
        return True
    except Exception as e:
        log.warning(f"[email] gagal kirim ke {to_address}: {e} - coba reconnect sekali.")

    close_smtp_session(server)
    server = open_smtp_session()
    smtp_state["server"] = server
    if server is None:
        log.warning("[email] reconnect SMTP gagal, sisa email run ini di-skip.")
        return False
    try:
        server.sendmail(GMAIL_ADDRESS, [to_address], raw)
        return True
    except Exception as e:
        log.warning(f"[email] gagal kirim ke {to_address} walau udah reconnect: {e}")
        return False
