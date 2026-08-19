"""Quick read-only check: print current WA quota + email count from CORE DATABASE. No writes.
Run manual: python scripts/check_quota.py [DD/MM/YYYY]
"""

import sys
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, ".")
from sheet_client import get_core_database_worksheet, get_wa_quota, get_daily_email_count

core_ws = get_core_database_worksheet()
quota = get_wa_quota(core_ws)
date_arg = sys.argv[1].strip() if len(sys.argv) > 1 and sys.argv[1].strip() else \
    datetime.now(ZoneInfo("Asia/Jakarta")).strftime("%d/%m/%Y")
email_today = get_daily_email_count(core_ws, date_arg)
print(f"WA quota saat ini: {quota}")
print(f"Email terkirim ({date_arg} WIB): {email_today}")
