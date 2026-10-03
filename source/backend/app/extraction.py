"""Resume text extractor and analyzer: PDF/DOCX extraction, experience estimator, keyword matcher."""
from __future__ import annotations

import os
import re
from datetime import date
from pathlib import Path

from .models import ResumeFacts

SUPPORTED_EXTENSIONS = {".pdf", ".docx"}

# Known skill vocabulary extracted when present (subset reported as detected).
KNOWN_SKILLS = [
    "Python", "Java", "TypeScript", "JavaScript", "React", "Angular", "Vue", "Vue.js",
    "Material UI", "MUI", "Node.js", "Django", "FastAPI", "Flask", "SQL", "PostgreSQL",
    "MongoDB", "Docker", "Kubernetes", "AWS", "Azure", "GCP", "Git", "Linux",
    "C++", "C#", ".NET", "Go", "Rust", "HTML", "CSS", "Tailwind",
    "Redux", "Next.js", "GraphQL", "REST", "Jenkins", "Terraform",
]

# Common aliases normalized to canonical keyword form.
ALIASES = {
    "reactjs": "react",
    "react.js": "react",
    "materialui": "material ui",
    "mui": "material ui",
    "vuejs": "vue",
    "vue.js": "vue",
    "nodejs": "node.js",
    "node": "node.js",
    "ts": "typescript",
    "js": "javascript",
    "postgres": "postgresql",
}


def normalize(text: str) -> str:
    """Lowercase, strip punctuation to spaces, collapse whitespace."""
    t = text.lower()
    t = re.sub(r"[^a-z0-9\u0600-\u06ff+#. ]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def normalize_keyword(kw: str) -> str:
    n = normalize(kw)
    return ALIASES.get(n, n)


def extract_pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            return ""
        parts = []
        for page in reader.pages:
            try:
                parts.append(page.extract_text() or "")
            except Exception:
                continue
        return "\n".join(parts)
    except Exception:
        return ""


def extract_docx_text(path: Path) -> str:
    try:
        from docx import Document
    except ImportError:
        return ""
    try:
        doc = Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs)
    except Exception:
        return ""


def extract_text(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".pdf":
        return extract_pdf_text(path)
    if ext == ".docx":
        return extract_docx_text(path)
    return ""


def list_resume_files(folder: str) -> list[str]:
    """Top-level PDF/DOCX only, sorted. No subfolder recursion."""
    p = Path(folder)
    if not p.is_dir():
        return []
    out = []
    for entry in sorted(os.listdir(folder)):
        full = p / entry
        if full.is_file() and full.suffix.lower() in SUPPORTED_EXTENSIONS:
            out.append(entry)
    return out


MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6,
    "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9,
    "september": 9, "oct": 10, "october": 10, "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

# Matches "Jan 2018 - Mar 2021", "2015 - 2020", "2019 - Present", "03/2016 – 06/2020"
DATE_RANGE_RE = re.compile(
    r"(?P<s1>(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{4}|\d{1,2}/\d{4}|\d{4})"
    r"\s*[–—-]\s*"
    r"(?P<e1>present|current|now|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{4}|\d{1,2}/\d{4}|\d{4})",
    re.IGNORECASE,
)

# Matches "7 years of experience", "5+ years experience"
TOTAL_YEARS_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)\s*(?:of\s+)?(?:work\s+|professional\s+)?experience",
    re.IGNORECASE,
)


def _parse_date(token: str, today: date) -> tuple[int, int] | None:
    t = token.strip().lower()
    if t in ("present", "current", "now"):
        return (today.year, today.month)
    m = re.match(r"(\d{1,2})/(\d{4})", t)
    if m:
        return (int(m.group(2)), int(m.group(1)))
    m = re.match(r"([a-z]+)\.?\s+(\d{4})", t)
    if m and m.group(1)[:3] in MONTHS:
        return (int(m.group(2)), MONTHS[m.group(1)[:3]])
    m = re.match(r"(\d{4})", t)
    if m:
        return (int(m.group(1)), 1)
    return None


def estimate_years(text: str, today: date | None = None) -> float | None:
    """Estimate total professional experience in years.

    Sums non-overlapping date ranges; falls back to explicit 'N years experience'
    statements; returns None when nothing reliable found. Conservative: Unknown over guess.
    """
    today = today or date.today()
    ranges: list[tuple[tuple[int, int], tuple[int, int]]] = []
    for m in DATE_RANGE_RE.finditer(text):
        s = _parse_date(m.group("s1"), today)
        e = _parse_date(m.group("e1"), today)
        if not s or not e:
            continue
        if e < s:
            continue
        if s[0] < 1970 or e[0] > today.year + 1:
            continue
        ranges.append((s, e))
    if ranges:
        # Merge overlapping ranges to avoid double counting.
        months: set[tuple[int, int]] = set()
        for (sy, sm), (ey, em) in ranges:
            y, mo = sy, sm
            while (y, mo) <= (ey, em):
                months.add((y, mo))
                mo += 1
                if mo > 12:
                    mo = 1
                    y += 1
                if len(months) > 12 * 60:  # ponytail: cap 60yr, sanity only
                    break
        return round(len(months) / 12, 1)
    totals = [float(x) for x in TOTAL_YEARS_RE.findall(text)]
    if totals:
        return max(totals)
    return None


def guess_name(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if not line or len(line) > 80:
            continue
        if re.search(r"[@\d]{1}", line) and "@" in line:
            continue
        if re.search(r"resume|curriculum|cv\b|phone|email|address", line, re.IGNORECASE):
            continue
        words = line.split()
        if 2 <= len(words) <= 4 and all(re.match(r"^[A-ZÀ-Þ\u0600-\u06FF][\w\u0600-\u06FF.'-]*$", w) for w in words):
            return line
    return ""


def detect_skills(text: str) -> list[str]:
    norm = " " + normalize(text) + " "
    found = []
    for skill in KNOWN_SKILLS:
        n = normalize(skill)
        n = ALIASES.get(n, n)
        if f" {n} " in norm or norm.startswith(n + " ") or norm.endswith(" " + n):
            found.append(skill)
        elif len(n) <= 3 and re.search(rf"(?<![a-z0-9]){re.escape(n)}(?![a-z0-9])", norm):
            if skill not in found:
                found.append(skill)
    return found


def match_keywords(text: str, keywords: list[str]) -> tuple[list[str], list[str]]:
    """Fuzzy case-insensitive match ignoring spacing/punctuation + aliases."""
    norm = " " + normalize(text) + " "
    found, missing = [], []
    for kw in keywords:
        n = normalize_keyword(kw)
        hit = f" {n} " in norm or norm.startswith(n + " ") or norm.endswith(" " + n)
        if not hit and len(n) <= 4:
            hit = bool(re.search(rf"(?<![a-z0-9]){re.escape(n)}(?![a-z0-9])", norm))
        (found if hit else missing).append(kw)
    return found, missing


def analyze_file(folder: str, filename: str) -> ResumeFacts:
    path = Path(folder) / filename
    try:
        text = extract_text(path)
    except Exception:
        text = ""
    facts = ResumeFacts(filename=filename, raw_text=text)
    if not text.strip():
        return facts
    facts.candidate_name = guess_name(text)
    facts.estimated_years = estimate_years(text)
    facts.skills_detected = detect_skills(text)
    return facts
