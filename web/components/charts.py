"""Plotly charts: monthly bars with category threshold lines, future-scenario lines, group breakdown bars."""
from __future__ import annotations

import calendar

import plotly.graph_objects as go

from hydris_risk.models import RiskResult
from hydris_risk.reasoning.formatters import fmt_value

SCENARIOS = {"bau": "Business as usual (SSP3-RCP7.0)", "opt": "Optimistic (SSP1-RCP2.6)", "pes": "Pessimistic (SSP5-RCP8.5)"}
COLORS = {"bau": "#b54708", "opt": "#067647", "pes": "#b42318"}


def _layout(fig: go.Figure, height: int = 260) -> go.Figure:
    fig.update_layout(height=height, margin=dict(l=10, r=10, t=30, b=10), paper_bgcolor="rgba(0,0,0,0)",
                      plot_bgcolor="rgba(0,0,0,0)", legend=dict(orientation="h", y=-0.25))
    return fig


def _scale(cfg: dict) -> float:
    return 100.0 if cfg.get("display") == "percent" else 1.0


def monthly_chart(r: RiskResult, cfg: dict) -> go.Figure | None:
    pts = [m for m in r.monthly if m.raw is not None and (m.category is None or m.category >= 0)]
    if not pts:
        return None
    k = _scale(cfg)
    fig = go.Figure(go.Bar(
        x=[calendar.month_abbr[m.month] for m in pts], y=[m.raw * k for m in pts], marker_color="#1570ef",
        customdata=[fmt_value(m.raw, cfg) for m in pts], hovertemplate="%{x}: %{customdata}<extra></extra>", name="Monthly",
    ))
    for t, name in zip(cfg.get("thresholds", []), ("Low-Medium", "Medium-High", "High", "Extremely High"), strict=False):
        fig.add_hline(y=t * k, line_dash="dot", line_color="#98a2b3",
                      annotation_text=f"{name} from {t * k:g}{'%' if k == 100 else ''}", annotation_position="top left",
                      annotation_font_size=10)
    fig.update_layout(title=dict(text=f"{r.risk_name}: monthly", font_size=13),
                      yaxis_title="%" if k == 100 else cfg.get("unit_display", cfg.get("unit", "")))
    return _layout(fig)


def future_chart(r: RiskResult, cfg: dict) -> go.Figure | None:
    fig = go.Figure()
    k = _scale(cfg)
    base = r.values.raw if r.values.category != -1 else None
    for key, name in SCENARIOS.items():
        vals = {f.year: f.raw for f in r.future if f.scenario == key and f.raw is not None}
        if not vals:
            continue
        xs = ["Baseline", *[str(y) for y in sorted(vals)]] if base is not None else [str(y) for y in sorted(vals)]
        ys = ([base * k] if base is not None else []) + [vals[y] * k for y in sorted(vals)]
        fig.add_scatter(x=xs, y=ys, mode="lines+markers", name=name, line_color=COLORS[key])
    if not fig.data:
        return None
    fig.update_layout(title=dict(text=f"{r.risk_name}: baseline to 2080", font_size=13),
                      yaxis_title="%" if k == 100 else "")
    return _layout(fig, 280)


def group_chart(groups: dict[str, dict], names: dict[str, str]) -> go.Figure | None:
    if not groups:
        return None
    fig = go.Figure(go.Bar(
        x=[groups[g]["score"] for g in groups], y=[names[g].capitalize() for g in groups], orientation="h",
        marker_color="#1570ef", text=[f"{groups[g]['score']:.2f}" for g in groups], textposition="outside",
        hovertemplate="%{y}: %{x:.2f} of 5<extra></extra>",
    ))
    fig.update_layout(xaxis=dict(range=[0, 5.6], title="Group score (0-5)"), yaxis=dict(autorange="reversed"))
    return _layout(fig, 200)
