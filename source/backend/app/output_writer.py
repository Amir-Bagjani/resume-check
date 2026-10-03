"""Output folder (Jalali-dated) plus qualified file copies."""
from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path


def jalali_today_str(today: date | None = None) -> str:
    today = today or date.today()
    try:
        import jdatetime
        j = jdatetime.date.fromgregorian(date=today)
        return f"{j.year:04d}-{j.month:02d}-{j.day:02d}"
    except Exception:
        # ponytail: offline fallback Gregorian when jdatetime missing.
        return today.strftime("%Y-%m-%d")


def make_output_dir(source_folder: str, today: date | None = None) -> Path:
    base = Path(source_folder)
    stem = f"resume-screening-output-{jalali_today_str(today)}"
    candidate = base / stem
    i = 1
    while candidate.exists():
        candidate = base / f"{stem}-{i}"
        i += 1
    candidate.mkdir(parents=True, exist_ok=False)
    return candidate


def copy_qualified(source_folder: str, output_dir: Path, filenames: list[str]) -> list[str]:
    """Copy only qualified files byte-identical. Skip-and-record on OS error."""
    copied = []
    for name in filenames:
        src = Path(source_folder) / name
        try:
            shutil.copy2(src, output_dir / name)
            copied.append(name)
        except OSError:
            continue
    return copied
