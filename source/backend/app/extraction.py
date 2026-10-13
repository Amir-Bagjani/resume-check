"""Resume text extractor and analyzer: PDF/DOCX extraction, declared-experience reader."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from .locale import to_ascii_digits
from .models import DetectionStatus, ResumeFacts
from .text_normalization import normalize_layout, normalize_layout_preserving_lines

# "Over 7 years" declares a duration on its own; no activity word is required.
_QUALIFIER_PRESENT_RE = re.compile(
    r"\b(?:over|more\s+than|at\s+least|approximately|around|nearly|about)\b|"
    r"بیش\s*از|بیشتر\s*از|حداقل|حدود|تقریباً|نزدیک",
    re.IGNORECASE,
)

SUPPORTED_EXTENSIONS = {".pdf", ".docx"}

# Known skill vocabulary extracted when present (subset reported as detected).
KNOWN_SKILLS = [
    "Python", "Java", "TypeScript", "JavaScript", "React", "Angular", "Vue", "Vue.js",
    "Material UI", "MUI", "Node.js", "Django", "FastAPI", "Flask", "SQL", "PostgreSQL",
    "MongoDB", "Docker", "Kubernetes", "AWS", "Azure", "GCP", "Git", "Linux",
    "C++", "C#", ".NET", "Go", "Rust", "HTML", "CSS", "Tailwind",
    "Redux", "Next.js", "GraphQL", "REST", "Jenkins", "Terraform",
]

# Aliases used by informational skill reporting.
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
    # ponytail: trim leftover separators at both ends so "material-ui." still
    # tokenizes as " material ui " for informational skill reporting.
    return t.strip("+#.")


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


def _is_supported_file(entry: Path) -> bool:
    return entry.is_file() and entry.suffix.lower() in SUPPORTED_EXTENSIONS


def list_resume_files(folder: str, recursive: bool = False) -> list[str]:
    """Supported resumes under ``folder``, as relative POSIX paths, sorted.

    The legacy local-folder flow stays top-level-only. Upload runs pass
    ``recursive=True``: the browser folder picker sends sub-folders, and two
    resumes can share a file name, so recursing keeps both instead of silently
    processing only one.
    """
    p = Path(folder)
    if not p.is_dir():
        return []
    entries = p.rglob("*") if recursive else p.iterdir()
    return sorted(
        entry.relative_to(p).as_posix()
        for entry in entries
        if _is_supported_file(entry)
    )


# --------------------------------------------------------------------------
# Declared-experience extraction (the only source for the experience filter)
# --------------------------------------------------------------------------

EN_NUM_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
}

FA_NUM_WORDS = {
    "یک": 1, "دو": 2, "سه": 3, "چهار": 4, "پنج": 5, "شش": 6, "شیش": 6,
    "هفت": 7, "هشت": 8, "نه": 9, "ده": 10, "یازده": 11, "دوازده": 12,
    "سیزده": 13, "چهارده": 14, "پانزده": 15, "پونزده": 15, "شانزده": 16,
    "شونزده": 16, "هفده": 17, "هیفده": 17, "هجده": 18, "هیجده": 18,
    "نوزده": 19, "بیست": 20, "سی": 30, "چهل": 40, "پنجاه": 50,
}

_EN_WORD_ALT = "|".join(sorted(EN_NUM_WORDS, key=len, reverse=True))
_FA_WORD_ALT = "|".join(sorted(FA_NUM_WORDS, key=len, reverse=True))

# Numeric token: digits (Latin/Persian folded to ASCII) or a spelled-out number.
# A number carrying a magnitude suffix (14K, 1M) is a count, never a duration.
NUM_TOKEN = rf"(?:\d{{1,3}}(?:[.,]\d+)?(?![KkMmBb])|(?<![0-9A-Za-z])(?:{_EN_WORD_ALT})(?![0-9A-Za-z])|(?:{_FA_WORD_ALT}))"

# "over", "more than", "بیش از", "حدود" ... appearing right before the number.
QUALIFIER_BEFORE = (
    r"(?:over|more\s+than|greater\s+than|at\s+least|minimum\s+of|min(?:imum)?|"
    r"approximately|approx|around|about|nearly|almost|up\s+to|over\s+the\s+past\s+of?|"
    r"بیش\s*از|بیشتر\s*از|بالاتر\s*از|حداقل|حدود|حدودا|تقریباً|نزدیک|بالای)"
)

DECLARATION_RE = re.compile(
    rf"(?P<qual>{QUALIFIER_BEFORE}[\s‌:،]*)?"
    rf"(?P<num>{NUM_TOKEN})"
    rf"[\s‌]*"
    rf"(?:\+|plus\b|and\s+(?:more|above)|or\s+more|یا\s*بیشتر)?"
    rf"[\s‌]*"
    rf"(?P<unit>years?|yrs?|سال|ساله|سالها|سال‌ها)"
    rf"(?P<plus>\+)?",
    re.IGNORECASE,
)

# What the candidate was doing during those years. This is what separates a total
# ("8+ years in software development") from a technology-specific one
# ("6+ years building React applications"); it is intentionally broad.
ACTIVITY_CONTEXT_RE = re.compile(
    r"(?:experience|experienced|professional|career|worked|work(?:ing)?|background|"
    r"track\s+record|develop(?:ing|ment|er|ed)?|build(?:ing)?|engineer(?:ing)?|"
    r"program(?:ming|med)?|cod(?:e|ing)|design(?:ing|ed)?|work(?:ed)?\s+with|"
    r"hands[\s-]?on|industry|shop|field|expertise|"
    r"سابقه|تجربه|کار|حرفه|فعالیت|پیشینه|توسعه|برنامه\s*نویسی|طراحی|توسعه\s*دهنده)",
    re.IGNORECASE,
)

# Words that keep a declaration "general" rather than technology-specific.
# "5 years of experience building React apps" is a total claim: "of experience"
# states the scope is the candidate's whole career, not one tool.
GENERAL_QUALIFIER_RE = re.compile(
    r"(?:experience|experienced|professional|total|overall|general|industry|business|"
    r"career|relevant|hands[\s-]?on|real[\s-]?world|software|development|work|"
    r"کاری|حرفه\s*ای|کلی|حرفه|کار|فعالیت|سابقه\s*کار|نرم\s*افزار|توسعه)",
    re.IGNORECASE,
)

# Evidence that a resume talks about a body of work at all.
EXPERIENCE_KEYWORD_RE = re.compile(
    r"(?:experience|experienced|professional|career|worked|work(?:ing)?\s+for|"
    r"background|track\s+record|"
    r"سابقه|تجربه|کار|حرفه|فعالیت|پیشینه)",
    re.IGNORECASE,
)

# Magnitudes and other non-duration figures that must never become "years".
COUNT_NOISE_RE = re.compile(
    r"(?:\d+\s*[KkMmBb]\+?|\d+\s*[KkMmBb]\b|"          # 14K+ users, 1M visits
    r"\+\s*users?\b|\+\s*visitors?\b|\+\s*customers?\b|"  # 14K+ users
    r"per\s+(?:day|week|month|year)|\d+\s*%)",            # 20% growth
    re.IGNORECASE,
)

TECH_TOKENS = [
    "react", "reactjs", "react.js", "angular", "vue", "vue.js", "svelte", "nextjs",
    "next.js", "node", "node.js", "nodejs", "express", "typescript", "javascript",
    "python", "django", "flask", "fastapi", "java", "spring", "kotlin", "scala",
    "php", "laravel", "symfony", "wordpress", "shopify", "ruby", "rails", "go",
    "golang", "rust", "cpp", "c#", "c++", ".net", "dotnet", "sql", "nosql",
    "mysql", "postgresql", "postgres", "mongodb", "redis", "kafka", "rabbitmq",
    "graphql", "rest", "api", "aws", "azure", "gcp", "docker", "kubernetes",
    "k8s", "terraform", "jenkins", "gitlab", "ci/cd", "devops", "linux", "unix",
    "git", "flutter", "dart", "android", "ios", "swift", "unity", "salesforce",
    "sap", "seo", "sem", "figma", "photoshop", "illustrator", "excel", "erp",
    "crm", "machine learning", "deep learning", "data science", "ai", "ml",
    "ریکت", "ری‌اکت", "جاوااسکریپت", "پایتون", "جنگو", "لاراول", "فیگما",
    "فتوشاپ", "دواچینگ",
]
_TECH_RE = re.compile(
    r"(?:(?<![0-9A-Za-z])(?:" + "|".join(re.escape(t) for t in TECH_TOKENS) + r")(?![0-9A-Za-z]))",
    re.IGNORECASE,
)

# "<preposition> <tech>" -> technology-specific phrasing.
TECH_LINK_RE = re.compile(
    r"(?:\b(?:in|with|for|on|of)\s+|\bدر\b|\bبا\b|\bروی\s+)\s*"
    r"(?:the\s+)?(?:" + "|".join(re.escape(t) for t in TECH_TOKENS) + r")\b",
    re.IGNORECASE,
)

# Same test applied to the window that belongs to one number only, so a
# technology-specific number elsewhere in the clause cannot taint it.
_TECH_LINK_RE_LOCAL = TECH_LINK_RE

# Recency/age phrasing that is not an experience claim ("graduated 5 years ago",
# "3 years old"). Checked on the sentence so "5 years ago" never becomes tenure.
_RECENCY_RE = re.compile(
    r"(?:\bago\b|\byears?\s+old\b|\blast\s+(?:\d+|one|two|three)\s+years?\b|"
    r"پیش\s*$|سال\s*پیش|ساله\s*$|بوده\s*$|\bfrom\s+now\b|مانده)",
    re.IGNORECASE,
)

# A duration inside a job-history entry: "at Acme, 01/2020 - 12/2023 (3 years 2 months)"
# states one role's length, not the candidate's total experience. The spec forbids
# using job durations as the filter value, so these are rejected outright.
_JOB_ENTRY_DURATION_RE = re.compile(
    r"\(\s*\d{1,2}\s*(?:years?|yrs?|سال)"
    r"(?:\s*\d{1,2}\s*(?:months?|ماه))?"
    r"\s*\)",
    re.IGNORECASE,
)

# Prose that scopes a duration to one role or period rather than the whole career:
# "during the first two years at Iran Talent", "in his 3 years at Acme". These are
# remembered facts about a job, not a self-declared total, so the words right before
# the number decide.
_SCOPED_TO_ROLE_RE = re.compile(
    r"(?:during|in\s+his|in\s+her|in\s+their|over\s+the\s+(?:course|period))\s+"
    r"(?:the\s+|his\s+|her\s+|their\s+|first\s+|last\s+|those\s+|these\s+|next\s+|"
    r"previous\s+|entire\s+|whole\s+|past\s+|\w+\s+){0,3}$",
    re.IGNORECASE,
)

# Connectors that introduce a subordinate, narrower claim inside the same sentence:
# "8+ years in software development, including 6+ years building React apps".
_CLAUSE_CONNECTOR_RE = re.compile(
    r"(?:\b(?:including|of\s+which|of\s+that|with\s+which|plus)\b|"
    r"\bاز\s*جمله\b|\bکه\s*از\s*آن\b|\bشامل\b)",
    re.IGNORECASE,
)

# Section headings and whether the section holds self-description prose.
# Anchored matching only, so "Some intro text here." is never read as a heading.
_SECTION_HEADINGS: tuple[tuple[str, bool], ...] = (
    # (pattern, is_summary)
    (r"professional summary", True),
    (r"career summary", True),
    (r"work summary", True),
    (r"executive summary", True),
    (r"professional profile", True),
    (r"career profile", True),
    (r"personal profile", True),
    (r"personal statement", True),
    (r"career objective", True),
    (r"about me", True),
    (r"about", True),
    (r"summary", True),
    (r"profile", True),
    (r"introduction", True),
    (r"intro", True),
    (r"objective", True),
    (r"overview", True),
    (r"خلاصه رزومه", True),
    (r"خلاصه سوابق", True),
    (r"خلاصه حرفه ای", True),
    (r"خلاصه", True),
    (r"درباره من", True),
    (r"دربارهٔ من", True),
    (r"دربیاره من", True),
    (r"معرفی شخصی", True),
    (r"معرفی کلی", True),
    (r"معرفی", True),
    (r"پیشینه", True),
    # History sections: they bound a block but never count as self-description.
    (r"work experience", False),
    (r"professional experience", False),
    (r"employment history", False),
    (r"employment", False),
    (r"work history", False),
    (r"career history", False),
    (r"experience", False),
    (r"سوابق شغلی", False),
    (r"سوابق کاری", False),
    (r"سابقه شغلی", False),
    (r"سابقه کاری", False),
    (r"سوابق", False),
    (r"تجربه کاری", False),
    (r"سوابق تحصیلی", False),
    (r"education", False),
    (r"تحصیلات", False),
    (r"مهارت", False),
    (r"skills", False),
)

_HEADING_RE = re.compile(
    r"^(?:"
    + "|".join(f"(?:{pat})" for pat, _ in _SECTION_HEADINGS)
    + r")\s*(?:[-–—:]*\s*[\w؀-ۿ(].*)?$",
    re.IGNORECASE,
)

SUMMARY_PATTERNS = tuple(pat for pat, is_sum in _SECTION_HEADINGS if is_sum)

# Folds ZWNJ/Arabic letter variants and digit systems without losing offsets.
_PERSIAN_NOISE_RE = re.compile(r"[‌‏‎]|[يﻯﻰ]|[كﻙ]|[ۀە]")


def _fold(text: str) -> str:
    return _PERSIAN_NOISE_RE.sub(" ", text).replace("ي", "ی").replace("ك", "ک")


def _parse_num_token(token: str) -> float | None:
    t = _fold(token).strip().lower()
    t = t.replace("٫", ".")
    if re.fullmatch(r"\d{1,3}(?:[.,]\d+)?", t):
        return float(t.replace(",", "."))
    if t in EN_NUM_WORDS:
        return float(EN_NUM_WORDS[t])
    if t in FA_NUM_WORDS:
        return float(FA_NUM_WORDS[t])
    return None


@dataclass
class ExperienceDeclaration:
    """One explicitly self-declared experience statement found in the text."""

    years: float
    source_text: str
    section: str
    is_summary: bool
    is_technology_specific: bool


@dataclass
class DeclaredExperience:
    years: float | None
    source_text: str = ""
    section: str = ""
    status: DetectionStatus = DetectionStatus.NOT_FOUND
    candidates: list[ExperienceDeclaration] | None = None


_SUMMARY_RE = re.compile(
    r"^(?:" + "|".join(f"(?:{p})" for p in SUMMARY_PATTERNS) + r")\s*$",
    re.IGNORECASE,
)


def _heading_kind(line: str) -> bool | None:
    """Return True for a self-description heading, False for other sections, None if not a heading."""
    clean = line.strip().strip("*#•–—-_ \t:")
    if not clean or len(clean) > 60:
        return None
    folded = _fold(clean).strip().rstrip(":").strip()
    if not _HEADING_RE.match(folded):
        return None
    return bool(_SUMMARY_RE.match(folded))


def _split_sections(text: str) -> list[tuple[str, str, int, bool]]:
    """Split raw text into (section_label, block_text, offset, is_summary) blocks.

    Every line still lands in a block, so declarations written on the heading
    line itself ("Summary: 5 years of experience") are never dropped.
    """
    blocks: list[tuple[str, str, int, bool]] = []
    label = ""
    is_summary = False
    buffer: list[str] = []
    start = 0
    offset = 0
    for line in text.splitlines(keepends=True):
        kind = _heading_kind(line)
        if kind is not None:
            if buffer:
                blocks.append((label, "".join(buffer), start, is_summary))
                buffer = []
                start = offset
            label = line.strip().strip("*#•–—-_ \t:")
            is_summary = bool(kind)
        buffer.append(line)
        offset += len(line)
    if buffer:
        blocks.append((label, "".join(buffer), start, is_summary))
    return blocks


def _split_sentences(block: str) -> list[str]:
    parts = re.split(r"(?<=[.!?؟。\n])\s+|[•\n]", block)
    return [p for p in (s.strip() for s in parts) if p]


def _is_summary_section(label: str, had_headings: bool, offset: int, is_summary: bool) -> bool:
    if label:
        return is_summary
    if not had_headings:
        # No headings at all: introductory text near the top acts as the summary.
        return offset < 1500
    return False


def _classify(sentence: str, before: str, after: str) -> tuple[bool, bool]:
    """Return (is_general, is_technology_specific) for one matched declaration.

    "8+ years in software development, including 6+ years building React apps" holds
    two numbers in one clause. The first is the professional total, the second is a
    technology-specific subset, so each is classified from its OWN surrounding
    words rather than from the whole sentence.
    """
    after_window = _fold(after)
    # "5 years of experience building React apps" is a total claim: "of experience"
    # states the scope is the candidate's whole career, not one tool. Order decides
    # the rest: "of React experience" names the tool FIRST and is technology-specific,
    # while "of experience building React apps" names the scope first.
    tech_span = _TECH_RE.search(after_window)
    general_span = GENERAL_QUALIFIER_RE.search(after_window)
    # The scope word only wins when it comes FIRST: "of experience building React"
    # is a total, "of React experience" names the tool first.
    general_nearby = bool(general_span) and (
        tech_span is None or general_span.start() < tech_span.start()
    )
    strict_tech = bool(tech_span) and not general_nearby
    linked_tech = bool(_TECH_LINK_RE_LOCAL.search(after_window)) and not general_nearby
    is_tech = strict_tech or linked_tech
    return (not is_tech), is_tech


def extract_experience_declarations(text: str) -> list[ExperienceDeclaration]:
    """Find every explicit 'N years ...' self-declared statement.

    Accepts the many phrasings candidates actually use — "8+ years in software
    development", "5 years working as a developer", "7+ years developing
    applications" — and does not require the literal phrase "years of experience".

    Only what the candidate wrote is returned: no date arithmetic, no summing of
    job durations, no inference from employment history.
    """
    found: list[ExperienceDeclaration] = []
    if not text.strip():
        return found

    # Section splitting keeps the line structure (headings must stay on their own
    # line); each block is then normalized for matching so PDF line breaks,
    # hyphenation and split letters cannot hide a declaration.
    structured = normalize_layout_preserving_lines(text)
    blocks = _split_sections(structured)
    had_headings = any(label for label, _, _, _ in blocks)
    for label, block, offset, heading_is_summary in blocks:
        is_summary = _is_summary_section(label, had_headings, offset, heading_is_summary)
        for sentence in _split_sentences(normalize_layout(block)):
            if not sentence.strip():
                continue
            folded_sentence = _fold(sentence)
            # Must talk about a body of work to count as experience, unless the
            # number already carries its own declarator ("Over 7 years", "بیش از ۳ سال").
            has_activity = bool(ACTIVITY_CONTEXT_RE.search(folded_sentence))
            if _RECENCY_RE.search(folded_sentence):
                continue
            if not has_activity and not _QUALIFIER_PRESENT_RE.search(sentence):
                continue
            folded = to_ascii_digits(folded_sentence)
            for m in DECLARATION_RE.finditer(folded):
                value = _parse_num_token(m.group("num"))
                if value is None or value <= 0 or value > 70:
                    continue
                # "14K+ users" / "1M visits" / "20% faster" are counts, not durations.
                window = folded[max(0, m.start() - 24): m.end() + 24]
                if COUNT_NOISE_RE.search(window):
                    continue
                # "(3 years 2 months)" next to a job entry is one role's length.
                if _JOB_ENTRY_DURATION_RE.search(folded[max(0, m.start() - 8): m.end() + 14]):
                    continue
                # "during the first two years at Acme" scopes a span to one role.
                if _SCOPED_TO_ROLE_RE.search(folded[max(0, m.start() - 40): m.start()]):
                    continue
                tail = folded[m.end():]
                # Context for THIS number runs until the next duration or clause end,
                # so a trailing technology-specific number is not absorbed into it.
                nxt = DECLARATION_RE.search(tail)
                limit = nxt.start() if nxt else len(tail)
                segment = tail[:limit]
                # A connector only starts a new claim when a further number follows it:
                # "including 6+ years ..." narrows to the second number, while
                # "including large-scale React platforms" merely adds detail to the
                # same total and must not re-scope it.
                split = _CLAUSE_CONNECTOR_RE.search(segment)
                if split and nxt is not None and nxt.start() > split.start():
                    after_ctx = segment[split.end():]
                else:
                    after_ctx = segment[:60]
                head = folded[max(0, m.start() - 30): m.start()]
                is_general, is_tech = _classify(folded_sentence, head, after_ctx)
                found.append(
                    ExperienceDeclaration(
                        years=value,
                        source_text=sentence.strip(),
                        section=label,
                        is_summary=is_summary,
                        is_technology_specific=is_tech,
                    )
                )
    return found


def extract_declared_experience(text: str) -> DeclaredExperience:
    """Resolve the single declared general-experience value, or report why not.

    Conflicting general statements are resolved only by preferring an explicit
    professional-summary statement; otherwise the result is Ambiguous (Unknown to
    the filter) rather than a guess.
    """
    candidates = extract_experience_declarations(text)
    general = [c for c in candidates if not c.is_technology_specific]
    if not general:
        return DeclaredExperience(
            years=None,
            status=DetectionStatus.NOT_FOUND,
            candidates=candidates,
        )
    values = {c.years for c in general}
    if len(values) == 1:
        best = next(c for c in general if c.is_summary) if any(c.is_summary for c in general) else general[0]
        return DeclaredExperience(
            years=best.years,
            source_text=best.source_text,
            section=best.section,
            status=DetectionStatus.FOUND,
            candidates=candidates,
        )
    summaries = {c.years for c in general if c.is_summary}
    if len(summaries) == 1:
        best = next(c for c in general if c.is_summary and c.years in summaries)
        return DeclaredExperience(
            years=best.years,
            source_text=best.source_text,
            section=best.section,
            status=DetectionStatus.FOUND,
            candidates=candidates,
        )
    return DeclaredExperience(years=None, status=DetectionStatus.AMBIGUOUS, candidates=candidates)


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
    declaration = extract_declared_experience(text)
    facts.declared_experience_years = declaration.years
    facts.experience_source_text = declaration.source_text
    facts.experience_source_section = declaration.section
    facts.experience_detection_status = declaration.status
    facts.skills_detected = detect_skills(text)
    return facts
