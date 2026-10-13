"""Single-sheet xlsx report: Persian summary block on top, then per-resume rows."""
from __future__ import annotations

from dataclasses import replace
from datetime import date
import logging
import os
from pathlib import Path
import re
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

logger = logging.getLogger(__name__)
SHEET_TITLE = "گزارش غربال"
MAX_CELL_CHARS = 32767
# Everything XML 1.0 allows: tab, line feed, carriage return and valid code points.
_NOT_XML_SAFE = re.compile(r"[^\u0009\u000a\u000d\u0020-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]")


def excel_safe(value: object) -> object:
    """Return a value openpyxl can store.

    Only the characters Excel forbids are removed, so Persian text, English,
    digits, ZWNJ, punctuation and line breaks survive untouched. Longer text is
    truncated at the cell limit instead of being dropped.
    """
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

    if not isinstance(value, str):
        return value
    text = ILLEGAL_CHARACTERS_RE.sub("", value)
    return text[:MAX_CELL_CHARS] if len(text) > MAX_CELL_CHARS else text


def _put(ws, row: int, column: int, value: object):
    """Write one cell safely: sanitize, and never let a single value break the file."""
    from openpyxl.utils.exceptions import IllegalCharacterError

    cell = ws.cell(row=row, column=column)
    try:
        cell.value = excel_safe(value)
    except IllegalCharacterError:
        text = _NOT_XML_SAFE.sub("", str(value))[:MAX_CELL_CHARS]
        logger.warning("Excel cell needed a stricter cleanup: sheet=%s cell=%s",
                       ws.title, cell.coordinate)
        try:
            cell.value = text
        except IllegalCharacterError:
            logger.error("Excel cell could not be written and was replaced: sheet=%s cell=%s length=%s",
                         ws.title, cell.coordinate, len(str(value)))
            cell.value = ""
    if isinstance(cell.value, str):
        # Values starting with "=" must stay text, not become formulas.
        cell.data_type = "s"
    return cell

COLUMNS = [
    "نام فایل رزومه",
    "نام داوطلب",
    "سابقه کار اعلام‌شده (سال)",
    "متن رزومه",
    "بخش رزومه",
    "وضعیت شناسایی سابقه",
    "نتیجه بررسی سابقه",
    "فناوری‌های شناسایی‌شده",
    "نتیجه نهایی",
    "دلیل / توضیح",
    "لینک جابینجا",
]

# Column widths tuned for the Persian headers above.
COLUMN_WIDTHS = [28, 24, 16, 52, 22, 18, 16, 34, 16, 70, 36]
APPLICANT_SHEET = "دریافت رزومه‌ها"


def _write_applicants(wb, run, rtl, border, header_font, fill):
    if not run.applicants:
        return
    from .jobinja import valid_url

    ws = wb.create_sheet(APPLICANT_SHEET)
    ws.sheet_view.rightToLeft = True
    headers = ["شناسه متقاضی", "ردیف Excel", "نام متقاضی", "لینک جابینجا", "نام فایل رزومه",
               "وضعیت دریافت", "خطای دریافت", "سابقه کار اعلام‌شده (سال)", "نتیجه بررسی", "دلیل بررسی"]
    for column, title in enumerate(headers, start=1):
        cell = _put(ws, 1, column, title)
        cell.font = header_font
        cell.fill = fill
    results = {r.filename: r for r in run.results}
    for index, applicant in enumerate(run.applicants, start=2):
        result = results.get(applicant.filename)
        values = [applicant.applicant_id, applicant.excel_row,
                  applicant.name or (result.candidate_name if result else ""), applicant.jobinja_url,
                  applicant.filename,
                  "دریافت شد" if applicant.download_status == "downloaded" else "دریافت نشد",
                  applicant.download_error, _declared_years_cell(result) if result else "",
                  final_status_fa(result.final_status.value) if result else "",
                  result.reason if result else ""]
        for column, value in enumerate(values, start=1):
            _put(ws, index, column, value)
    for row in ws:
        for cell in row:
            cell.alignment = rtl
            cell.border = border
        if row[0].row > 1 and valid_url(row[3].value or ""):
            row[3].hyperlink = row[3].value
    for column, width in enumerate((34, 14, 24, 38, 28, 18, 48, 18, 18, 60), start=1):
        ws.column_dimensions[ws.cell(1, column).column_letter].width = width
    ws.freeze_panes = "A2"


def _refresh_applicants(wb, run):
    if APPLICANT_SHEET not in wb.sheetnames:
        return
    results = {r.filename: r for r in run.results}
    for row in wb[APPLICANT_SHEET].iter_rows(min_row=2):
        result = results.get(row[4].value)
        if result is not None:
            _put(wb[APPLICANT_SHEET], row[7].row, 8, _declared_years_cell(result))
            _put(wb[APPLICANT_SHEET], row[7].row, 9, final_status_fa(result.final_status.value))
            _put(wb[APPLICANT_SHEET], row[7].row, 10, result.reason)


def criteria_text(criteria: ScreeningCriteria) -> str:
    parts = []
    if criteria.min_years is not None:
        parts.append(f"حداقل سابقه کار: {format_years(criteria.min_years)}")
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


def _row_values(result: ResumeResult, jobinja_url: str = "") -> list[object]:
    return [
        result.filename,
        result.candidate_name,
        _declared_years_cell(result),
        result.experience_source_text,
        result.experience_source_section,
        detection_status_fa(result.experience_detection_status.value),
        experience_status_fa(result.experience_status.value),
        "، ".join(result.skills_detected),
        final_status_fa(result.final_status.value),
        result.reason,
        jobinja_url,
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
        cell = _put(ws, row_index, 1, label)
        cell.font = label_font
        cell.alignment = rtl
        _put(ws, row_index, 2, value).alignment = rtl
        row_index += 1

    row_index += 1  # blank spacer row
    header_row = row_index
    for col, name in enumerate(COLUMNS, start=1):
        cell = _put(ws, header_row, col, name)
        cell.font = header_font
        cell.alignment = rtl
        cell.fill = fill
        cell.border = border

    applicants = {a.filename: a for a in run.applicants if a.filename}
    for result in run.results:
        row_index += 1
        for col, value in enumerate(_row_values(result, applicants[result.filename].jobinja_url if result.filename in applicants else ""), start=1):
            # PDF text can contain control characters forbidden in Excel cells.
            cell = _put(ws, row_index, col, value)
            cell.alignment = rtl
            cell.border = border

    for col, width in enumerate(COLUMN_WIDTHS, start=1):
        ws.column_dimensions[ws.cell(row=header_row, column=col).column_letter].width = width
    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)

    _write_applicants(wb, run, rtl, border, header_font, fill)
    path = output_dir / REPORT_FILENAME
    wb.save(path)
    wb.close()
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
            _put(ws, row[8].row, 9, final_status_fa(result.final_status.value))
            _put(ws, row[8].row, 10, result.reason)
        if len(seen) != len(results) or set(seen) != set(results):
            raise ValueError("گزارش Excel با نتایج این بررسی مطابقت ندارد.")
        _refresh_applicants(wb, run)
        counts = dict(summary_rows(run)[:5])
        for row in ws.iter_rows(max_row=header - 1):
            if row[0].value in counts:
                _put(ws, row[0].row, 2, counts[row[0].value])
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
                _put(ws, index, 1, names[name])
                result = results_by_name[name]
                _put(ws, index, 9, final_status_fa(result.final_status.value))
                _put(ws, index, 10, result.reason)
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
                _put(ws, row[0].row, 2, values[row[0].value])
        _refresh_applicants(wb, run)
        path = output_dir / REPORT_FILENAME
        wb.save(path)
        return path
    finally:
        wb.close()
