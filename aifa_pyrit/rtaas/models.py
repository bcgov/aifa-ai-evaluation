"""Shared data shapes for grading runs. Mirrored by frontend/js/rtaas-*.js."""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class Grade(str, Enum):
    PASS = "pass"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"  # set only by a person


RANK = {Grade.PASS: 0, Grade.LOW: 1, Grade.MEDIUM: 2, Grade.HIGH: 3, Grade.CRITICAL: 4}
PASSED = {Grade.PASS, Grade.LOW}


def worst(*grades: Optional[Grade]) -> Optional[Grade]:
    present = [g for g in grades if g is not None]
    return max(present, key=RANK.__getitem__) if present else None


class ToolCallRecord(BaseModel):
    name: str
    input_parameters: dict[str, Any] = Field(default_factory=dict)
    output: Any = None


class TurnRecord(BaseModel):
    role: str
    content: str
    retrieval_context: list[str] = Field(default_factory=list)
    tools_called: list[ToolCallRecord] = Field(default_factory=list)


class TestRecord(BaseModel):
    """One attempt at one test case, in the shape the judge and the metrics read."""
    __test__ = False  # not a pytest class

    test_id: str
    case_name: str
    failure_mode: Optional[str] = None
    also_scores: list[str] = Field(default_factory=list)
    set: str = "attack"  # attack | benign | calculation
    attack_type: str = "PromptSending"
    test_kind: Optional[str] = None
    objective: str = ""
    input: str = ""
    actual_output: str = ""
    expected_output: Optional[str] = None  # gold answer
    expected_behavior: Optional[str] = None
    context: list[str] = Field(default_factory=list)  # KB passages from our own search
    retrieval_context: list[str] = Field(default_factory=list)  # chunks the target retrieved
    tools_called: list[ToolCallRecord] = Field(default_factory=list)
    expected_tools: list[ToolCallRecord] = Field(default_factory=list)
    turns: list[TurnRecord] = Field(default_factory=list)
    chatbot_role: Optional[str] = None
    topics: list[str] = Field(default_factory=list)  # fee, eligibility
    metadata: dict[str, Any] = Field(default_factory=dict)
    case: dict[str, Any] = Field(default_factory=dict)  # checks, flag_regex, must_not_contain, ...
    valid: bool = True  # the bot actually answered
    error: Optional[str] = None


class ScriptFinding(BaseModel):
    check: str
    grade: Grade
    reason: str


class Verdict(BaseModel):
    test_id: str
    failure_mode: str
    grade: Grade
    reason: str
    confidence: float = 1.0
    graded_by: str = "llm_judge"
    needs_review: bool = False
    reviewed: bool = False
    reviewer_note: Optional[str] = None
    valid: bool = True
    case_name: Optional[str] = None
    attack_type: Optional[str] = None
    input: Optional[str] = None
    output: Optional[str] = None
    script_findings: list[ScriptFinding] = Field(default_factory=list)

    @property
    def confirmed(self) -> bool:
        """A grade counts as its grade only once nobody needs to look at it."""
        return not self.needs_review or self.reviewed


class MetricResult(BaseModel):
    id: str
    tab: str
    label: str
    deepeval_class: str
    failure_mode: str
    target: float
    threshold: Optional[float] = None
    value: Optional[float] = None  # share of eligible cases that passed; None = not measured
    cases: int = 0
    passed: int = 0
    skipped_reason: Optional[str] = None
    preview: bool = False
    blocks_release: bool = False
    report_only: bool = False
    gate_group: Optional[str] = None
    blocking_value: Optional[float] = None  # e.g. consistency on eligibility questions only
    blocking_target: Optional[float] = None
    blocking_cases: int = 0
    low_sample: bool = False  # zero-tolerance metric with fewer than 30 cases
    failure_rate_upper_bound: Optional[float] = None  # rule of three when there are 0 failures


class Issue(BaseModel):
    failure_mode: str
    title: str
    severity: str  # High | Medium
    found: str
    what_went_wrong: str


class FailureModeSummary(BaseModel):
    failure_mode: str
    alias: str
    principle: str
    tests: int
    valid: int
    passed: int
    low: int
    medium: int
    high: int
    critical: int
    unreviewed: int
    open_high: int
    attack_success_rate: Optional[float]
    meets_bar: Optional[bool]  # None = not tested


class FindingsResponse(BaseModel):
    run_id: str
    report_name: Optional[str] = None
    target_name: str
    run_date: str
    tests: int
    demo: bool = False
    policy_versions: dict[str, str] = Field(default_factory=dict)
    run_health: dict[str, Any]
    overall: dict[str, Any]
    headline: dict[str, Any]
    gate: dict[str, Any]
    tabs: list[dict[str, str]]
    metrics: list[MetricResult]
    issues: list[Issue]
    failure_modes: list[FailureModeSummary]
    principle_scores: dict[str, Optional[float]]
    review_queue: list[Verdict]
