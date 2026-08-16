"""Kirim email per-klien lewat Gmail SMTP + App Password (bukan OAuth - lebih simpel, gratis, gak
butuh daftar apa-apa selain generate App Password dari akun Gmail sendiri di
myaccount.google.com/apppasswords, butuh 2FA aktif dulu). Jalan 100% dari cloud runner, gak butuh
device/akun tetap login di device manapun.

GMAIL_ADDRESS/GMAIL_APP_PASSWORD kosong atau SMTP error apa pun -> return False (dianggap gagal),
BUKAN exception yang bikin run mati.
"""

import logging
import smtplib
from email.mime.text import MIMEText

from config import GMAIL_ADDRESS, GMAIL_APP_PASSWORD

log = logging.getLogger(__name__)

_SMTP_HOST = "smtp.gmail.com"
_SMTP_PORT = 587


def send_email(to_address, subject, body):
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        log.info("[email] GMAIL_ADDRESS/GMAIL_APP_PASSWORD kosong, skip kirim email.")
        return False
    if not to_address:
        log.info("[email] to_address kosong, skip.")
        return False

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = to_address

    try:
        with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT, timeout=30) as server:
            server.starttls()
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_ADDRESS, [to_address], msg.as_string())
        return True
    except Exception as e:
        log.warning(f"[email] gagal kirim ke {to_address}: {e}")
        return False
