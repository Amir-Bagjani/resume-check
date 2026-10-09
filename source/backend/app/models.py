from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class ExperienceStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"


class FinalStatus(str, Enum):
    QUALIFIED = "Qualified"
    NOT_QUALIFIED = "Not Qualified"
    UNDETERMINED = "Undetermined"


class RunState(str, Enum):
    RUNNING = "running"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    FINISHED = "finished"


class DetectionStatus(str, Enum):
    """Outcome of looking for an explicitly declared experience value."""

    FOUND = "found"
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"


@dataclass
class ScreeningCriteria:
    min_years: Optional[float] = None
    keywords: list[str] = field(default_factory=list)


@dataclass
class ResumeFacts:
    filename: str
    candidate_name: str = ""
    # The ONLY experience source for filtering: the number the candidate wrote.
    declared_experience_years: Optional[float] = None
    experience_source_text: str = ""
    experience_source_section: str = ""
    experience_detection_status: DetectionStatus = DetectionStatus.NOT_FOUND
    skills_detected: list[str] = field(default_factory=list)
    raw_text: str = ""


@dataclass
class ResumeResult:
    filename: str
    candidate_name: str = ""
    declared_experience_years: Optional[float] = None
    experience_source_text: str = ""
    experience_source_section: str = ""
    experience_detection_status: DetectionStatus = DetectionStatus.NOT_FOUND
    experience_status: ExperienceStatus = ExperienceStatus.UNKNOWN
    skills_detected: list[str] = field(default_factory=list)
    required_found: list[str] = field(default_factory=list)
    required_missing: list[str] = field(default_factory=list)
    final_status: FinalStatus = FinalStatus.UNDETERMINED
    reason: str = ""


@dataclass
class ScreeningRun:
    run_id: str
    folder_path: str
    criteria: ScreeningCriteria
    state: RunState = RunState.RUNNING
    found: int = 0
    processed: int = 0
    qualified: int = 0
    not_qualified: int = 0
    undetermined: int = 0
    output_path: Optional[str] = None
    results: list[ResumeResult] = field(default_factory=list)