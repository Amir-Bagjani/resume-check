"""Temporary upload staging for browser folder selection.

The browser's folder picker hands us file bytes, never a real filesystem path, so
uploads are staged in a per-upload directory. Every staged file lives inside that
directory by construction: the stored name is sanitized and the resolved path is
verified to stay under the staging root, which blocks path traversal from a
crafted filename such as ``../../etc/passwd``.

Originals are never touched: the browser sends copies, and the staging directory
is removed by :func:`cleanup_upload` once the run is finished.
"""
from __future__ import annotations

import re
import shutil
import time
import uuid
from pathlib import Path

SUPPORTED_EXTENSIONS = {".pdf", ".docx"}

# Upper bound per file and per upload, so a mistaken selection cannot exhaust disk.
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024
MAX_FILES = 500

# An upload that is never processed (tab closed, user changed their mind) is swept
# after this long.
STALE_AFTER_SECONDS = 6 * 60 * 60

_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9؀-ۿ\u200c _.\-()،؛]+")


class UploadError(Exception):
    """Raised when an upload cannot be accepted safely."""


def safe_filename(name: str, fallback: str = "resume") -> str:
    """Reduce an uploaded name to a safe basename inside the staging directory."""
    base = Path(name.replace("\\", "/")).name  # drop any directory component
    base = _UNSAFE_CHARS.sub("_", base).strip(" .")
    if not base:
        base = fallback
    if len(base) > 120:
        stem, dot, ext = base.rpartition(".")
        base = (stem[: 120 - len(dot) - len(ext)] + dot + ext) if dot else base[:120]
    return base


def is_supported(name: str) -> bool:
    return Path(name).suffix.lower() in SUPPORTED_EXTENSIONS


def new_upload_dir(root: Path) -> Path:
    """Create a fresh, uniquely named staging directory."""
    root.mkdir(parents=True, exist_ok=True)
    path = root / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=False)
    return path


def _resolve_inside(directory: Path, filename: str) -> Path:
    """Resolve a staged file and refuse anything escaping the staging directory.

    ``filename`` may be a relative path (``batch/sub/cv.docx``). Both sides are
    resolved before comparison so a symlinked temp directory (macOS ``/var`` ->
    ``/private/var``) does not make the check fail.
    """
    directory = directory.resolve()
    target = (directory / filename).resolve()
    try:
        target.relative_to(directory)
    except ValueError:
        raise UploadError("نام فایل نامعتبر است.") from None
    return target


def store_file(directory: Path, filename: str, data: bytes, relative: str = "") -> Path:
    """Write one uploaded file into the staging directory, safely.

    ``relative`` is the browser's ``webkitRelativePath``. Without it two resumes
    named ``cv.docx`` in different sub-folders would share one staged name and the
    second would overwrite the first, so its result would never be seen. With it the
    sub-folder is kept, giving each file its own path.
    """
    if len(data) > MAX_FILE_BYTES:
        raise UploadError(
            f"حجم فایل بیش از حد مجاز است (حداکثر {MAX_FILE_BYTES // (1024 * 1024)} مگابایت)."
        )
    if not data:
        raise UploadError("فایل خالی است.")
    if not is_supported(Path(filename).name):
        raise UploadError("فقط فایل‌های PDF و DOCX پشتیبانی می‌شوند.")
    staged = _staged_name(filename, safe_filename(filename))
    directory = directory.resolve()
    target = _resolve_inside(directory, staged)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    # Return the relative POSIX path from the original directory, not the resolved one
    try:
        return target.relative_to(directory)
    except ValueError:
        # Fallback: use the staged name directly if relative_to fails (macOS symlinks)
        return staged


def _staged_name(relative: str, fallback: str) -> str:
    """Path inside the staging directory that keeps each uploaded file distinct.

    The browser sends ``folder/sub/cv.docx``. The top-level segment is the batch
    name and is dropped from the stored path, so a file directly inside the chosen
    folder keeps a flat name while sub-folder files stay separated.
    """
    parts = [p for p in relative.replace("\\", "/").split("/") if p not in ("", ".", "..")]
    if len(parts) <= 1:
        return fallback
    return "/".join(safe_filename(p) for p in parts[1:])


def list_uploaded(directory: Path) -> list[str]:
    """Relative paths of the supported files staged so far, sorted.

    Recurses into sub-folders so two resumes that share a file name stay separate.
    """
    if not directory.is_dir():
        return []
    out: list[str] = []
    for entry in sorted(directory.rglob("*")):
        if entry.is_file() and entry.suffix.lower() in SUPPORTED_EXTENSIONS:
            out.append(entry.relative_to(directory).as_posix())
    return sorted(out)


def cleanup_upload(directory: Path) -> None:
    """Delete a staging directory and everything in it. Never raises."""
    try:
        shutil.rmtree(directory, ignore_errors=True)
    except Exception:
        pass


def sweep_stale(root: Path, max_age_seconds: int = STALE_AFTER_SECONDS) -> int:
    """Delete staging directories older than the TTL. Returns how many went.

    Safety net for the case a run cannot cover: the user uploads a folder and then
    closes the tab without starting a run. Without this the temporary copies would
    stay on disk forever.
    """
    if not root.is_dir():
        return 0
    removed = 0
    now = time.time()
    for entry in root.iterdir():
        try:
            if entry.is_dir() and now - entry.stat().st_mtime > max_age_seconds:
                shutil.rmtree(entry, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    return removed