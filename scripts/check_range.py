"""Read-only: cek isi baris tertentu di CLIENT sheet - dipakai buat verifikasi manual sebelum
tindakan destruktif (hapus baris dll). Gak nulis apa pun ke sheet.

Run manual: python scripts/check_range.py <start_row> <end_row>
"""

import sys

sys.path.insert(0, ".")
from sheet_client import get_worksheet, HEADER_ROW, _col_letter

start_row = int(sys.argv[1]) if len(sys.argv) > 1 else 4228
end_row = int(sys.argv[2]) if len(sys.argv) > 2 else 4566

ws = get_worksheet()
header = ws.row_values(HEADER_ROW)
last_col = _col_letter(len(header))

all_values = ws.get_all_values()
total_rows = len(all_values)
print(f"Total baris di sheet (get_all_values): {total_rows}")
print(f"Header row: {HEADER_ROW}, jumlah kolom: {len(header)}")

blank_count = 0
nonblank_count = 0
first_nonblank = None
last_nonblank = None

for i in range(start_row, min(end_row, total_rows) + 1):
    row = all_values[i - 1] if i - 1 < len(all_values) else []
    is_blank = not any(c.strip() for c in row)
    if is_blank:
        blank_count += 1
    else:
        nonblank_count += 1
        if first_nonblank is None:
            first_nonblank = i
        last_nonblank = i

print(f"Range dicek: {start_row}-{end_row}")
print(f"Baris blank: {blank_count}")
print(f"Baris ADA isinya: {nonblank_count}")
if first_nonblank:
    print(f"Non-blank pertama: baris {first_nonblank}")
    print(f"  isi: {all_values[first_nonblank - 1][:6]}")
    print(f"Non-blank terakhir: baris {last_nonblank}")
    print(f"  isi: {all_values[last_nonblank - 1][:6]}")

# Cek juga baris tepat sebelum dan sesudah range, buat konteks.
if start_row - 3 >= 1:
    print(f"\nKonteks sebelum range (baris {start_row-3}-{start_row-1}):")
    for i in range(start_row - 3, start_row):
        row = all_values[i - 1] if i - 1 < len(all_values) else []
        print(f"  baris {i}: {row[:6]}")

print(f"\nKonteks sesudah range (baris {end_row+1}-{end_row+3}):")
for i in range(end_row + 1, end_row + 4):
    row = all_values[i - 1] if i - 1 < len(all_values) else []
    print(f"  baris {i}: {row[:6]}")
