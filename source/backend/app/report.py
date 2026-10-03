"""Single-sheet xlsx report: summary block on top, then per-resume rows."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from .models import ResumeResult, ScreeningCriteria, ScreeningRun
from .output_writer import jalali_today_str

REPORT_FILENAME = "screening-report.xlsx"

COLUMNS = [
    "Resume file name", "Candidate name", "Estimated years of experience",
    "Experience status", "Technologies / skills detected",
    "Required technologies found", "Required technologies missing",
    "Final status", "Reason / explanation",
]


def criteria_text(criteria: ScreeningCriteria) -> str:
    parts = []
    if criteria.min_years is not None:
        parts.append(f"min experience {criteria.min_years} years")
    if criteria.keywords:
        parts.append("keywords: " + ", ".join(criteria.keywords))
    return "; ".join(parts) or "(none)"


def write_report(run: ScreeningRun, output_dir: Path, today: date | None = None) -> Path:
    from openpyxl import Workbook
    today = today or date.today()
    wb = Workbook()
    ws = wb.active
    ws.title = "Screening Report"
    jalali = jalali_today_str(today)
    gregorian = today.strftime("%Y-%m-%d")
    summary = [
        ("Total number of resumes found", run.found),
        ("Total number of resumes processed", run.processed),
        ("Number of qualified resumes", run.qualified),
        ("Number of non-qualified resumes", run.not_qualified),
        ("Number of resumes that could not be fully analyzed", run.undetermined),
        ("Screening criteria used", criteria_text(run.criteria)),
        ("Screening date (Jalali)", jalali),
        ("Screening date (Gregorian)", gregorian),
    ]
    for label, value in summary:
        ws.append([label, value])
    ws.append([])
    ws.append(COLUMNS)
    for r in run.results:
        ws.append([
            r.filename,
            r.candidate_name,
            r.estimated_years if r.estimated_years is not None else "Unknown",
            r.experience_status.value,
            ", ".join(r.skills_detected),
            ", ".join(r.required_found),
            ", ".join(r.required_missing),
            r.final_status.value,
            r.reason,
        ])
    # ponytail: no styling pass, plain rows suffice for v1 audit.
    path = output_dir / REPORT_FILENAME
    wb.save(path)
    return path
