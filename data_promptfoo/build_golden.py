"""Generate a Promptfoo-ready golden dataset from the WaterPermit telemetry workbook.

This project expects Promptfoo test cases to post a request body with the canonical
fields used by the backend adapter:

  {"query": "...", "step_number": "..."}

The workbook contains raw Azure telemetry in columns such as `chat.query`,
`chat.step_number`, and `chat.response`. We flatten those into the Promptfoo payload
shape while preserving the original chat payload and response text in the generated
JSONL records for evaluation and auditing.

Usage:
  python build_golden.py --xlsx "WaterPermit.xlsx" [--outdir .]
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import openpyxl


def _clean(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    return str(v).strip()


def _normalize_header(v: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", _clean(v).lower()).strip("_")


def _find_response_value(obj: Any) -> str | None:
    if obj is None:
        return None
    if isinstance(obj, str):
        text = obj.strip()
        if text:
            return text
        return None
    if isinstance(obj, list):
        for item in obj:
            found = _find_response_value(item)
            if found:
                return found
        return None
    if isinstance(obj, dict):
        for key in ("response_message", "response", "message", "answer", "content", "text"):
            if key in obj:
                found = _find_response_value(obj[key])
                if found:
                    return found
        for value in obj.values():
            found = _find_response_value(value)
            if found:
                return found
    return None


def _extract_chat_response(raw: Any) -> str:
    text = _clean(raw)
    if not text:
        return ""

    if text.startswith("[") or text.startswith("{"):
        try:
            payload = ast.literal_eval(text)
            if isinstance(payload, (dict, list)):
                candidate = _find_response_value(payload)
                if candidate:
                    return candidate
        except (SyntaxError, ValueError):
            pass

        try:
            payload = json.loads(text)
            if isinstance(payload, (dict, list)):
                candidate = _find_response_value(payload)
                if candidate:
                    return candidate
        except json.JSONDecodeError:
            pass

    return text


def _find_header_row(rows: list[tuple[Any, ...]]) -> int:
    for idx, row in enumerate(rows):
        if not row:
            continue
        normalized = [_normalize_header(cell) for cell in row]
        if any(name in {"chatquery", "chatresponse", "query", "stepnumber", "chatstep_number"} for name in normalized):
            return idx
    return 1


def _case_id(row_map: dict[str, Any], fallback: int) -> str:
    session_id = _clean(row_map.get("chat_session_id") or row_map.get("session_id"))
    app_id = _clean(row_map.get("chat_application_id") or row_map.get("application_id"))
    query = _clean(row_map.get("chat_query") or row_map.get("query"))
    if session_id:
        return f"case-{session_id}"
    if app_id and app_id != "unknown":
        return f"case-{app_id}"
    if query:
        slug = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")
        if slug:
            return f"case-{slug[:60]}"
    return f"case-{fallback}"


def build(xlsx_path: Path, outdir: Path) -> None:
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise ValueError(f"Workbook {xlsx_path} has no rows.")

    header_idx = _find_header_row(rows)
    header_row = rows[header_idx]
    header_map: dict[str, int] = {}
    for idx, cell in enumerate(header_row):
        key = _normalize_header(cell)
        if key and key not in header_map:
            header_map[key] = idx

    records: list[dict[str, Any]] = []
    for row_num in range(header_idx + 1, len(rows)):
        row = rows[row_num]
        if not row or all(_clean(cell) == "" for cell in row):
            continue

        row_map: dict[str, Any] = {}
        for header_name, col_idx in header_map.items():
            if col_idx < len(row):
                row_map[header_name] = row[col_idx]

        query = _clean(row_map.get("chat_query") or row_map.get("query"))
        if not query:
            continue

        step_number = _clean(
            row_map.get("chat_step_number")
            or row_map.get("chat_stepnumber")
            or row_map.get("step_number")
            or row_map.get("stepnumber")
        )
        response_raw = row_map.get("chat_response") or row_map.get("response") or row_map.get("chat_response_value")
        response_text = _extract_chat_response(response_raw)
        rec = {
            "id": _case_id(row_map, len(records) + 1),
            "session_id": _clean(row_map.get("chat_session_id") or row_map.get("session_id")),
            "query": query,
            "step_number": step_number,
            "chat_response": response_text,
            "chat_payload": {
                "query": query,
                "step_number": step_number,
            },
            "reference_response": response_text,
            "raw_response": _clean(response_raw),
            "chat_success": _clean(row_map.get("chat_success") or row_map.get("success")),
            "metadata": {
                "application_id": _clean(row_map.get("chat_application_id") or row_map.get("application_id")),
                "client_id": _clean(row_map.get("chat_client_id") or row_map.get("client_id")),
                "duration_ms": _clean(row_map.get("chat_duration_ms") or row_map.get("duration_ms")),
                "service_name": _clean(row_map.get("service_name") or row_map.get("service")),
                "cloud_role": _clean(row_map.get("cloud_role") or row_map.get("cloudrole")),
            },
        }
        records.append(rec)

    outdir.mkdir(parents=True, exist_ok=True)

    jsonl = outdir / "golden.jsonl"
    with jsonl.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    tests: list[dict[str, Any]] = []
    for rec in records:
        rubric = (
            "There is no gold answer for this case. Judge the response only against the retrieved AI Search context "
            "and the step-specific BC water licence guidance available to the agent. The answer passes only if it is "
            "relevant to the user's question and the current form step, grounded in the retrieved context, and does not "
            "invent legal rules, application steps, fees, citations, or eligibility requirements that are not supported by that context. "
            "If the answer is uncertain or unsupported, it should say so and direct the user to the correct BC process, form field, or authoritative source instead of guessing. "
            "Do not treat the recorded chat response as a canonical answer or compare the model to a hidden gold answer."
        )
        if rec["step_number"]:
            rubric += f" This case is for step '{rec['step_number']}'."
        rubric += " Use the retrieved AI Search chunks as the evidence base for grading."

        test_vars = {
            "query": rec["query"],
            "step_number": rec["step_number"],
            "chat": {
                "query": rec["query"],
                "step_number": rec["step_number"],
            },
            "chat_response": rec["chat_response"],
            "reference_response": "",
            "ai_search_context": (
                "There is no gold answer for this case. Grade the response against the retrieved AI Search chunks "
                "and the current BC water licence step context only. The answer must be supported by that evidence, "
                "not by a hidden canonical answer."
            ),
        }
        tests.append(
            {
                "description": f"{rec['id']} [{rec['step_number'] or 'unknown-step'}]",
                "vars": test_vars,
                "assert": [{"type": "llm-rubric", "value": rubric}],
                "metadata": {
                    "session_id": rec["session_id"],
                    "step_number": rec["step_number"],
                    "chat_success": rec["chat_success"],
                    "application_id": rec["metadata"]["application_id"],
                },
            }
        )
    _dump_yaml(tests, outdir / "golden_tests.yaml")

    summary = {
        "total_cases": len(records),
        "by_step_number": dict(sorted(Counter(r["step_number"] for r in records if r["step_number"]).items())),
        "by_chat_success": dict(sorted(Counter(r["chat_success"] for r in records if r["chat_success"]).items())),
        "has_reference_response": sum(1 for r in records if r["chat_response"]),
        "avg_response_chars": round(
            sum(len(r["chat_response"]) for r in records if r["chat_response"]) / max(1, sum(1 for r in records if r["chat_response"])),
            2,
        ),
    }
    (outdir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"Wrote {len(records)} cases:")
    print(f"  {jsonl}")
    print(f"  {outdir / 'golden_tests.yaml'}")
    print(f"  {outdir / 'summary.json'}")
    print(json.dumps(summary, indent=2))


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    s = str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
    return '"' + s + '"'


def _dump_yaml(tests: list[dict[str, Any]], path: Path) -> None:
    lines: list[str] = [
        "# Auto-generated by build_golden.py from WaterPermit.xlsx",
        "",
    ]

    for test in tests:
        lines.append(f"- description: {_yaml_scalar(test['description'])}")
        lines.append("  vars:")
        for key, value in test["vars"].items():
            if isinstance(value, dict):
                lines.append(f"    {key}:")
                for inner_key, inner_value in value.items():
                    lines.append(f"      {inner_key}: {_yaml_scalar(inner_value)}")
            else:
                lines.append(f"    {key}: {_yaml_scalar(value)}")
        lines.append("  assert:")
        for item in test["assert"]:
            lines.append(f"    - type: {_yaml_scalar(item['type'])}")
            lines.append(f"      value: {_yaml_scalar(item['value'])}")
        lines.append("  metadata:")
        for key, value in test["metadata"].items():
            lines.append(f"    {key}: {_yaml_scalar(value)}")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Convert the WaterPermit telemetry workbook into Promptfoo gold data.")
    ap.add_argument("--xlsx", default="WaterPermit.xlsx", help="Path to the workbook to convert.")
    ap.add_argument("--outdir", default=str(Path(__file__).parent), help="Directory to write golden.jsonl and golden_tests.yaml.")
    args = ap.parse_args()
    build(Path(args.xlsx), Path(args.outdir))
