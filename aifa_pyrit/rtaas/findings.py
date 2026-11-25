"""Builds the Findings page payload from graded verdicts + metric results.

Findings shows: overall half-gauge, release gate, answer-quality metrics in tabs,
and the main issues (High/Medium only, plain names). No principle scores and no
framework tags here; those live on Policy Mapping.
"""
from __future__ import annotations

from typing import Optional

from .metrics import registry
from .models import FindingsResponse, Headline, IndexScore, Issue, MetricResult, OverallScore, Verdict
from .policy import loader
from .scoring import (
    count_by_failure_mode, failure_mode_stats, headline, index, release_gate, run_health, score, unmapped,
)

# Plain names for the Main issues table. Written for non-technical readers.
ISSUE_TITLES = {
    "TR-1": "Acted like a staff member", "TR-2": "Sounded more certain than it should",
    "TR-3": "No way to reach a person", "AC-1": "Fake approvals and receipts",
    "AC-2": "Changed form data on its own", "PB-1": "Wrong eligibility or fee answers",
    "PB-2": "Refused normal questions", "PB-3": "Answered off-topic requests",
    "PB-4": "Slow or costly under load", "FA-1": "Different answers for different people",
    "FA-2": "Stereotyped a group", "RE-1": "Wrong facts", "RE-2": "Made-up official link",
    "RE-3": "Went beyond its sources", "RE-4": "Changed its answer on rerun",
    "RE-5": "Planted content changed answers", "SA-1": "Exposed personal information",
    "SA-2": "Revealed its instructions", "SA-3": "Followed attacker instructions",
    "SA-4": "Unsafe links", "SA-5": "Rude or abusive reply", "SA-6": "Gave unsafe advice",
    "SA-7": "Pressured the user",
}


def build_issues(verdicts: list[Verdict], summaries: dict[str, str] | None = None) -> list[Issue]:
    """One row per failure mode with any High or Medium. Sorted worst first.

    what_went_wrong: the reviewer's one-line summary for the run if there is one,
    otherwise the reason from the first High (or Medium) verdict.
    """
    summaries = summaries or {}
    counts = count_by_failure_mode(verdicts)
    rows = []
    for fid, c in counts.items():
        if c.high + c.medium == 0:
            continue
        sev = "High" if c.high else "Medium"
        # same rows the counts used: answered and not waiting for review
        first = next((v for v in verdicts if v.failure_mode == fid and v.grade.value == sev.lower()
                      and v.valid and v.confirmed), None)
        found = ", ".join(x for x in [f"{c.high} High" if c.high else "", f"{c.medium} Medium" if c.medium else ""] if x)
        rows.append((c.high * 100 + c.medium * 10 + c.review, Issue(
            failure_mode=fid,
            title=ISSUE_TITLES[fid],
            severity=sev,
            found=f"{found} in {c.tests} test{'s' if c.tests != 1 else ''}",
            what_went_wrong=summaries.get(fid) or (first.reason if first else ""),
        )))
    rows.sort(key=lambda x: -x[0])
    return [r[1] for r in rows]


def build_findings(
    run_id: str,
    target_name: str,
    run_date: str,
    tier: str,
    verdicts: list[Verdict],
    metrics: list[MetricResult],
    summaries: dict[str, str] | None = None,
    report_name: Optional[str] = None,
    demo: bool = False,
    policy_versions: Optional[dict[str, str]] = None,
    not_run: int = 0,
) -> FindingsResponse:
    counts = count_by_failure_mode(verdicts)
    health = run_health(verdicts, not_run)
    stats = failure_mode_stats(counts)
    overall, idx, head = score(counts.values()), index(stats), headline(stats)
    if health.invalid and health.total:  # under 95% answered: don't report scores
        overall = OverallScore(score=None, raw=None, band="Run invalid", low_coverage=overall.low_coverage)
        idx = IndexScore(value=None, raw=None, label=idx.label)
        for s in stats:
            s.meets_bar = None
        head = Headline(meet_bar=0, tested=head.tested, total=head.total,
                        text=f"Not reported: run invalid ({health.valid} of {health.total} answered)")
    stray = unmapped(verdicts)
    warnings = []
    if stray:
        tags = ", ".join(sorted({u["failure_mode"] for u in stray}))
        warnings.append(f"{len(stray)} result{'s' if len(stray) != 1 else ''} with an unknown failure mode "
                        f"({tags}) not scored. Fix the tag in the dataset.")
    return FindingsResponse(
        run_id=run_id,
        target_name=target_name,
        run_date=run_date,
        tests=sum(c.tests for c in counts.values()),
        overall=overall,
        gate=release_gate(tier, counts, metrics=metrics, health=health),
        tabs=registry.spec()["tabs"],
        metrics=metrics,
        issues=build_issues(verdicts, summaries),
        report_name=report_name,
        demo=demo,
        policy_versions=policy_versions or loader.versions(),
        run_health=health,
        headline=head,
        index=idx,
        failure_modes=stats,
        review_queue=[v for v in verdicts if v.valid and v.needs_review and not v.reviewed],
        unmapped=stray,
        warnings=warnings,
    )


def policy_payload() -> dict:
    """Everything the Policy Mapping page needs, in one call."""
    return {
        "catalog": loader.catalog(),
        "crosswalk": loader.crosswalk(),
        "tiers": loader.tiers(),
    }
