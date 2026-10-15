"""Flatten saved scan/run reports into a single CSV: one row per turn, across every case and attempt."""

from __future__ import annotations

import csv
import io
from typing import Any, Dict, Iterable, List, Tuple

from aifa_pyrit.run_manager import attempt_status, result_turns

COLUMNS = [
    "report", "run_id", "timestamp", "attack_type", "converters", "case_name", "attempt", "turn",
    "status", "outcome", "category", "transport_error", "expected_behavior", "original_prompt",
    "sent_prompt", "prompt_readable", "response", "error",
]
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        value = " -> ".join(str(v) for v in value)
    text = str(value)
    return "'" + text if text.startswith(FORMULA_PREFIXES) else text


def _case_entries(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    results = report.get("results")
    if isinstance(results, dict):
        return [{**report, "results": results}]
    return [entry for entry in results or [] if isinstance(entry, dict)]


def report_rows(name: str, report: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    base = {
        "report": name,
        "run_id": report.get("run_id"),
        "timestamp": report.get("timestamp") or report.get("scan_timestamp"),
        "attack_type": report.get("attack_type"),
    }
    for case in _case_entries(report):
        shared = {
            **base,
            "converters": case.get("converters", report.get("converters")),
            "case_name": case.get("case_name") or case.get("query"),
            "attempt": case.get("attempt", 1),
            "status": case.get("status") or attempt_status(case),
            "expected_behavior": case.get("expected_behavior") or report.get("expected_behavior"),
            "error": case.get("error"),
        }
        turns = result_turns(case)
        if not turns:
            yield {**shared, "original_prompt": case.get("query")}
        for index, turn in enumerate(turns, 1):
            yield {
                **shared,
                "turn": turn.get("turn", index),
                "outcome": turn.get("outcome"),
                "category": turn.get("category"),
                "transport_error": bool(turn.get("transport_error")),
                "original_prompt": turn.get("original_prompt") or turn.get("prompt"),
                "sent_prompt": turn.get("prompt"),
                "prompt_readable": turn.get("prompt_readable"),
                "response": turn.get("response"),
                "error": turn.get("error") or shared["error"],
            }


def reports_to_csv(reports: List[Tuple[str, Dict[str, Any]]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=COLUMNS, extrasaction="ignore", lineterminator="\r\n")
    writer.writeheader()
    for name, report in reports:
        for row in report_rows(name, report):
            writer.writerow({col: _cell(row.get(col)) for col in COLUMNS})
    return buffer.getvalue()
