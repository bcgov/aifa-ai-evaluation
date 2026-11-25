"""Re-query the live AIFA backend for every golden question, then judge the fresh answers.

Unlike `uat_judge` (which scores the *recorded* `chat_response` already in golden.jsonl),
this module sends each `query` to the live `BACKEND_API_URL` WebSocket target, captures the
response the chatbot actually returns *now*, and runs the same LLM + KB groundedness judge
on that fresh answer.

This module is intentionally self-contained: it talks WebSocket directly (no PyRIT dependency)
so it can run in a light Python environment.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import websockets

from aifa_pyrit.config import settings
from aifa_pyrit.evaluators.golden_prep import KNOWN_STEPS, clean_steps, write_rejects
from aifa_pyrit.evaluators.uat_judge import KB, DEFAULT_INPUT, Judge, OfflineJudge, deterministic

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "private" / "judge_results"

CLIENT_ID = "11111111-1111-4111-8111-111111111111"
APPLICATION_ID = 234554
ORIGIN = "https://train.j200.gov.bc.ca"


def extract_response(data: Any) -> Optional[str]:
    if isinstance(data, dict) and data.get("event") == "session_init":
        return None
    if isinstance(data, dict) and "response" in data:
        rl = data.get("response", [])
        if isinstance(rl, list) and rl:
            agg = rl[0]
            if isinstance(agg, dict):
                if "response" in agg:
                    return str(agg["response"]) or "(empty response)"
                if "original_results" in agg:
                    results = agg["original_results"]
                    if isinstance(results, list) and results:
                        return str(results[0].get("response", "(empty)"))
    if isinstance(data, dict) and "error" in data:
        return str(data["error"])
    return None


def build_frame(query: str, step: str, session_id: Optional[str] = None) -> str:
    """The exact text sent over the WebSocket: JSON, so spaces stay spaces (never '+')."""
    if step not in KNOWN_STEPS:
        raise ValueError(f"unknown step_number {step!r}; clean rows with golden_prep.clean_steps first")
    return json.dumps({
        "client_id": CLIENT_ID,
        "query": query,
        "step_number": step,
        "session_id": session_id or str(uuid.uuid4()),
        "application_id": APPLICATION_ID,
    }, ensure_ascii=False)


async def requery_one(endpoint: str, query: str, step: str, timeout: int = 120,
                      raw_log: Optional[Dict[str, Any]] = None) -> str:
    """raw_log, if given, receives the exact frame sent and every frame received (for bug reports)."""
    try:
        frame = build_frame(query, step)
        if raw_log is not None:
            raw_log.update(sent=frame, received=[])
        async with websockets.connect(
            endpoint,
            additional_headers={"Origin": ORIGIN},
            open_timeout=30,
            proxy=None,
        ) as ws:
            await ws.send(frame)
            for _ in range(10):
                raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
                if raw_log is not None:
                    raw_log["received"].append(raw if isinstance(raw, str) else raw.decode("utf-8", "replace"))
                text = extract_response(json.loads(raw))
                if text is not None:
                    return text
        return "INFRA_ERROR::NO_FINAL_RESPONSE"
    except Exception as exc:  # noqa: BLE001
        return f"INFRA_ERROR::{type(exc).__name__}: {exc}"


def _fresh_records(path: Path, rejects: Optional[Path] = None) -> List[Dict[str, Any]]:
    out = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        r = json.loads(line)
        out.append({
            "row": i,
            "id": r.get("id", ""),
            "session_id": r.get("session_id", ""),
            "query": r.get("query", ""),
            "step": r.get("step_number", ""),
            "reference_response": r.get("reference_response", ""),
        })
    kept, repairs, rejected = clean_steps(out)
    for fix in repairs:
        print(f"row {fix['row']}: step {fix['from'][:40]!r} -> {fix['to']} ({fix['why']})", file=sys.stderr)
    if rejected:
        write_rejects(rejected, rejects or OUT_DIR / "golden_rejects.jsonl")
        print(f"{len(rejected)} rows rejected (unknown step) -> {rejects or OUT_DIR / 'golden_rejects.jsonl'}", file=sys.stderr)
    return kept


async def run(records: List[Dict[str, Any]], judge, kb: KB, endpoint: str, concurrency: int, delay: float = 1.5) -> List[Dict[str, Any]]:
    sem = asyncio.Semaphore(concurrency)

    async def one(r: Dict[str, Any]) -> Dict[str, Any]:
        async with sem:
            await asyncio.sleep(delay)
            answer = await requery_one(endpoint, r["query"], r["step"])
            is_err = answer.startswith("INFRA_ERROR")
            if is_err:
                return {
                    "row": r["row"],
                    "id": r["id"],
                    "query": r["query"],
                    "answer": answer,
                    "step": r["step"],
                    "reference_response": r.get("reference_response", ""),
                    "deterministic": [],
                    "judge": {"verdict": "error", "notes": answer},
                    "kb_sources": [],
                }
            rec = {"query": r["query"], "answer": answer, "bot_context": ""}
            hits = kb.top(f"{r['query']} {answer[:300]}", k=4)
            det = deterministic(answer)
            j = await judge(rec, hits) if judge else {}
            return {
                "row": r["row"],
                "id": r["id"],
                "query": r["query"],
                "answer": answer,
                "step": r["step"],
                "reference_response": r.get("reference_response", ""),
                "deterministic": det,
                "judge": j if isinstance(j, dict) else {"verdict": "not_judged"},
                "kb_sources": sorted({n for n, _ in hits}),
            }

    results: List[Dict[str, Any]] = []
    for i in range(0, len(records), concurrency):
        results.extend(await asyncio.gather(*(one(r) for r in records[i : i + concurrency])))
    return results


def write_live(results: List[Dict[str, Any]], tag: str) -> Path:
    import csv

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    cp = OUT_DIR / f"uat_eval_{tag}_{ts}.csv"
    with open(cp, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["row", "step", "query", "fresh_answer", "reference_response", "verdict", "score", "correctness",
                    "unsupported_claims", "contradictions", "deterministic", "kb_sources", "notes"])
        for r in results:
            j = r["judge"]
            w.writerow([
                r["row"], r["step"], r["query"], r["answer"], r.get("reference_response", ""),
                j.get("verdict", ""), j.get("groundedness_score", ""), j.get("correctness", ""),
                json.dumps(j.get("unsupported_claims", []), ensure_ascii=False),
                json.dumps(j.get("contradictions", []), ensure_ascii=False),
                "; ".join(f"{d['type']}: {d['detail']}" for d in r["deterministic"]),
                "; ".join(r["kb_sources"]), j.get("notes", ""),
            ])
    return cp


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    ap.add_argument("--rows", default="", help="e.g. 5-20")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--delay", type=float, default=2.0, help="seconds between sends to avoid backend rate limiting")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--tag", default="live_requery")
    a = ap.parse_args()

    recs = _fresh_records(a.input)
    if a.rows:
        lo, hi = map(int, a.rows.split("-"))
        recs = [r for r in recs if lo <= r["row"] <= hi]
    if a.limit:
        recs = recs[: a.limit]

    endpoint = settings.backend_api_url
    if not endpoint:
        print("! BACKEND_API_URL not set")
        return 1

    kb = KB()
    print(f"records={len(recs)}  backend={endpoint}  kb_files={kb.files}")
    judge = None
    if a.offline:
        judge = OfflineJudge(kb)
    else:
        try:
            judge = Judge()
            print(f"judge deployment={judge.c['deployment']} endpoint={judge.c['endpoint']}")
        except ValueError as e:
            print(f"judge unavailable: {e} -> re-query only")

    res = asyncio.run(run(recs, judge, kb, endpoint, a.concurrency, a.delay))
    cp = write_live(res, a.tag)
    print("answers:", dict(Counter("error" if r["answer"].startswith("INFRA_ERROR") else "ok" for r in res)))
    print("verdict:", dict(Counter(r["judge"].get("verdict") for r in res)))
    print("det    :", dict(Counter(d["type"] for r in res for d in r["deterministic"])))
    print(f"wrote {cp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())