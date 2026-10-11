"""Backend tests: declared-experience extraction, strict filtering, Persian output."""
from __future__ import annotations

import tempfile
import time
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _client():
    from backend.app.main import app
    return TestClient(app)


def _make_docx(path: Path, lines: list[str]):
    from docx import Document
    doc = Document()
    for line in lines:
        doc.add_paragraph(line)
    doc.save(path)


def _declared(text: str):
    from backend.app.extraction import extract_declared_experience
    return extract_declared_experience(text)


def _years(text: str):
    return _declared(text).years


@pytest.fixture()
def resume_dir(tmp_path: Path):
    d = tmp_path / "resumes"
    d.mkdir()
    # Candidate A: declared 7 years + React + Material UI -> Qualified
    _make_docx(d / "candidate_a.docx", [
        "Alice Anderson",
        "Senior Frontend Developer",
        "Professional Summary",
        "I have 7+ years of professional experience building web applications.",
        "Work Experience:",
        "Frontend Developer at FooCorp, Jan 2018 - Mar 2023",
        "Junior Developer at BarInc, Jun 2016 - Dec 2017",
        "Skills: React, Material UI, TypeScript",
    ])
    # Candidate B: declared 3 years + React -> Not Qualified on experience
    _make_docx(d / "candidate_b.docx", [
        "Bob Baker",
        "Frontend Developer",
        "Summary",
        "3+ years of professional experience as a frontend developer.",
        "Skills: React, JavaScript",
    ])
    # Candidate C: no declared value + React + Material UI -> Undetermined
    _make_docx(d / "candidate_c.docx", [
        "Carol Clark",
        "Designer",
        "A creative professional with React and Material UI skills.",
    ])
    # Candidate D: declared 6 years but Vue/Angular only -> Not Qualified on keywords
    _make_docx(d / "candidate_d.docx", [
        "Dan Davis",
        "Frontend Developer",
        "Work Experience: 6 years of professional experience.",
        "Skills: Vue, Angular",
    ])
    # Ignored: subfolder file + txt file
    (d / "sub").mkdir()
    _make_docx(d / "sub" / "nested.docx", ["Nested Nora", "Skills: React"])
    (d / "notes.txt").write_text("React expert")
    return d


# --------------------------------------------------------------------------
# Declared-experience extraction (spec section 5 + required tests 1-8)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("I have 2+ years of experience.", 2),
        ("5+ years of experience", 5),
        ("Over 7 years", 7),
        ("More than 10 years of experience", 10),
        ("7+ years of professional experience", 7),
        ("3 years of experience", 3),
        ("بیش از ۳ سال سابقه", 3),
        ("بیش از ۲ سال سابقه کار", 2),
        ("دارای ۵ سال سابقه", 5),
        ("دارای پنج سال تجربه کاری", 5),
        ("۱۰ سال سابقه حرفه‌ای", 10),
        ("۷+ سال سابقه فعالیت حرفه‌ای", 7),
        ("حدود ۴ سال سابقه کار", 4),
        ("تقریباً ٨ سال خبرة مهنية", 8),
        ("Over 4 years of experience", 4),
        ("دارای ٢ سال تجربه", 2),
    ],
)
def test_declared_experience_values(text: str, expected: int):
    assert _years(text) == expected


def test_plus_sign_never_inflates_value():
    # The "+" is part of the sentence but must not change the compared number.
    assert _years("2+ years of experience") == 2
    assert _years("5+ years of professional experience") == 5
    assert _years("2+ years of experience") != 3


def test_employment_dates_without_declaration_is_unknown():
    d = _declared("Work Experience\nDeveloper, Jan 2010 - Dec 2020\nManager, 2005 - 2010")
    assert d.years is None
    assert d.status.value == "not_found"


def test_declared_wins_over_employment_dates():
    text = (
        "Professional Summary\n"
        "I have 2+ years of professional experience.\n"
        "Work Experience\n"
        "Lead Developer at Corp, Jan 2016 - Present\n"
        "Senior Developer at Inc, 2010 - 2016\n"
        "Developer at Ltd, 2005 - 2010\n"
    )
    assert _years(text) == 2


def test_declared_two_years_with_ten_year_history_uses_two():
    text = (
        "About Me\n"
        "2+ years of experience.\n"
        "Employment History\n"
        "Engineer A, 2005 - 2010\nEngineer B, 2010 - 2015\nEngineer C, 2015 - 2021\n"
    )
    assert _years(text) == 2


def test_source_text_and_section_recorded():
    d = _declared("Professional Summary\nI have 7+ years of professional experience.")
    assert d.years == 7
    assert "7+ years" in d.source_text
    assert d.section.lower() == "professional summary"


def test_persian_summary_section_recorded():
    d = _declared("خلاصه رزومه\nبیش از ۶ سال سابقه کار دارم.")
    assert d.years == 6
    assert "خلاصه رزومه" in d.section


def test_technology_specific_statement_is_not_total_experience():
    # "2+ years of React experience" is not a total professional experience claim.
    assert _years("Frontend developer with 2+ years of React experience.") is None


def test_general_declaration_used_alongside_tech_statement():
    text = "About Me\n9+ years of professional experience.\nSkills\n2+ years of React experience"
    assert _years(text) == 9


def test_conflicting_values_prefer_summary():
    text = (
        "Professional Summary\nI have 7+ years of professional experience.\n"
        "Work Experience\n3 years of experience at BazCo\n"
    )
    assert _years(text) == 7


def test_conflicting_values_without_summary_are_ambiguous():
    d = _declared("7+ years of professional experience.\n3 years of experience somewhere else.\n")
    assert d.years is None
    assert d.status.value == "ambiguous"


def test_recency_phrasing_is_not_experience():
    assert _years("Graduated 5 years ago. Nothing else here.") is None
    assert _years("I am 28 years old.") is None


def test_never_fabricates_value_for_empty_text():
    assert _years("") is None
    assert _years("   \n  ") is None


# --------------------------------------------------------------------------
# Filtering (spec section 4 + required tests 9-10)
# --------------------------------------------------------------------------


def _evaluate(text: str, min_years: float | None, keywords: list[str] | None = None):
    from backend.app.extraction import extract_declared_experience
    from backend.app.models import ResumeFacts, ScreeningCriteria
    from backend.app.qualification import evaluate
    facts = ResumeFacts(filename="cv.pdf", raw_text=text)
    d = extract_declared_experience(text)
    facts.declared_experience_years = d.years
    facts.experience_source_text = d.source_text
    facts.experience_source_section = d.section
    facts.experience_detection_status = d.status
    return evaluate(facts, ScreeningCriteria(min_years=min_years, keywords=keywords or []))


def test_minimum_five_declared_two_plus_is_rejected():
    r = _evaluate("2+ years of professional experience", 5)
    assert r.final_status.value == "Not Qualified"
    assert r.declared_experience_years == 2
    assert "۲ سال" in r.reason
    assert "رد" in r.reason


def test_minimum_five_declared_five_plus_is_approved():
    r = _evaluate("5+ years of professional experience", 5)
    assert r.final_status.value == "Qualified"
    assert r.declared_experience_years == 5
    assert "۵ سال" in r.reason


def test_more_than_five_approved_against_five():
    r = _evaluate("More than 5 years of experience", 5)
    assert r.final_status.value == "Qualified"
    assert r.declared_experience_years == 5


def test_missing_declaration_is_needs_review():
    r = _evaluate("Developer, Jan 2010 - Dec 2020", 5)
    assert r.final_status.value == "Undetermined"
    assert r.declared_experience_years is None
    assert "نیازمند بررسی" in r.reason


def test_persian_rejection_reason_is_fa():
    r = _evaluate("بیش از ۲ سال سابقه کار", 5)
    assert r.final_status.value == "Not Qualified"
    assert "۲ سال" in r.reason


def test_qualification_matrix():
    from backend.app.models import DetectionStatus, ResumeFacts, ScreeningCriteria
    from backend.app.qualification import evaluate
    crit = ScreeningCriteria(min_years=5, keywords=["React"])

    def facts(**kw):
        kw.setdefault("experience_detection_status", DetectionStatus.FOUND)
        return ResumeFacts(filename="a", raw_text="React dev", **kw)

    assert evaluate(facts(declared_experience_years=7), crit).final_status.value == "Qualified"
    r = evaluate(facts(declared_experience_years=3), crit)
    assert r.final_status.value == "Not Qualified"
    assert "۳" in r.reason
    r = evaluate(
        facts(declared_experience_years=None, experience_detection_status=DetectionStatus.NOT_FOUND),
        crit,
    )
    assert r.final_status.value == "Undetermined"
    assert "اعلام نشده" in r.reason


def test_unreadable_marked_undetermined():
    from backend.app.models import ResumeFacts, ScreeningCriteria
    from backend.app.qualification import evaluate
    r = evaluate(ResumeFacts(filename="x.pdf"), ScreeningCriteria(min_years=5), unreadable=True)
    assert r.final_status.value == "Undetermined"
    assert "قابل تحلیل نبود" in r.reason


def test_keyword_fuzzy_variants():
    from backend.app.extraction import match_keywords
    found, missing = match_keywords("Experienced with react, REACT.JS and material-ui.", ["React", "Material UI"])
    assert found == ["React", "Material UI"]
    assert missing == []


def test_keyword_vue_only_misses_react():
    from backend.app.extraction import match_keywords
    found, missing = match_keywords("Vue.js and Angular developer.", ["React"])
    assert found == []
    assert missing == ["React"]


# --------------------------------------------------------------------------
# API + end-to-end (spec required test 13)
# --------------------------------------------------------------------------


def test_scan_top_level_only(resume_dir: Path):
    c = _client()
    res = c.post("/api/folders/scan", json={"folderPath": str(resume_dir)})
    assert res.status_code == 200, res.text
    assert res.json()["fileCount"] == 4


def test_scan_empty_folder(tmp_path: Path):
    c = _client()
    res = c.post("/api/folders/scan", json={"folderPath": str(tmp_path)})
    assert res.status_code == 422


def test_scan_missing_folder():
    c = _client()
    res = c.post("/api/folders/scan", json={"folderPath": "/no/such/dir"})
    assert res.status_code == 404


def test_start_requires_criterion(resume_dir: Path):
    c = _client()
    res = c.post("/api/runs", json={"folderPath": str(resume_dir), "criteria": {}})
    assert res.status_code == 400


def test_api_errors_are_persian():
    c = _client()
    res = c.post("/api/folders/scan", json={"folderPath": "/no/such/dir"})
    detail = res.json()["detail"]
    assert any("\u0600" <= ch <= "\u06ff" for ch in detail), detail


def test_full_run_end_to_end(resume_dir: Path):
    c = _client()
    res = c.post("/api/runs", json={
        "folderPath": str(resume_dir),
        "criteria": {"minYears": 5, "keywords": ["React", "Material UI"]},
    })
    assert res.status_code == 200, res.text
    run_id = res.json()["runId"]
    data = None
    for _ in range(60):
        data = c.get(f"/api/runs/{run_id}").json()
        if data["state"] == "finished":
            break
        time.sleep(0.2)
    assert data["state"] == "finished"
    assert data["found"] == 4
    assert data["processed"] == 4
    by_name = {r["filename"]: r for r in data["results"]}
    assert by_name["candidate_a.docx"]["finalStatus"] == "Qualified"
    assert by_name["candidate_b.docx"]["finalStatus"] == "Not Qualified"
    assert by_name["candidate_c.docx"]["finalStatus"] == "Undetermined"
    assert by_name["candidate_d.docx"]["finalStatus"] == "Not Qualified"
    # Declared values come straight from the resume text.
    assert by_name["candidate_a.docx"]["declaredExperienceYears"] == 7
    assert by_name["candidate_b.docx"]["declaredExperienceYears"] == 3
    assert by_name["candidate_c.docx"]["declaredExperienceYears"] is None
    assert "7+ years" in by_name["candidate_a.docx"]["experienceSourceText"]
    # Persian payload fields present.
    assert by_name["candidate_b.docx"]["finalStatusFa"] == "رد"
    assert by_name["candidate_b.docx"]["declaredExperienceYearsFa"] == "۳ سال"

    out = Path(data["outputPath"])
    assert out.is_dir()
    assert out.name.startswith("resume-screening-output-")
    # Every processed resume is copied, whatever its status, so the viewer can
    # open rejected and undetermined files too.
    assert (out / "candidate_a.docx").exists()
    assert (out / "candidate_b.docx").exists()
    assert (out / "candidate_c.docx").exists()
    assert (out / "candidate_d.docx").exists()
    assert (out / "screening-report.xlsx").exists()
    # Originals untouched
    assert (resume_dir / "candidate_b.docx").exists()


def test_pdf_processing_without_regression(tmp_path: Path):
    """A generated PDF with a declared statement is read end to end."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    d = tmp_path / "pdfs"
    d.mkdir()
    p = d / "pdf_candidate.pdf"
    c = canvas.Canvas(str(p), pagesize=A4)
    c.setFont("Helvetica", 12)
    c.drawString(72, 780, "PDF Candidate")
    c.drawString(72, 760, "Professional Summary")
    c.drawString(72, 740, "I have 8+ years of professional experience.")
    c.drawString(72, 720, "Skills: React, TypeScript")
    c.save()

    client = _client()
    res = client.post("/api/runs", json={
        "folderPath": str(d),
        "criteria": {"minYears": 5, "keywords": ["React"]},
    })
    assert res.status_code == 200, res.text
    run_id = res.json()["runId"]
    data = None
    for _ in range(60):
        data = client.get(f"/api/runs/{run_id}").json()
        if data["state"] == "finished":
            break
        time.sleep(0.2)
    assert data["state"] == "finished"
    row = data["results"][0]
    assert row["declaredExperienceYears"] == 8
    assert row["finalStatus"] == "Qualified"


# --------------------------------------------------------------------------
# Excel localization (spec required test 12)
# --------------------------------------------------------------------------


def _report_for(run, out: Path):
    from backend.app.report import write_report
    return write_report(run, out, today=date(2026, 10, 9))


def _sample_run():
    from backend.app.models import ScreeningCriteria, ScreeningRun
    return ScreeningRun(run_id="t", folder_path="/tmp", criteria=ScreeningCriteria(min_years=5, keywords=["React"]))


def test_excel_headers_and_sheet_are_persian_rtl(tmp_path: Path):
    from openpyxl import load_workbook

    from backend.app.models import DetectionStatus, ExperienceStatus, FinalStatus, ResumeResult

    run = _sample_run()
    run.found = 1
    run.processed = 1
    run.results = [ResumeResult(
        filename="cv.pdf",
        candidate_name="Sara",
        declared_experience_years=7,
        experience_source_text="7+ years of professional experience",
        experience_source_section="Professional Summary",
        experience_detection_status=DetectionStatus.FOUND,
        experience_status=ExperienceStatus.PASS,
        final_status=FinalStatus.QUALIFIED,
        reason="سابقه کار اعلام‌شده: ۷ سال.",
    )]
    path = _report_for(run, tmp_path)
    wb = load_workbook(path)
    ws = wb.active
    assert ws.title == "گزارش غربال"
    assert ws.sheet_view.rightToLeft is True
    labels = [c.value for c in ws[1]]
    assert labels[0] == "تعداد کل رزومه‌های یافت‌شده"
    header_row = next(i for i, row in enumerate(ws.rows, start=1) if row[0].value == "نام فایل رزومه")
    headers = [c.value for c in ws[header_row]]
    assert "سابقه کار اعلام‌شده (سال)" in headers
    assert "نتیجه نهایی" in headers
    assert "دلیل / توضیح" in headers
    # RTL alignment on data cells.
    assert ws.cell(row=header_row + 1, column=1).alignment.horizontal == "right"


def test_excel_uses_jalali_and_persian_digits(tmp_path: Path):
    from openpyxl import load_workbook

    from backend.app.report import summary_rows
    run = _sample_run()
    run.found = 12
    rows = dict(summary_rows(run, today=date(2026, 10, 9)))
    assert rows["تاریخ غربال (شمسی)"] == "۱۴۰۵/۰۷/۱۷"
    assert rows["تاریخ غربال (شمسی - کامل)"] == "۱۷ مهر ۱۴۰۵"
    assert rows["تعداد کل رزومه‌های یافت‌شده"] == "۱۲"

    path = _report_for(run, tmp_path)
    ws = load_workbook(path).active
    assert ws.cell(row=1, column=2).value == "۱۲"


def test_excel_preserves_filename_and_declared_value(tmp_path: Path):
    from openpyxl import load_workbook

    from backend.app.models import (
        DetectionStatus, ExperienceStatus, FinalStatus, ResumeResult,
    )

    run = _sample_run()
    run.results = [ResumeResult(
        filename="candidate_b.docx",
        candidate_name="Bob",
        declared_experience_years=2,
        experience_source_text="2+ years of professional experience",
        experience_source_section="Summary",
        experience_detection_status=DetectionStatus.FOUND,
        experience_status=ExperienceStatus.FAIL,
        final_status=FinalStatus.NOT_QUALIFIED,
        reason="سابقه کار اعلام‌شده کمتر از حداقل موردنیاز است.",
    )]
    ws = load_workbook(_report_for(run, tmp_path)).active
    header_row = next(i for i, row in enumerate(ws.rows, start=1) if row[0].value == "نام فایل رزومه")
    values = [c.value for c in ws[header_row + 1]]
    assert values[0] == "candidate_b.docx"  # filename preserved, not translated
    assert values[2] == "۲"  # integer years, no trailing .0
    assert "2+ years of professional experience" in values[3]  # original resume text preserved
    assert "رد" in values  # Persian status


def test_excel_year_cell_has_no_trailing_decimal(tmp_path: Path):
    from openpyxl import load_workbook

    from backend.app.models import DetectionStatus, ResumeResult

    run = _sample_run()
    run.results = [ResumeResult(
        filename="cv.pdf",
        declared_experience_years=7.0,
        experience_detection_status=DetectionStatus.FOUND,
    )]
    ws = load_workbook(_report_for(run, tmp_path)).active
    header_row = next(i for i, row in enumerate(ws.rows, start=1) if row[0].value == "نام فایل رزومه")
    assert ws.cell(row=header_row + 1, column=3).value == "۷"


def test_excel_removes_illegal_controls_from_all_input_cells(tmp_path: Path):
    from openpyxl import load_workbook

    from backend.app.models import ResumeResult

    controls = "".join(chr(n) for n in range(32) if n not in (9, 10, 13))
    clean = "ㅤFront-End توسعه‌دهنده\tReact\n۵ سال\rتهران"
    dirty = clean + controls
    run = _sample_run()
    run.criteria.keywords = [dirty]
    result = ResumeResult(
        filename=dirty,
        candidate_name=dirty,
        experience_source_text=dirty,
        experience_source_section=dirty,
        skills_detected=[dirty],
        required_found=[dirty],
        required_missing=[dirty],
        reason=dirty,
    )
    run.results = [result]

    ws = load_workbook(_report_for(run, tmp_path)).active
    header_row = next(i for i, row in enumerate(ws.rows, start=1) if row[0].value == "نام فایل رزومه")
    for col in (1, 2, 4, 5, 8, 9, 10, 12):
        assert ws.cell(row=header_row + 1, column=col).value == clean
    summary = dict((row[0].value, row[1].value) for row in ws.iter_rows(max_row=9))
    assert clean in summary["معیارهای غربال استفاده‌شده"]
    # Sanitizing the report must leave the extracted text and criteria intact.
    assert result.experience_source_text == dirty
    assert run.criteria.keywords == [dirty]


def test_output_collision_suffix(tmp_path: Path):
    from backend.app.output_writer import make_output_dir
    a = make_output_dir(str(tmp_path))
    b = make_output_dir(str(tmp_path))
    assert a != b
    assert b.name.endswith("-1")


def test_pause_resume_cancel(tmp_path: Path):
    from backend.app import runner
    from backend.app.models import ScreeningCriteria
    d = tmp_path / "r"
    d.mkdir()
    for i in range(12):
        _make_docx(d / f"r{i:02d}.docx", [f"نامزد {i}", "5 years of professional experience.", "Skills: React"])
    run = runner.create_run(str(d), ScreeningCriteria(min_years=3, keywords=["React"]))
    assert runner.pause_run(run.run_id) is True
    assert runner.get_run(run.run_id).state.value == "paused"
    assert runner.resume_run(run.run_id) is True
    for _ in range(100):
        r = runner.get_run(run.run_id)
        if r.state.value in ("finished", "cancelled"):
            break
        time.sleep(0.1)
    assert runner.get_run(run.run_id).state.value == "finished"
    run2 = runner.create_run(str(d), ScreeningCriteria(keywords=["React"]))
    assert runner.cancel_run(run2.run_id) is True

# --------------------------------------------------------------------------
# Regression: real PDFs whose line breaks and phrasing defeated extraction
# (spec section 6). Text below is verbatim PDF output, breaks included.
# --------------------------------------------------------------------------

# Example 1, as extracted from "CV-frontend-2026.pdf": every keyword is broken
# across a line ending by a hyphen.
EXAMPLE_1_PDF_TEXT = """CV-frontend-2026.pdf layout text
Senior Front-End Engineer with 4 years of pro-
fessional experience specializing in building high-
performance, scalable, and security-conscious
web applications using React.js, Next.js, Type-
Script, and JavaScript.
"""

# Example 2, as extracted from "Arash_Nassiri_CV (1).pdf".
EXAMPLE_2_PDF_TEXT = """Professional Summary
Senior Frontend Developer with 8+ years in software development, including 6+ years building production
React.js and Next.js applications for enterprise clients across Germany and Europe.
"""

# Example 3, as extracted from a Senior Front-End Engineer summary.
EXAMPLE_3_PDF_TEXT = """Senior Frontend Engineer with 6+ years of experience building and modernizing
production web applications using React, Next.js, and TypeScript.
"""


def test_regression_example_1_hyphenated_line_breaks():
    """4 years of pro-\\nfessional must read as 4 years of professional experience."""
    assert _years(EXAMPLE_1_PDF_TEXT) == 4


def test_regression_example_1_decision_is_reject_at_five():
    r = _evaluate(EXAMPLE_1_PDF_TEXT, 5)
    assert r.final_status.value == "Not Qualified"
    assert r.declared_experience_years == 4


def test_regression_example_2_total_and_technology_specific_are_separated():
    from backend.app.extraction import extract_experience_declarations

    decls = extract_experience_declarations(EXAMPLE_2_PDF_TEXT)
    assert {d.years for d in decls} == {8, 6}
    general = [d for d in decls if not d.is_technology_specific]
    tech = [d for d in decls if d.is_technology_specific]
    assert [d.years for d in general] == [8]
    assert [d.years for d in tech] == [6]


def test_regression_example_2_filter_uses_total_not_react_subtotal():
    assert _years(EXAMPLE_2_PDF_TEXT) == 8
    # At minimum 6 the technology-specific subtotal alone would still pass, but the
    # value actually compared is the declared total of 8.
    r = _evaluate(EXAMPLE_2_PDF_TEXT, 5)
    assert r.final_status.value == "Qualified"
    assert r.declared_experience_years == 8


def test_regression_example_3_detected_and_approved():
    assert _years(EXAMPLE_3_PDF_TEXT) == 6
    r = _evaluate(EXAMPLE_3_PDF_TEXT, 5)
    assert r.final_status.value == "Qualified"
    assert r.declared_experience_years == 6


@pytest.mark.parametrize(
    "text,expected",
    [
        ("4 years of pro-\nfessional experience", 4),
        ("8+ years in software development", 8),
        ("6+ years of experience building applications", 6),
        ("5 years working as a frontend developer", 5),
        ("7+ years developing enterprise applications", 7),
        ("over 5 years in frontend engineering", 5),
        ("more than 3 years of professional experience", 3),
        ("4 years of professional experience", 4),
        ("6+ years of experience building web applications", 6),
        ("بیش از ۵ سال سابقه کار", 5),
        ("۶ سال تجربه در توسعه نرم‌افزار", 6),
        ("7 years of software engineering experience", 7),
        ("3 years building scalable backend systems", 3),
        ("10+ years experience", 10),
        # Newlines alone must not hide a declaration.
        ("Senior Engineer\nwith 9\nyears of\nprofessional experience\n", 9),
        ("6+ years of experience\nbuilding and modernizing\nproduction apps", 6),
        # Hyphenated compound keeps its hyphen.
        ("2+ years of front-end development experience", 2),
    ],
)
def test_regression_declaration_phrasings(text: str, expected: int):
    assert _years(text) == expected


def test_regression_split_letters_are_rejoined():
    # A renderer that separates glyphs must not defeat the match.
    assert _years("3+ y ears of experience in web development") == 3


def test_regression_blank_line_run_between_words():
    assert _years("4+\n \nyears of experience") == 4


def test_regression_multiple_values_in_one_sentence():
    from backend.app.extraction import extract_experience_declarations

    text = "10+ years of professional experience, including 4+ years building React applications."
    decls = extract_experience_declarations(text)
    assert {d.years for d in decls} == {10, 4}
    assert _years(text) == 10


def test_regression_two_totals_conflict_stays_ambiguous():
    d = _declared("I have 10+ years of professional experience. Later I say 4+ years of experience building apps.")
    assert d.years is None
    assert d.status.value == "ambiguous"


def test_regression_long_professional_summary():
    text = (
        "PROFESSIONAL SUMMARY\n"
        "Results-driven engineering leader with a track record of shipping products. "
        "I have spent the last 9+ years of professional experience building high-traffic "
        "platforms, leading small teams, and mentoring engineers across the organization. "
        "Recently focused on performance and design systems.\n"
        "SKILLS\nReact, Node.js, AWS"
    )
    assert _years(text) == 9


def test_regression_counts_are_not_durations():
    assert _years("Served 14K+ users with 1M visits per day over the years.") is None
    assert _years("Improved performance by 40% within 3 years.") is None


def test_regression_employment_dates_are_never_summarized():
    text = (
        "Work Experience\n"
        "Senior Engineer, Acme, Jan 2015 - Dec 2023\n"
        "Engineer, Globex, 2011 - 2015\n"
        "Intern, Initech, Summer 2010\n"
    )
    assert _years(text) is None


def test_regression_date_mentions_do_not_create_a_value():
    text = "Experienced developer. Led a team of 8 from 2015 to 2022 across three companies."
    assert _years(text) is None


def test_regression_plus_sign_never_inflates_after_fix():
    assert _years("2+ years of professional experience") == 2
    assert _years("8+ years in software development") == 8
    assert _years("6+ years of experience building applications") == 6


def test_regression_threshold_matrix_at_five():
    """The strict comparison rule is unchanged by the detection fix."""
    cases = [
        ("4 years of professional experience", "Not Qualified"),
        ("5+ years of professional experience", "Qualified"),
        ("6+ years of experience building web applications", "Qualified"),
        ("8+ years in software development", "Qualified"),
    ]
    for text, expected in cases:
        assert _evaluate(text, 5).final_status.value == expected, text


def test_regression_technology_only_stays_undetermined():
    """A lone technology-specific claim is still not a total, per spec section 4."""
    r = _evaluate("Frontend developer with 3 years of React experience.", 5)
    assert r.final_status.value == "Undetermined"
    assert r.declared_experience_years is None


def test_layout_normalization_is_separate_from_raw_text():
    """Hyphenation repair and line joining are available as analysis-only helpers."""
    from backend.app.text_normalization import (
        dehyphenate,
        dehyphenate_for_matching,
        normalize_layout,
    )

    # A genuine compound keeps its hyphen; the matching variant also joins the word.
    assert dehyphenate("Front-\nEnd") == "Front-End"
    assert dehyphenate_for_matching("pro-\nfessional") == "professional"
    assert normalize_layout("a\nb\nc") == "a b c"
    assert normalize_layout("") == ""
    raw = EXAMPLE_1_PDF_TEXT
    assert raw != normalize_layout(raw)  # derived text differs, raw is untouched


def test_analyze_file_keeps_original_text(tmp_path: Path):
    """The stored raw_text is the original document text, not the normalized form."""
    from backend.app.extraction import analyze_file

    _make_docx(tmp_path / "cv.docx", ["Jane Doe", EXAMPLE_1_PDF_TEXT.strip()])
    facts = analyze_file(str(tmp_path), "cv.docx")
    assert facts.declared_experience_years == 4
    # The broken wording survives verbatim in raw_text; only detection used the repair.
    assert "pro-\nfessional" in facts.raw_text
    # The source sentence reported to the user is the readable, repaired one.
    assert "professional experience" in facts.experience_source_text
    assert "pro-\nfessional" not in facts.experience_source_text


def test_end_to_end_real_pdf_pipeline(tmp_path: Path):
    """Full path: PDF file -> extraction -> declared years -> decision."""
    pytest.importorskip("reportlab")
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    from backend.app.extraction import extract_text, extract_declared_experience

    # Example 2's layout, but as a real PDF whose text layer hyphenates words.
    d = tmp_path / "resumes"
    d.mkdir()
    p = d / "example2.pdf"
    c = canvas.Canvas(str(p), pagesize=A4)
    c.setFont("Helvetica", 11)
    c.drawString(60, 780, "Professional Summary")
    c.drawString(60, 760, "Senior Frontend Developer with 8+ years in software development, including 6+ years building production")
    c.drawString(60, 744, "React.js and Next.js applications for enterprise clients.")
    c.save()

    text = extract_text(p)
    assert "8+ years in software development" in text
    assert extract_declared_experience(text).years == 8

    client = _client()
    res = client.post("/api/runs", json={"folderPath": str(d), "criteria": {"minYears": 5}})
    assert res.status_code == 200, res.text
    run_id = res.json()["runId"]
    data = None
    for _ in range(60):
        data = client.get(f"/api/runs/{run_id}").json()
        if data["state"] == "finished":
            break
        time.sleep(0.2)
    assert data["state"] == "finished"
    row = data["results"][0]
    assert row["declaredExperienceYears"] == 8
    assert row["finalStatus"] == "Qualified"
    assert row["finalStatusFa"] == "تأیید"


def test_regression_job_entry_duration_is_not_total():
    """A role's own length in parentheses is never the candidate's total."""
    text = "Frontend Developer at Kixy 10/2023 - 09/2025 (2 year)"
    assert _years(text) is None
    text2 = "Developer at Farazpardazan 06/2022 - 10/2023 (1 year 10 months)"
    assert _years(text2) is None


def test_regression_duration_scoped_to_one_role_is_ignored():
    """"during the first two years at Acme" describes a role, not the career."""
    text = "Delivered three projects during the first two years at Iran Talent."
    assert _years(text) is None


def test_regression_scope_word_order_decides_technology_specific():
    """The tool name decides: before the scope word it is tech-specific."""
    assert _years("Developer with 3 years of React experience.") is None
    assert _years("3+ years of React experience.") is None
    assert _years("Developer with 5 years of Python experience.") is None
    # Scope word first, tool mentioned later: still a total claim.
    assert _years("Developer with 5 years of experience building React apps.") == 5
    assert _years("Engineer with 7 years of professional experience with React.") == 7


def test_regression_split_letters_extracted_from_a_real_pdf_shape():
    """"o v e r 5 y e a r s" is the shape one renderer produced in the real set."""
    assert _years("Fullstack Developer with over 5 years of experience building web applications") == 5


def test_regression_phone_number_is_not_a_duration():
    """A long digit run in contact details must not read as years."""
    assert _years("Senior Front-End Developer +989163077757 email@example.com") is None


# --------------------------------------------------------------------------
# Regression: samples reported as false "unknown" (spec section 2)
# --------------------------------------------------------------------------

# Sample 1: ordinary English summary, broke only because "years of experience"
# was not required to be followed by more wording.
SAMPLE_1_PDF_TEXT = """Creative and results-driven Software Engineer with 7+ years of experience building scalable,
SEO-optimized, and high-performance web and mobile applications."""

# Sample 2: the renderer spaced out the header, one letter per gap.
SAMPLE_2_PDF_TEXT = """F r o n t e n d
S u m m a ry
e x p e r i e n c e
Frontend Engineer with 4+ years of experience building and maintaining large-scale,
production-grade web applications using React, Next.js, and TypeScript."""

# Sample 3: Persian text in Arabic presentation forms (U+FEFC and friends),
# with a ZWNJ and the phrase split across four lines.
SAMPLE_3_PDF_TEXT = """خﻼصه رزومه
دهنده ارشد فرانت‌اند با بیش از ۷ سال
توسعه
تجربه در طراحی، توسعه و نگهداری
وب ‌اپلیکیشن‌های مقیاس ‌پذیر و با عملکرد باﻻ."""


def test_regression_sample_1_detected_and_approved():
    assert _years(SAMPLE_1_PDF_TEXT) == 7
    r = _evaluate(SAMPLE_1_PDF_TEXT, 5)
    assert r.final_status.value == "Qualified"
    assert r.declared_experience_years == 7


def test_regression_sample_2_detected_and_rejected():
    assert _years(SAMPLE_2_PDF_TEXT) == 4
    r = _evaluate(SAMPLE_2_PDF_TEXT, 5)
    assert r.final_status.value == "Not Qualified"
    assert r.declared_experience_years == 4


def test_regression_sample_3_persian_presentation_forms_detected():
    assert _years(SAMPLE_3_PDF_TEXT) == 7
    r = _evaluate(SAMPLE_3_PDF_TEXT, 5)
    assert r.final_status.value == "Qualified"
    assert r.declared_experience_years == 7


def test_regression_sample_3_section_recognised():
    """Arabic presentation forms must fold before heading detection."""
    from backend.app.extraction import extract_declared_experience

    d = extract_declared_experience(SAMPLE_3_PDF_TEXT)
    assert "خلاصه رزومه" in d.section


def test_regression_previously_reported_samples_still_pass():
    """The three samples from the earlier report must keep working."""
    assert _years(EXAMPLE_1_PDF_TEXT) == 4
    assert _years(EXAMPLE_2_PDF_TEXT) == 8
    assert _years(EXAMPLE_3_PDF_TEXT) == 6


def test_regression_all_six_samples_together():
    from backend.app.extraction import extract_experience_declarations

    # Sample 2's subtotal stays technology-specific.
    decls = extract_experience_declarations(EXAMPLE_2_PDF_TEXT)
    assert [d.years for d in decls if not d.is_technology_specific] == [8]
    assert [d.years for d in decls if d.is_technology_specific] == [6]


# --------------------------------------------------------------------------
# Unicode / normalization units
# --------------------------------------------------------------------------


def test_normalize_unicode_folds_presentation_forms():
    from backend.app.text_normalization import normalize_unicode

    # U+FEFC has no NFC decomposition; only NFKC maps it back.
    assert normalize_unicode("خﻼصه") == "خلاصه"
    assert normalize_unicode("ﺗﺠﺮﺑﻪ") == "تجربه"


def test_normalize_unicode_folds_digits():
    from backend.app.text_normalization import normalize_unicode

    assert normalize_unicode("بیش از ۷ سال") == "بیش از 7 سال"
    assert normalize_unicode("٧ سنوات") == "7 سنوات"


def test_normalize_unicode_strips_zero_width_and_folds_letters():
    from backend.app.text_normalization import normalize_unicode

    assert normalize_unicode("سابقه‌کار") == "سابقه‌کار"  # ZWNJ preserved
    assert normalize_unicode("پروفایل") == "پروفایل"
    assert normalize_unicode("ARABIC ي ك") == "ARABIC ی ک"


def test_normalize_unicode_preserves_latin_typography():
    """Folding must not rewrite ASCII words, hyphens or file extensions."""
    from backend.app.text_normalization import normalize_unicode

    assert normalize_unicode("CV-front-end.pdf") == "CV-front-end.pdf"
    assert normalize_unicode("Café – naïve") == "Café – naïve"
    assert normalize_unicode("ﬁle office") == "ﬁle office"


def test_normalization_does_not_corrupt_clean_prose():
    from backend.app.text_normalization import normalize_layout

    for clean in [
        "I am a good developer and write clean code",
        "Worked at U S A company as a dev",
        "Senior Front-End Engineer React",
        "CV-frontend-2026.pdf layout",
        "over 5 years of experience building apps",
    ]:
        assert normalize_layout(clean) == clean, clean


def test_normalization_repairs_exploded_letters():
    from backend.app.extraction import extract_declared_experience
    from backend.app.text_normalization import normalize_layout

    text = (
        "D e v e l o p e r with o v e r  5 \n"
        "y e a r s  o f  e x p e r i e n c e  b u i l d i n g"
    )
    out = normalize_layout(text)
    assert "over 5" in out
    # The declaration is readable even though every letter was spaced out.
    assert extract_declared_experience(text).years == 5


# --------------------------------------------------------------------------
# Browser upload + download flow
# --------------------------------------------------------------------------


def _pdf_bytes(text: str = "Senior Engineer with 7+ years of professional experience.") -> bytes:
    reportlab = pytest.importorskip("reportlab")
    import io
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont("Helvetica", 11)
    c.drawString(60, 780, text)
    c.save()
    return buf.getvalue()


def _docx_bytes(lines: list[str]) -> bytes:
    import io
    from docx import Document

    doc = Document()
    for line in lines:
        doc.add_paragraph(line)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _upload(client, items, folder="resumes"):
    """POST /api/uploads with (filename, content) pairs under one folder."""
    files = [("files", (f"{folder}/{name}", data, "application/octet-stream")) for name, data in items]
    return client.post("/api/uploads", files=files)


def test_upload_accepts_pdf_and_docx():
    c = _client()
    res = _upload(c, [
        ("a.pdf", _pdf_bytes()),
        ("b.docx", _docx_bytes(["Bob", "3+ years of professional experience."])),
        ("notes.txt", b"ignored"),
    ])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["fileCount"] == 2
    assert body["folderName"] == "resumes"
    assert body["skipped"] == 1
    assert set(body["files"]) == {"a.pdf", "b.docx"}


def test_upload_rejects_folder_without_supported_files():
    c = _client()
    res = _upload(c, [("notes.txt", b"x"), ("data.json", b"{}")])
    assert res.status_code == 422


@pytest.mark.parametrize("name", ["CON.docx", "nul.pdf", "Aux .docx", "COM1.pdf", "LPT9.docx"])
def test_upload_names_are_valid_on_windows(name):
    from backend.app.uploads import safe_filename

    assert safe_filename(name) == "_" + name


def test_upload_does_not_overwrite_colliding_names(tmp_path: Path):
    from backend.app.uploads import store_file

    names = ["batch/cv.docx", "batch/CV.docx", "batch/cv+.docx", "batch/cv#.docx"]
    paths = [store_file(tmp_path, name, str(i).encode()) for i, name in enumerate(names)]
    assert len({str(p).casefold() for p in paths}) == len(names)
    assert [(tmp_path / p).read_bytes() for p in paths] == [b"0", b"1", b"2", b"3"]


def test_output_does_not_overwrite_names_differing_by_case(tmp_path: Path):
    from backend.app.output_writer import copy_resumes

    source = tmp_path / "input"
    source.mkdir()
    for sub, name, data in (("first", "a-CV.docx", b"first"), ("FIRST-a", "cv.docx", b"second")):
        folder = source / sub
        folder.mkdir()
        (folder / name).write_bytes(data)
    output = tmp_path / "output"
    output.mkdir()
    # Flattened names collide by case despite different source paths.
    pairs = copy_resumes(str(source), output, ["first/a-CV.docx", "FIRST-a/cv.docx"])
    assert len(pairs) == 2
    assert len({written.casefold() for _, written in pairs}) == 2
    assert [(output / written).read_bytes() for _, written in pairs] == [b"first", b"second"]


def test_upload_reads_only_up_to_the_file_limit(tmp_path: Path, monkeypatch):
    import asyncio
    from fastapi import HTTPException
    from backend.app import routes_runs, uploads

    monkeypatch.setattr(routes_runs.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(uploads, "MAX_FILE_BYTES", 16)
    read_sizes = []

    class LargeUpload:
        filename = "batch/large.pdf"

        async def read(self, size=-1):
            read_sizes.append(size)
            return b"x" * 17

    with pytest.raises(HTTPException) as exc:
        asyncio.run(routes_runs.create_upload([LargeUpload()]))
    assert exc.value.status_code == 400
    assert read_sizes == [17]
    assert not list((tmp_path / "resume-check-uploads").iterdir())


@pytest.mark.parametrize("operation", ["new_upload_dir", "store_file"])
def test_upload_unwritable_temp_folder_returns_a_clear_error(tmp_path: Path, monkeypatch, operation):
    from backend.app import routes_runs
    from backend.app import uploads

    def denied(*args):
        raise PermissionError("test: access denied")

    monkeypatch.setattr(routes_runs.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(uploads, operation, denied)
    client = _client()
    res = _upload(client, [("cv.pdf", b"%PDF")])
    assert res.status_code == 507
    assert "دسترسی" in res.json()["detail"]
    assert client.get("/api/health").status_code == 200
    staging = tmp_path / "resume-check-uploads"
    assert not staging.exists() or not list(staging.iterdir())


def test_upload_rejects_path_traversal_filename(tmp_path: Path):
    """A crafted name must not escape the staging directory."""
    c = _client()
    res = _upload(c, [("../../evil.pdf", _pdf_bytes())])
    assert res.status_code == 200
    stored = res.json()["files"]
    assert stored == ["evil.pdf"]  # directory component dropped
    assert all(".." not in name for name in stored)


def test_upload_run_produces_report_and_downloads(tmp_path: Path):
    c = _client()
    up = _upload(c, [
        ("a.pdf", _pdf_bytes("Senior Engineer with 7+ years of professional experience.")),
        ("b.docx", _docx_bytes(["Bob", "3+ years of professional experience."])),
    ])
    assert up.status_code == 200, up.text
    upload_id = up.json()["uploadId"]

    run_res = c.post(f"/api/uploads/{upload_id}/run", json={"folderPath": "", "criteria": {"minYears": 5}})
    assert run_res.status_code == 200, run_res.text
    run_id = run_res.json()["runId"]

    data = None
    for _ in range(60):
        data = c.get(f"/api/runs/{run_id}").json()
        if data["state"] == "finished":
            break
        time.sleep(0.2)
    assert data["state"] == "finished", data["state"]
    statuses = {r["filename"]: r["finalStatus"] for r in data["results"]}
    assert statuses["a.pdf"] == "Qualified"
    assert statuses["b.docx"] == "Not Qualified"

    # Excel report downloads and is a real workbook.
    rep = c.get(f"/api/runs/{run_id}/report")
    assert rep.status_code == 200
    assert "spreadsheet" in rep.headers["content-type"]
    tmp = Path(tmp_path) / "report.xlsx"
    tmp.write_bytes(rep.content)
    from openpyxl import load_workbook
    ws = load_workbook(tmp).active
    assert ws.title == "گزارش غربال"
    assert ws.sheet_view.rightToLeft is True

    # Every processed resume opens, whatever its status.
    res_file = c.get(f"/api/runs/{run_id}/resumes/a.pdf")
    assert res_file.status_code == 200
    assert res_file.content.startswith(b"%PDF")

    rejected_file = c.get(f"/api/runs/{run_id}/resumes/b.docx")
    assert rejected_file.status_code == 200
    assert len(rejected_file.content) > 0


def test_download_report_missing_returns_404():
    c = _client()
    assert c.get("/api/runs/does-not-exist/report").status_code == 404


def test_resume_download_refuses_traversal():
    c = _client()
    up = _upload(c, [("a.pdf", _pdf_bytes())])
    upload_id = up.json()["uploadId"]
    run_res = c.post(f"/api/uploads/{upload_id}/run", json={"folderPath": "", "criteria": {"minYears": 5}})
    run_id = run_res.json()["runId"]
    for _ in range(60):
        if c.get(f"/api/runs/{run_id}").json()["state"] == "finished":
            break
        time.sleep(0.2)
    assert c.get(f"/api/runs/{run_id}/resumes/..%2F..%2Fetc%2Fpasswd").status_code == 404


def test_upload_staging_retained_for_viewing_until_sweep():
    """Staging stays while results are live: it backs rejected/undetermined views.

    Deleting it at finalize was the original bug (only qualified files were in the
    output folder, so every other row went 404). Orphaned staging is reclaimed by
    the TTL sweep instead.
    """
    c = _client()
    up = _upload(c, [("a.pdf", _pdf_bytes())])
    upload_id = up.json()["uploadId"]
    run_res = c.post(f"/api/uploads/{upload_id}/run", json={"folderPath": "", "criteria": {"minYears": 5}})
    run_id = run_res.json()["runId"]
    for _ in range(60):
        if c.get(f"/api/runs/{run_id}").json()["state"] == "finished":
            break
        time.sleep(0.2)

    from backend.app import runner
    assert runner.upload_dir(upload_id) is not None
    staging = Path(tempfile.gettempdir()) / "resume-check-uploads" / upload_id
    assert staging.exists()
    # ...until the TTL sweep removes abandoned uploads.
    assert runner.sweep_stale_uploads(max_age_seconds=0) >= 1
    assert not staging.exists()


def test_upload_output_survives_staging_cleanup():
    """The report must still be downloadable after the staging folder is gone."""
    c = _client()
    up = _upload(c, [("a.pdf", _pdf_bytes())])
    upload_id = up.json()["uploadId"]
    run_res = c.post(f"/api/uploads/{upload_id}/run", json={"folderPath": "", "criteria": {"minYears": 5}})
    run_id = run_res.json()["runId"]
    for _ in range(60):
        if c.get(f"/api/runs/{run_id}").json()["state"] == "finished":
            break
        time.sleep(0.2)
    assert c.get(f"/api/runs/{run_id}/report").status_code == 200
    assert c.get(f"/api/runs/{run_id}/resumes/a.pdf").status_code == 200


def test_run_over_unknown_upload_is_404():
    c = _client()
    res = c.post("/api/uploads/nope/run", json={"folderPath": "", "criteria": {"minYears": 5}})
    assert res.status_code == 404


def test_sweep_removes_never_processed_uploads(tmp_path: Path):
    """An upload the user abandons must not stay on disk forever."""
    import os
    import time

    from backend.app import uploads

    root = tmp_path / "uploads"
    root.mkdir()
    stale = uploads.new_upload_dir(root)
    fresh = uploads.new_upload_dir(root)

    old = time.time() - uploads.STALE_AFTER_SECONDS - 60
    os.utime(stale, (old, old))

    assert uploads.sweep_stale(root) == 1
    assert not stale.exists()
    assert fresh.exists()


def test_normalization_keeps_ascii_and_digits_sane():
    from backend.app.text_normalization import normalize_layout

    assert normalize_layout("CV-front-end.pdf") == "CV-front-end.pdf"
    assert normalize_layout("7+ years") == "7+ years"


def _upload_paths(client, items, folder="resumes"):
    """Upload with explicit folder-relative paths (sub-folders included)."""
    files = [("files", (f"{folder}/{name}", data, "application/octet-stream")) for name, data in items]
    return client.post("/api/uploads", files=files)


def _wait_finished(client, run_id, limit=60):
    data = None
    for _ in range(limit):
        data = client.get(f"/api/runs/{run_id}").json()
        if data["state"] == "finished":
            break
        time.sleep(0.2)
    assert data["state"] == "finished", data["state"]
    return data


def test_output_contains_every_processed_resume():
    """Bug fix: the output folder previously held qualified files only."""
    c = _client()
    up = _upload(c, [
        ("q.pdf", _pdf_bytes("Senior Engineer with 7+ years of professional experience.")),
        ("r.docx", _docx_bytes(["Bob", "3+ years of professional experience."])),
        ("u.docx", _docx_bytes(["Niloofar", "A creative professional."])),
    ])
    assert up.status_code == 200, up.text
    upload_id = up.json()["uploadId"]
    run_res = c.post(f"/api/uploads/{upload_id}/run", json={"folderPath": "", "criteria": {"minYears": 5}})
    assert run_res.status_code == 200, run_res.text
    data = _wait_finished(c, run_res.json()["runId"])

    by_status = {r["filename"]: r["finalStatus"] for r in data["results"]}
    assert by_status == {"q.pdf": "Qualified", "r.docx": "Not Qualified", "u.docx": "Undetermined"}

    out = Path(data["outputPath"])
    present = {p.name for p in out.iterdir()}
    assert {"q.pdf", "r.docx", "u.docx"} <= present

    # Reconciliation: output file count matches processed count.
    resumes_in_output = {p.name for p in out.iterdir() if p.suffix.lower() in {".pdf", ".docx"}}
    assert len(resumes_in_output) == data["processed"] == 3

    # The viewer opens all three, whatever the status.
    for name in ("q.pdf", "r.docx", "u.docx"):
        assert c.get(f"/api/runs/{data['runId']}/resumes/{name}").status_code == 200


def test_colliding_filenames_do_not_overwrite_each_other():
    """Two resumes named cv.docx in different sub-folders both survive."""
    c = _client()
    up = _upload_paths(c, [
        ("a/cv.docx", _docx_bytes(["Ali", "6+ years of professional experience."])),
        ("b/cv.docx", _docx_bytes(["Sara", "2+ years of professional experience."])),
    ])
    assert up.status_code == 200, up.text
    upload_id = up.json()["uploadId"]
    run_res = c.post(f"/api/uploads/{upload_id}/run", json={"folderPath": "", "criteria": {"minYears": 5}})
    data = _wait_finished(c, run_res.json()["runId"])
    assert data["processed"] == 2

    out = Path(data["outputPath"])
    names = sorted(p.name for p in out.iterdir() if p.suffix.lower() == ".docx")
    assert len(names) == 2
    assert names[0] != names[1]

    for row in data["results"]:
        fetched = c.get(f"/api/runs/{data['runId']}/resumes/{row['filename']}")
        assert fetched.status_code == 200, row["filename"]
        assert len(fetched.content) > 0


def test_persian_and_special_filenames_round_trip():
    """Persian names, spaces and parentheses survive upload, copy and view."""
    c = _client()
    names = ["علی رضایی (فرانت‌اند).docx", "سارا محمدی.docx"]
    up = _upload(c, [
        (names[0], _docx_bytes(["Ali", "7+ years of professional experience."])),
        (names[1], _docx_bytes(["Sara", "3+ years of professional experience."])),
    ])
    assert up.status_code == 200, up.text
    upload_id = up.json()["uploadId"]
    run_res = c.post(f"/api/uploads/{upload_id}/run", json={"folderPath": "", "criteria": {"minYears": 5}})
    data = _wait_finished(c, run_res.json()["runId"])

    out = Path(data["outputPath"])
    for name in names:
        fetched = c.get(f"/api/runs/{data['runId']}/resumes/{name}")
        assert fetched.status_code == 200, name
        assert len(fetched.content) > 0
    stored = {p.name for p in out.iterdir() if p.suffix.lower() == ".docx"}
    assert len(stored) == 2


def test_report_name_endpoint_suggests_default():
    c = _client()
    up = _upload(c, [("a.pdf", _pdf_bytes())])
    upload_id = up.json()["uploadId"]
    run_res = c.post(f"/api/uploads/{upload_id}/run", json={"folderPath": "", "criteria": {"minYears": 5}})
    run_id = run_res.json()["runId"]
    _wait_finished(c, run_id)
    res = c.get(f"/api/runs/{run_id}/report-name")
    assert res.status_code == 200
    assert res.json()["fileName"].endswith(".xlsx")


def test_report_name_missing_run_is_404():
    c = _client()
    assert c.get("/api/runs/does-not-exist/report-name").status_code == 404
