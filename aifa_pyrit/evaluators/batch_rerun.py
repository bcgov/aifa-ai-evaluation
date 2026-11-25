"""Rerun golden batch 1 against the live bot, then grade with the RTaaS judge.

Run inside the VNet (both the judge endpoint and the bot are private):

    python -m aifa_pyrit.evaluators.batch_rerun \
        --before private/judge_results/golden559_batches/golden559_batch_01.csv \
        --out rerun.json --csv batch1_comparison.csv --graded graded_batch1_rerun.json

Produces three files:
  --out      raw per-row data: the fresh answer, the reference answer, the verdict
  --csv      one row per question: old verdict vs new grade, expected/observed/fix. For people.
  --graded   a graded run in the dashboard's shape: drop it in the results store and it
             appears on Run Results and Findings.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from aifa_pyrit.config import settings
from aifa_pyrit.evaluators import golden_prep, live_requery, uat_judge
from aifa_pyrit.rtaas import llm, pipeline
from aifa_pyrit.rtaas.metrics import registry
from aifa_pyrit.rtaas.policy import loader


def _load_rows(golden: Path, last_row: int) -> list[dict]:
    rows = [r for r in uat_judge.load_records(golden) if r["row"] <= last_row]
    golden_prep.classify_leftovers(rows, lambda m: llm.chat(m, max_tokens=1200))
    return rows


async def fetch_answers(rows: list[dict], endpoint: str, concurrency: int, delay: float) -> dict[int, str]:
    sem = asyncio.Semaphore(concurrency)

    async def one(r: dict) -> tuple[int, str]:
        async with sem:
            await asyncio.sleep(delay)
            return r["row"], await live_requery.requery_one(endpoint, r["query"], r["step"])

    return dict(await asyncio.gather(*(one(r) for r in rows)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--golden", type=Path, default=uat_judge.DEFAULT_INPUT)
    ap.add_argument("--before", type=Path, help="the earlier batch results CSV (old verdict/score columns)")
    ap.add_argument("--rows", type=int, default=56, help="batch 1 = golden rows 1..56")
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--delay", type=float, default=2.0)
    ap.add_argument("--no-llm", action="store_true", help="grade with script checks only (no judge calls)")
    ap.add_argument("--script-metrics", action="store_true",
                    help="skip the LLM metrics (for local dry runs; the judge endpoint is private)")
    ap.add_argument("--answers", type=Path, help="reuse saved answers JSON instead of querying the bot")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--csv", type=Path, required=True)
    ap.add_argument("--graded", type=Path, required=True)
    a = ap.parse_args()

    endpoint = settings.backend_api_url
    if not endpoint and not a.answers:
        print("! BACKEND_API_URL not set")
        return 1

    rows = _load_rows(a.golden, a.rows)
    print(f"rows={len(rows)} backend={endpoint}")

    if a.answers:
        answers = {int(k): v for k, v in json.loads(a.answers.read_text(encoding="utf-8")).items()}
    else:
        answers = asyncio.run(fetch_answers(rows, endpoint, a.concurrency, a.delay))
    ok = sum(1 for v in answers.values() if not v.startswith("INFRA_ERROR"))
    print(f"answers: {ok} ok, {len(answers) - ok} infra errors")

    records = [golden_prep.to_record(r, answers.get(r["row"], "INFRA_ERROR::NO_ANSWER"),
                                     kb_passages=pipeline.kb_passages(r["query"], answers.get(r["row"], "")))
               for r in rows]
    app = registry.AppConfig.from_target()
    graded = pipeline.grade_records(records, app, use_llm=not a.no_llm,
                                    run_metrics=not a.script_metrics,
                                    metric_ids=pipeline.SCRIPT_METRICS if a.script_metrics else None)
    verdicts = {int(v["test_id"].removeprefix("batch_row")): v for v in graded["verdicts"]}

    before = {}
    if a.before and a.before.exists():
        before = {int(r["row"]): r for r in csv.DictReader(a.before.open(encoding="utf-8-sig"))}

    a.out.write_text(json.dumps({
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "rows": [{"row": r["row"], "step": r["step"], "query": r["query"],
                  "question_type": r.get("question_type"), "fresh_answer": answers.get(r["row"], ""),
                  "reference_response": r.get("reference_response", "")} for r in rows],
        "graded": graded,
    }, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"wrote {a.out}")

    with a.csv.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["row", "step", "question_type", "query", "old status", "old verdict", "old score",
                    "new grade", "confidence", "title", "reason", "expected", "observed (bot did)",
                    "suggested fix", "fix tags", "needs review", "fresh answer (first 200)", "reference answer (first 200)",
                    "kb sources"])
        kb_names = {rec.test_id: sorted({p.split("] ", 1)[0].lstrip("[") for p in rec.context if p.startswith("[")})
                    for rec in records}
        for r in rows:
            b, v = before.get(r["row"], {}), verdicts.get(r["row"], {})
            w.writerow([
                r["row"], r["step"], r.get("question_type", ""), r["query"],
                b.get("status", ""), b.get("verdict", ""), b.get("score", ""),
                v.get("grade", ""), v.get("confidence", ""), v.get("title", ""), v.get("reason", ""),
                v.get("expected", ""), v.get("observed", ""), v.get("dev_fix", ""),
                "; ".join([v.get("fix_tag", ""), *v.get("extra_fix_tags", [])]).strip("; "),
                "yes" if v.get("needs_review") else "",
                (answers.get(r["row"], "") or "")[:200].replace("\n", " "),
                (r.get("reference_response", "") or "")[:200].replace("\n", " "),
                "; ".join(kb_names.get(f"batch_row{r['row']}", [])),
            ])
    print(f"wrote {a.csv}")

    run = {
        "run_id": "golden_batch1_rerun",
        "report_name": a.graded.name,
        "target_name": registry.target_config().get("target", {}).get("name", "Target"),
        "run_date": datetime.now(timezone.utc).isoformat(),
        "tier": "medium",
        "attack_type": "Golden",
        "dataset_id": "golden:golden.jsonl",
        "graded_at": datetime.now(timezone.utc).isoformat(),
        "run_name": f"Batch 1 rerun · golden rows 1-{a.rows}",
        "converters": [],
        "judge": {"use_llm": not a.no_llm, "metrics": "default", "model": "gpt-5.2", "rubric": "v0.1"},
        "policy_versions": loader.versions(),
        **graded,
        "skipped": [],
        "summaries": {},
    }
    a.graded.write_text(json.dumps(run, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"wrote {a.graded}")

    print("grades :", dict(Counter(v["grade"] for v in verdicts.values())))
    if before:
        print("before :", dict(Counter(r.get("verdict", "?") for r in before.values())))
        print("status :", dict(Counter(r.get("status", "?") for r in before.values())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
