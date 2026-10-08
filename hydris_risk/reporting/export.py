"""One entry point for the CLI and the app: engine output -> report bytes + file name."""
from __future__ import annotations

from datetime import datetime

from hydris_risk.config import RiskRules
from hydris_risk.engine import EngineOutput
from hydris_risk.reporting.builder import build_report, report_filename
from hydris_risk.reporting.render_html import render_html
from hydris_risk.reporting.render_pdf import render_pdf

FORMATS = ("pdf", "html")
MIME = {"pdf": "application/pdf", "html": "text/html"}


def render_report(out: EngineOutput, rules: RiskRules, report_type: str, site_id: str | None, fmt: str,
                  generated_at: datetime) -> tuple[str, bytes]:
    """(file name, bytes). A portfolio covers every factory in `out`; a factory report needs `site_id`. Filters never apply."""
    if fmt not in FORMATS:
        raise ValueError(f"Unknown format {fmt!r}; use one of {FORMATS}")
    doc = build_report(out, rules, report_type, [site_id] if report_type == "factory" and site_id else None, generated_at)
    data = render_pdf(doc) if fmt == "pdf" else render_html(doc).encode("utf-8")
    return report_filename(report_type, site_id, generated_at, fmt), data
