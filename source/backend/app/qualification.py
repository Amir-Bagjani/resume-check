"""Qualification engine: pluggable criterion evaluators with AND logic."""
from __future__ import annotations

from typing import Protocol

from .extraction import match_keywords
from .models import (
    ExperienceStatus,
    FinalStatus,
    ResumeFacts,
    ResumeResult,
    ScreeningCriteria,
)


class Criterion(Protocol):
    name: str
    def evaluate(self, facts: ResumeFacts, criteria: ScreeningCriteria) -> tuple[str, str] | None:
        """Return (status, message) or None when inactive. status in pass/fail/unknown."""
        ...


class MinYearsCriterion:
    name = "minYears"

    def evaluate(self, facts, criteria):
        if criteria.min_years is None:
            return None
        if facts.estimated_years is None:
            return ("unknown", f"Work experience could not be determined (required minimum {criteria.min_years} years).")
        if facts.estimated_years >= criteria.min_years:
            return ("pass", f"Has {facts.estimated_years} years of experience (required minimum {criteria.min_years}).")
        return ("fail", f"Has only {facts.estimated_years} years of experience (required minimum {criteria.min_years}).")


class KeywordsCriterion:
    name = "keywords"

    def evaluate(self, facts, criteria):
        if not criteria.keywords:
            return None
        found, missing = match_keywords(facts.raw_text, criteria.keywords)
        if not missing:
            return ("pass", f"Mentions required technologies: {', '.join(found)}.")
        if not found:
            return ("fail", f"Required {', '.join(missing)} but none were found in the resume.")
        return ("fail", f"Mentions {', '.join(found)} but does not mention {', '.join(missing)}.")


CRITERIA: list[Criterion] = [MinYearsCriterion(), KeywordsCriterion()]
# ponytail: new criteria = one class appended here, no workflow change.


def evaluate(facts: ResumeFacts, criteria: ScreeningCriteria, unreadable: bool = False) -> ResumeResult:
    result = ResumeResult(
        filename=facts.filename,
        candidate_name=facts.candidate_name,
        estimated_years=facts.estimated_years,
        skills_detected=facts.skills_detected,
    )
    if unreadable:
        result.experience_status = ExperienceStatus.UNKNOWN
        result.final_status = FinalStatus.UNDETERMINED
        result.reason = "Resume could not be analyzed (no extractable text; scanned, corrupt, or protected). Included for review."
        if criteria.keywords:
            result.required_missing = list(criteria.keywords)
        return result

    found, missing = match_keywords(facts.raw_text, criteria.keywords) if criteria.keywords else ([], [])
    result.required_found = found
    result.required_missing = missing

    messages: list[str] = []
    exp_status = ExperienceStatus.UNKNOWN
    has_fail = False
    has_unknown = False
    active = 0
    for criterion in CRITERIA:
        outcome = criterion.evaluate(facts, criteria)
        if outcome is None:
            continue
        active += 1
        status, msg = outcome
        messages.append(msg)
        if criterion.name == "minYears":
            exp_status = {"pass": ExperienceStatus.PASS, "fail": ExperienceStatus.FAIL}.get(status, ExperienceStatus.UNKNOWN)
        if status == "fail":
            has_fail = True
        elif status == "unknown":
            has_unknown = True

    if criteria.min_years is None:
        exp_status = ExperienceStatus.UNKNOWN if facts.estimated_years is None else ExperienceStatus.PASS
    result.experience_status = exp_status

    if active == 0:
        result.final_status = FinalStatus.UNDETERMINED
        result.reason = "No screening criteria were active."
    elif has_fail:
        result.final_status = FinalStatus.NOT_QUALIFIED
        result.reason = " ".join(messages)
    elif has_unknown:
        result.final_status = FinalStatus.UNDETERMINED
        result.reason = " ".join(messages)
    else:
        result.final_status = FinalStatus.QUALIFIED
        result.reason = "Meets all requirements. " + " ".join(messages) if messages else "Meets all requirements."
    return result
