"""Backend tests covering PRD acceptance criteria."""
from __future__ import annotations

import os
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


@pytest.fixture()
def resume_dir(tmp_path: Path):
    d = tmp_path / "resumes"
    d.mkdir()
    # Candidate A: 7 years (date ranges) + React + Material UI -> Qualified
    _make_docx(d / "candidate_a.docx", [
        "Alice Anderson",
        "Senior Frontend Developer",
        "Work Experience:",
        "Frontend Developer at FooCorp, Jan 2018 - Mar 2023",
        "Junior Developer at BarInc, Jun 2016 - Dec 2017",
        "Skills: React, Material UI, TypeScript",
    ])
    # Candidate B: 3 years + React -> Not Qualified on experience
    _make_docx(d / "candidate_b.docx", [
        "Bob Baker",
        "Frontend Developer",
        "Work Experience:",
        "Developer at BazCo, Jan 2020 - Dec 2022",
        "Skills: React, JavaScript",
    ])
    # Candidate C: unknown experience + React + Material UI -> Undetermined
    _make_docx(d / "candidate_c.docx", [
        "Carol Clark",
        "Designer",
        "A creative professional with React and Material UI skills.",
    ])
    # Candidate D: 6 years + Vue/Angular only -> Not Qualified on keywords
    _make_docx(d / "candidate_d.docx", [
        "Dan Davis",
        "Frontend Developer",
        "Work Experience: 6 years of professional experience.",
        "Developer at Qux, 2018 - 2024.",
        "Skills: Vue, Angular",
    ])
    # Ignored: subfolder file + txt file
    (d / "sub").mkdir()
    _make_docx(d / "sub" / "nested.docx", ["Nested Nora", "Skills: React"])
    (d / "notes.txt").write_text("React expert")
    return d


def test_experience_estimator_ranges():
    from backend.app.extraction import estimate_years
    assert estimate_years("Jan 2018 - Mar 2023", today=date(2023, 4, 1)) == pytest.approx(5.25, abs=0.2)


def test_experience_estimator_unknown():
    from backend.app.extraction import estimate_years
    assert estimate_years("A creative professional with no dates.") is None


def test_keyword_fuzzy_variants():
    from backend.app.extraction import match_keywords
    text = "Experienced with react, REACT.JS and material-ui."
    found, missing = match_keywords(text, ["React", "Material UI"])
    assert found == ["React", "Material UI"]
    assert missing == []


def test_keyword_vue_only_misses_react():
    from backend.app.extraction import match_keywords
    found, missing = match_keywords("Vue.js and Angular developer.", ["React"])
    assert found == []
    assert missing == ["React"]


def test_qualification_matrix():
    from backend.app.models import ResumeFacts, ScreeningCriteria
    from backend.app.qualification import evaluate
    crit = ScreeningCriteria(min_years=5, keywords=["React"])
    r = evaluate(ResumeFacts(filename="a", estimated_years=7, raw_text="React dev"), crit)
    assert r.final_status.value == "Qualified"
    r = evaluate(ResumeFacts(filename="b", estimated_years=3, raw_text="React dev"), crit)
    assert r.final_status.value == "Not Qualified"
    assert "3" in r.reason
    r = evaluate(ResumeFacts(filename="c", estimated_years=None, raw_text="React dev"), crit)
    assert r.final_status.value == "Undetermined"
    assert "could not be determined" in r.reason.lower()


def test_unreadable_marked_undetermined():
    from backend.app.models import ResumeFacts, ScreeningCriteria
    from backend.app.qualification import evaluate
    r = evaluate(ResumeFacts(filename="x.pdf"), ScreeningCriteria(min_years=5), unreadable=True)
    assert r.final_status.value == "Undetermined"
    assert "could not be analyzed" in r.reason.lower()


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
    statuses = {r["filename"]: r["finalStatus"] for r in data["results"]}
    assert statuses["candidate_a.docx"] == "Qualified"
    assert statuses["candidate_b.docx"] == "Not Qualified"
    assert statuses["candidate_c.docx"] == "Undetermined"
    assert statuses["candidate_d.docx"] == "Not Qualified"
    # Output folder: Jalali-dated, only qualified copied, xlsx present
    out = Path(data["outputPath"])
    assert out.is_dir()
    assert out.name.startswith("resume-screening-output-")
    assert (out / "candidate_a.docx").exists()
    assert not (out / "candidate_b.docx").exists()
    assert (out / "screening-report.xlsx").exists()
    from openpyxl import load_workbook
    wb = load_workbook(out / "screening-report.xlsx")
    ws = wb.active
    rows = list(ws.rows)
    assert rows[0][0].value == "Total number of resumes found"
    assert len([r for r in data["results"]]) == 4
    # Originals untouched
    assert (resume_dir / "candidate_b.docx").exists()


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
        _make_docx(d / f"r{i:02d}.docx", [f"Candidate {i}", "5 years of professional experience.", "Skills: React"])
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
    # Cancel a fresh run
    run2 = runner.create_run(str(d), ScreeningCriteria(keywords=["React"]))
    assert runner.cancel_run(run2.run_id) is True
