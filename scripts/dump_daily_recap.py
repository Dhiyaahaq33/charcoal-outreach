"""Read-only: dump seluruh tabel rekap harian CORE DATABASE (kolom X-AA) apa adanya."""

import sys

sys.path.insert(0, ".")
from sheet_client import get_core_database_worksheet

core_ws = get_core_database_worksheet()
values = core_ws.get("X1:AA30")
for i, row in enumerate(values, start=1):
    if any(c.strip() for c in row if c):
        print(f"row {i}: {row}")
