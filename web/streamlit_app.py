"""Hydris water-risk screening app. Run: streamlit run web/streamlit_app.py"""
from __future__ import annotations

import hashlib
import io
import sys
from collections import Counter
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parent
for p in (str(ROOT), str(APP_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
from components.charts import group_chart  # noqa: E402
from components.factory_map import factory_map  # noqa: E402
from components.factory_table import build_table, factory_table  # noqa: E402
from components.report_downloads import report_button  # noqa: E402
from components.risk_card import STATUS_ORDER, badge_html, risk_card, status_rank, tag_html  # noqa: E402

from hydris_risk.config import load_rules, load_settings  # noqa: E402
from hydris_risk.engine import RiskEngine  # noqa: E402
from hydris_risk.io.input_loader import load_factories  # noqa: E402
from hydris_risk.io.output_writer import csv_bytes, json_bytes, long_frame, wide_frame  # noqa: E402
from hydris_risk.models import MatchMethod  # noqa: E402
from hydris_risk.reasoning import formatters as F  # noqa: E402

GROUPS = ["Physical: quantity", "Physical: quality", "Regulatory & reputational"]
IMPACT = "Downstream impact"
CITATION = ('Kuzma, S. et al. 2023. "Aqueduct 4.0: Updated decision-relevant global water risk indicators." '
            "Technical Note. WRI. doi.org/10.46830/writn.23.00061 (data: WRI Aqueduct 4.0, CC BY 4.0).")
DISCLAIMER = "Basin-level screening data. Not a substitute for site-level assessment."

st.set_page_config(page_title="Hydris water-risk screening", page_icon="💧", layout="wide")


@st.cache_resource(show_spinner="Loading Aqueduct data (first run builds a cache, about 20 seconds)...")
def get_repo():
    from hydris_risk.data.aqueduct_repository import AqueductRepository

    s = load_settings()
    return AqueductRepository(s.find_gdb(), s.cache_path)


@st.cache_resource
def get_rules():
    return load_rules()


@st.cache_data(show_spinner="Assessing factories...")
def run_engine(file_hash: str, _csv_bytes: bytes):
    """Cached per file hash. Returns the engine output, input issues and the three download payloads."""
    factories, issues = load_factories(io.BytesIO(_csv_bytes))
    if not factories:
        return None, issues, {}
    out = RiskEngine(get_repo(), get_rules()).run(factories)
    exports = {"long": csv_bytes(long_frame(out)), "wide": csv_bytes(wide_frame(out)), "json": json_bytes(out)}
    return out, issues, exports


def footer() -> None:
    st.divider()
    st.caption(CITATION)
    st.caption(DISCLAIMER)


# ---------------------------------------------------------------- sidebar
rules = get_rules()
settings = load_settings()
if settings.find_gdb() is None:
    st.error("Aqueduct data not found. Put the Aqueduct 4.0 .gdb under data/raw/ (see README), then reload.")
    st.stop()

st.sidebar.header("Factories")
upload = st.sidebar.file_uploader("Factories CSV", type="csv", help="Required columns: site_id, site_name, lat, lon")
use_sample = st.sidebar.toggle("Use sample factories", value=upload is None, disabled=upload is not None)
if upload is not None:
    csv_data = upload.getvalue()
elif use_sample:
    csv_data = (ROOT / "sample" / "factories.csv").read_bytes()
else:
    csv_data = None

st.title("Hydris water-risk screening")
if csv_data is None:
    st.info("Upload a factories CSV or switch on 'Use sample factories' in the sidebar.")
    footer()
    st.stop()

file_hash = hashlib.sha256(csv_data).hexdigest()
if st.session_state.get("_file_hash") != file_hash:  # new file: forget the previous file's selection state
    for k in ("_last_table_site", "_synced", "factory_choice"):
        st.session_state.pop(k, None)
    st.session_state["_file_hash"] = file_hash
out, issues, exports = run_engine(file_hash, csv_data)

if issues:
    n_err = sum(i.level == "error" for i in issues)
    with st.sidebar.expander(f"Input validation: {n_err} error(s), {len(issues) - n_err} warning(s)", expanded=n_err > 0):
        for i in issues:
            (st.error if i.level == "error" else st.warning)(str(i))
if out is None:
    st.error("No valid factories in the file. See the validation messages in the sidebar.")
    footer()
    st.stop()

st.sidebar.header("Filters")
status_labels = {s: s.value.replace("_", " ").capitalize() for s in STATUS_ORDER}
chosen_status = st.sidebar.multiselect("Risk status (cards and summary table)", STATUS_ORDER, default=STATUS_ORDER,
                                       format_func=status_labels.get)
chosen_groups = st.sidebar.multiselect("Risk group (cards and summary table)", [*GROUPS, IMPACT], default=[*GROUPS, IMPACT])
only_present = st.sidebar.checkbox("Show only factories with at least 1 present risk")
st.sidebar.header("Download")
st.sidebar.download_button("results_long.csv", exports["long"], "results_long.csv", "text/csv")
st.sidebar.download_button("results_wide.csv", exports["wide"], "results_wide.csv", "text/csv")
st.sidebar.download_button("results.json", exports["json"], "results.json", "application/json")
with st.sidebar:
    st.caption("Reports include all 14 results for every factory, whatever the filters above.")
    report_button("Download portfolio report (PDF)", "portfolio", None, "pdf", "dl_portfolio_pdf", out, file_hash)
    report_button("Download portfolio report (HTML)", "portfolio", None, "html", "dl_portfolio_html", out, file_hash)

# ---------------------------------------------------------------- top: all factories
table = build_table(out, rules)
unmatched = int((table["Match"] == MatchMethod.UNMATCHED.value).sum())
LOCAL = {"sub-basin", "aquifer"}  # country-level and composite scores are the same for a whole region, so they say nothing local
common = Counter(r for s in out.summary for r in s.present_risks if rules.risks[r].get("scale") in LOCAL).most_common(1)
k1, k2, k3, k4 = st.columns(4)
k1.metric("Factories", len(table))
k2.metric("With 1 or more present risk", int((table["# present"] > 0).sum()))
k3.metric("Most common local risk",
          rules.risks[common[0][0]].get("short_name", rules.risks[common[0][0]]["name"]).capitalize() if common else "None",
          f"in {common[0][1]} of {len(table)} factories" if common else None, delta_color="off", delta_arrow="off")
k4.metric("Unmatched factories", unmatched)
st.caption("Counts cover risks only: the overall textile score and downstream-impact indicators are not counted. 'Most common local risk' counts sub-basin and aquifer-scale risks only (country-level ones such as untreated wastewater and RepRisk are excluded).")

visible = table[table["# present"] > 0] if only_present else table
if visible.empty:
    st.warning("No factories match the filter.")
    footer()
    st.stop()

options = list(visible["Site ID"])
names = dict(zip(table["Site ID"], table["Factory"], strict=True))
if st.session_state.get("factory_choice") not in options:
    st.session_state["factory_choice"] = options[0]

st.subheader("All factories")
st.session_state.setdefault("table_gen", 0)
map_slot = st.container()
clicked = factory_table(visible, key=f"factory_table_{file_hash[:8]}_{st.session_state['table_gen']}")
if clicked:
    st.session_state["factory_choice"] = clicked
    st.session_state["_synced"] = clicked
st.selectbox("Selected factory", options, key="factory_choice", format_func=lambda s: f"{s} - {names[s]}")
site = st.session_state["factory_choice"]
if st.session_state.get("_synced") != site:
    # changed through the selectbox: the table's row highlight is stale, so give the table a fresh key to clear it
    st.session_state["_synced"] = site
    if st.session_state.pop("_last_table_site", None):
        st.session_state["table_gen"] += 1
        st.rerun()
with map_slot:
    factory_map(visible, site)

# ---------------------------------------------------------------- bottom: selected factory
ctx = next(c for c in out.contexts if c.factory.site_id == site)
results = [r for r in out.results if r.site_id == site]
by_id = {r.risk_id: r for r in results}

st.divider()
st.header(ctx.factory.site_name)
h1, h2, h3, h4 = st.columns(4)
h1.markdown(f"**Coordinates**  \n{ctx.factory.lat:.4f}, {ctx.factory.lon:.4f}")
h2.markdown(f"**Sub-basin (pfaf_id)**  \n{ctx.pfaf_id or 'n/a'}  \n`{ctx.string_id or 'n/a'}`")
h3.markdown(f"**State / country**  \n{ctx.name_1 or 'n/a'}, {ctx.name_0 or 'n/a'}")
h4.markdown(f"**Match method**  \n{ctx.match_method.value}")
if ctx.match_method == MatchMethod.NEAREST:
    st.warning(f"This site is outside every Aqueduct polygon; values are from the nearest one, {ctx.snap_distance_km:.1f} km away.")
elif ctx.match_method == MatchMethod.UNMATCHED:
    st.error("This site could not be matched to an Aqueduct polygon, so there are no results for it.")
for c in ctx.caveats:
    st.warning(c)
rb1, rb2, rb3 = st.columns([1, 1, 3])
with rb1:
    report_button("Download factory report (PDF)", "factory", site, "pdf", "dl_factory_pdf", out, file_hash)
with rb2:
    report_button("Download factory report (HTML)", "factory", site, "html", "dl_factory_html", out, file_hash)
rb3.caption("Reports include all 14 results, regardless of the filters.")

# overall textile card
ov = by_id["overall_textile"]
with st.container(border=True, key="card_overall_textile"):
    st.markdown(f"### Overall water risk (textiles) &nbsp; {badge_html(ov.status)} &nbsp; {tag_html('composite')}",
                unsafe_allow_html=True)
    c1, c2 = st.columns([1, 2])
    with c1:
        score = ov.values.score
        st.metric("Overall score (0-5)", f"{score:.2f}" if score is not None else "no data", ov.values.label,
                  delta_color="off", delta_arrow="off")
        st.write(ov.headline)
        top = ov.drivers.get("top_indicators", [])
        if top:
            st.markdown("**Top 3 drivers**")
            for t in top:
                cfg = rules.for_risk(t["risk_id"])
                title = F.cat_titles(cfg).get(t["category"], "")
                st.markdown(f"- {cfg.get('short_name', t['name']).capitalize()}: {t['score']:.2f} {f'({title})' if title else ''}")
    with c2:
        names_g = rules.risks["overall_textile"]["group_names"]
        fig = group_chart(ov.drivers.get("groups", {}), names_g)
        if fig:
            st.plotly_chart(fig, key="overall_groups", width="stretch")
    with st.expander("Why"):
        st.write(ov.reason)
    st.caption("\n".join(f"- {c}" for c in ov.caveats))

# summary table (risks + impact, filtered)
risks = [r for r in results if r.risk_id != "overall_textile"]


def group_of(r) -> str:
    return IMPACT if r.kind == "impact" else r.group


shown = [r for r in risks if r.status in chosen_status and group_of(r) in chosen_groups]
st.subheader("Risk summary")
if shown:
    summary = pd.DataFrame([{
        "Risk": r.risk_name, "Type": "Downstream impact" if r.kind == "impact" else "Risk",
        "Status": status_labels[r.status], "Value": r.values.raw_display or "", "Label": r.values.label or "",
        "Scale": r.scale or "",
    } for r in sorted(shown, key=lambda r: status_rank(r.status))])
    st.dataframe(summary, hide_index=True, width="stretch")
else:
    st.info("No risks match the status and group filters.")


def card_grid(items) -> None:
    items = sorted(items, key=lambda r: status_rank(r.status))  # Present, Watch, Not present, No data, Error
    for i in range(0, len(items), 2):
        cols = st.columns(2)
        for col, r in zip(cols, items[i:i + 2], strict=False):
            with col:
                risk_card(r, rules.for_risk(r.risk_id))


st.subheader("Risks")
for g in GROUPS:
    items = [r for r in shown if r.kind == "risk" and r.group == g]
    if g in chosen_groups and items:
        st.markdown(f"#### {g}")
        card_grid(items)
impact_items = [r for r in shown if r.kind == "impact"]
if IMPACT in chosen_groups and impact_items:
    st.markdown(f"#### {IMPACT}")
    st.caption("Pollution the basin contributes downstream. Shown with its status but not counted as a risk to the factory.")
    card_grid(impact_items)

footer()
