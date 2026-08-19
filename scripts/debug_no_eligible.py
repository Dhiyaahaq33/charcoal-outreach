"""Debug: kenapa 0 baris eligible di outreach run terakhir. Cek satu-satu alasan skip buat
sample baris (termasuk lead paling baru yang harusnya round 0 / belum pernah dikontak)."""

import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, ".")
from config import MAX_ROUNDS, MIN_DAYS_BETWEEN_ROUNDS
from sheet_client import get_worksheet, load_rows, HEADER_ROW, ORIGINAL_DATA_END_ROW
from timezone_rules import is_open_hour_window

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


# Ambil 15 baris TERAKHIR (lead paling baru, harusnya round 0 = paling gampang eligible)
sample = [r for r in rows if r["_row_number"] > ORIGINAL_DATA_END_ROW][-15:]

skip_reasons = {}
for row in sample:
    company = row.get("Company", "?")
    country = row.get("Country", "")
    fcbk = str(row.get("FINAL", "")).strip().upper()
    last_round = _last_round(row)
    round_number = last_round + 1

    reason = None
    if fcbk in _FINAL_NEGATIVE:
        reason = f"FINAL={fcbk}"
    elif round_number > MAX_ROUNDS:
        reason = f"round {round_number} > MAX_ROUNDS"
    else:
        is_open, detail = is_open_hour_window(country)
        if not is_open:
            reason = f"jam tutup: {detail}"
        else:
            reason = f"HARUSNYA ELIGIBLE! (round={round_number}, {detail})"

    skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
    print(f"{company[:40]:40s} | {country:20s} | LAST_ROUND={last_round} | {reason}")

print("\n--- ringkasan alasan skip (sample 15 baris terakhir) ---")
for k, v in skip_reasons.items():
    print(f"  {v}x: {k}")

# Cek juga waktu sekarang & sebaran country di seluruh sheet (buka-tutup jam kerja).
print(f"\nWaktu sekarang UTC: {datetime.now(timezone.utc).isoformat()}")
open_count = 0
closed_count = 0
for row in rows:
    if row["_row_number"] <= ORIGINAL_DATA_END_ROW:
        continue
    country = row.get("Country", "")
    if not country:
        continue
    is_open, _ = is_open_hour_window(country)
    if is_open:
        open_count += 1
    else:
        closed_count += 1
print(f"Dari semua baris (row > {ORIGINAL_DATA_END_ROW}): {open_count} negara lagi BUKA jam kerja, "
      f"{closed_count} lagi TUTUP (dihitung skrg).")
