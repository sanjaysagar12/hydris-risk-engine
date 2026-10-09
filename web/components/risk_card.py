"""One risk card: status badge (word + colour), scale tag, headline, Why / Values expanders, charts, caveats."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from components.charts import future_chart, monthly_chart
from hydris_risk.models import RiskResult, RiskStatus

# Worst first. not_applicable is unused with the current data but kept so the enum is fully handled.
STATUS_ORDER = [RiskStatus.PRESENT, RiskStatus.WATCH, RiskStatus.NOT_PRESENT, RiskStatus.NOT_APPLICABLE,
                RiskStatus.NO_DATA, RiskStatus.ERROR]

# (label, background, text colour, border). Colour is secondary: the word is always shown.
BADGE = {
    RiskStatus.PRESENT: ("Present", "#b42318", "#ffffff", "#b42318"),
    RiskStatus.WATCH: ("Watch", "#fdb022", "#1d2939", "#fdb022"),
    RiskStatus.NOT_PRESENT: ("Not present", "#067647", "#ffffff", "#067647"),
    RiskStatus.NOT_APPLICABLE: ("Not applicable", "#667085", "#ffffff", "#667085"),
    RiskStatus.NO_DATA: ("No data", "transparent", "inherit", "#667085"),
    RiskStatus.ERROR: ("Error", "#6941c6", "#ffffff", "#6941c6"),
}


def status_rank(status: RiskStatus) -> int:
    return STATUS_ORDER.index(status)


def badge_html(status: RiskStatus) -> str:
    label, bg, fg, border = BADGE[status]
    return (f'<span style="background:{bg};color:{fg};border:1.5px solid {border};border-radius:999px;'
            f'padding:2px 10px;font-size:0.8rem;font-weight:600;white-space:nowrap">{label}</span>')


def tag_html(text: str) -> str:
    return (f'<span style="border:1px solid #98a2b3;border-radius:4px;padding:1px 6px;font-size:0.72rem;'
            f'color:inherit;opacity:0.85;white-space:nowrap">{text}</span>')


def risk_card(r: RiskResult, cfg: dict) -> None:
    with st.container(border=True, key=f"card_{r.risk_id}"):
        tags = tag_html(r.scale or "scale n/a") + " " + tag_html(f"Aqueduct {r.indicator_vintage}")
        if r.kind == "impact":
            tags = tag_html("Downstream impact") + " " + tags
        st.markdown(f"**{r.risk_name}** &nbsp; {badge_html(r.status)} &nbsp; {tags}", unsafe_allow_html=True)
        st.write(r.headline)

        with st.expander("Why"):
            st.write(r.reason)
        with st.expander("Values"):
            v = r.values
            rows = {
                "Raw": v.raw, "Raw (displayed)": v.raw_display, "Unit": v.unit, "Score (0-5)": v.score,
                "Category": v.category, "Label": v.label, "Scale": r.scale, "Indicator vintage": r.indicator_vintage,
                "Source": r.source, "Sub-basin (pfaf_id)": r.pfaf_id, "Polygon (string_id)": r.string_id,
            }
            st.dataframe(pd.DataFrame({"Field": list(rows), "Value": ["" if x is None else str(x) for x in rows.values()]}),
                         hide_index=True, width="stretch")

        if r.monthly and (fig := monthly_chart(r, cfg)):
            st.plotly_chart(fig, key=f"monthly_{r.risk_id}", width="stretch")
        elif r.monthly:
            st.caption("No monthly values to chart for this site.")
        if r.future and (fig := future_chart(r, cfg)):
            st.plotly_chart(fig, key=f"future_{r.risk_id}", width="stretch")
            with st.expander("Future values"):
                st.dataframe(future_table(r, cfg), hide_index=True, width="stretch")

        if r.caveats:
            st.caption("\n".join(f"- {c}" for c in r.caveats))


def future_table(r: RiskResult, cfg: dict) -> pd.DataFrame:
    from components.charts import SCENARIOS
    from hydris_risk.reasoning.formatters import fmt_value
    rows = []
    for key, name in SCENARIOS.items():
        row = {"Scenario": name}
        for y in (2030, 2050, 2080):
            f = next((x for x in r.future if x.scenario == key and x.year == y), None)
            row[str(y)] = (fmt_value(f.raw, cfg) if f and f.raw is not None else "") or ""
        rows.append(row)
    return pd.DataFrame(rows)
