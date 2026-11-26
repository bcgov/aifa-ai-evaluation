from __future__ import annotations

import asyncio
import json
import os
import re
import httpx
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from aifa_pyrit.config import settings
from aifa_pyrit.csv_export import reports_to_csv
from aifa_pyrit import datasets
from aifa_pyrit.logging_utils import setup_logger
from aifa_pyrit.orchestrator import RedTeamOrchestrator
from aifa_pyrit.pyrit_runner import PyRITRunner
from aifa_pyrit.run_manager import RunManager
from aifa_pyrit.storage import get_report_store

logger = setup_logger("aifa_pyrit.web_app")

BASE_DIR = Path(__file__).resolve().parents[1]
RESULTS_DIR = BASE_DIR / "results"
RESULTS_DIR.mkdir(exist_ok=True, parents=True)
FRONTEND_DIR = BASE_DIR / "frontend"
REPORT_STORE = get_report_store()
PROMPTFOO_SCRIPT = BASE_DIR / "promptfoo" / "run_promptfoo_eval.sh"
PROMPTFOO_RESULT = BASE_DIR / "results-promptfoo" / "promptfoo-report.json"
PROMPTFOO_RUN_TOKEN = os.getenv("PROMPTFOO_RUN_TOKEN")
PROMPTFOO_LOCK = asyncio.Lock()

AttackType = Literal["PromptSending", "Crescendo", "MultiTurn", "RedTeaming", "TAP", "PromptSeed"]


def resolve_runtime_port() -> int:
    value = os.getenv("PORT", "8000")
    try:
        return int(value)
    except (TypeError, ValueError):
        return 8000


class RunScanRequest(BaseModel):
    attack_type: AttackType = "PromptSending"
    use_file: bool = True
    cases: str | None = None
    query: str | None = Field(default=None, max_length=20000)
    expected_behavior: str | None = Field(default=None, max_length=4000)
    threat_models: str | None = None
    converters: list[str] | None = None
    max_iterations: int = Field(default_factory=lambda: settings.red_team_max_iterations)
    evaluate: bool = True
    evaluate_llm: bool = True


class RunSeedAttackRequest(BaseModel):
    datasets: str | None = None
    limit_seeds: int | None = None
    verbose: bool = False


class StartRunRequest(BaseModel):
    mode: Literal["pyrit-scan"] = "pyrit-scan"
    tenant_id: str
    attack_type: AttackType = "PromptSending"
    repeats: int = Field(default=1, ge=1, le=20)
    converters: list[str] = Field(default_factory=list, max_length=6)
    dataset_id: str | None = None
    only_failed: bool = False
    questions: list[str] | None = Field(default=None, max_length=50)
    name: str | None = Field(default=None, max_length=200)


class ExportRequest(BaseModel):
    reports: list[str] = Field(default_factory=list, max_length=1000)
    all: bool = False


class GenerateTestCasesRequest(BaseModel):
    count: int = Field(default=12, ge=1, le=60)
    categories: list[str] | None = None
    use_llm: bool = True
    save_to_data: bool = True


class EvaluateReportRequest(BaseModel):
    use_llm: bool = True
    save_copy: bool = True


DEFAULT_DATASET_ID = datasets.DEFAULT_DATASET_ID
REPORT_NAME_PATTERN = re.compile(r"^[\w.-]+\.json$")
EXPORTABLE_PREFIXES = ("run_", "scan_")
TENANTS = [{"id": "aifa-water-licence", "name": "AI Forms Assist — Water Licence Application"}]


def _tenants() -> list[dict[str, Any]]:
    return [{**t, "approved": bool(settings.backend_api_url)} for t in TENANTS]


def _save_report(report: dict[str, Any], filename: str | None = None) -> Path:
    RESULTS_DIR.mkdir(exist_ok=True, parents=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    if filename is None:
        filename = f"report_{timestamp}.json"

    if REPORT_STORE and REPORT_STORE.__class__.__name__ == "AzureBlobReportStore":
        REPORT_STORE.save_report(report, filename)
        return Path(filename)

    path = RESULTS_DIR / filename
    with path.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    return path


def _load_cases(case_names: str | None = None, dataset_id: str | None = None) -> list[dict[str, Any]]:
    if dataset_id is None:
        all_cases = RedTeamOrchestrator.load_test_cases()
    else:
        try:
            all_cases = datasets.load_dataset(dataset_id)
        except datasets.DatasetUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=400, detail="Unknown or invalid test-case dataset.") from exc
    if not all_cases:
        raise HTTPException(status_code=400, detail="No test cases loaded. Check the test-case source or choose Custom query.")

    if case_names:
        allowed = {name.strip() for name in case_names.split(",") if name.strip()}
        missing = allowed - {case.get("name") for case in all_cases}
        if not allowed or missing:
            raise HTTPException(status_code=400, detail=f"Unknown or empty case filter: {', '.join(sorted(missing))}")
        return [case for case in all_cases if case.get("name") in allowed]

    return all_cases


def _normalized_turns(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        turns = value.get("turns", [])
        if isinstance(turns, list):
            return [entry for entry in turns if isinstance(entry, dict)]
        return []
    if isinstance(value, list):
        return [entry for entry in value if isinstance(entry, dict)]
    return []


def _summarize_report(report: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(report, dict):
        return {"attack_type": None, "seed_datasets": [], "total_turns": 0, "turn_count": 0, "status": "error"}

    results = report.get("results", {})
    if isinstance(results, dict):
        turns = _normalized_turns(results)
        total_turns = results.get("total_turns", len(turns))
        case_count = 1 if turns or results else 0
    elif isinstance(results, list):
        turns = []
        for item in results:
            if isinstance(item, dict):
                turns.extend(_normalized_turns(item.get("results", {})))
        total_turns = len(turns)
        case_count = len([item for item in results if isinstance(item, dict)])
    else:
        turns = []
        total_turns = 0
        case_count = 0

    case_errors = sum(bool(item.get("error")) for item in results if isinstance(item, dict)) if isinstance(results, list) else 0
    error_count = int(bool(report.get("error"))) + case_errors
    successful_turns = 0
    completed_turns = 0
    unscored_turns = 0
    outcome_counts: dict[str, int] = {}
    for item in turns:
        outcome = str(item.get("outcome") or item.get("status") or "unknown")
        outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1
        verdict = outcome.rsplit(".", 1)[-1].lower()
        if "error" in verdict or item.get("transport_error") or item.get("error"):
            error_count += 1
        else:
            completed_turns += 1
            successful_turns += int(verdict == "success")
            unscored_turns += int(verdict not in {"success", "failure"})

    eval_summary = report.get("evaluation_summary") or {}
    return {
        "attack_type": report.get("attack_type"),
        "seed_datasets": report.get("seed_datasets", []),
        "total_turns": total_turns,
        "turn_count": len(turns),
        "successful_turns": successful_turns,
        "completed_turns": completed_turns,
        "unscored_turns": unscored_turns,
        "security_verdict": "review_required" if completed_turns > unscored_turns else "not_assessed",
        "error_count": error_count,
        "total_cases": case_count,
        "outcome_counts": outcome_counts,
        "evaluated": bool(eval_summary),
        "judge_verdicts": eval_summary.get("verdict_counts", {}),
        "status": "error" if error_count else "ok",
    }


def _report_insights(report: dict[str, Any]) -> dict[str, Any]:
    summary = _summarize_report(report)
    raw_results = report.get("results", [])
    if isinstance(raw_results, dict):
        case_entries = [raw_results]
    elif isinstance(raw_results, list):
        case_entries = [entry for entry in raw_results if isinstance(entry, dict)]
    else:
        case_entries = []

    attack_breakdown: dict[str, dict[str, Any]] = {}
    outcome_distribution: dict[str, dict[str, Any]] = {}
    execution_timeline: list[dict[str, Any]] = []
    case_drilldown: list[dict[str, Any]] = []

    for idx, item in enumerate(case_entries, start=1):
        attack_name = str(item.get("attack_type") or report.get("attack_type") or "unknown")
        attack_entry = attack_breakdown.setdefault(attack_name, {"name": attack_name, "count": 0, "queries": []})
        attack_entry["count"] += 1
        query = str(item.get("query") or item.get("prompt") or "").strip()
        if query:
            attack_entry["queries"].append(query)

        case_turns = _normalized_turns(item.get("results", {}))
        if case_turns:
            for turn in case_turns[:3]:
                outcome_name = str(turn.get("outcome") or turn.get("status") or "unknown")
                entry = outcome_distribution.setdefault(outcome_name, {"name": outcome_name, "count": 0})
                entry["count"] = entry.get("count", 0) + 1

            latest_turn = case_turns[0]
            response_preview = str(latest_turn.get("response") or "").strip()
            prompt_preview = str(latest_turn.get("prompt") or query or "").strip()
        else:
            response_preview = ""
            prompt_preview = query

        execution_timeline.append({
            "step": idx,
            "query": query,
            "attack_type": attack_name,
            "turn_count": len(case_turns),
            "outcome": str(case_turns[0].get("outcome") if case_turns else "unknown").upper(),
            "prompt": prompt_preview[:180],
            "response": response_preview[:220],
        })

        case_drilldown.append({
            "attack_type": attack_name,
            "query": query,
            "turn_count": len(case_turns),
            "response_preview": response_preview[:220],
        })

    timeline = execution_timeline[:12]
    return {
        "summary": {
            **summary,
            "total_cases": len(case_entries) or summary.get("total_cases", 0),
        },
        "timeline": timeline,
        "execution_timeline": timeline,
        "attack_breakdown": sorted(attack_breakdown.values(), key=lambda item: item["count"], reverse=True),
        "outcome_distribution": sorted(outcome_distribution.values(), key=lambda item: item["count"], reverse=True),
        "case_drilldown": case_drilldown,
        "report_metadata": {
            "attack_type": report.get("attack_type"),
            "timestamp": report.get("timestamp"),
            "threat_models": report.get("threat_models", []),
            "seed_datasets": report.get("seed_datasets", []),
        },
    }


app = FastAPI(
    title="NR AI Red Team Browser",
    description="Browser-based runner for PyRIT red-team evaluations and JSON report viewing.",
    version="0.1.0",
)
GRADED_PREFIX = "rtaas_"


def _graded_name(report_name: str) -> str:
    return report_name if report_name.startswith(GRADED_PREFIX) else GRADED_PREFIX + report_name


def _grade_and_save(report: dict[str, Any], report_name: str, use_llm: bool = True) -> str:
    """Grade one saved run with the RTaaS judge and save it next to the raw report."""
    from aifa_pyrit.rtaas import pipeline as rtaas_pipeline

    graded = rtaas_pipeline.grade_report(report, report_name, use_llm=use_llm)
    name = _graded_name(report_name)
    _save_report(graded, filename=name)
    return name


RUNS = RunManager(
    runner_factory=lambda **kwargs: PyRITRunner(
        threat_models=[m.strip() for m in settings.red_team_threat_models.split(",") if m.strip()],
        max_iterations=settings.red_team_max_iterations,
        verbose=True,
        **kwargs,
    ),
    save_report=lambda report, filename: _save_report(report, filename=filename),
    grade_report=_grade_and_save,
)


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "results_dir": str(RESULTS_DIR),
        "reports": [p.name for p in sorted(RESULTS_DIR.glob("*.json"))],
    }


@app.get("/api/reports")
async def list_reports() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if REPORT_STORE is not None and REPORT_STORE.__class__.__name__ == "AzureBlobReportStore":
        stored_items = REPORT_STORE.list_reports()
        if stored_items:
            return stored_items

    for path in sorted(RESULTS_DIR.glob("*.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            items.append(
                {
                    "name": path.name,
                    "updated_at": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
                    "summary": _summarize_report(data),
                    "size": path.stat().st_size,
                }
            )
        except Exception:
            items.append({
                "name": path.name,
                "updated_at": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
                "summary": {"status": "unreadable"},
                "size": path.stat().st_size,
            })
    return items


@app.get("/api/reports/summary")
async def report_summary() -> dict[str, Any]:
    reports = await list_reports()
    total = len(reports)
    success = sum(1 for item in reports if str(item.get("summary", {}).get("status", "")).lower() == "ok")
    unreadable = sum(1 for item in reports if str(item.get("summary", {}).get("status", "")).lower() == "unreadable")
    error = sum(1 for item in reports if str(item.get("summary", {}).get("status", "")).lower() not in {"ok", "unreadable"})
    last_updated = max((item.get("updated_at") for item in reports), default=None)

    return {
        "total_reports": total,
        "successful_reports": success,
        "error_reports": error,
        "unreadable_reports": unreadable,
        "last_updated": last_updated,
    }


@app.get("/api/reports/{report_name}")
async def get_report(report_name: str) -> dict[str, Any]:
    if REPORT_STORE is not None and REPORT_STORE.__class__.__name__ == "AzureBlobReportStore":
        try:
            return REPORT_STORE.get_report(report_name)
        except Exception:
            pass

    path = RESULTS_DIR / report_name
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Report not found")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON report: {exc}") from exc


@app.get("/api/reports/{report_name}/insights")
async def get_report_insights(report_name: str) -> dict[str, Any]:
    # Try Azure-backed store first (if configured), then fall back to local results dir
    if REPORT_STORE is not None and REPORT_STORE.__class__.__name__ == "AzureBlobReportStore":
        try:
            data = REPORT_STORE.get_report(report_name)
            return _report_insights(data)
        except Exception:
            # fall through to local file lookup
            pass

    path = RESULTS_DIR / report_name
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Report not found")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON report: {exc}") from exc
    return _report_insights(data)


@app.get("/api/converters")
async def list_converters() -> list[str]:
    from aifa_pyrit.converters import available_converters
    return available_converters()


@app.get("/api/tenants")
async def list_tenants() -> list[dict[str, Any]]:
    return _tenants()


@app.get("/api/datasets", responses={503: {"description": "Dataset storage unavailable"}})
async def list_datasets() -> list[dict[str, Any]]:
    try:
        return await asyncio.to_thread(datasets.list_datasets)
    except datasets.DatasetUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/golden-cases")
async def golden_cases(search: str = "", limit: int = 50, offset: int = 0) -> dict[str, Any]:
    rows = datasets.load_golden_cases(search=search)
    return {"total": len(rows), "offset": offset, "cases": rows[offset : offset + limit]}


@app.post("/api/generate-test-cases")
async def generate_test_cases(request: GenerateTestCasesRequest) -> dict[str, Any]:
    from aifa_pyrit.test_generator import generate_kb_test_cases

    try:
        payload = await generate_kb_test_cases(
            count=request.count,
            categories=request.categories,
            use_llm=request.use_llm,
            save_to_data=request.save_to_data,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "success", **payload}


@app.post("/api/reports/{report_name}/evaluate")
async def evaluate_report(report_name: str, request: EvaluateReportRequest) -> dict[str, Any]:
    report = await get_report(report_name)
    from aifa_pyrit.evaluators.pipeline import EvaluationPipeline

    stamped = await EvaluationPipeline(use_llm=request.use_llm).stamp_report(report)
    saved_name = report_name
    if request.save_copy:
        saved_name = f"eval_{report_name}"
        _save_report(stamped, filename=saved_name)
    return {
        "status": "success",
        "report_name": saved_name,
        "evaluation_summary": stamped.get("evaluation_summary", {}),
    }


@app.get("/api/findings")
async def findings(limit: int = 100) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    report_summaries: list[dict[str, Any]] = []
    for meta in await list_reports():
        try:
            report = await get_report(meta["name"])
        except Exception:
            continue
        eval_summary = report.get("evaluation_summary")
        if not eval_summary:
            continue
        report_summaries.append({"report": meta["name"], **eval_summary})
        results = report.get("results")
        cases = results if isinstance(results, list) else [report]
        for case in cases:
            if not isinstance(case, dict):
                continue
            inner = case.get("results") if isinstance(case.get("results"), dict) else {}
            for turn in _normalized_turns(inner):
                ev = turn.get("evaluation") or {}
                verdict = ev.get("verdict") or turn.get("judge_verdict")
                if verdict and verdict != "PASS":
                    items.append({
                        "report": meta["name"],
                        "case": case.get("case_name") or case.get("name") or "",
                        "verdict": verdict,
                        "severity": ev.get("severity") or turn.get("severity"),
                        "risk_class": ev.get("risk_class") or turn.get("risk_class"),
                        "explanation": ev.get("explanation") or turn.get("judge_explanation"),
                        "query": str(turn.get("original_prompt") or turn.get("prompt") or case.get("query") or "")[:300],
                        "response": str(turn.get("response") or "")[:300],
                        "presidio": ev.get("presidio"),
                    })
    return {
        "evaluated_reports": len(report_summaries),
        "report_summaries": report_summaries,
        "findings": items[:limit],
    }


def _previous_failed_cases(dataset_id: str | None) -> list[str]:
    failed = RUNS.previous_failures(dataset_id)
    if failed is None:
        for path in sorted(RESULTS_DIR.glob("run_*.json"), reverse=True):
            try:
                report = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if report.get("dataset_id") == dataset_id:
                failed = sorted({r["case_name"] for r in report.get("results", []) if r.get("status") in {"fail", "error"}})
                break
    if failed is None:
        raise HTTPException(status_code=400, detail="No earlier run of this dataset found, so there are no failed cases to re-run.")
    if not failed:
        raise HTTPException(status_code=400, detail="Nothing failed in the last run of this dataset.")
    return failed


@app.post("/api/runs", responses={
    400: {"description": "Invalid dataset or run request"},
    409: {"description": "Run already active"},
    503: {"description": "Dataset storage unavailable"},
})
async def start_run(request: StartRunRequest) -> dict[str, Any]:
    tenant = next((t for t in _tenants() if t["id"] == request.tenant_id), None)
    if tenant is None or not tenant["approved"]:
        raise HTTPException(status_code=400, detail="This system is not approved for testing.")

    if request.questions is not None:
        questions = [q.strip() for q in request.questions if q.strip()]
        if not questions or any(len(q) > 20000 for q in questions):
            raise HTTPException(status_code=400, detail="Enter at least one question (each under 20,000 characters).")
        test_cases = [{"name": f"custom_{i}", "query": q} for i, q in enumerate(questions, 1)]
        source, dataset_id = "custom_query", None
    else:
        if not request.dataset_id:
            raise HTTPException(status_code=400, detail="Unknown dataset.")
        failed = _previous_failed_cases(request.dataset_id) if request.only_failed else None
        test_cases = await asyncio.to_thread(_load_cases, ",".join(failed) if failed else None, request.dataset_id)
        source, dataset_id = "saved_cases", request.dataset_id

    name = request.name or f"{tenant['name']} · {request.attack_type}"
    try:
        run = RUNS.start(
            name=name, tenant_id=tenant["id"], dataset_id=dataset_id, attack_type=request.attack_type,
            repeats=request.repeats, converters=request.converters, test_cases=test_cases, test_source=source,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"id": run.id}


@app.get("/api/runs")
async def list_runs() -> list[dict[str, Any]]:
    return RUNS.list()


def _run_or_404(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Run not found. Runs are kept in memory until the server restarts; saved reports remain on the Export page.")
    return snapshot


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    return _run_or_404(RUNS.snapshot(run_id))


@app.get("/api/runs/{run_id}/cases/{case_id}")
async def get_run_case(run_id: str, case_id: str) -> dict[str, Any]:
    return _run_or_404(RUNS.case_detail(run_id, case_id))


@app.post("/api/runs/{run_id}/pause")
async def pause_run(run_id: str) -> dict[str, Any]:
    return _run_or_404(RUNS.toggle_pause(run_id))


@app.post("/api/runs/{run_id}/stop")
async def stop_run(run_id: str) -> dict[str, Any]:
    return _run_or_404(RUNS.stop(run_id))


@app.post("/api/export/csv")
async def export_csv(request: ExportRequest) -> Response:
    if request.all:
        names = [r["name"] for r in await list_reports() if str(r.get("name", "")).startswith(EXPORTABLE_PREFIXES)]
    else:
        names = list(dict.fromkeys(request.reports))
    if not names:
        raise HTTPException(status_code=400, detail="Choose at least one report to export.")
    if any(not REPORT_NAME_PATTERN.match(n) for n in names):
        raise HTTPException(status_code=400, detail="Invalid report name.")
    reports = [(n, await get_report(n)) for n in names]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return Response(
        content="\ufeff" + reports_to_csv(reports),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="red_team_export_{stamp}.csv"'},
    )


# ---------------------------------------------------------------- RTaaS: graded runs, findings, policy

class ReviewRequest(BaseModel):
    case: str = Field(min_length=1, max_length=300)
    agreed: bool = False
    grade: Literal["Pass", "Low", "Medium", "High"] | None = None
    critical: bool = False
    note: str | None = Field(default=None, max_length=500)


class GradeRequest(BaseModel):
    use_llm: bool = True


class RerunRequest(BaseModel):
    case: str | None = Field(default=None, max_length=300)
    failed_only: bool = False


def _valid_name(name: str) -> str:
    if not REPORT_NAME_PATTERN.match(name):
        raise HTTPException(status_code=400, detail="Invalid report name.")
    return name


async def _graded(name: str) -> dict[str, Any]:
    report = await get_report(_valid_name(_graded_name(name)))
    if "verdicts" not in report:
        raise HTTPException(status_code=404, detail="Not a graded run.")
    return report


_RUN_TS = re.compile(r"_(\d{8}_\d{6})_")


def _graded_ts(name: str) -> str:
    m = _RUN_TS.search(name)
    return m.group(1) if m else ""


async def _graded_names() -> list[str]:
    names = [r["name"] for r in await list_reports() if str(r.get("name", "")).startswith(GRADED_PREFIX)]
    return sorted(names, key=lambda n: (_graded_ts(n), n), reverse=True)


@app.get("/api/policy")
async def policy() -> dict[str, Any]:
    """catalog + crosswalk + tiers for Policy Mapping, and {id: [name, principle]} for Run Results."""
    from aifa_pyrit.rtaas.findings import policy_payload
    from aifa_pyrit.rtaas.policy import loader as policy_loader

    principles = {p["code"]: p["name"] for p in policy_loader.catalog()["principles"]}
    return {**policy_payload(), "versions": policy_loader.versions(),
            "failure_modes": {fid: [f["name"], principles[f["principle"]]] for fid, f in policy_loader.failure_modes().items()}}


@app.get("/api/run-results")
async def run_results_list(limit: int = 20) -> dict[str, Any]:
    from aifa_pyrit.rtaas import run_results

    graded = await _graded_names()
    runs = []
    for name in graded[: max(1, min(limit, 50))]:
        try:
            runs.append(run_results.build_run(await get_report(name)))
        except Exception as exc:  # one bad file must not hide the rest
            logger.warning("skipping graded run %s: %s", name, exc)
    done = {n.removeprefix(GRADED_PREFIX) for n in graded}
    ungraded = [r["name"] for r in await list_reports()
                if str(r.get("name", "")).startswith(EXPORTABLE_PREFIXES) and r["name"] not in done]
    return {"runs": runs, "ungraded": ungraded[:50]}


@app.get("/api/run-results/{name}")
async def run_results_one(name: str) -> dict[str, Any]:
    from aifa_pyrit.rtaas import run_results

    return run_results.build_run(await _graded(name))


@app.post("/api/run-results/{report_name}/grade")
async def grade_saved_report(report_name: str, request: GradeRequest) -> dict[str, Any]:
    from aifa_pyrit.rtaas import run_results

    report = await get_report(_valid_name(report_name))
    if "verdicts" in report:
        raise HTTPException(status_code=400, detail="This file is already graded.")
    name = await asyncio.to_thread(_grade_and_save, report, report_name, request.use_llm)
    return run_results.build_run(await get_report(name))


@app.post("/api/run-results/{name}/review")
async def review_case(name: str, request: ReviewRequest) -> dict[str, Any]:
    from aifa_pyrit.rtaas import run_results

    graded = await _graded(name)
    try:
        changed = run_results.apply_review(graded, request.case, request.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not changed:
        raise HTTPException(status_code=404, detail="No graded answers for that case.")
    _save_report(graded, filename=_graded_name(name))
    return {"changed": changed, "result": next(r for r in run_results.build_run(graded)["results"] if r["id"] == request.case)}


@app.post("/api/run-results/{name}/rerun")
async def rerun_cases(name: str, request: RerunRequest) -> dict[str, Any]:
    from aifa_pyrit.rtaas import run_results

    graded = await _graded(name)
    if not graded.get("dataset_id"):
        raise HTTPException(status_code=400, detail="Only runs started from a saved dataset can be re-run from here.")
    results = run_results.build_run(graded)["results"]
    if request.case:
        cases = [request.case]
    else:
        cases = [r["id"] for r in results if r["grade"] in {"Medium", "High", "Critical", "Not run"}]
    if not cases:
        raise HTTPException(status_code=400, detail="Nothing to re-run.")
    test_cases = await asyncio.to_thread(_load_cases, ",".join(cases), graded["dataset_id"])
    tenant = _tenants()[0]
    try:
        run = RUNS.start(name=f"Re-run · {graded.get('run_name') or name}", tenant_id=tenant["id"],
                         dataset_id=graded["dataset_id"], attack_type=graded.get("attack_type") or "PromptSending",
                         repeats=1, converters=list(graded.get("converters") or []), test_cases=test_cases,
                         test_source="saved_cases")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"id": run.id, "cases": len(test_cases)}


@app.get("/api/run-results/{name}/download")
async def download_run(name: str, format: Literal["json", "csv", "html"] = "json", kind: Literal["exec", "dev"] = "exec") -> Response:
    from aifa_pyrit.rtaas import run_results

    graded = await _graded(name)
    stem = _graded_name(name).removesuffix(".json")
    if format == "json":
        return Response(json.dumps(graded, indent=1, ensure_ascii=False), media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{stem}.json"'})
    if format == "csv":
        return Response("\ufeff" + run_results.to_csv(run_results.build_run(graded)), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{stem}.csv"'})
    return Response(_report_html(graded, kind), media_type="text/html; charset=utf-8")


def _findings(graded: dict[str, Any]):
    from aifa_pyrit.rtaas import service

    return service.findings_for(graded["run_id"], load=lambda _id: graded)


def _report_html(graded: dict[str, Any], kind: str) -> str:
    from aifa_pyrit.rtaas.export import pdf as rtaas_export

    f, verdicts = _findings(graded)
    return rtaas_export.render_html(kind, f, verdicts, graded)


@app.get("/api/rtaas/findings")
async def rtaas_findings(run: str = "latest") -> dict[str, Any]:
    """Findings for one graded run. run=demo serves the sample run (marked demo); run=latest the newest."""
    from aifa_pyrit.rtaas import service

    if run == "demo":
        f, _ = service.findings_for("demo")
    else:
        if run == "latest":
            names = await _graded_names()
            if not names:
                from aifa_pyrit.rtaas import findings as rtaas_findings

                return rtaas_findings.empty_findings().model_dump(mode="json")
            run = names[0]
        f, _ = _findings(await _graded(run))
    return f.model_dump(mode="json")


@app.get("/api/rtaas/report")
async def rtaas_report(run: str = "demo", kind: Literal["exec", "dev"] = "exec") -> Response:
    """Printable HTML report (exec: one page, dev: two pages). Use the browser's Print > Save as PDF."""
    from aifa_pyrit.rtaas import service
    from aifa_pyrit.rtaas.export import pdf as rtaas_export

    if run == "demo":
        f, verdicts = service.findings_for("demo")
        return Response(rtaas_export.render_html(kind, f, verdicts, service.get_run("demo")),
                        media_type="text/html; charset=utf-8")
    return Response(_report_html(await _graded(run), kind), media_type="text/html; charset=utf-8")


@app.get("/api/dev-fixes/{name}")
async def dev_fixes(name: str) -> list[dict[str, Any]]:
    return (await _graded(name)).get("dev_fixes") or []


@app.post("/api/run-scan")
async def run_scan(request: RunScanRequest) -> dict[str, Any]:
    models = [m.strip() for m in (request.threat_models or settings.red_team_threat_models).split(",") if m.strip()]
    try:
        runner = PyRITRunner(
            threat_models=models,
            max_iterations=request.max_iterations,
            verbose=True,
            converters=request.converters,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if request.use_file:
        if request.query:
            raise HTTPException(status_code=400, detail="Choose Custom query to run the supplied query.")
        test_cases = _load_cases(request.cases)
    else:
        if not request.query or not request.query.strip():
            raise HTTPException(status_code=400, detail="Enter a custom query. No default question will be substituted.")
        test_cases = [{"name": "custom_query", "query": request.query, "expected_behavior": request.expected_behavior}]

    if not test_cases:
        raise HTTPException(status_code=400, detail="No test cases available to run.")

    results = await asyncio.to_thread(
        lambda: asyncio.run(runner.scan_test_cases(test_cases, attack_type=request.attack_type))
    )

    report = {
        "report_type": "PyRIT",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "attack_type": request.attack_type,
        "converters": list(runner.converter_names),
        "threat_models": models,
        "test_source": "saved_cases" if request.use_file else "custom_query",
        "expected_behavior": request.expected_behavior,
        **runner.results,
    }
    if request.evaluate:
        try:
            from aifa_pyrit.evaluators.pipeline import EvaluationPipeline

            report = await EvaluationPipeline(use_llm=request.evaluate_llm).stamp_report(report)
        except Exception:
            logger.exception("auto_evaluation_failed")
    report_path = _save_report(report, filename=f"scan_{request.attack_type.lower()}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json")

    summary = _summarize_report(report)
    return {
        "status": "error" if summary["status"] == "error" else "success",
        "report_name": report_path.name,
        "report_path": str(report_path),
        "summary": summary,
        "results": results,
    }


@app.post("/api/run-seed-attack")
async def run_seed_attack(request: RunSeedAttackRequest) -> dict[str, Any]:
    runner = PyRITRunner(verbose=request.verbose)
    selected = None
    if request.datasets:
        if request.datasets.lower() == "all":
            selected = list(runner.available_seed_datasets.keys())
        else:
            selected = [d.strip() for d in request.datasets.split(",") if d.strip()]

    result = await asyncio.to_thread(
        lambda: asyncio.run(
            runner.run_attack_seed(seed_datasets=selected, limit_seeds=request.limit_seeds)
        )
    )

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    report_path = _save_report(result, filename=f"seed_attack_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json")
    return {
        "status": "success",
        "report_name": report_path.name,
        "report_path": str(report_path),
        "summary": _summarize_report(result),
        "result": result,
    }


@app.post("/api/run-promptfoo")
async def run_promptfoo(request: Request) -> dict[str, Any]:
    logger.info("api_run_promptfoo_start headers=%s content_type=%s", dict(request.headers), request.headers.get("content-type"))
    # Optional token-based auth: set PROMPTFOO_RUN_TOKEN env var to require X-Run-Token header
    if PROMPTFOO_RUN_TOKEN:
        header = request.headers.get("x-run-token")
        if not header or header != PROMPTFOO_RUN_TOKEN:
            logger.warning("api_run_promptfoo_unauthorized")
            raise HTTPException(status_code=401, detail="Unauthorized")

    # Run the promptfoo orchestration script and collect the produced report
    if not PROMPTFOO_SCRIPT.exists():
        # If the runner script is not present (for example Promptfoo runs
        # in a separate container), try calling the Promptfoo container's
        # HTTP `/run` endpoint. The container listens on `PORT` 8001 by
        # convention; allow overriding via `PROMPTFOO_CONTAINER_RUN_URL`.
        run_url = os.getenv("PROMPTFOO_CONTAINER_RUN_URL", "http://127.0.0.1:8001/run")
        headers = {}
        if PROMPTFOO_RUN_TOKEN:
            headers["x-run-token"] = PROMPTFOO_RUN_TOKEN
        try:
            resp = httpx.post(run_url, timeout=900.0, headers=headers)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Promptfoo runner not found and container run failed: {exc}") from exc

        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=f"Promptfoo container run failed: {resp.text[:500]}")

        try:
            payload = resp.json()
        except Exception:
            raise HTTPException(status_code=500, detail="Promptfoo container returned non-JSON response")

        # If the container returned the report inline, save it locally so
        # the rest of the API can read it the same way as the local runner.
        report = None
        if isinstance(payload, dict):
            report = payload.get("report") or payload.get("data")
            if payload.get("status") == "success_with_warnings" and payload.get("raw"):
                # save raw text
                PROMPTFOO_RESULT.parent.mkdir(exist_ok=True, parents=True)
                PROMPTFOO_RESULT.write_text(str(payload.get("raw")), encoding="utf-8")
                return {"status": "success_with_warnings", "report_name": PROMPTFOO_RESULT.name, "summary": {"status": "unreadable"}}

        if report is not None:
            try:
                PROMPTFOO_RESULT.parent.mkdir(exist_ok=True, parents=True)
                PROMPTFOO_RESULT.write_text(json.dumps(report, indent=2), encoding="utf-8")
            except Exception:
                pass
            return {"status": "success", "report_name": PROMPTFOO_RESULT.name, "summary": _summarize_report(report)}

        raise HTTPException(status_code=500, detail="Promptfoo did not produce a report via container run")

    # Ensure results-promptfoo dir exists
    PROMPTFOO_RESULT.parent.mkdir(exist_ok=True, parents=True)

    async with PROMPTFOO_LOCK:
        proc = await asyncio.create_subprocess_exec(
            str(PROMPTFOO_SCRIPT),
            cwd=str(PROMPTFOO_SCRIPT.parent),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=900)
            stdout_text = stdout.decode(errors="replace")[:2000]
            stderr_text = stderr.decode(errors="replace")[:2000]
            logger.info(
                "api_run_promptfoo_process_finished returncode=%s stdout_preview=%s stderr_preview=%s",
                proc.returncode,
                stdout_text,
                stderr_text,
            )
            if proc.returncode != 0 and not PROMPTFOO_RESULT.exists():
                logger.error("api_run_promptfoo_nonzero_exit_without_result returncode=%s stderr_preview=%s", proc.returncode, stderr_text)
                raise HTTPException(status_code=500, detail=f"Promptfoo failed: {stderr_text[:500]}")
        except asyncio.TimeoutError:
            proc.kill()
            logger.exception("api_run_promptfoo_process_timeout")
            raise HTTPException(status_code=504, detail="Promptfoo run timed out")

    if not PROMPTFOO_RESULT.exists():
        raise HTTPException(status_code=500, detail="Promptfoo did not produce a result file")

    try:
        data = json.loads(PROMPTFOO_RESULT.read_text(encoding='utf-8'))
    except Exception as exc:
        # If the JSON is invalid but the file exists, return a readable error
        # message and include the raw text so the frontend can show partial
        # information instead of failing entirely.
        raw = PROMPTFOO_RESULT.read_text(encoding='utf-8', errors='replace')
        return {
            "status": "success_with_warnings",
            "report_name": PROMPTFOO_RESULT.name,
            "summary": {"status": "unreadable"},
            "raw": raw[:10000],
            "stderr": stderr_text,
        }

    # Optionally store in the report store
    if REPORT_STORE and REPORT_STORE.__class__.__name__ == "AzureBlobReportStore":
        try:
            REPORT_STORE.save_report(data, PROMPTFOO_RESULT.name)
        except Exception:
            pass

    resp = {"status": "success", "report_name": PROMPTFOO_RESULT.name, "summary": _summarize_report(data)}
    if proc.returncode != 0:
        resp["status"] = "success_with_warnings"
        resp["stderr"] = stderr_text
    return resp


# Local dev only: in containers nginx routes /api/promptfoo/* straight to the promptfoo service.
PROMPTFOO_SERVICE_URL = os.getenv("PROMPTFOO_SERVICE_URL", "http://127.0.0.1:8001").rstrip("/")


@app.api_route("/api/promptfoo/{path:path}", methods=["GET", "POST"])
async def promptfoo_dev_proxy(path: str, request: Request) -> Response:
    headers = {"content-type": request.headers.get("content-type", "application/json")}
    if PROMPTFOO_RUN_TOKEN:
        headers["x-run-token"] = PROMPTFOO_RUN_TOKEN
    try:
        # trust_env=False: a developer SOCKS proxy (ALL_PROXY) must not intercept this local call.
        async with httpx.AsyncClient(timeout=120.0, trust_env=False) as client:
            upstream = await client.request(
                request.method, f"{PROMPTFOO_SERVICE_URL}/api/promptfoo/{path}",
                params=request.query_params, content=await request.body(), headers=headers,
            )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Promptfoo service unreachable at {PROMPTFOO_SERVICE_URL}: {exc}") from exc
    passthrough = {k: v for k, v in upstream.headers.items() if k.lower() in {"content-type", "content-disposition"}}
    return Response(content=upstream.content, status_code=upstream.status_code, headers=passthrough)


if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


def main() -> None:
    import uvicorn

    uvicorn.run("aifa_pyrit.web_app:app", host="0.0.0.0", port=resolve_runtime_port(), reload=True)


if __name__ == "__main__":
    main()
