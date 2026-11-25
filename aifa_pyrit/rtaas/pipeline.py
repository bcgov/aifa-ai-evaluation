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
import re
from collections import defaultdict
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from . import judge
from .metrics import registry, runner
from .models import TestRecord, TurnRecord
from .policy import loader

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
    from aifa_pyrit.evaluators.uat_judge import KB

    return KB()


def kb_passages(query: str, answer: str = "", k: int = 4) -> list[str]:
    try:
        return [chunk for _, chunk in _kb().top(f"{query} {answer[:300]}", k=k)]
    except Exception:  # noqa: BLE001  (no KB on this machine)
        return []


def _turns(result: dict) -> list[dict]:
    inner = result.get("results")
    turns = inner.get("turns", []) if isinstance(inner, dict) else inner if isinstance(inner, list) else []
    return [t for t in turns if isinstance(t, dict)]


def _bad(text: str) -> bool:
    return not text.strip() or text.startswith("INFRA_ERROR")


def records_from_report(report: dict, app: Optional[registry.AppConfig] = None) -> list[TestRecord]:
    app = app or registry.AppConfig.from_target()
    technique = report.get("attack_type") or "PromptSending"
    records: list[TestRecord] = []
    for i, res in enumerate(report.get("results") or [], 1):
        if not isinstance(res, dict):
            continue
        meta = res.get("case_meta") or {}
        name = res.get("case_name") or meta.get("name") or f"case_{i}"
        turns_raw = _turns(res)
        turns: list[TurnRecord] = []
        for t in turns_raw:
            prompt = str(t.get("original_prompt") or t.get("prompt") or "")
            reply = str(t.get("response") or "")
            if prompt:
                turns.append(TurnRecord(role="user", content=prompt))
            if reply:
                turns.append(TurnRecord(role="assistant", content=reply))
        last_user = next((t.content for t in reversed(turns) if t.role == "user"), res.get("query", ""))
        last_reply = next((t.content for t in reversed(turns) if t.role == "assistant"), "")
        error = res.get("error") or next((t.get("error") for t in turns_raw if t.get("error") or t.get("transport_error")), None)
        valid = not error and not _bad(last_reply)
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
                      "attempt": res.get("attempt", 1)},
            valid=valid,
            error=str(error)[:300] if error else (None if valid else "empty or INFRA_ERROR reply"),
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


def grade_records(records: list[TestRecord], app: registry.AppConfig, use_llm: bool = True,
                  metric_ids: Optional[list[str]] = None, run_metrics: bool = True, client=None) -> dict[str, Any]:
    canary = registry.target_config().get("checks", {}).get("canary", {}).get("value", "")
    canary = None if not canary or canary.startswith("<FILL") else canary
    verdicts = [judge.grade(r, app.allow_list, canary, client=client, kb_passages=r.context, use_llm=use_llm)
                for r in records]
    metrics = runner.run_all(records, app, metric_ids=metric_ids) if run_metrics else \
        runner.run_all(records, app, metric_ids=["link_safety", "no_over_refusal", "calc_sanity", "exact_values"])
    return {"verdicts": [v.model_dump(mode="json") for v in verdicts],
            "metrics": [m.model_dump(mode="json") for m in metrics]}


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
        "judge": {"use_llm": use_llm, "metrics": metric_ids or ("all" if run_metrics else "scripts only")},
        "policy_versions": loader.versions(),
        **graded,
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

    records = [TestRecord(**json.loads(line)) for line in a.records.read_text().splitlines() if line.strip()]
    app = registry.AppConfig.from_target()

    attack = [r for r in records if r.set == "attack"]
    verdicts = [judge.grade(r, app.allow_list, a.canary) for r in attack]
    metrics = runner.run_all(records, app)

    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps({
        "run_id": a.out.stem,
        "target_name": a.target,
        "run_date": date.today().isoformat(),
        "tier": a.tier,
        "policy_versions": loader.versions(),
        "verdicts": [v.model_dump(mode="json") for v in verdicts],
        "metrics": [m.model_dump(mode="json") for m in metrics],
        "summaries": {},   # reviewer fills one line per failure mode after review
    }, indent=1, ensure_ascii=False))
    print(f"{len(verdicts)} verdicts, {sum(m.value is not None for m in metrics)} metrics measured -> {a.out}")


if __name__ == "__main__":
    main()
