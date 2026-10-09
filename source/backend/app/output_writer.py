"""Output folder (Jalali-dated) plus copies of every processed resume.

Every processed resume is copied, whatever its screening status. The viewer must be
able to open rejected and undetermined ones too, and it cannot rely on the staged
upload: that directory is temporary and is swept once the session is over.
"""
from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

REPORT_FILENAME = "screening-report.xlsx"


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


def _unique_name(desired: str, taken: set[str]) -> str:
    """Return a name free within the output folder, keeping the extension intact.

    Two resumes can share a file name (``cv.pdf`` in two sub-folders). They must not
    overwrite each other, so a counter is appended to the stem. Persian names,
    spaces and other characters are preserved as-is.
    """
    if desired not in taken:
        return desired
    path = Path(desired)
    stem, suffix = path.stem, path.suffix
    i = 2
    while f"{stem}-{i}{suffix}" in taken:
        i += 1
    return f"{stem}-{i}{suffix}"


def copy_resumes(source_folder: str, output_dir: Path, filenames: list[str]) -> list[tuple[str, str]]:
    """Copy every listed resume into the output folder, byte-identical.

    Returns (original, written) pairs; the written name may differ on collision.
    Subdirectory paths are flattened with their folder prefix (``a/cv.docx`` ->
    ``a-cv.docx``) so the output folder stays flat and no file is dropped for a
    missing parent dir. An unreadable source is skipped rather than aborting the
    run, but never silently: the caller compares written vs processed counts.
    """
    source = Path(source_folder)
    written: list[tuple[str, str]] = []
    taken: set[str] = set()
    for name in filenames:
        src = source / name
        safe_flat = name.replace("/", "-")
        target_name = _unique_name(safe_flat, taken)
        try:
            shutil.copy2(src, output_dir / target_name)
        except OSError:
            continue
        taken.add(target_name)
        written.append((name, target_name))
    return written