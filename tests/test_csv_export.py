import csv
import io

import pytest
from fastapi import HTTPException

from aifa_pyrit import web_app
from aifa_pyrit.csv_export import reports_to_csv


def rows_of(csv_text):
    return list(csv.DictReader(io.StringIO(csv_text.lstrip("\ufeff"))))


def test_one_csv_contains_every_case_attempt_and_turn():
    report = {
        "attack_type": "PromptSending",
        "converters": ["base64"],
        "run_id": "run_1",
        "timestamp": "2026-10-13T00:00:00+00:00",
        "results": [
            {
                "case_name": "france", "attempt": 1, "status": "fail", "query": "capital?",
                "results": {"turns": [
                    {"original_prompt": "capital?", "prompt": "Y2FwaXRhbD8=", "response": "Paris.", "outcome": "AttackOutcome.SUCCESS"},
                ]},
            },
            {"case_name": "pii", "attempt": 2, "status": "pass",
             "results": {"turns": [{"outcome": "AttackOutcome.FAILURE", "score": 0.0}]}},
        ],
    }
    rows = rows_of(reports_to_csv([("scan_x.json", report)]))
    assert len(rows) == 2
    assert [r["case_name"] for r in rows] == ["france", "pii"]
    assert [r["attempt"] for r in rows] == ["1", "2"]
    assert rows[0]["sent_prompt"] == "Y2FwaXRhbD8="
    assert rows[0]["original_prompt"] == "capital?"
    assert rows[0]["status"] == "fail"
    assert rows[0]["converters"] == "base64"
    assert rows[1]["status"] == "pass"


def test_export_is_one_file_even_for_multiple_reports():
    reports = [
        ("run_a.json", {"attack_type": "PromptSending", "results": [{"case_name": "c1", "results": {"turns": [{"outcome": "AttackOutcome.UNDETERMINED"}]}}]}),
        ("run_b.json", {"attack_type": "Crescendo", "results": [{"case_name": "c2", "results": {"turns": [{"outcome": "AttackOutcome.SUCCESS"}, {"outcome": "AttackOutcome.SUCCESS"}]}}]}),
    ]
    rows = rows_of(reports_to_csv(reports))
    assert len(rows) == 3
    assert {r["report"] for r in rows} == {"run_a.json", "run_b.json"}


def test_cells_with_csv_and_formula_characters_are_quoted_safely():
    report = {
        "attack_type": "PromptSending",
        "results": [{"case_name": "c", "results": {"turns": [
            {"response": 'Has "quotes", commas\nand =SUM(A1) formulas', "outcome": "AttackOutcome.UNDETERMINED"},
        ]}}],
    }
    text = reports_to_csv([("r.json", report)])
    assert '"quotes"' in text  # csv module quotes the cell
    rows = rows_of(text)
    assert rows[0]["response"] == 'Has "quotes", commas\nand =SUM(A1) formulas'


def test_formula_injection_is_prefixed():
    report = {
        "attack_type": "PromptSending",
        "results": [{"case_name": "=cmd", "query": "+2+2", "results": {"turns": [{"prompt": "@evil", "response": "=1+1", "outcome": "x"}]}}],
    }
    rows = rows_of(reports_to_csv([("r.json", report)]))
    row = rows[0]
    assert row["case_name"] == "'=cmd"
    assert row["original_prompt"] == "'@evil"  # turn prompt wins over the case-level query
    assert row["response"] == "'=1+1"


def test_case_without_turns_still_exports_one_row():
    report = {"attack_type": "PromptSending", "results": [{"case_name": "broken", "query": "q", "error": "boom"}]}
    rows = rows_of(reports_to_csv([("r.json", report)]))
    assert len(rows) == 1
    assert rows[0]["error"] == "boom"
    assert rows[0]["original_prompt"] == "q"


@pytest.mark.asyncio
async def test_export_endpoint_rejects_bad_names(monkeypatch):
    request = web_app.ExportRequest(reports=["../secrets.json"])
    with pytest.raises(HTTPException) as error:
        await web_app.export_csv(request)
    assert error.value.status_code == 400


@pytest.mark.asyncio
async def test_export_endpoint_rejects_empty_selection():
    with pytest.raises(HTTPException) as error:
        await web_app.export_csv(web_app.ExportRequest())
    assert error.value.status_code == 400
