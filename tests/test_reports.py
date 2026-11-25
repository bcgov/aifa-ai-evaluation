"""Step 7: the sample run must reproduce the numbers in design/executive-summary.pdf."""
import re

import pytest

from aifa_pyrit.rtaas import service
from aifa_pyrit.rtaas.export import pdf
from aifa_pyrit.rtaas.scoring import count_by_failure_mode, failure_mode_stats, headline, index, principle_index


@pytest.fixture(scope="module")
def sample():
    f, verdicts = service.findings_for("demo")
    return f, verdicts, failure_mode_stats(count_by_failure_mode(verdicts))


def test_headline_and_index_match_design(sample):
    _, _, stats = sample
    h, idx = headline(stats), index(stats)
    assert (h.meet_bar, h.tested, h.total) == (5, 12, 23)
    assert (idx.value, idx.raw, idx.capped_by) == (6.0, 6.4, "high")


def test_principle_rows_match_design(sample):
    _, _, stats = sample
    rows = {p["name"]: p for p in principle_index(stats)}
    expected = {  # name: (index, band, meet_bar, tested, total, tests, open_high, open_medium)
        "Transparency": (7.0, "Needs work", 1, 1, 3, 3, 0, 0),
        "Accountability": (6.0, "Needs work", 0, 2, 2, 26, 5, 1),
        "Public benefit": (4.4, "Fail", 2, 3, 4, 36, 2, 6),
        "Fairness": (None, "Not tested", 0, 0, 2, 0, 0, 0),
        "Reliability": (4.3, "Fail", 0, 2, 5, 12, 1, 7),
        "Safety": (6.0, "Needs work", 2, 4, 7, 134, 3, 9),
    }
    for name, exp in expected.items():
        r = rows[name]
        got = (r["index"], r["band"], r["meet_bar"], r["tested"], r["total"], r["tests"], r["open_high"], r["open_medium"])
        assert got == exp, name
    assert rows["Transparency"]["low_coverage"] is True


def test_exec_report_has_no_framework_section(sample):
    f, verdicts, _ = sample
    html = pdf.render_html("exec", f, verdicts, service.get_run("demo"))
    text = re.sub(r"<[^>]+>", " ", html)
    assert "5 of 12 tested" in text and "12 of 23 failure modes tested" in text
    assert "6.0 / 10" in text and "6.4 before the cap" in text
    for banned in ("EU AI Act", "2024/1689", "NIST", "OWASP", "Art. "):
        assert banned not in text, banned
    assert 'class="break"' not in html  # one page


def test_dev_report_is_two_pages_with_high_findings(sample):
    f, verdicts, _ = sample
    html = pdf.render_html("dev", f, verdicts, service.get_run("demo"))
    assert html.count('class="break"') == 1
    assert "High findings: fix these before release" in html and "Results by failure mode" in html
    assert "OWASP cross-reference" in html
    for fid in ("AC-1", "PB-1", "SA-2", "SA-4", "AC-2", "RE-2"):
        assert fid in html
