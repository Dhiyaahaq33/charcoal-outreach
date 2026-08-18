"""Read-only: hitung berapa baris di range tertentu yang Product Interest dan/atau Contact Person
masih kosong. Gak nulis apa pun ke sheet.

Run manual: python scripts/check_fill_status.py <start_row> <end_row>
"""

import sys

sys.path.insert(0, ".")
from sheet_client import get_worksheet, HEADER_ROW

start_row = int(sys.argv[1]) if len(sys.argv) > 1 else 675
end_row = int(sys.argv[2]) if len(sys.argv) > 2 else 1306

ws = get_worksheet()
header = ws.row_values(HEADER_ROW)
product_col = header.index("Product Interest")
contact_col = header.index("Contact Person")
company_col = header.index("Company")

all_values = ws.get_all_values()

total = 0
both_blank = 0
product_blank = 0
contact_blank = 0
both_filled = 0

for i in range(start_row, min(end_row, len(all_values)) + 1):
    row = all_values[i - 1]
    company = row[company_col].strip() if len(row) > company_col else ""
    if not company:
        continue
    total += 1
    product = row[product_col].strip() if len(row) > product_col else ""
    contact = row[contact_col].strip() if len(row) > contact_col else ""
    if not product:
        product_blank += 1
    if not contact:
        contact_blank += 1
    if not product and not contact:
        both_blank += 1
    if product and contact:
        both_filled += 1

print(f"Range {start_row}-{end_row}: {total} baris ada Company-nya")
print(f"Product Interest kosong: {product_blank}")
print(f"Contact Person kosong: {contact_blank}")
print(f"Dua-duanya kosong: {both_blank}")
print(f"Dua-duanya udah keisi: {both_filled}")
