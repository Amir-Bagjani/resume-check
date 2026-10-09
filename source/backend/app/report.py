"""Single-sheet xlsx report: Persian summary block on top, then per-resume rows."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from .locale import (
    UNKNOWN_FA,
    detection_status_fa,
    experience_status_fa,
    final_status_fa,
    format_years,
    jalali_display_date,
    jalali_display_date_long,
    to_persian_digits,
)
from .output_writer import REPORT_FILENAME
from .models import ResumeResult, ScreeningCriteria, ScreeningRun

SHEET_TITLE = "گزارش غربال"

COLUMNS = [
    "نام فایل رزومه",
    "نام داوطلب",
    "سابقه کار اعلام‌شده (سال)",
    "متن رزومه",
    "بخش رزومه",
    "وضعیت شناسایی سابقه",
    "نتیجه بررسی سابقه",
    "فناوری‌های شناسایی‌شده",
    "فناوری‌های موردنیاز یافت‌شده",
    "فناوری‌های موردنیاز یافت‌نشده",
    "نتیجه نهایی",
    "دلیل / توضیح",
]

# Column widths tuned for the Persian headers above.
COLUMN_WIDTHS = [28, 24, 16, 52, 22, 18, 16, 34, 30, 30, 16, 70]


def criteria_text(criteria: ScreeningCriteria) -> str:
    parts = []
    if criteria.min_years is not None:
        parts.append(f"حداقل سابقه کار: {format_years(criteria.min_years)}")
    if criteria.keywords:
        parts.append("فناوری‌های موردنیاز: " + "، ".join(criteria.keywords))
    return "؛ ".join(parts) or "(هیچ)"


def summary_rows(
    run: ScreeningRun,
    today: date | None = None,
    copied_count: int | None = None,
    missing_count: int = 0,
) -> list[tuple[str, object]]:
    rows = [
        ("تعداد کل رزومه‌های یافت‌شده", to_persian_digits(run.found)),
        ("تعداد رزومه‌های پردازش‌شده", to_persian_digits(run.processed)),
        ("تعداد رزومه‌های تأییدشده", to_persian_digits(run.qualified)),
        ("تعداد رزومه‌های ردشده", to_persian_digits(run.not_qualified)),
        ("تعداد رزومه‌های نیازمند بررسی", to_persian_digits(run.undetermined)),
        ("معیارهای غربال استفاده‌شده", criteria_text(run.criteria)),
        ("تاریخ غربال (شمسی)", jalali_display_date(today)),
        ("تاریخ غربال (شمسی - کامل)", jalali_display_date_long(today)),
        ("منبع تعیین سابقه", "فقط عدد صریح اعلام‌شده توسط داوطلب در رزومه"),
    ]
    if copied_count is not None:
        # Every processed resume is copied so the viewer can open it later.
        rows.insert(5, ("تعداد فایل‌های ذخیره‌شده در پوشه خروجی", to_persian_digits(copied_count)))
        if missing_count:
            rows.insert(6, ("تعداد فایل‌های کپی‌نشده", to_persian_digits(missing_count)))
    return rows


def _declared_years_cell(result: ResumeResult) -> str:
    value = result.declared_experience_years
    if value is None:
        return UNKNOWN_FA
    if float(value).is_integer():
        return to_persian_digits(int(value))
    return to_persian_digits(f"{value:g}")


def _row_values(result: ResumeResult) -> list[object]:
    return [
        result.filename,
        result.candidate_name,
        _declared_years_cell(result),
        result.experience_source_text,
        result.experience_source_section,
        detection_status_fa(result.experience_detection_status.value),
        experience_status_fa(result.experience_status.value),
        "، ".join(result.skills_detected),
        "، ".join(result.required_found),
        "، ".join(result.required_missing),
        final_status_fa(result.final_status.value),
        result.reason,
    ]


def write_report(
    run: ScreeningRun,
    output_dir: Path,
    today: date | None = None,
    copied_count: int | None = None,
    missing_count: int = 0,
) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    wb = Workbook()
    ws = wb.active
    ws.title = SHEET_TITLE
    ws.sheet_view.rightToLeft = True  # ponytail: one flag gives RTL sheet layout.

    rtl = Alignment(horizontal="right", vertical="top", wrap_text=True, readingOrder=2)
    header_font = Font(bold=True)
    label_font = Font(bold=True)
    fill = PatternFill("solid", fgColor="F2F2F2")
    thin = Side(style="thin", color="CCCCCC")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    row_index = 1
    for label, value in summary_rows(run, today, copied_count, missing_count):
        ws.cell(row=row_index, column=1, value=label).font = label_font
        ws.cell(row=row_index, column=1).alignment = rtl
        ws.cell(row=row_index, column=2, value=value).alignment = rtl
        row_index += 1

    row_index += 1  # blank spacer row
    header_row = row_index
    for col, name in enumerate(COLUMNS, start=1):
        cell = ws.cell(row=header_row, column=col, value=name)
        cell.font = header_font
        cell.alignment = rtl
        cell.fill = fill
        cell.border = border

    for result in run.results:
        row_index += 1
        for col, value in enumerate(_row_values(result), start=1):
            cell = ws.cell(row=row_index, column=col, value=value)
            cell.alignment = rtl
            cell.border = border

    for col, width in enumerate(COLUMN_WIDTHS, start=1):
        ws.column_dimensions[ws.cell(row=header_row, column=col).column_letter].width = width
    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)

    path = output_dir / REPORT_FILENAME
    wb.save(path)
    return path