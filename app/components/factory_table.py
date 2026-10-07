"""Factory list: built from the engine summary; row selection via st.dataframe on_select."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from hydris_risk.config import RiskRules
from hydris_risk.engine import EngineOutput


def build_table(out: EngineOutput, rules: RiskRules) -> pd.DataFrame:
    """One row per factory. Counts exclude overall_textile and downstream-impact indicators (engine summary)."""
    ctx = {c.factory.site_id: c for c in out.contexts}
    rows = []
    for s in out.summary:
        c = ctx[s.site_id]
        overall = (f"{s.overall_textile_score:.2f} ({s.overall_textile_label})"
                   if s.overall_textile_score is not None else "no data")
        rows.append({
            "Site ID": s.site_id, "Factory": c.factory.site_name, "State": c.name_1 or "", "Country": c.name_0 or "",
            "# present": s.n_present, "# watch": s.n_watch,
            "Present risks": ", ".join(rules.risks[r]["name"] for r in s.present_risks),
            "Overall textile (0-5)": s.overall_textile_score, "Overall label": s.overall_textile_label or "",
            "Match": s.match_method.value, "_lat": c.factory.lat, "_lon": c.factory.lon, "_overall": overall,
        })
    return pd.DataFrame(rows)


def factory_table(df: pd.DataFrame, key: str = "factory_table") -> str | None:
    """Show the table; return the Site ID of a newly clicked row (or None)."""
    shown = df[["Site ID", "Factory", "State", "Country", "# present", "# watch", "Present risks",
                "Overall textile (0-5)", "Overall label", "Match"]].reset_index(drop=True)
    event = st.dataframe(
        shown, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row", key=key,
        column_config={"Overall textile (0-5)": st.column_config.NumberColumn(format="%.2f")},
    )
    rows = [r for r in event.selection.rows if r < len(shown)]  # ignore a stale index from a previous, larger table
    if not rows:
        st.session_state.pop("_last_table_site", None)  # allow re-clicking the same row
        return None
    site = shown.iloc[rows[0]]["Site ID"]
    if st.session_state.get("_last_table_site") != site:
        st.session_state["_last_table_site"] = site
        return site
    return None
