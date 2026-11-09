"""Generate a Promptfoo-ready dataset from the WaterPermit workbook with Azure AI Search grounding.

Each record is converted into Promptfoo-compatible test variables that include the raw
question and the retrieved AI Search context used to ground the assertion. When the
search service is unavailable or returns no hits, the fallback context is explicit and
honest: "No relevant source documents found.".
"""

# Local run
# export HTTP_PROXY="http://127.0.0.1:8118"
# export HTTPS_PROXY="http://127.0.0.1:8118"
# export ALL_PROXY="http://127.0.0.1:8118"
# export NO_PROXY="localhost,127.0.0.1,::1"

# export AZURE_SEARCH_ENDPOINT="https://css-ai-dev-aisearch.search.windows.net"
# export AZURE_SEARCH_INDEX="rag-bc-waterpermit-dev"
# export AZURE_SEARCH_API_KEY="<your-key>"

# python data_promptfoo/build_golden.py --xlsx "WaterPermit.xlsx" --outdir data_promptfoo

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import openpyxl

try:
    import yaml
except Exception:  # pragma: no cover - yaml is available in project dependencies
    yaml = None

try:
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents import SearchClient
except Exception:  # pragma: no cover - keep the script importable when Azure libs are absent
    AzureKeyCredential = None
    SearchClient = None

FALLBACK_CONTEXT = "No relevant source documents found."


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


def normalize_search_endpoint(endpoint: str | None) -> str:
    """Return the service root for Azure AI Search, even if the env value includes /indexes/.../docs/search."""
    if not endpoint:
        return ""

    value = endpoint.strip().rstrip("/")
    if not value:
        return ""

    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        return value

    if parsed.path and "/indexes/" in parsed.path.lower():
        return f"{parsed.scheme}://{parsed.netloc}"
    return f"{parsed.scheme}://{parsed.netloc}"


def _search_settings() -> dict[str, str] | None:
    """Return the Azure AI Search configuration if present; otherwise None."""
    endpoint = (os.getenv("AZURE_SEARCH_ENDPOINT") or "").strip()
    api_key = (os.getenv("AZURE_SEARCH_API_KEY") or "").strip()
    index_name = (os.getenv("AZURE_SEARCH_INDEX") or os.getenv("AZURE_SEARCH_INDEX_NAME") or "").strip()

    if not endpoint or not api_key or not index_name:
        return None

    return {
        "endpoint": normalize_search_endpoint(endpoint),
        "api_key": api_key,
        "index_name": index_name,
    }


def _extract_search_result_text(result: Any) -> str:
    if isinstance(result, dict):
        for key in ("content", "text", "chunk", "body", "content_text", "summary", "description"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, list):
                joined = " ".join(str(item).strip() for item in value if str(item).strip())
                if joined:
                    return joined

        captions = result.get("@search.captions") or []
        if isinstance(captions, list):
            for caption in captions:
                text = caption.get("text") if isinstance(caption, dict) else str(caption)
                if text and str(text).strip():
                    return str(text).strip()

        for value in result.values():
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    if isinstance(result, str):
        return result.strip()
    return ""


def fetch_azure_search_context(query: str) -> str:
    """Fetch the top relevant snippet from Azure AI Search for a query.

    Missing env vars or unavailable search services are treated as a safe, explicit
    fallback so the generated Promptfoo cases remain valid and honest.
    """
    clean_query = _clean(query)
    if not clean_query:
        return FALLBACK_CONTEXT

    settings = _search_settings()
    if settings is None:
        return FALLBACK_CONTEXT

    if SearchClient is None or AzureKeyCredential is None:
        return FALLBACK_CONTEXT

    try:
        client = SearchClient(
            endpoint=settings["endpoint"],
            index_name=settings["index_name"],
            credential=AzureKeyCredential(settings["api_key"]),
        )
        results = client.search(search_text=clean_query, top=1)
        results_list = list(results)
        if not results_list:
            return FALLBACK_CONTEXT

        for result in results_list:
            text = _extract_search_result_text(result)
            if text:
                return text

        return FALLBACK_CONTEXT
    except Exception as exc:  # pragma: no cover - runtime environment may not have live Azure search
        print(f"Warning: Azure AI Search lookup failed for query '{clean_query[:80]}': {exc}", file=sys.stderr)
        return FALLBACK_CONTEXT


def build_promptfoo_case(record: dict[str, Any], azure_search_context: str | None = None) -> dict[str, Any]:
    """Build a Promptfoo case using the retrieved Azure AI Search evidence as the grounding context."""
    query = _clean(record.get("query"))
    step_number = _clean(record.get("step_number"))
    context = _clean(azure_search_context or FALLBACK_CONTEXT) or FALLBACK_CONTEXT

    rubric = (
        "Evaluate whether the application response is accurate, contextually grounded, and honest about missing information. "
        "Use the supplied azure_search_context as the only evidence source. The response should be supported by that context and by the current water-permit step. "
        "If the context is empty or unhelpful, the response must clearly say that the information is missing or uncertain instead of inventing details. "
        "Do not assume legal rules, fees, timelines, citations, eligibility requirements, or application steps that are not explicitly supported by the retrieved context. "
        "The response should be accurate, cautious, and clearly grounded in the available evidence.\n\n"
        "Query: {{query}}\n"
        "Step: {{step_number}}\n"
        "Retrieved AI Search context (evidence):\n"
        "{{azure_search_context}}"
    )

    vars_payload: dict[str, Any] = {
        "query": query,
        "step_number": step_number,
        "azure_search_context": context,
        "chat_response": _clean(record.get("chat_response")),
    }

    return {
        "description": f"{record.get('id', 'case')} [{step_number or 'unknown-step'}]",
        "vars": vars_payload,
        "assert": [{"type": "llm-rubric", "value": rubric}],
        "metadata": {
            "session_id": _clean(record.get("session_id")),
            "step_number": step_number,
            "chat_success": _clean(record.get("chat_success")),
            "application_id": _clean(record.get("metadata", {}).get("application_id")),
        },
    }


def build_promptfoo_suite(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Create the Promptfoo dynamic test suite structure, one test per workbook record."""
    tests: list[dict[str, Any]] = []

    for record in records:
        query = _clean(record.get("query"))
        if not query:
            continue

        context = fetch_azure_search_context(query)
        tests.append(build_promptfoo_case(record, azure_search_context=context))

    return {"tests": tests}


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
            "chat_payload": {"query": query, "step_number": step_number},
            "metadata": {
                "application_id": _clean(row_map.get("chat_application_id") or row_map.get("application_id")),
                "client_id": _clean(row_map.get("chat_client_id") or row_map.get("client_id")),
                "duration_ms": _clean(row_map.get("chat_duration_ms") or row_map.get("duration_ms")),
                "service_name": _clean(row_map.get("service_name") or row_map.get("service")),
                "cloud_role": _clean(row_map.get("cloud_role") or row_map.get("cloudrole")),
            },
            "chat_success": _clean(row_map.get("chat_success") or row_map.get("success")),
        }
        records.append(rec)

    outdir.mkdir(parents=True, exist_ok=True)

    jsonl = outdir / "golden.jsonl"
    with jsonl.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    promptfoo_suite = build_promptfoo_suite(records)
    yaml_path = outdir / "golden_tests.yaml"
    json_path = outdir / "golden_tests.json"

    if yaml is not None:
        yaml_path.write_text(
            yaml.safe_dump(promptfoo_suite, sort_keys=False, allow_unicode=True, default_flow_style=False),
            encoding="utf-8",
        )
    json_path.write_text(json.dumps(promptfoo_suite, indent=2, ensure_ascii=False), encoding="utf-8")

    summary = {
        "total_cases": len(records),
        "by_step_number": dict(sorted(Counter(r["step_number"] for r in records if r["step_number"]).items())),
        "by_chat_success": dict(sorted(Counter(r["chat_success"] for r in records if r["chat_success"]).items())),
        "has_response_text": sum(1 for r in records if r["chat_response"]),
        "avg_response_chars": round(
            sum(len(r["chat_response"]) for r in records if r["chat_response"]) / max(1, sum(1 for r in records if r["chat_response"])),
            2,
        ),
    }
    (outdir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"Wrote {len(records)} cases and Promptfoo suite:")
    print(f"  {jsonl}")
    print(f"  {yaml_path}")
    print(f"  {json_path}")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Convert the WaterPermit telemetry workbook into Promptfoo gold data grounded by Azure AI Search.")
    ap.add_argument("--xlsx", default="WaterPermit.xlsx", help="Path to the workbook to convert.")
    ap.add_argument("--outdir", default=str(Path(__file__).parent), help="Directory to write the generated Promptfoo suite.")
    args = ap.parse_args()
    build(Path(args.xlsx), Path(args.outdir))
