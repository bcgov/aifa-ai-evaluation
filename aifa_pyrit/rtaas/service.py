"""Loads graded runs and builds Findings. The HTTP routes live in aifa_pyrit/web_app.py.

run_id "demo" serves rtaas/sample_run.json so the frontend works before any real graded run exists.
Real graded runs are JSON documents saved next to the PyRIT reports (rtaas_<report>.json).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Optional

from .findings import build_findings, policy_payload  # noqa: F401  (re-exported for the API)
from .metrics import registry
from .models import FindingsResponse, MetricResult, Verdict

SAMPLE = Path(__file__).parent / "sample_run.json"
RunLoader = Callable[[str], dict]


def get_run(run_id: str, load: Optional[RunLoader] = None) -> dict:
    if run_id == "demo" or load is None:
        return json.loads(SAMPLE.read_text(encoding="utf-8"))
    return load(run_id)


def metrics_for(run: dict) -> list[MetricResult]:
    """Real runs store metric results. Demo builds preview rows from placeholder values."""
    if "metrics" in run:
        return [MetricResult(**m) for m in run["metrics"]]
    pv = run.get("preview_metric_values", {})
    out = []
    for m in registry.spec()["metrics"]:
        out.append(MetricResult(
            id=m["id"], tab=m["tab"], label=m["label"], deepeval_class=registry.display_class(m),
            failure_mode=m["failure_mode"], target=m["target"], threshold=m.get("threshold"),
            value=pv.get(m["id"]), preview=True, blocks_release=registry.blocks(m),
            report_only=bool(m.get("report_only")), gate_group=m.get("gate_group"),
        ))
    return out


def findings_for(run_id: str, load: Optional[RunLoader] = None) -> tuple[FindingsResponse, list[Verdict]]:
    run = get_run(run_id, load)
    verdicts = [Verdict(**v) for v in run["verdicts"]]
    f = build_findings(run_id=run["run_id"], target_name=run["target_name"], run_date=run["run_date"],
                       tier=run["tier"], verdicts=verdicts, metrics=metrics_for(run),
                       summaries=run.get("summaries"), report_name=run.get("report_name"),
                       demo=run_id == "demo" or "preview_metric_values" in run,
                       policy_versions=run.get("policy_versions"))
    return f, verdicts
