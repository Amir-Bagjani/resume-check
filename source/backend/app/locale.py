"""Persian (fa-IR) presentation helpers: digits, labels, Jalali display dates."""
from __future__ import annotations

from datetime import date
from typing import Optional

# Machine statuses stay ASCII in the API; this module maps them to Persian copy.
EXPERIENCE_STATUS_FA = {
    "pass": "تأیید",
    "fail": "رد",
    "unknown": "نامشخص",
}

FINAL_STATUS_FA = {
    "Qualified": "تأیید",
    "Not Qualified": "رد",
    "Undetermined": "نیازمند بررسی",
}

RUN_STATE_FA = {
    "running": "در حال اجرا",
    "paused": "متوقف",
    "cancelled": "لغو شده",
    "finished": "پایان‌یافته",
}

DETECTION_STATUS_FA = {
    "found": "یافت شد",
    "not_found": "یافت نشد",
    "ambiguous": "نامشخص — نیازمند بررسی",
}

UNKNOWN_FA = "نامشخص"
YEARS_FA = "سال"

# Latin and Arabic-Indic digits -> ASCII, used for parsing and for display.
ASCII_DIGITS = "0123456789"
PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"

_LATIN_TO_PERSIAN = {ord(a): p for a, p in zip(ASCII_DIGITS, PERSIAN_DIGITS)}
_PERSIAN_TO_ASCII = {ord(p): a for p, a in zip(PERSIAN_DIGITS, ASCII_DIGITS)}
_ARABIC_TO_ASCII = {ord(chr(0x0660 + i)): str(i) for i in range(10)}


def to_persian_digits(text: object) -> str:
    """Render digits as Persian numerals. Non-digits (paths, words) untouched."""
    return str(text).translate(_LATIN_TO_PERSIAN)


def to_ascii_digits(text: str) -> str:
    """Fold Persian and Arabic-Indic digits to ASCII for numeric parsing."""
    return text.translate(_PERSIAN_TO_ASCII).translate(_ARABIC_TO_ASCII)


def format_years(value: Optional[float]) -> str:
    """«۵ سال» / «نامشخص» for user-facing text."""
    if value is None:
        return UNKNOWN_FA
    if float(value).is_integer():
        return f"{to_persian_digits(int(value))} {YEARS_FA}"
    return f"{to_persian_digits(f'{value:g}')} {YEARS_FA}"


def format_number(value: object) -> str:
    return to_persian_digits(value)


def experience_status_fa(value: object) -> str:
    return EXPERIENCE_STATUS_FA.get(str(value), UNKNOWN_FA)


def final_status_fa(value: object) -> str:
    return FINAL_STATUS_FA.get(str(value), str(value))


def run_state_fa(value: object) -> str:
    return RUN_STATE_FA.get(str(value), str(value))


def detection_status_fa(value: object) -> str:
    return DETECTION_STATUS_FA.get(str(value), UNKNOWN_FA)


def _gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    """Standard Khayyam/Birashk conversion; keeps Jalali working without jdatetime."""
    g_d_m = (0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334)
    if gy > 1600:
        jy = 979
        gy -= 1600
    else:
        jy = 0
        gy -= 621
    gy2 = gy + 1 if gm > 2 else gy
    days = (
        365 * gy
        + (gy2 + 3) // 4
        - (gy2 + 99) // 100
        + (gy2 + 399) // 400
        - 80
        + gd
        + g_d_m[gm - 1]
    )
    jy += 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + days // 31
        jd = 1 + days % 31
    else:
        jm = 7 + (days - 186) // 30
        jd = 1 + (days - 186) % 30
    return jy, jm, jd


MONTH_NAMES_FA = (
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
)


def jalali_parts(today: date | None = None) -> tuple[int, int, int]:
    today = today or date.today()
    try:
        import jdatetime

        j = jdatetime.date.fromgregorian(date=today)
        return j.year, j.month, j.day
    except Exception:
        return _gregorian_to_jalali(today.year, today.month, today.day)


def jalali_display_date(today: date | None = None) -> str:
    """«۱۴۰۵/۰۷/۱۷» — Jalali with Persian digits, for UI and Excel cells."""
    jy, jm, jd = jalali_parts(today)
    return to_persian_digits(f"{jy:04d}/{jm:02d}/{jd:02d}")


def jalali_display_date_long(today: date | None = None) -> str:
    """«۱۷ مهر ۱۴۰۵»."""
    jy, jm, jd = jalali_parts(today)
    return f"{to_persian_digits(jd)} {MONTH_NAMES_FA[jm - 1]} {to_persian_digits(jy)}"


def gregorian_display_date(today: date | None = None) -> str:
    today = today or date.today()
    return to_persian_digits(today.strftime("%Y-%m-%d"))