"""Shared data shapes. The frontend (frontend/js/rtaas-*.js) reads these."""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class Grade(str, Enum):
    PASS = "pass"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"  # set by a person only, never by the judge


SEVERITY_ORDER = [Grade.PASS, Grade.LOW, Grade.MEDIUM, Grade.HIGH, Grade.CRITICAL]
RANK = {g: i for i, g in enumerate(SEVERITY_ORDER)}


def worst(*grades: Optional[Grade]) -> Optional[Grade]:
    present = [g for g in grades if g is not None]
    return max(present, key=RANK.__getitem__) if present else None


# ---------- what one test produced ----------

class ToolCallRecord(BaseModel):
    name: str
    input_parameters: dict[str, Any] = {}
    output: Any = None


class TurnRecord(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    retrieval_context: list[str] = []
    tools_called: list[ToolCallRecord] = []


class TestRecord(BaseModel):
    """One attack or one normal question, plus what the target said.

    Single-turn tests fill input/actual_output. Multi-turn tests fill turns (and the last
    exchange in input/actual_output, so single-answer checks still run on them).
    """
    __test__ = False  # not a pytest class

    test_id: str
    failure_mode: str                     # e.g. "SA-3"
    technique: str                        # e.g. "Crescendo", "PromptSending"
    converters: list[str] = []            # e.g. ["Base64"]
    objective: str = ""                   # attack goal given to PyRIT
    set: Literal["attack", "benign", "calculation"] = "attack"

    input: str = ""
    actual_output: str = ""
    expected_output: Optional[str] = None  # gold answer, from goldens.jsonl
    context: list[str] = []                # KB reference text (HallucinationMetric)
    retrieval_context: list[str] = []      # chunks the target actually retrieved
    tools_called: list[ToolCallRecord] = []
    expected_tools: list[ToolCallRecord] = []

    turns: list[TurnRecord] = []
    chatbot_role: Optional[str] = None
    metadata: dict[str, Any] = {}          # reruns, pair_output, retrieved_doc_ids, tokens, latency_ms

    # added for the AIFA harness
    case_name: str = ""
    also_scores: list[str] = []
    test_kind: Optional[str] = None
    expected_behavior: Optional[str] = None
    topics: list[str] = []                 # fee, eligibility (strict thresholds)
    case: dict[str, Any] = {}              # checks, flag_regex, must_not_contain, must_contain_any, success_hint
    valid: bool = True                     # False = the bot never answered (error or empty): "not run"
    error: Optional[str] = None


class ScriptFinding(BaseModel):
    check: str
    grade: Grade
    reason: str


# ---------- judge output ----------

class Verdict(BaseModel):
    test_id: str
    failure_mode: str
    grade: Grade
    reason: str
    confidence: float = Field(ge=0, le=1)
    graded_by: Literal["script", "classifier", "llm_judge", "script+llm_judge", "human", "unjudged"]
    needs_review: bool = False
    reviewed: bool = False
    # Short notes for the dev team (one sentence each, <= 30 words)
    expected: str = ""        # what a correct answer would say/do, with the KB doc name if any
    observed: str = ""        # what the bot actually said/did
    dev_fix: str = ""         # one concrete change for the owner below
    fix_tag: str = "none"     # from policy/fix_tags.yaml; used to group fixes without extra LLM calls
    fix_owner: Literal["bot", "kb", "harness", "judge", "none"] = "none"
    # Run Results screen
    title: str = ""           # <= 8 words, plain language
    highlight: str = ""       # exact substring of the bot answer, or ""

    # added for the AIFA harness
    valid: bool = True
    reviewer_note: Optional[str] = None
    case_name: Optional[str] = None
    technique: Optional[str] = None
    input: Optional[str] = None
    output: Optional[str] = None
    script_findings: list[ScriptFinding] = []

    @property
    def confirmed(self) -> bool:
        """A grade only counts as its grade once nobody needs to look at it."""
        return not self.needs_review or self.reviewed


# ---------- what the Findings page reads ----------

class MetricResult(BaseModel):
    id: str
    tab: str
    label: str
    deepeval_class: str        # shown without the "Metric" suffix
    failure_mode: str
    target: float              # 0..1
    value: Optional[float]     # 0..1, share of cases that passed. None = not measured
    cases: int = 0
    passed: int = 0
    skipped_reason: Optional[str] = None
    preview: bool = False      # true when value is a placeholder, not measured

    # added: release thresholds table
    threshold: Optional[float] = None
    blocks_release: bool = False
    report_only: bool = False
    gate_group: Optional[str] = None          # "grounded": Faithfulness or Hallucination
    blocking_value: Optional[float] = None    # consistency on eligibility questions only
    blocking_target: Optional[float] = None
    blocking_cases: int = 0
    low_sample: bool = False                  # zero-tolerance metric with fewer than 30 cases
    failure_rate_upper_bound: Optional[float] = None  # rule of three when there are 0 failures


class Issue(BaseModel):
    failure_mode: str
    title: str                 # plain name, e.g. "Fake approvals and receipts"
    severity: Literal["High", "Medium"]
    found: str                 # e.g. "4 High in 4 tests"
    what_went_wrong: str


class FailureModeCounts(BaseModel):
    id: str
    principle: str
    tests: int = 0
    pass_: int = Field(0, alias="pass")
    low: int = 0
    medium: int = 0
    high: int = 0
    critical: int = 0
    review: int = 0
    not_run: int = 0           # the bot never answered; excluded from tests

    model_config = {"populate_by_name": True}


class OverallScore(BaseModel):
    score: Optional[float]
    raw: Optional[float]
    band: Literal["Pass", "Needs work", "Fail", "Not tested", "Run invalid"]
    capped_by: Optional[str] = None
    low_coverage: bool = False


class ReleaseGate(BaseModel):
    tier: Literal["low", "medium", "high"]
    blocked: bool
    reasons: list[str]
    not_measured: list[str] = []   # release-blocking metrics with no eligible cases yet


class RunHealth(BaseModel):
    total: int
    valid: int
    share: Optional[float]
    min_share: float
    invalid: bool              # True = under 95% valid: don't report scores


class FailureModeStat(BaseModel):
    id: str
    alias: str
    principle: str
    valid: int
    passed: int                # pass + low
    medium: int
    high: int
    critical: int
    review: int
    open_high: int
    attack_success_rate: Optional[float]   # (confirmed Medium + High) / valid
    meets_bar: Optional[bool]              # None = not tested


class Headline(BaseModel):
    meet_bar: int
    tested: int
    total: int
    text: str


class IndexScore(BaseModel):
    value: Optional[float]
    raw: Optional[float]
    capped_by: Optional[str] = None
    eligible_failure_modes: int = 0
    label: str = "Our index, not a standard"


class FindingsResponse(BaseModel):
    run_id: str
    target_name: str
    run_date: str
    tests: int
    overall: OverallScore
    gate: ReleaseGate
    tabs: list[dict]           # [{key, label, note}]
    metrics: list[MetricResult]
    issues: list[Issue]

    # added
    report_name: Optional[str] = None
    demo: bool = False
    policy_versions: dict[str, str] = {}
    run_health: Optional[RunHealth] = None
    headline: Optional[Headline] = None
    index: Optional[IndexScore] = None
    failure_modes: list[FailureModeStat] = []
    review_queue: list[Verdict] = []
    unmapped: list[dict] = []      # verdicts with a failure_mode the catalog doesn't know
    warnings: list[str] = []
