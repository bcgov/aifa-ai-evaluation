"""Executive and developer PDFs, each 2 pages max.

HTML template (Jinja2) -> PDF with headless Chromium (Playwright). Chromium is
used because it prints the same CSS the dashboard uses; WeasyPrint also works
if Chromium can't be installed on the App Service.

    pip install playwright && playwright install chromium
"""
from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..models import FindingsResponse
from ..policy import loader
from ..scoring import count_by_failure_mode, principle_scores

TEMPLATES = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html"]),
)


def render_html(kind: str, f: FindingsResponse, verdicts) -> str:
    counts = count_by_failure_mode(verdicts)
    ctx = dict(
        f=f,
        tier=loader.tier(f.gate.tier),
        principles=loader.catalog()["principles"],
        principle_scores=principle_scores(counts),   # PDFs may show these; Findings page does not
        counts=counts,
        fms=loader.failure_modes(),
        headline=[m for m in f.metrics if m.tab == "headline"],
    )
    return TEMPLATES.get_template(f"{kind}.html").render(**ctx)


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
