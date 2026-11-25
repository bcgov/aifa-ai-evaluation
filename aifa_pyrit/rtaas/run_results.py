"""Graded run JSON -> the Run Results screen's data shape (RunResults-v2 sampleRunData.js).

One result per case: the worst attempt sets the grade, `repeats` counts attempts that passed
(Pass or Low), failed calls are "Not run" (with `error`), missing test hooks are "Skipped"
(with `skip_reason`). Reviews are stored on the verdicts, so they survive reloads.
"""
from __future__ import annotations

import csv
import io
from collections import defaultdict
from typing import Any, Optional

from .judge import fix_tags
from .models import RANK, Grade, Verdict

GRADE_LABEL = {"pass": "Pass", "low": "Low", "medium": "Medium", "high": "High", "critical": "Critical"}
LABEL_GRADE = {v: k for k, v in GRADE_LABEL.items()}


def _case_of(v: dict) -> str:
    return v.get("case_name") or v["test_id"].split("#")[0]


def _area(tag: str) -> str:
    return fix_tags().get(tag, {}).get("area", "none")


def _worst_turn(turns: list[dict], highlight: str) -> tuple[int, dict, dict]:
    """(1-based exchange number, user turn, bot turn) of the exchange that holds the highlight, else the last."""
    pairs = [(turns[i], turns[i + 1]) for i in range(len(turns) - 1)
             if turns[i]["role"] == "user" and turns[i + 1]["role"] == "assistant"]
    for n, (u, b) in enumerate(pairs, 1):
        if highlight and highlight in b["content"]:
            return n, u, b
    return (len(pairs), *pairs[-1]) if pairs else (1, {}, {})


def build_run(graded: dict) -> dict[str, Any]:
    records = {r["test_id"]: r for r in graded.get("records") or []}
    verdicts: dict[str, list[dict]] = defaultdict(list)
    for v in graded.get("verdicts") or []:
        verdicts[_case_of(v)].append(v)
    not_run: dict[str, list[dict]] = defaultdict(list)
    for n in graded.get("not_run") or []:
        not_run[n.get("case_name") or n["test_id"].split("#")[0]].append(n)

    order = list(dict.fromkeys([*verdicts, *not_run]))
    results = []
    for case in order:
        vs, nr = verdicts.get(case, []), not_run.get(case, [])
        base = {"id": case, "name": case, "repeats": {"passed": 0, "total": len(vs) + len(nr)}}
        if not vs:
            first = nr[0]
            rec = records.get(first["test_id"], {})
            results.append({**base, "title": "No answer received", "failure_mode": first.get("failure_mode"),
                            "attack_type": _attack(rec, graded), "question_type": rec.get("question_type"),
                            "converters": rec.get("converters") or [], "grade": "Not run", "confidence": None,
                            "error": first.get("error"), "turns": 0})
            continue
        worst = max(vs, key=lambda v: RANK[Grade(v["grade"])])
        rec = records.get(worst["test_id"], {})
        turns = rec.get("turns") or [{"role": "user", "content": rec.get("input", worst.get("input") or "")},
                                     {"role": "assistant", "content": rec.get("answer", worst.get("output") or "")}]
        wt, user, bot = _worst_turn(turns, worst.get("highlight") or "")
        tag = worst.get("fix_tag") or "none"
        fix = worst.get("dev_fix") if worst.get("dev_fix") not in (None, "", "none") else ""
        results.append({
            **base,
            "title": worst.get("title") or ("No problem found" if worst["grade"] in ("pass", "low") else worst["reason"][:60]),
            "failure_mode": worst["failure_mode"],
            "attack_type": _attack(rec, graded),
            "question_type": rec.get("question_type"),
            "converters": rec.get("converters") or graded.get("converters") or [],
            "grade": GRADE_LABEL[worst["grade"]],
            "critical": worst["grade"] == "critical",
            "confidence": worst.get("confidence"),
            "repeats": {"passed": sum(v["grade"] in ("pass", "low") for v in vs), "total": len(vs) + len(nr)},
            "turns": max(1, len([t for t in turns if t["role"] == "assistant"])),
            "worst_turn": wt,
            "expected": worst.get("expected") or "",
            "observed": worst.get("observed") or "",
            "reason": worst.get("reason") or "",
            "fix_tag": tag,
            "extra_fix_tags": worst.get("extra_fix_tags") or [],
            "fix_area": _area(tag) if fix else "none",
            "fix": fix,
            "flags": [{"check": f["check"], "evidence": f["reason"]} for f in worst.get("script_findings") or []],
            "exchange": {"user": user.get("content", ""), "bot": bot.get("content", ""),
                         "highlight": worst.get("highlight") or ""},
            "transcript": turns,
            "needs_review": any(v.get("needs_review") and not v.get("reviewed") for v in vs),
            "review": _review_state(vs),
            "graded_by": worst.get("graded_by"),
        })
    for s in graded.get("skipped") or []:
        results.append({"id": s["case_name"], "name": s["case_name"], "title": "Needs a test hook we don't have yet",
                        "failure_mode": s.get("failure_mode"), "attack_type": graded.get("attack_type"),
                        "grade": "Skipped", "skip_reason": s.get("skip_reason"), "confidence": None,
                        "repeats": None, "turns": 0})
    return {
        "id": graded.get("report_name") or graded["run_id"],
        "name": graded.get("run_name") or graded["run_id"],
        "meta": _meta(graded, len(results)),
        "report_name": graded.get("report_name"),
        "graded_at": graded.get("graded_at"),
        "fix_rollup": {},
        "dev_fixes": graded.get("dev_fixes") or [],
        "unmapped": graded.get("unmapped") or [],
        "results": results,
    }


def _attack(rec: dict, graded: dict) -> Optional[str]:
    technique = rec.get("technique") or graded.get("attack_type")
    return None if technique in (None, "Golden") else technique


def _review_state(vs: list[dict]) -> Optional[dict]:
    done = [v for v in vs if v.get("reviewed")]
    if not done:
        return None
    v = max(done, key=lambda v: RANK[Grade(v["grade"])])
    changed = v.get("judge_grade") and v["judge_grade"] != v["grade"]
    return {"critical": v["grade"] == "critical", "grade": GRADE_LABEL[v["grade"]] if changed else None,
            "agreed": not changed, "note": v.get("reviewer_note")}


def _meta(graded: dict, n: int) -> str:
    bits = [graded.get("target_name") or "", graded.get("attack_type") or "", f"{n} cases",
            f"graded {str(graded.get('graded_at') or '')[:16].replace('T', ' ')}",
            "rules " + "/".join(sorted(set((graded.get("policy_versions") or {}).values())))]
    return " · ".join(b for b in bits if b and not b.endswith(" "))


def apply_review(graded: dict, case: str, patch: dict) -> int:
    """Store a person's review on every attempt of one case. Returns how many verdicts changed.

    agreed: confirm the judge. grade: Pass/Low/Medium/High (keeps judge_grade). critical: set Critical.
    """
    changed = 0
    for v in graded.get("verdicts") or []:
        if _case_of(v) != case:
            continue
        if v.get("judge_grade") is None:
            v["judge_grade"] = v["grade"]
        if patch.get("critical"):
            v["grade"] = "critical"
        elif patch.get("grade"):
            new = LABEL_GRADE.get(patch["grade"])
            if new is None or new == "critical":
                raise ValueError("grade must be Pass, Low, Medium or High")
            v["grade"] = new
        v["reviewed"] = True
        if patch.get("note"):
            v["reviewer_note"] = str(patch["note"])[:500]
        Verdict(**v)  # still a valid verdict
        changed += 1
    return changed


CSV_COLUMNS = ["id", "grade", "failure_mode", "attack_type", "question_type", "title", "confidence", "repeats",
               "expected", "observed", "reason", "fix_area", "fix_tag", "fix", "needs_review", "error", "skip_reason"]


def to_csv(run: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_COLUMNS)
    for r in run["results"]:
        rep = r.get("repeats")
        w.writerow([r.get("id"), r.get("grade"), r.get("failure_mode"), r.get("attack_type") or "", r.get("question_type") or "",
                    r.get("title"), r.get("confidence"), f"{rep['passed']}/{rep['total']}" if rep else "",
                    r.get("expected", ""), r.get("observed", ""), r.get("reason", ""), r.get("fix_area", ""),
                    r.get("fix_tag", ""), r.get("fix", ""), r.get("needs_review", ""), r.get("error", ""), r.get("skip_reason", "")])
    return buf.getvalue()
