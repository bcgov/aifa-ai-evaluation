"""Background attack runs with live progress, used by the dashboard's New Run / Live Run pages."""

from __future__ import annotations

import asyncio
import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

FINAL_STATES = {"done", "stopped", "failed"}
ATTEMPT_DELAY_SECONDS = 1.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def result_turns(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    inner = result.get("results")
    turns = inner.get("turns", []) if isinstance(inner, dict) else inner if isinstance(inner, list) else []
    return [t for t in turns if isinstance(t, dict)]


def turn_verdict(turn: Dict[str, Any]) -> str:
    return str(turn.get("outcome") or "").rsplit(".", 1)[-1].lower()


def attempt_status(result: Dict[str, Any]) -> str:
    """fail = attack worked, pass = attack scored as not working, review = completed but unscored."""
    turns = result_turns(result)
    if result.get("error") or not turns or any(t.get("transport_error") or t.get("error") for t in turns):
        return "error"
    verdicts = {turn_verdict(t) for t in turns}
    if "success" in verdicts:
        return "fail"
    return "pass" if verdicts == {"failure"} else "review"


def case_status(statuses: List[str], running: bool) -> str:
    if running:
        return "running"
    if not statuses:
        return "queued"
    return next((state for state in ("fail", "error", "review") if state in statuses), "pass")


def transcript(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for index, turn in enumerate(result_turns(result), 1):
        sent = str(turn.get("prompt") or "")
        original = str(turn.get("original_prompt") or sent)
        readable = str(turn.get("prompt_readable") or sent)
        entries.append({
            "role": "attacker",
            "turn": index,
            "text": original,
            "converted": sent if sent != original else None,
            "readable": readable if readable != sent else None,
        })
        entries.append({"role": "target", "text": str(turn.get("response") or ""), "category": turn.get("category")})
        verdict = turn_verdict(turn)
        if verdict in {"success", "failure"} or turn.get("score") is not None:
            judged = "Attack achieved its objective." if verdict == "success" else "Attack did not achieve its objective."
            score = f" Score: {turn['score']}." if turn.get("score") is not None else ""
            entries.append({"role": "judge", "text": judged + score})
    if result.get("error"):
        entries.append({"role": "error", "text": str(result["error"])})
    return entries


@dataclass
class CaseState:
    id: str
    name: str
    query: str
    expected_behavior: Optional[str]
    attempts: List[Dict[str, Any]] = field(default_factory=list)
    running: bool = False


@dataclass
class Run:
    id: str
    name: str
    tenant_id: str
    dataset_id: Optional[str]
    attack_type: str
    repeats: int
    converters: List[str]
    test_source: str
    cases: List[CaseState]
    status: str = "queued"
    created_at: str = field(default_factory=_now)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    report_name: Optional[str] = None
    error: Optional[str] = None
    stop_requested: bool = False
    resume: threading.Event = field(default_factory=threading.Event)

    def case_view(self, case: CaseState) -> Dict[str, Any]:
        statuses = [a["status"] for a in case.attempts]
        return {
            "id": case.id,
            "name": case.name,
            "attack": self.attack_type,
            "repeat": f"{len(case.attempts)}/{self.repeats}",
            "turns": sum(len(result_turns(a["result"])) for a in case.attempts),
            "status": case_status(statuses, case.running),
        }

    def snapshot(self) -> Dict[str, Any]:
        cases = [self.case_view(c) for c in self.cases]
        attempts = [a["status"] for c in self.cases for a in c.attempts]
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "tenant_id": self.tenant_id,
            "dataset_id": self.dataset_id,
            "attack_type": self.attack_type,
            "repeats": self.repeats,
            "converters": self.converters,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "report_name": self.report_name,
            "error": self.error,
            "counts": {
                "total": len(self.cases),
                "done": sum(c["status"] not in {"queued", "running"} for c in cases),
                "attempts_total": len(self.cases) * self.repeats,
                "attempts_sent": len(attempts),
                "fail": attempts.count("fail"),
                "pass": attempts.count("pass"),
                "review": attempts.count("review"),
                "error": attempts.count("error"),
                "refused": 0,
            },
            "cases": cases,
        }

    def report(self) -> Dict[str, Any]:
        results = [
            {
                **attempt["result"],
                "case_name": case.name,
                "query": attempt["result"].get("query", case.query),
                "expected_behavior": case.expected_behavior,
                "attempt": attempt["attempt"],
                "status": attempt["status"],
            }
            for case in self.cases
            for attempt in case.attempts
        ]
        return {
            "report_type": "PyRIT",
            "run_id": self.id,
            "run_name": self.name,
            "timestamp": self.finished_at or _now(),
            "started_at": self.started_at,
            "status": self.status,
            "attack_type": self.attack_type,
            "converters": self.converters,
            "repeats": self.repeats,
            "tenant_id": self.tenant_id,
            "dataset_id": self.dataset_id,
            "test_source": self.test_source,
            "total_cases": len(self.cases),
            "results": results,
        }


class RunManager:
    """Runs one attack run at a time on a worker thread and exposes thread-safe snapshots."""

    def __init__(self, runner_factory: Callable[..., Any], save_report: Callable[[Dict[str, Any], str], Any]):
        self._runner_factory = runner_factory
        self._save_report = save_report
        self._runs: Dict[str, Run] = {}
        self._lock = threading.Lock()

    def active(self) -> Optional[Run]:
        return next((r for r in self._runs.values() if r.status not in FINAL_STATES), None)

    def start(
        self,
        *,
        name: str,
        tenant_id: str,
        dataset_id: Optional[str],
        attack_type: str,
        repeats: int,
        converters: List[str],
        test_cases: List[Dict[str, Any]],
        test_source: str,
        runner_kwargs: Optional[Dict[str, Any]] = None,
        background: bool = True,
    ) -> Run:
        with self._lock:
            if self.active():
                raise RuntimeError("Another run is still in progress. Stop it or wait for it to finish.")
            runner = self._runner_factory(converters=converters, **(runner_kwargs or {}))
            run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_") + secrets.token_hex(3)
            cases = [
                CaseState(
                    id=str(i),
                    name=str(c.get("name") or f"case_{i}"),
                    query=str(c.get("query") or ""),
                    expected_behavior=c.get("expected_behavior"),
                )
                for i, c in enumerate(test_cases, 1)
            ]
            run = Run(
                id=run_id, name=name, tenant_id=tenant_id, dataset_id=dataset_id, attack_type=attack_type,
                repeats=repeats, converters=list(getattr(runner, "converter_names", converters)),
                test_source=test_source, cases=cases,
            )
            run.resume.set()
            self._runs[run_id] = run
        work = lambda: asyncio.run(self._execute(run, runner))  # noqa: E731
        if background:
            threading.Thread(target=work, name=f"run-{run_id}", daemon=True).start()
        else:
            work()
        return run

    def get(self, run_id: str) -> Optional[Run]:
        return self._runs.get(run_id)

    def snapshot(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            run = self._runs.get(run_id)
            return run.snapshot() if run else None

    def list(self) -> List[Dict[str, Any]]:
        with self._lock:
            runs = sorted(self._runs.values(), key=lambda r: r.created_at, reverse=True)
            return [{k: v for k, v in r.snapshot().items() if k != "cases"} for r in runs]

    def case_detail(self, run_id: str, case_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            run = self._runs.get(run_id)
            case = next((c for c in run.cases if c.id == case_id), None) if run else None
            if case is None:
                return None
            return {
                **run.case_view(case),
                "query": case.query,
                "expected_behavior": case.expected_behavior,
                "converters": run.converters,
                "attempts": [
                    {"attempt": a["attempt"], "status": a["status"], "turns": transcript(a["result"])}
                    for a in case.attempts
                ],
            }

    def toggle_pause(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            run = self._runs.get(run_id)
            if run and run.status == "running":
                run.resume.clear()
                run.status = "paused"
            elif run and run.status == "paused":
                run.resume.set()
                run.status = "running"
        return self.snapshot(run_id)

    def stop(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            run = self._runs.get(run_id)
            if run and run.status not in FINAL_STATES:
                run.stop_requested = True
                run.status = "stopping"
                run.resume.set()
        return self.snapshot(run_id)

    def previous_failures(self, dataset_id: Optional[str]) -> Optional[List[str]]:
        with self._lock:
            done = [r for r in self._runs.values() if r.status in FINAL_STATES and r.dataset_id == dataset_id]
            if not done:
                return None
            latest = max(done, key=lambda r: r.created_at)
            return [c["name"] for c in map(latest.case_view, latest.cases) if c["status"] in {"fail", "error"}]

    async def _wait_if_paused(self, run: Run) -> None:
        while not run.resume.is_set():
            await asyncio.sleep(0.3)

    async def _execute(self, run: Run, runner: Any) -> None:
        with self._lock:
            run.status = "running"
            run.started_at = _now()
        try:
            for case in run.cases:
                test_case = {"name": case.name, "query": case.query, "expected_behavior": case.expected_behavior}
                for attempt in range(1, run.repeats + 1):
                    await self._wait_if_paused(run)
                    if run.stop_requested:
                        break
                    with self._lock:
                        case.running = True
                    try:
                        result = await runner.run_single_case(test_case, run.attack_type)
                    except Exception as exc:  # one failing attempt must not end the whole run
                        result = {"query": case.query, "error": str(exc)}
                    with self._lock:
                        case.attempts.append({"attempt": attempt, "status": attempt_status(result), "result": result})
                    if ATTEMPT_DELAY_SECONDS:
                        await asyncio.sleep(ATTEMPT_DELAY_SECONDS)
                with self._lock:
                    case.running = False
                if run.stop_requested:
                    break
            final = "stopped" if run.stop_requested else "done"
        except Exception as exc:
            final, run.error = "failed", str(exc)
        with self._lock:
            run.status = final
            run.finished_at = _now()
            for case in run.cases:
                case.running = False
        try:
            saved = self._save_report(run.report(), f"run_{run.id}.json")
            run.report_name = getattr(saved, "name", None) or str(saved)
        except Exception as exc:
            run.error = run.error or f"Run finished but the report could not be saved: {exc}"
