"""Compare only the candidate's declared experience with the required minimum."""
from __future__ import annotations

from .locale import format_years
from .models import (
    DetectionStatus,
    ExperienceStatus,
    FinalStatus,
    ResumeFacts,
    ResumeResult,
    ScreeningCriteria,
)


class MinYearsCriterion:
    """Compares ONLY the candidate's self-declared number against the minimum.

    No date arithmetic, no job-duration summing, no "+" inflation: "2+ years"
    is compared as 2.
    """

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
        return result

    outcome = MinYearsCriterion().evaluate(facts, criteria)
    status, message = outcome if outcome is not None else ("unknown", "هیچ معیار غربالی فعال نبود.")
    result.experience_status = {"pass": ExperienceStatus.PASS, "fail": ExperienceStatus.FAIL}.get(status, ExperienceStatus.UNKNOWN)

    declared_note = ""
    if result.declared_experience_years is not None:
        declared_note = f" سابقه کار اعلام‌شده: {format_years(result.declared_experience_years)}."

    if outcome is None:
        result.final_status = FinalStatus.UNDETERMINED
        result.reason = message
    elif status == "fail":
        result.final_status = FinalStatus.NOT_QUALIFIED
        result.reason = declared_note + _source_note(result) + " نتیجه: رد. " + message
    elif status == "unknown":
        result.final_status = FinalStatus.UNDETERMINED
        result.reason = declared_note + _source_note(result) + " نتیجه: نیازمند بررسی. " + message
    else:
        result.final_status = FinalStatus.QUALIFIED
        result.reason = declared_note + _source_note(result) + " نتیجه: تأیید. " + message
    return result
