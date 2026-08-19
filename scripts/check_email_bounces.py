"""Cek inbox Gmail buat notifikasi bounce ("Message blocked"/"Mail Delivery Subsystem") dari email
outreach yang baru dikirim, dan REVERT tanda "offer sent" (LAST_ROUND, LAST_SENT_AT, kolom
Email=DONE round terkait, FINAL=PENDING kalau itu round 3) buat baris yang emailnya bounce - biar
gak keanggep udah ditawarin padahal gak pernah nyampe. Per user request: "klo misal ke block maka
input offer checklist nya di cancel aja".

Pakai IMAP (imaplib, bukan SMTP - itu cuma buat kirim) ke inbox Gmail yang sama
(GMAIL_ADDRESS/GMAIL_APP_PASSWORD, App Password yang sama kepake buat SMTP juga jalan buat IMAP).
Cuma proses email BELUM DIBACA (UNSEEN) dari mailer-daemon, abis diproses ditandai Seen - biar
idempotent, run berikutnya gak reproses notifikasi yang sama. CATATAN: kalau kamu buka manual
notifikasi bounce-nya di Gmail sebelum script ini sempat jalan, otomatis kehitung "udah dibaca"
dan bakal KELEWATAN sama script ini - biarin aja script yang baca duluan.

Run manual: python scripts/check_email_bounces.py
Via workflow_dispatch/schedule: .github/workflows/check-email-bounces.yml
"""

import email
import imaplib
import logging
import re
import sys

sys.path.insert(0, ".")
from config import GMAIL_ADDRESS, GMAIL_APP_PASSWORD
from sheet_client import get_worksheet, ensure_extra_columns, load_rows, HEADER_ROW, _col_letter

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_ROUND_OFFSET = {1: 0, 2: 2, 3: 4}


def _extract_bounced_address(msg):
    """Ambil email tujuan yang bounce dari body notifikasi Gmail (format khas: "Your message to
    <email> has been blocked/bounced")."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    body += part.get_payload(decode=True).decode(errors="ignore")
                except Exception:
                    pass
    else:
        try:
            body = msg.get_payload(decode=True).decode(errors="ignore")
        except Exception:
            body = str(msg.get_payload())

    m = re.search(r"(?:message to|for)\s+(" + _EMAIL_RE.pattern + r")", body, re.IGNORECASE)
    if m:
        return m.group(1)
    m = _EMAIL_RE.search(body)
    return m.group() if m else None


def _revert_offer(ws, header, row):
    row_number = row["_row_number"]
    try:
        last_round = int(row.get("LAST_ROUND") or 0)
    except (TypeError, ValueError):
        last_round = 0
    if last_round <= 0 or last_round not in _ROUND_OFFSET:
        log.warning(f"[bounce] {row.get('Company', '?')}: LAST_ROUND={last_round} gak valid buat "
                    f"di-revert, dilewatin.")
        return False

    first_whatsapp_col = header.index("WHATSAPP") + 1
    email_done_col = first_whatsapp_col + _ROUND_OFFSET[last_round] + 1
    last_round_col = header.index("LAST_ROUND") + 1
    last_sent_col = header.index("LAST_SENT_AT") + 1

    updates = [
        {"range": f"{_col_letter(email_done_col)}{row_number}", "values": [[""]]},
        {"range": f"{_col_letter(last_round_col)}{row_number}", "values": [[max(0, last_round - 1)]]},
        {"range": f"{_col_letter(last_sent_col)}{row_number}", "values": [[""]]},
    ]
    if last_round == 3 and "FINAL" in header:
        final_col = header.index("FINAL") + 1
        if row.get("FINAL", "").strip().upper() == "PENDING":
            updates.append({"range": f"{_col_letter(final_col)}{row_number}", "values": [[""]]})

    ws.batch_update(updates, value_input_option="RAW")
    return True


def run():
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        log.info("[bounce] GMAIL_ADDRESS/GMAIL_APP_PASSWORD kosong, skip.")
        return

    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
    mail.select("INBOX")

    status, data = mail.search(None, 'UNSEEN FROM "mailer-daemon"')
    ids = data[0].split() if data and data[0] else []
    log.info(f"[bounce] {len(ids)} notifikasi bounce belum diproses ditemukan.")
    if not ids:
        mail.logout()
        return

    ws = get_worksheet()
    ensure_extra_columns(ws)
    header = ws.row_values(HEADER_ROW)
    rows = load_rows(ws)
    email_to_row = {}
    for r in rows:
        e = r.get("Email", "").strip().lower()
        if e and e not in email_to_row:
            email_to_row[e] = r

    reverted = 0
    not_found = 0
    for msg_id in ids:
        status, msg_data = mail.fetch(msg_id, "(RFC822)")
        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)
        bounced_email = _extract_bounced_address(msg)

        if not bounced_email:
            log.warning(f"[bounce] gagal parse email tujuan dari notifikasi bounce (msg {msg_id!r}).")
            mail.store(msg_id, "+FLAGS", "\\Seen")
            continue

        row = email_to_row.get(bounced_email.strip().lower())
        if not row:
            log.warning(f"[bounce] {bounced_email} bounce tapi gak ketemu row-nya di sheet.")
            not_found += 1
            mail.store(msg_id, "+FLAGS", "\\Seen")
            continue

        if _revert_offer(ws, header, row):
            reverted += 1
            log.info(f"[bounce] {row.get('Company', '?')} ({bounced_email}) - offer di-revert.")
        mail.store(msg_id, "+FLAGS", "\\Seen")

    mail.logout()
    log.info(f"[bounce] selesai - {reverted} offer di-revert, {not_found} bounce gak ketemu row-nya "
             f"di sheet, dari {len(ids)} notifikasi diproses.")


if __name__ == "__main__":
    run()
