"""Hitung sendiri hari & jam lokal client dari Country (bukan bergantung formula Sheet manual),
biar DO/DONT selalu akurat tiap run - fix untuk bug yang disebut user: "kadang waktunya ga works
krn masih pake aturan jam kerja bukan hari kerja" - di sini urutan cek SENGAJA weekday dulu baru jam,
supaya weekend selalu DONT tanpa peduli jam berapa pun."""

from datetime import datetime
from zoneinfo import ZoneInfo

from config import OPEN_HOUR_START, OPEN_HOUR_END
from country_timezones import get_timezone

_WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def local_now(country):
    """Return (datetime lokal, None) atau (None, alasan) kalau timezone country gak dikenal."""
    tz_name = get_timezone(country)
    if not tz_name:
        return None, f"timezone untuk country '{country}' belum ada di country_timezones.py"
    return datetime.now(ZoneInfo(tz_name)), None


def is_open_hour_window(country):
    """True hanya kalau: weekday lokal Senin-Jumat DAN jam lokal ada di [OPEN_HOUR_START, OPEN_HOUR_END).
    Return (bool, detail_dict_or_reason)."""
    now, err = local_now(country)
    if err:
        return False, err

    is_weekday = now.weekday() < 5  # 0=Senin ... 4=Jumat
    if not is_weekday:
        return False, f"weekend di lokal ({_WEEKDAY_NAMES[now.weekday()]} {now.strftime('%H:%M')})"

    is_open_hour = OPEN_HOUR_START <= now.hour < OPEN_HOUR_END
    if not is_open_hour:
        return False, f"di luar jam kerja lokal ({now.strftime('%H:%M')})"

    return True, {
        "local_day": _WEEKDAY_NAMES[now.weekday()],
        "local_time": now.strftime("%H:%M"),
    }
