"""Debug: kenapa 0 baris eligible di outreach run terakhir, padahal ada ratusan negara yang lagi
buka jam kerja. Cek detail skip reason KHUSUS buat baris yang negaranya lagi BUKA."""

import sys

sys.path.insert(0, ".")
from config import MAX_ROUNDS, MIN_DAYS_BETWEEN_ROUNDS
from sheet_client import get_worksheet, load_rows, HEADER_ROW, ORIGINAL_DATA_END_ROW
from timezone_rules import is_open_hour_window
from send_whatsapp import extract_number, has_office_format

ws = get_worksheet()
rows = load_rows(ws)
print(f"Total baris: {len(rows)}")

_FINAL_NEGATIVE = {"LOST", "NO"}


def _last_round(row):
    val = row.get("LAST_ROUND")
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0


open_rows = []
for row in rows:
    if row["_row_number"] <= ORIGINAL_DATA_END_ROW:
        continue
    country = row.get("Country", "")
    if not country:
        continue
    is_open, detail = is_open_hour_window(country)
    if is_open:
        open_rows.append((row, detail))

print(f"{len(open_rows)} baris negaranya lagi BUKA jam kerja sekarang.\n")

skip_reasons = {}
truly_eligible = []
for row, detail in open_rows:
    company = row.get("Company", "?")
    country = row.get("Country", "")
    fcbk = str(row.get("FINAL", "")).strip().upper()
    last_round = _last_round(row)
    round_number = last_round + 1
    email = row.get("Email", "").strip()
    raw_number = extract_number(row.get("WhatsApp", ""), row.get("Phone", ""))
    is_office = has_office_format(row.get("Phone", ""), row.get("WhatsApp", ""))
    number = raw_number if (raw_number and not is_office) else None

    reason = None
    if fcbk in _FINAL_NEGATIVE:
        reason = f"FINAL={fcbk}"
    elif round_number > MAX_ROUNDS:
        reason = "round > MAX_ROUNDS"
    elif not number and not email:
        reason = "gak ada nomor WA-capable maupun email"
    else:
        reason = "ELIGIBLE"
        truly_eligible.append((company, country, round_number, email, number))

    skip_reasons[reason] = skip_reasons.get(reason, 0) + 1

print("--- ringkasan skip reason (dari yang negaranya BUKA) ---")
for k, v in sorted(skip_reasons.items(), key=lambda x: -x[1]):
    print(f"  {v}x: {k}")

print(f"\n--- {len(truly_eligible)} baris SEHARUSNYA eligible (sample 20) ---")
for company, country, round_number, email, number in truly_eligible[:20]:
    print(f"  {company[:40]:40s} | {country:20s} | round={round_number} | "
          f"email={'ADA' if email else '-'} | wa={'ADA' if number else '-'}")
