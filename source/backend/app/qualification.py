"""Qualification engine: pluggable criterion evaluators with AND logic."""
from __future__ import annotations

from typing import Protocol

from .extraction import match_keywords
from .locale import format_years
from .models import (
    DetectionStatus,
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
    """Compares ONLY the candidate's self-declared number against the minimum.

    No date arithmetic, no job-duration summing, no "+" inflation: "2+ years"
    is compared as 2.
    """

    name = "minYears"

    def evaluate(self, facts, criteria):
        if criteria.min_years is None:
            return None
        minimum = criteria.min_years
        declared = facts.declared_experience_years
        if declared is None:
            if facts.experience_detection_status == DetectionStatus.AMBIGUOUS:
                return (
                    "unknown",
                    "چند مقدار مختلف برای سابقه کار اعلام شده و انتخاب قطعی ممکن نیست؛ نیازمند بررسی.",
                )
            return (
                "unknown",
                f"میزان سابقه کار به‌صورت صریح در رزومه اعلام نشده است. حداقل سابقه موردنیاز: {format_years(minimum)}.",
            )
        if declared >= minimum:
            return (
                "pass",
                f"سابقه کار اعلام‌شده: {format_years(declared)} (حداقل موردنیاز: {format_years(minimum)}).",
            )
        return (
            "fail",
            f"سابقه کار اعلام‌شده کمتر از حداقل موردنیاز است: {format_years(declared)} در برابر {format_years(minimum)}.",
        )


class KeywordsCriterion:
    name = "keywords"

    def evaluate(self, facts, criteria):
        if not criteria.keywords:
            return None
        found, missing = match_keywords(facts.raw_text, criteria.keywords)
        if not missing:
            return ("pass", f"فناوری‌های موردنیاز در رزومه ذکر شده است: {'، '.join(found)}.")
        if not found:
            return (
                "fail",
                f"هیچ‌کدام از فناوری‌های موردنیاز یافت نشد: {'، '.join(missing)}.",
            )
        return (
            "fail",
            f"فناوری‌های ذکرشده: {'، '.join(found)} — فناوری‌های یافت‌نشده: {'، '.join(missing)}.",
        )


CRITERIA: list[Criterion] = [MinYearsCriterion(), KeywordsCriterion()]
# ponytail: new criteria = one class appended here, no workflow change.


def _source_note(result: ResumeResult) -> str:
    if not result.experience_source_text:
        return ""
    section = result.experience_source_section.strip()
    where = f" (بخش: {section})" if section else ""
    return f" متن رزومه: «{result.experience_source_text}»{where}."


def evaluate(facts: ResumeFacts, criteria: ScreeningCriteria, unreadable: bool = False) -> ResumeResult:
    result = ResumeResult(
        filename=facts.filename,
        candidate_name=facts.candidate_name,
        declared_experience_years=facts.declared_experience_years,
        experience_source_text=facts.experience_source_text,
        experience_source_section=facts.experience_source_section,
        experience_detection_status=facts.experience_detection_status,
        skills_detected=facts.skills_detected,
    )
    if unreadable:
        result.experience_status = ExperienceStatus.UNKNOWN
        result.final_status = FinalStatus.UNDETERMINED
        result.reason = (
            "رزومه قابل تحلیل نبود (متن قابل استخراجی یافت نشد؛ فایل اسکن‌شده، خراب یا محافظت‌شده است). "
            "برای بررسی در نظر گرفته شد."
        )
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
        exp_status = (
            ExperienceStatus.UNKNOWN
            if facts.declared_experience_years is None
            else ExperienceStatus.PASS
        )
    result.experience_status = exp_status

    declared_note = ""
    if result.declared_experience_years is not None:
        declared_note = f" سابقه کار اعلام‌شده: {format_years(result.declared_experience_years)}."

    if active == 0:
        result.final_status = FinalStatus.UNDETERMINED
        result.reason = "هیچ معیار غربالی فعال نبود."
    elif has_fail:
        result.final_status = FinalStatus.NOT_QUALIFIED
        result.reason = declared_note + _source_note(result) + " نتیجه: رد. " + " ".join(messages)
    elif has_unknown:
        result.final_status = FinalStatus.UNDETERMINED
        result.reason = (
            declared_note + _source_note(result) + " نتیجه: نیازمند بررسی. " + " ".join(messages)
        )
    else:
        result.final_status = FinalStatus.QUALIFIED
        detail = " ".join(messages)
        result.reason = declared_note + _source_note(result) + " نتیجه: تأیید."
        if detail:
            result.reason += " " + detail
    return result