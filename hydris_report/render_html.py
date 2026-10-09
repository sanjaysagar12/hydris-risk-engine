"""ReportDocument -> one self-contained HTML string (Jinja2, inline CSS, charts as base64 PNG, no external requests)."""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from hydris_report.models import ReportDocument

STATUS_WORDS = {"present": "Present", "watch": "Watch", "not_present": "Not present", "no_data": "No data", "error": "Error",
                "impact": "Downstream impact"}
_env = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"), autoescape=select_autoescape(["j2", "html"]),
                   undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True)


def _b64(png: bytes | None) -> str | None:
    return base64.b64encode(png).decode("ascii") if png else None


def _prep(block: Any) -> Any:
    return block.model_copy(update={"monthly_chart_png": _b64(block.monthly_chart_png)})


def render_html(doc: ReportDocument) -> str:
    """PNG bytes are base64-encoded on copies, so the document itself is left untouched."""
    factories = [fr.model_copy(update={
        "overall": _prep(fr.overall), "present": [_prep(b) for b in fr.present], "watch": [_prep(b) for b in fr.watch],
        "not_present": [_prep(b) for b in fr.not_present], "no_data": [_prep(b) for b in fr.no_data],
        "impact": [_prep(b) for b in fr.impact], "overall_chart_png": _b64(fr.overall_chart_png)}) for fr in doc.factories]
    d = doc.model_copy(update={"factories": factories})
    cols = d.portfolio.columns if d.portfolio else []
    names = [f.context_header["name"] for f in d.factories]
    return _env.get_template("report.html.j2").render(
        doc=d, names=", ".join(names[:12]) + (f" and {len(names) - 12} more" if len(names) > 12 else ""),
        generated=f"{doc.generated_at.day} {doc.generated_at:%B %Y}", status_words=STATUS_WORDS,
        risk_cols=[c for c in cols if c["kind"] != "impact"], impact_cols=[c for c in cols if c["kind"] == "impact"])
