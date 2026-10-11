"""Single-sheet xlsx report: Persian summary block on top, then per-resume rows."""
from __future__ import annotations

from dataclasses import replace
from datetime import date
import os
from pathlib import Path
import tempfile

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
from .models import FinalStatus, ResumeResult, ScreeningCriteria, ScreeningRun

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
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
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
        value = ILLEGAL_CHARACTERS_RE.sub("", value) if isinstance(value, str) else value
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
            # PDF text can contain control characters forbidden in Excel cells.
            value = ILLEGAL_CHARACTERS_RE.sub("", value) if isinstance(value, str) else value
            cell = ws.cell(row=row_index, column=col, value=value)
            cell.alignment = rtl
            cell.border = border

    for col, width in enumerate(COLUMN_WIDTHS, start=1):
        ws.column_dimensions[ws.cell(row=header_row, column=col).column_letter].width = width
    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)

    path = output_dir / REPORT_FILENAME
    wb.save(path)
    return path


def save_review_report(path: Path, run: ScreeningRun) -> None:
    """Update decisions in the saved workbook without replacing its metadata or styles."""
    from openpyxl import load_workbook

    wb = load_workbook(path)
    temporary = None
    try:
        ws = wb[SHEET_TITLE]
        header = next(row[0].row for row in ws.iter_rows()
                      if [cell.value for cell in row] == COLUMNS)
        results = {result.filename: result for result in run.results}
        seen = []
        for row in ws.iter_rows(min_row=header + 1):
            result = results.get(row[0].value)
            if result is None:
                raise ValueError("گزارش Excel با نتایج این بررسی مطابقت ندارد.")
            seen.append(result.filename)
            row[10].value = final_status_fa(result.final_status.value)
            row[11].value = result.reason
        if len(seen) != len(results) or set(seen) != set(results):
            raise ValueError("گزارش Excel با نتایج این بررسی مطابقت ندارد.")
        counts = dict(summary_rows(run)[:5])
        for row in ws.iter_rows(max_row=header - 1):
            if row[0].value in counts:
                row[1].value = counts[row[0].value]
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".xlsx", delete=False) as file:
            temporary = Path(file.name)
        wb.save(temporary)
        os.replace(temporary, path)
    finally:
        wb.close()
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_filtered_report(source: Path, run: ScreeningRun, names: dict[str, str], output_dir: Path) -> Path:
    """Filter the saved report, preserving its screening dates, layout and styles."""
    from openpyxl import load_workbook

    wb = load_workbook(source)
    try:
        ws = wb[SHEET_TITLE]
        header = next(row[0].row for row in ws.iter_rows()
                      if [cell.value for cell in row] == COLUMNS)
        kept = []
        results_by_name = {result.filename: result for result in run.results}
        for index in range(ws.max_row, header, -1):
            name = ws.cell(index, 1).value
            if name not in names:
                ws.delete_rows(index)
            else:
                kept.append(name)
                ws.cell(index, 1).value = names[name]
                result = results_by_name[name]
                ws.cell(index, 11).value = final_status_fa(result.final_status.value)
                ws.cell(index, 12).value = result.reason
        if len(kept) != len(names) or set(kept) != set(names):
            raise ValueError("گزارش Excel با رزومه‌های انتخاب‌شده مطابقت ندارد.")
        results = [result for result in run.results if result.filename in names]
        selected = replace(run, results=results, found=len(results), processed=len(results),
                           qualified=sum(r.final_status == FinalStatus.QUALIFIED for r in results),
                           not_qualified=sum(r.final_status == FinalStatus.NOT_QUALIFIED for r in results),
                           undetermined=sum(r.final_status == FinalStatus.UNDETERMINED for r in results))
        # Only the first six summary rows are counts; keep the saved metadata.
        values = dict(summary_rows(selected, copied_count=len(results))[:6])
        values["تعداد فایل‌های کپی‌نشده"] = "۰"
        for row in ws.iter_rows(max_row=header - 1):
            if row[0].value in values:
                row[1].value = values[row[0].value]
        path = output_dir / REPORT_FILENAME
        wb.save(path)
        return path
    finally:
        wb.close()
