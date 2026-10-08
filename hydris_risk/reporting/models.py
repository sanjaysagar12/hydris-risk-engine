"""The report as data: one ReportDocument feeds both the PDF and the HTML renderer."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from hydris_risk.models import FutureValue, IndicatorValues, RiskStatus


class RiskBlock(BaseModel):
    risk_id: str
    risk_name: str
    group: str
    kind: Literal["risk", "impact", "composite"]
    scale: str
    vintage: str
    status: RiskStatus
    status_word: str
    detail: Literal["full", "compact"] = "full"   # compact: title, why, position, change, notes, caveats only
    headline: str
    why: str                          # the engine's reason, unchanged
    threshold_position: str | None = None
    what_would_change: str | None = None
    extra_notes: list[str] = []       # special-case lines (gtd, country-scale, no data, ...)
    outlook_rows: list[FutureValue] = []
    outlook_table: list[dict[str, str]] = []   # pre-formatted: scenario, today, 2030, 2050, 2080
    outlook_sentence: str | None = None
    monthly_chart_png: bytes | None = None
    values: IndicatorValues
    source: str
    pfaf_id: int | None = None
    string_id: str | None = None
    caveats: list[str] = []


class FactoryReport(BaseModel):
    context_header: dict[str, Any]    # name, ids, coordinates, basin, match info
    location_caveats: list[str]
    counts: dict[str, int]            # by status; risks only (overall and impact excluded), as in the engine summary
    at_a_glance: str
    summary_rows: list[dict[str, Any]]
    overall: RiskBlock
    overall_chart_png: bytes | None = None
    present: list[RiskBlock]
    watch: list[RiskBlock]
    not_present: list[RiskBlock]
    no_data: list[RiskBlock]          # no data, error (and not applicable)
    impact: list[RiskBlock]
    not_present_framing: str
    impact_intro: str


class PortfolioSummary(BaseModel):
    kpis: dict[str, Any]
    columns: list[dict[str, Any]]     # matrix columns: risk_id, name, short_name, group, kind
    matrix: list[dict[str, Any]]      # one row per factory
    paragraph: str


class ReportDocument(BaseModel):
    report_type: Literal["factory", "portfolio"]
    title: str
    subtitle: str
    generated_at: datetime            # injected, never datetime.now() inside the builder
    hydris_version: str
    dataset_version: str
    disclaimer: str
    citation: str
    citation_url: str
    data_license: str
    portfolio: PortfolioSummary | None = None
    factories: list[FactoryReport]
    methodology: list[dict[str, Any]]  # per-risk rule table for the appendix
    methodology_intro: str
    methodology_notes: list[str]
    status_definitions: list[dict[str, str]]
    limitations: list[str]
