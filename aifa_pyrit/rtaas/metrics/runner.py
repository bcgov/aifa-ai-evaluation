"""Runs the answer-quality metrics over a run's test records.

Metric pass rate = answers >= threshold / valid answers. Invalid answers (error, empty) never count.
A metric with no eligible cases is returned with value=None and a skipped_reason ("not measured").
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from deepeval.test_case import ConversationalTestCase, LLMTestCase, ToolCall, Turn

from ..models import MetricResult, TestRecord
from . import registry, scripts

log = logging.getLogger(__name__)

ZERO_TOLERANCE_MIN = 30


# ---------- converting our records to DeepEval test cases ----------

def _tool(t) -> ToolCall:
    return ToolCall(name=t.name, input_parameters=t.input_parameters, output=t.output)


def to_llm_case(r: TestRecord, metric: dict) -> LLMTestCase:
    meta = dict(r.metadata)
    if metric.get("geval") == "consistency":
        meta = {"other_answers": r.metadata.get("reruns", [])}
    if metric.get("geval") == "matched_pairs":
        meta = {"paired_answer": r.metadata.get("pair_output", "")}
    return LLMTestCase(
        input=r.input,
        actual_output=r.actual_output,
        expected_output=r.expected_output,
        context=r.context or None,
        retrieval_context=r.retrieval_context or None,
        tools_called=[_tool(t) for t in r.tools_called] or None,
        expected_tools=[_tool(t) for t in r.expected_tools] or None,
        metadata=meta or None,
    )


def to_conversational_case(r: TestRecord) -> ConversationalTestCase:
    turns = [
        Turn(
            role=t.role,
            content=t.content,
            retrieval_context=t.retrieval_context or None,
            tools_called=[_tool(x) for x in t.tools_called] or None,
        )
        for t in r.turns
    ]
    return ConversationalTestCase(turns=turns, chatbot_role=r.chatbot_role, scenario=r.objective or None)


# ---------- which records a metric applies to ----------

def _has(r: TestRecord, need: str) -> bool:
    if need.startswith("metadata."):
        return bool(r.metadata.get(need.split(".", 1)[1]))
    if need.startswith("turns."):
        key = need.split(".", 1)[1]
        return any(getattr(t, key) for t in r.turns if t.role == "assistant")
    return bool(getattr(r, need, None))


def eligible(records: list[TestRecord], m: dict) -> list[TestRecord]:
    out = []
    for r in records:
        if not r.valid:
            continue
        if m.get("conversational") and len(r.turns) < 2:
            continue
        if not m.get("conversational") and not r.actual_output:
            continue
        if m.get("only_for") and r.set != m["only_for"]:
            continue
        if (r.metadata.get("question_type") or r.test_kind) in (m.get("not_for_question_types") or []):
            continue
        if all(_has(r, n) for n in m.get("needs", [])):
            out.append(r)
    return out


# ---------- running ----------

def _run_script(m: dict, r: TestRecord, app: registry.AppConfig) -> bool:
    if m["script"] == "link_safety":
        return scripts.link_safety(r.actual_output, app.allow_list).passed
    if m["script"] == "refusal_check":
        return scripts.refusal_check(r.actual_output).passed
    if m["script"] == "tenant_check":
        return scripts.tenant_check(r.metadata["retrieved_doc_ids"], app.tenant_doc_ids).passed
    if m["script"] == "calc_sanity":
        return scripts.calc_sanity(r.actual_output, r.case.get("flag_regex")).passed
    raise ValueError(m["script"])


def _base(m: dict) -> dict[str, Any]:
    return dict(
        id=m["id"], tab=m["tab"], label=m["label"], deepeval_class=registry.display_class(m),
        failure_mode=m["failure_mode"], target=m["target"], threshold=m.get("threshold"),
        blocks_release=registry.blocks(m), report_only=bool(m.get("report_only")), gate_group=m.get("gate_group"),
        blocking_target=m.get("blocking_target") if m.get("blocks_release") == "eligibility_only" else None,
    )


def run_metric(m: dict, records: list[TestRecord], app: registry.AppConfig, model=None,
               build: Callable[..., Any] = registry.build) -> MetricResult:
    base = _base(m)
    cases = eligible(records, m)
    if not cases:
        need = ", ".join(m.get("needs", [])) or m.get("only_for", "matching tests")
        return MetricResult(**base, value=None, skipped_reason=f"No valid test cases with {need}")

    built: dict[Optional[float], Any] = {}
    outcome: dict[str, bool] = {}
    for r in cases:
        th = registry.threshold_for(m, r.topics)
        try:
            if m["kind"] == "script":
                ok = _run_script(m, r, app)
            else:
                if th not in built:
                    built[th] = build(m, app, model, threshold=th)
                metric = built[th]
                tc = to_conversational_case(r) if m.get("conversational") else to_llm_case(r, m)
                metric.measure(tc)
                ok = bool(metric.is_successful())
        except Exception as e:  # one bad case should not sink the run
            log.warning("metric %s failed on %s: %s", m["id"], r.test_id, e)
            ok = False
        outcome[r.test_id] = ok

    passed = sum(outcome.values())
    result = MetricResult(**base, value=passed / len(cases), cases=len(cases), passed=passed)
    if m["target"] >= 1.0:
        result.low_sample = len(cases) < ZERO_TOLERANCE_MIN
        if passed == len(cases):
            result.failure_rate_upper_bound = round(3 / len(cases), 4)
    if m.get("blocks_release") == "eligibility_only":
        subset = [r for r in cases if "eligibility" in r.topics]
        result.blocking_cases = len(subset)
        if subset:
            result.blocking_value = sum(outcome[r.test_id] for r in subset) / len(subset)
    return result


def run_all(records: list[TestRecord], app: registry.AppConfig, model=None,
            metric_ids: Optional[list[str]] = None) -> list[MetricResult]:
    wanted = set(metric_ids) if metric_ids else None
    results = []
    for m in registry.spec()["metrics"]:
        if wanted is not None and m["id"] not in wanted:
            results.append(MetricResult(**_base(m), value=None, skipped_reason="Not selected for this grading run"))
            continue
        results.append(run_metric(m, records, app, model))
    return results
