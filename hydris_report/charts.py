"""PNG charts for the report (matplotlib, Agg backend: no browser needed). Colours match the app."""
from __future__ import annotations

import calendar
import io
from typing import Any

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from hydris_risk.models import MonthlyValue
from hydris_report.explain import fmt_line

BAR, WATCH, PRESENT, GRID, TEXT = "#1570ef", "#f79009", "#b42318", "#d0d5dd", "#1d2939"
DPI = 150  # 945 px wide at 6.3 in: sharp in print, and a third cheaper to encode than 200


def _png(fig: Figure) -> bytes:
    buf = io.BytesIO()
    FigureCanvasAgg(fig)
    fig.savefig(buf, format="png", dpi=DPI, facecolor="white", pil_kwargs={"compress_level": 1})
    return buf.getvalue()


def _style(ax) -> None:
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=TEXT, labelsize=8)
    ax.yaxis.grid(True, color=GRID, linewidth=0.5)
    ax.set_axisbelow(True)


def monthly_chart_png(months: list[MonthlyValue], cfg: dict[str, Any], title: str) -> bytes | None:
    """12 monthly bars with the Watch and Present lines. None when there is nothing meaningful to plot (e.g. arid basins)."""
    pts = [m for m in months if m.raw is not None and (m.category is None or m.category >= 0)]
    if not pts:
        return None
    k = 100.0 if cfg.get("display") == "percent" else 1.0
    thr = cfg.get("thresholds") or []
    lines = [("Watch line", thr[cfg["watch_min_cat"] - 1], WATCH), ("Present line", thr[cfg["present_min_cat"] - 1], PRESENT)] if thr else []
    fig = Figure(figsize=(6.3, 2.3))
    ax = fig.add_subplot()
    ax.bar([calendar.month_abbr[m.month] for m in pts], [m.raw * k for m in pts], color=BAR, width=0.7, zorder=2)
    for name, value, colour in lines:
        ax.axhline(value * k, color=colour, linestyle="--", linewidth=1.2, zorder=3)
        ax.annotate(f"{name} ({fmt_line(value, cfg)})", xy=(1, value * k), xycoords=("axes fraction", "data"), xytext=(-2, 2),
                    textcoords="offset points", color=colour, fontsize=7, ha="right", va="bottom", zorder=4)
    top = max([m.raw * k for m in pts] + [v * k for _, v, _ in lines])
    ax.set_ylim(0, top * 1.18)
    unit = "%" if k == 100 else cfg.get("unit_display", cfg.get("unit", ""))
    ax.set_ylabel("" if unit in (None, "", "ratio") else unit, fontsize=8, color=TEXT)
    ax.set_title(title, fontsize=9, color=TEXT, loc="left")
    _style(ax)
    fig.subplots_adjust(left=0.085, right=0.985, top=0.86, bottom=0.14)  # fixed margins: tight_layout costs half the render time
    return _png(fig)


def overall_chart_png(groups: dict[str, dict[str, Any]], names: dict[str, str]) -> bytes | None:
    """Horizontal bars of the qan/qal/rrr group scores (0-5)."""
    if not groups:
        return None
    fig = Figure(figsize=(6.3, 1.9))
    ax = fig.add_subplot()
    labels = [names[g].capitalize() for g in groups]
    scores = [groups[g]["score"] for g in groups]
    ax.barh(labels, scores, color=BAR, height=0.55, zorder=2)
    for y, s in enumerate(scores):
        ax.text(s + 0.06, y, f"{s:.2f}", va="center", fontsize=8, color=TEXT)
    ax.set_xlim(0, 5.6)
    ax.invert_yaxis()
    ax.set_xlabel("Group score (0-5)", fontsize=8, color=TEXT)
    _style(ax)
    ax.yaxis.grid(False)
    ax.xaxis.grid(True, color=GRID, linewidth=0.5)
    fig.subplots_adjust(left=0.30, right=0.97, top=0.95, bottom=0.26)
    return _png(fig)
