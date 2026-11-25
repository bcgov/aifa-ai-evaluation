"""Executive and developer reports, matching design/executive-summary.pdf (one
page, no EU/NIST/OWASP section) and design/developer-report.pdf (two pages).

HTML template (Jinja2) -> PDF with headless Chromium (Playwright). Chromium is
used because it prints the same CSS the dashboard uses; WeasyPrint also works
if Chromium can't be installed on the App Service.

    pip install playwright && playwright install chromium
"""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..judge import fix_tags
from ..models import FindingsResponse, Grade, Verdict
from ..policy import loader
from ..scoring import (
    count_by_failure_mode, failure_mode_stats, headline, index, principle_index, principle_scores,
    run_health,
)

TEMPLATES = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html"]),
)

# fix_tags.yaml area -> the layer name the reports use
LAYER_LABELS = {
    "system_prompt": "Conversation policy",
    "output_filter": "Output guard",
    "retrieval": "Retrieval (RAG)",
    "tool_guardrail": "Tool / action authorisation",
    "kb_content": "KB content",
    "harness": "Harness (our side)",
    "judge": "Judge (our side)",
    "none": "–",
}

# Fallback fix layer per failure mode, used when a run has no per-verdict fix tags
# (e.g. the sample run). Real runs prefer the tags the judge wrote.
FM_FIX_LAYER = {
    "TR-1": "Conversation policy", "TR-2": "Conversation policy", "TR-3": "Conversation policy",
    "AC-1": "Conversation policy + output guard", "AC-2": "Tool / action authorisation",
    "PB-1": "Retrieval (RAG)", "PB-2": "Conversation policy", "PB-3": "Conversation policy",
    "PB-4": "Platform limits", "FA-1": "Conversation policy", "FA-2": "Output guard",
    "RE-1": "Retrieval (RAG)", "RE-2": "Output guard", "RE-3": "Retrieval (RAG)",
    "RE-4": "Conversation policy", "RE-5": "Retrieval (RAG)",
    "SA-1": "Output guard", "SA-2": "Output guard", "SA-3": "Conversation policy",
    "SA-4": "Output guard", "SA-5": "Output guard", "SA-6": "Conversation policy",
    "SA-7": "Conversation policy",
}

BAND_FLOOR = {"high": 3, "medium": 2}   # design: High findings table shows Highs; mediums noted in counts


def _layer_for(verdicts: list[Verdict], fid: str) -> str:
    """Dominant fix layer for a failure mode: judge tags first, static map second."""
    tags = fix_tags()
    areas = Counter()
    for v in verdicts:
        if v.failure_mode != fid or not v.valid:
            continue
        for t in [v.fix_tag, *v.extra_fix_tags]:
            area = (tags.get(t) or {}).get("area")
            if area and area != "none":
                areas[area] += 1
    if areas:
        return " + ".join(LAYER_LABELS[a] for a, _ in areas.most_common(2))
    return FM_FIX_LAYER.get(fid, "–")


def _top_risks(stats, verdicts: list[Verdict], fms: dict) -> list[dict]:
    """Three failure modes with the most open High, then Medium."""
    rows = [s for s in stats if s.open_high or s.medium]
    rows.sort(key=lambda s: (-(s.open_high * 100 + s.medium * 10), s.id))
    out = []
    for s in rows[:3]:
        fm = fms[s.id]
        related = [v for v in verdicts if v.failure_mode == s.id and v.valid and v.confirmed
                   and v.grade in (Grade.HIGH, Grade.MEDIUM)]
        out.append({
            "id": s.id, "alias": s.alias, "principle": fm["principle"],
            "harm": (fm.get("harm") or {}).get("plain", ""),
            "high": s.open_high, "medium": s.medium, "review": s.review,
            "layer": _layer_for(verdicts, s.id),
            "what": next((v.reason for v in related), ""),
        })
    return out


def _high_findings(stats, verdicts: list[Verdict], fms: dict, tier: str) -> list[dict]:
    """One row per failure mode with an open (confirmed) High, worst first."""
    rows = [s for s in stats if s.open_high]
    rows.sort(key=lambda s: (-s.open_high, -s.medium, s.id))
    out = []
    for i, s in enumerate(rows, 1):
        fm = fms[s.id]
        related = [v for v in verdicts if v.failure_mode == s.id and v.valid and v.confirmed
                   and v.grade == Grade.HIGH]
        mediums = [v for v in verdicts if v.failure_mode == s.id and v.valid and v.confirmed
                   and v.grade == Grade.MEDIUM]
        worst = max(related or mediums, key=lambda v: v.confidence, default=None)
        examples = [v.test_id for v in (related or mediums)[:3]]
        techniques = sorted({v.technique for v in related + mediums if v.technique})
        out.append({
            "fid": s.id, "num": f"F-{i:02d}", "alias": s.alias,
            "what": (worst.observed or worst.reason) if worst else "",
            "reason": worst.reason if worst else "",
            "examples": ", ".join(examples),
            "techniques": " · ".join(techniques),
            "layer": _layer_for(verdicts, s.id),
            "fix": (worst.dev_fix if worst and worst.dev_fix else "") or fm.get("mitigation", {}).get(tier, ""),
            "expected": (worst.expected if worst and worst.expected else "") or fm.get("passes_when", ""),
            "high": s.open_high, "medium": s.medium,
        })
    return out


def _owasp_status(stats_by_id: dict, fms: dict) -> list[dict]:
    """OWASP/Agentic items -> tested / partial / not tested, from the mapped failure modes."""
    cross = loader.crosswalk()
    out = []
    for group in ("owasp",):
        for item in cross[group]["items"]:
            mapped = item.get("failure_modes") or []
            if not mapped:
                status = "not prompt-testable"
            else:
                tested = [stats_by_id[m] for m in mapped if m in stats_by_id and stats_by_id[m].valid]
                if not tested:
                    status = "not tested"
                elif all(s.meets_bar for s in tested) and len(tested) == len(mapped):
                    status = "tested"
                else:
                    status = "partial"
            out.append({"code": item["code"], "name": item["name"], "status": status,
                        "note": item.get("note", "")})
    return out


def _script_checks(verdicts: list[Verdict]) -> list[dict]:
    """Aggregate script_findings across verdicts: check -> counts by grade."""
    agg: dict[str, Counter] = defaultdict(Counter)
    for v in verdicts:
        for sf in v.script_findings:
            agg[sf.check][sf.grade.value] += 1
    return [{"check": c, "counts": dict(n), "total": sum(n.values())}
            for c, n in sorted(agg.items())]


def _review_groups(verdicts: list[Verdict], fms: dict) -> list[dict]:
    groups: dict[str, list[Verdict]] = defaultdict(list)
    for v in verdicts:
        if v.valid and v.needs_review and not v.reviewed:
            groups[v.failure_mode].append(v)
    out = []
    for fid, vs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        fm = fms.get(fid, {})
        reasons = []
        for v in vs:
            r = v.reviewer_note or v.reason
            if r and r not in reasons:
                reasons.append(r)
        out.append({"id": fid, "alias": fm.get("alias", fid), "count": len(vs),
                    "reasons": reasons[:3]})
    return out


def report_context(f: FindingsResponse, verdicts: list[Verdict], run: Optional[dict] = None) -> dict:
    run = run or {}
    counts = count_by_failure_mode(verdicts)
    stats = failure_mode_stats(counts)
    stats_by_id = {s.id: s for s in stats}
    fms = loader.failure_modes()
    principles = loader.catalog()["principles"]
    pnames = {p["code"]: p["name"] for p in principles}
    pidx = principle_index(stats)
    untested = [fid for fid, fm in fms.items() if not stats_by_id[fid].valid]
    techniques = Counter(v.technique for v in verdicts if v.technique)
    grade_counts = Counter()
    for v in verdicts:
        if not v.valid:
            continue
        if v.needs_review and not v.reviewed:
            grade_counts["review"] += 1
        else:
            grade_counts[v.grade.value] += 1
    health = run_health(verdicts, not_run=len(run.get("not_run") or []))
    judge = run.get("judge") or {}
    pscores = principle_scores(counts)
    return {
        "f": f, "tier": loader.tier(f.gate.tier),
        "principles": principles,
        "principle_scores": pscores,
        "pindex": pidx,
        "counts": counts, "fms": fms,
        "stats": stats, "stats_by_id": stats_by_id,
        "headline": headline(stats), "index": index(stats),
        "principle_names": pnames,
        "below_seven": [p["name"] for p in principles
                        if (ps := pscores.get(p["code"])) and ps.score is not None and ps.score < 7],
        "top_risks": _top_risks(stats, verdicts, fms),
        "high_findings": _high_findings(stats, verdicts, fms, f.gate.tier),
        "fm_rows": [s for s in stats if s.valid],
        "untested": [(fid, fms[fid]["alias"]) for fid in untested],
        "techniques": dict(techniques),
        "grade_counts": grade_counts,
        "review_groups": _review_groups(verdicts, fms),
        "script_checks": _script_checks(verdicts),
        "owasp": _owasp_status(stats_by_id, fms),
        "not_covered": loader.crosswalk()["owasp"].get("not_covered_by_owasp", []),
        "health": health,
        "judge_model": judge.get("model") or judge.get("deployment") or "gpt-5.2",
        "judge_rubric": judge.get("rubric") or "v0.1",
        "summaries": run.get("summaries") or {},
        "policy_versions": f.policy_versions,
        "catalog_note": loader.catalog().get("note", ""),
    }


def render_html(kind: str, f: FindingsResponse, verdicts, run: Optional[dict] = None) -> str:
    return TEMPLATES.get_template(f"{kind}.html").render(**report_context(f, verdicts, run))


async def html_to_pdf(html: str) -> bytes:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.set_content(html, wait_until="networkidle")
        pdf = await page.pdf(format="Letter", print_background=True,
                             margin={"top": "14mm", "bottom": "14mm", "left": "14mm", "right": "14mm"})
        await browser.close()
        return pdf
