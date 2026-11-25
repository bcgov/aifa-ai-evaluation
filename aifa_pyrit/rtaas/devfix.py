"""Turns per-row judge notes into one fix list for the dev team.

No extra LLM call: rows are grouped by the judge's fix_tag (a fixed list in
policy/fix_tags.yaml). A reviewer confirms each item before it goes out.
"""
from __future__ import annotations

from collections import defaultdict

from .judge import fix_tags
from .models import SEVERITY_ORDER, Verdict

RANK = {g: i for i, g in enumerate(SEVERITY_ORDER)}


def group(verdicts: list[Verdict]) -> list[dict]:
    buckets: dict[str, list[Verdict]] = defaultdict(list)
    for v in verdicts:
        if v.fix_tag != "none":
            buckets[v.fix_tag].append(v)

    out = []
    for tag, vs in buckets.items():
        worst = max(vs, key=lambda v: RANK[v.grade])
        out.append({
            "fix_tag": tag,
            "owner": fix_tags()[tag]["owner"],
            "title": fix_tags()[tag]["title"],
            "worst_grade": worst.grade.value,
            "rows": sorted(v.test_id for v in vs),
            "count": len(vs),
            "example_expected": worst.expected,
            "example_observed": worst.observed,
            "suggested_fix": worst.dev_fix,
            "confirmed": False,          # reviewer flips this before it goes to the dev team
        })
    # worst first, then most rows
    out.sort(key=lambda x: (-RANK[next(g for g in SEVERITY_ORDER if g.value == x["worst_grade"])], -x["count"]))
    return out
