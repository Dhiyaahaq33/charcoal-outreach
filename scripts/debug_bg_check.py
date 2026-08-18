"""Debug: cari baris "Tradeasia International" (diketahui kena mark_row_unreachable dari log
outreach sebelumnya) dan print raw response API buat background-nya - verifikasi apakah
_black_rows() di fix_wrongly_lost_rows.py bener nangkep warnanya."""

import json
import sys

sys.path.insert(0, ".")
from config import GOOGLE_SERVICE_ACCOUNT_JSON, GOOGLE_SHEET_ID, CLIENT_SHEET_TAB
from sheet_client import get_worksheet, HEADER_ROW

ws = get_worksheet()
all_values = ws.get_all_values()

target_row = None
for i, row in enumerate(all_values[HEADER_ROW:], start=HEADER_ROW + 1):
    if len(row) > 1 and "Tradeasia" in row[1]:
        target_row = i
        print(f"Ketemu baris {i}: {row[:9]}")
        break

if not target_row:
    print("Gak ketemu baris Tradeasia International.")
    sys.exit(0)

from google.auth.transport.requests import AuthorizedSession
from google.oauth2.service_account import Credentials

info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/spreadsheets"])
session = AuthorizedSession(creds)

url = f"https://sheets.googleapis.com/v4/spreadsheets/{GOOGLE_SHEET_ID}"
params = {
    "ranges": f"{CLIENT_SHEET_TAB}!A{target_row}:A{target_row}",
    "fields": "sheets.data.rowData.values.userEnteredFormat.backgroundColor,sheets.data.rowData.values.userEnteredFormat",
}
resp = session.get(url, params=params, timeout=20)
print("STATUS:", resp.status_code)
print("BODY:", json.dumps(resp.json(), indent=2))
