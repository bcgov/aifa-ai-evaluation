"""End-to-end for one run: PyRIT results in, run JSON out (what the API serves).

    python -m aifa_pyrit.rtaas.pipeline --records run_records.jsonl --out runs/run-001.json \
        --target "Water Permit Assistant" --tier medium --canary "CANARY-7f3a"

run_records.jsonl = one TestRecord per line. `records_from_report` is the adapter that turns a
saved PyRIT run report (aifa_pyrit/run_manager.py) into TestRecords:
  objective        -> objective
  last user turn   -> input        (and all turns -> turns, for multi-turn attacks)
  last reply       -> actual_output
  technique        -> report attack_type, converters
  failure mode     -> the case's failure_mode tag from the attack catalogue (data/aifa_*.json)
Retrieved chunks and tool calls come from the target's test endpoint, not PyRIT.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from . import devfix, judge
from .metrics import registry, runner, scripts
from .models import TestRecord, TurnRecord
from .policy import loader

log = logging.getLogger(__name__)

BENIGN_KINDS = {"gold_answer", "over_refusal", "contradiction_in_kb", "outdated_source", "missing_fact",
                "citation", "matched_pair", "human_route", "identity"}
# Older datasets have no failure_mode tag; infer one from the case name so they can still be graded.
NAME_HINTS = [
    (r"sysprompt|recon|system_prompt|knowledge_id|internal_id", "SA-2"),
    (r"pii|named_record|licence_number|staff_contact|latest_application|fee_lookup|exfil", "SA-1"),
    (r"inject|staff_mode|jailbreak|smuggle|role_compromise", "SA-3"),
    (r"forgery|approval|letter", "AC-1"),
    (r"drought|evasion|inspector|unlicensed|advice", "SA-6"),
    (r"fee|exempt|underreport|misclassify", "PB-1"),
    (r"boundary|off_?topic|cover_letter|quick_math|op_ed", "PB-3"),
    (r"objection|competitor|pressure", "SA-7"),
]


def infer_failure_mode(name: str) -> str:
    low = (name or "").lower()
    return next((fm for pat, fm in NAME_HINTS if re.search(pat, low)), "SA-3")


@lru_cache
def _kb():
    """Loaded once. A failure is cached too (None), so a machine without the KB doesn't retry per record."""
    try:
        from aifa_pyrit.evaluators.uat_judge import KB

        return KB()
    except Exception as exc:  # noqa: BLE001
        log.warning("KB unavailable, grading without KB passages: %s", exc)
        return None


def kb_passages(query: str, answer: str = "", k: int = 4) -> list[str]:
    kb = _kb()
    if kb is None:
        return []
    try:
        return [f"[{src}] {chunk}" for src, chunk in kb.top(f"{query} {answer[:300]}", k=k)]
    except Exception:  # noqa: BLE001
        return []


def _turns(result: dict) -> list[dict]:
    inner = result.get("results")
    turns = inner.get("turns", []) if isinstance(inner, dict) else inner if isinstance(inner, list) else []
    return [t for t in turns if isinstance(t, dict)]


def records_from_report(report: dict, app: Optional[registry.AppConfig] = None) -> list[TestRecord]:
    app = app or registry.AppConfig.from_target()
    technique = report.get("attack_type") or "PromptSending"
    records: list[TestRecord] = []
    for i, res in enumerate(report.get("results") or [], 1):
        if not isinstance(res, dict) or res.get("skipped"):  # skipped = never sent (missing test hook)
            continue
        meta = res.get("case_meta") or {}
        name = res.get("case_name") or meta.get("name") or f"case_{i}"
        turns_raw = _turns(res)
        turns: list[TurnRecord] = []
        errored: list[int] = []
        turn_error = None
        for n, t in enumerate(turns_raw, 1):
            prompt = str(t.get("original_prompt") or t.get("prompt") or "")
            reply = str(t.get("response") or "")
            failed = scripts.is_infra_error(reply) or t.get("error") or t.get("transport_error")
            if prompt:
                turns.append(TurnRecord(role="user", content=prompt))
            if failed:  # an errored turn is not something the bot said
                errored.append(n)
                turn_error = turn_error or t.get("error") or t.get("transport_error") or reply or "empty reply"
            else:
                turns.append(TurnRecord(role="assistant", content=reply))
        answered_pairs = [(u, a) for u, a in zip(turns, turns[1:]) if u.role == "user" and a.role == "assistant"]
        last_user, last_reply = (answered_pairs[-1][0].content, answered_pairs[-1][1].content) if answered_pairs \
            else (res.get("query", ""), "")
        # A case is "not run" only when the bot never answered any turn.
        error = res.get("error") if not answered_pairs else None
        if not answered_pairs and not error:
            error = turn_error or "empty or INFRA_ERROR reply"
        valid = bool(answered_pairs) and not res.get("error")
        kind = meta.get("test_kind")
        gold = meta.get("gold_answer")
        fm = meta.get("failure_mode") or infer_failure_mode(name)
        rec = TestRecord(
            test_id=f"{name}#{res.get('attempt', 1)}",
            case_name=name,
            failure_mode=fm,
            also_scores=meta.get("also_scores") or [],
            technique=technique,
            converters=list(report.get("converters") or []),
            objective=str(res.get("query") or meta.get("query") or ""),
            set="calculation" if kind == "tool_misuse" and gold else ("benign" if kind in BENIGN_KINDS else "attack"),
            test_kind=kind,
            input=last_user,
            actual_output=last_reply if valid else "",
            expected_output=gold,
            expected_behavior=res.get("expected_behavior") or meta.get("expected_behavior"),
            context=kb_passages(last_user, last_reply) if valid else [],
            turns=turns if len(turns) > 2 else [],
            chatbot_role=app.chatbot_role,
            topics=registry.detect_topics(last_user, gold),
            case={k: meta[k] for k in ("checks", "flag_regex", "must_not_contain", "must_contain_any", "success_hint", "test_kind") if k in meta}
                 | ({"must_not_contain": res.get("must_not_contain")} if res.get("must_not_contain") and "must_not_contain" not in meta else {}),
            metadata={"pair_group": meta.get("pair_group"), "failure_mode_inferred": not meta.get("failure_mode"),
                      "attempt": res.get("attempt", 1), "question_type": meta.get("question_type") or kind,
                      "step_number": meta.get("step") or res.get("step_number"), "errored_turns": errored},
            valid=valid,
            error=str(error)[:300] if error else None,
        )
        records.append(rec)

    by_case: dict[str, list[TestRecord]] = defaultdict(list)
    by_pair: dict[str, list[TestRecord]] = defaultdict(list)
    for r in records:
        if r.valid:
            by_case[r.case_name].append(r)
            if r.metadata.get("pair_group"):
                by_pair[r.metadata["pair_group"]].append(r)
    for group in by_case.values():
        for r in group:
            others = [o.actual_output for o in group if o is not r]
            if others:
                r.metadata["reruns"] = others
    for group in by_pair.values():
        for r in group:
            other = next((o for o in group if o.case_name != r.case_name), None)
            if other:
                r.metadata["pair_output"] = other.actual_output
    return records


def _last_output(r: TestRecord) -> str:
    return r.actual_output or (r.turns[-1].content if r.turns else "")


def split_not_run(records: list[TestRecord]) -> tuple[list[TestRecord], list[TestRecord]]:
    """(answered, not_run). Infra errors and empty replies are never graded."""
    not_run = [r for r in records if not r.valid or scripts.is_infra_error(_last_output(r))]
    skip = {id(r) for r in not_run}
    return [r for r in records if id(r) not in skip], not_run


def record_summary(r: TestRecord) -> dict[str, Any]:
    """What the Run Results screen shows for one attempt: the exchange, in full, so highlights match."""
    return {"test_id": r.test_id, "case_name": r.case_name, "failure_mode": r.failure_mode,
            "question_type": r.metadata.get("question_type") or r.test_kind, "technique": r.technique,
            "converters": r.converters, "step": r.metadata.get("step_number"), "input": r.input[:2000],
            "answer": r.actual_output[:4000], "attempt": r.metadata.get("attempt", 1),
            "turns": [{"role": t.role, "content": t.content[:1500]} for t in r.turns[-14:]],
            "errored_turns": r.metadata.get("errored_turns") or []}


def skipped_rows(report: dict) -> list[dict[str, Any]]:
    return [{"case_name": res.get("case_name"), "failure_mode": (res.get("case_meta") or {}).get("failure_mode"),
             "skip_reason": res.get("skipped")} for res in report.get("results") or []
            if isinstance(res, dict) and res.get("skipped")]


def not_run_rows(not_run: list[TestRecord]) -> list[dict[str, Any]]:
    return [{"test_id": r.test_id, "case_name": r.case_name, "failure_mode": r.failure_mode,
             "error": (r.error or _last_output(r) or "empty reply")[:120]} for r in not_run]


def split_unmapped(records: list[TestRecord]) -> tuple[list[TestRecord], list[dict[str, Any]]]:
    """Records whose failure_mode isn't in the catalog can't be graded (no ladder). Set them aside."""
    known = loader.failure_modes()
    keep = [r for r in records if r.failure_mode in known]
    stray = [{"test_id": r.test_id, "case_name": r.case_name, "failure_mode": r.failure_mode}
             for r in records if r.failure_mode not in known]
    return keep, stray


def default_metric_ids() -> list[str]:
    """Release-blocking metrics plus the free script checks. Diagnostics are opt-in (token cost)."""
    return [m["id"] for m in registry.spec()["metrics"] if registry.blocks(m) or m["kind"] == "script"]


SCRIPT_METRICS = ["link_safety", "no_over_refusal", "calc_sanity", "exact_values"]
JUDGE_WORKERS = 4  # concurrent judge calls; keeps a 300-row batch to minutes without hitting rate limits


def grade_records(records: list[TestRecord], app: registry.AppConfig, use_llm: bool = True,
                  metric_ids: Optional[list[str]] = None, run_metrics: bool = True, client=None,
                  workers: int = JUDGE_WORKERS, canary: Optional[str] = None) -> dict[str, Any]:
    canary = canary or registry.target_config().get("checks", {}).get("canary", {}).get("value", "")
    canary = None if not canary or canary.startswith("<FILL") else canary
    mapped, stray = split_unmapped(records)
    answered, not_run = split_not_run(mapped)

    def one(r: TestRecord):
        return judge.grade(r, app.allow_list, canary, client=client, kb_passages=r.context, use_llm=use_llm)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        verdicts = list(pool.map(one, answered))  # map keeps input order
    ids = (metric_ids or default_metric_ids()) if run_metrics else SCRIPT_METRICS
    metrics = runner.run_all(answered, app, metric_ids=ids)
    return {"verdicts": [v.model_dump(mode="json") for v in verdicts],
            "metrics": [m.model_dump(mode="json") for m in metrics],
            "not_run": not_run_rows(not_run),
            "unmapped": stray,
            "run_health": round(len(answered) / max(1, len(mapped)), 3),
            "dev_fixes": devfix.group(verdicts),
            "records": [record_summary(r) for r in mapped]}


def grade_report(report: dict, report_name: str, *, tier: str = "medium", use_llm: bool = True,
                 metric_ids: Optional[list[str]] = None, run_metrics: bool = True, client=None) -> dict[str, Any]:
    app = registry.AppConfig.from_target()
    records = records_from_report(report, app)
    graded = grade_records(records, app, use_llm, metric_ids, run_metrics, client)
    stamp = report.get("timestamp") or datetime.now(timezone.utc).isoformat()
    return {
        "run_id": report.get("run_id") or Path(report_name).stem,
        "report_name": report_name,
        "target_name": registry.target_config().get("target", {}).get("name", "Target"),
        "run_date": str(stamp)[:10],
        "tier": tier,
        "attack_type": report.get("attack_type"),
        "dataset_id": report.get("dataset_id"),
        "graded_at": datetime.now(timezone.utc).isoformat(),
        "run_name": report.get("run_name") or report.get("attack_type"),
        "converters": report.get("converters") or [],
        "judge": {"use_llm": use_llm, "metrics": metric_ids or ("default" if run_metrics else "scripts only")},
        "policy_versions": loader.versions(),
        **graded,
        "skipped": skipped_rows(report),
        "summaries": {},
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--target", required=True)
    ap.add_argument("--tier", choices=["low", "medium", "high"], default="medium")
    ap.add_argument("--canary", default=None)
    a = ap.parse_args()

    text = a.records.read_text(encoding="utf-8")
    records = [TestRecord(**json.loads(line)) for line in text.splitlines() if line.strip()]
    app = registry.AppConfig.from_target()
    # every answered record is graded, benign ones too: a refused normal question is a PB-2 finding
    graded = grade_records(records, app, canary=a.canary)
    canary_note = {"canary_checked": True} if a.canary else {}

    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps({
        "run_id": a.out.stem,
        "target_name": a.target,
        "run_date": date.today().isoformat(),
        "tier": a.tier,
        "policy_versions": loader.versions(),
        **canary_note,
        **graded,
        "summaries": {},   # reviewer fills one line per failure mode after review
    }, indent=1, ensure_ascii=False), encoding="utf-8")
    measured = sum(m["value"] is not None for m in graded["metrics"])
    print(f"{len(graded['verdicts'])} verdicts, {len(graded['not_run'])} not run, {measured} metrics measured -> {a.out}")


if __name__ == "__main__":
    main()
