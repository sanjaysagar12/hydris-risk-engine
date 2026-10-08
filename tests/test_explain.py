"""Threshold-position and what-would-change sentences, on contexts built from the synthetic GDB fixtures."""
import re

import pytest

from hydris_risk.config import load_rules
from hydris_risk.geo.locator import Locator
from hydris_risk.models import Factory, RiskStatus
from hydris_risk.reporting.explain import explain, fmt_gap, fmt_line, outlook_sentence
from hydris_risk.services.registry import REGISTRY

RULES = load_rules()
SITES = {"inland": (10.5, 10.5), "coast": (10.5, 11.5), "arid": (11.5, 10.5)}
P, W, N = RiskStatus.PRESENT, RiskStatus.WATCH, RiskStatus.NOT_PRESENT


@pytest.fixture
def ctxs(synthetic_repo):
    loc = Locator(synthetic_repo)
    fs = [Factory(site_id=n, site_name=n, lat=la, lon=lo) for n, (la, lo) in SITES.items()]
    return dict(zip(SITES, loc.locate(fs), strict=True))


def run(ctxs, rid, site="inland", base=None, future=None, country=None, **ctx_attrs):
    """Assess `rid` on a copy of a fixture context with baseline/future values overridden; return (result, explanation)."""
    ctx = ctxs[site].model_copy(deep=True, update=ctx_attrs)
    ctx.baseline.update(base or {})
    ctx.future.update(future or {})
    result = REGISTRY[rid](RULES).assess(ctx)
    return result, explain(result, RULES, country)


def bws(raw, cat, label):
    return {"bws_raw": raw, "bws_cat": float(cat), "bws_label": label}


def ws_future(flat=0.1, **by_year):
    """ws values per scenario: ws_future(bau={2030: .3, 2050: .35, 2080: .45}). Scenarios not given stay flat at `flat`,
    so a crossing in one scenario is never caused by fixture leftovers in another."""
    out = {}
    for sc in ("bau", "opt", "pes"):
        for y, raw in {**{2030: flat, 2050: flat, 2080: flat}, **by_year.get(sc, {})}.items():
            cat = sum(t <= raw for t in (0.1, 0.2, 0.4, 0.8))
            out.update({f"{sc}{y % 100}_ws_x_r": raw, f"{sc}{y % 100}_ws_x_c": float(cat), f"{sc}{y % 100}_ws_x_l": "x"})
    return out


def no_junk(*texts):
    for t in texts:
        assert t is None or not re.search(r"\bNone\b|\bnan\b|[{}]", t), t


# ---- formatting helpers --------------------------------------------------------------------------------------
def test_line_and_gap_formatting():
    assert fmt_line(0.4, RULES.for_risk("bws")) == "40%"
    assert fmt_line(0.8, RULES.for_risk("drr")) == "0.80"
    assert fmt_line(60, RULES.for_risk("rri")) == "60/100"
    assert fmt_line(4, RULES.for_risk("gtd")) == "4 cm/yr"
    assert fmt_line(0.006161, RULES.for_risk("rfr")) == "0.62%"
    assert fmt_line(0.0029867, RULES.for_risk("rfr")) == "0.3%"
    assert fmt_line(0.333333, RULES.for_risk("sev")) == "0.33"
    assert fmt_gap(0.164, RULES.for_risk("bwd")) == "16.4 points"
    assert fmt_gap(0.011, RULES.for_risk("drr")) == "0.01"
    assert fmt_gap(3, RULES.for_risk("rri")) == "3 points"
    assert fmt_gap(1.25, RULES.for_risk("gtd")) == "1.2 cm/yr" or fmt_gap(1.25, RULES.for_risk("gtd")) == "1.3 cm/yr"
    assert fmt_gap(0.00004, RULES.for_risk("bws")) == "0.004 points"  # never "0.0 points" for a nonzero gap


# ---- generic position and what-would-change, per status -------------------------------------------------------
def test_present_sentences(ctxs):
    r, e = run(ctxs, "bws")  # fixture: 50%, High
    assert r.status == P
    assert e.threshold_position == "At 50.0%, water stress is 10.0 points above the High line (40%)."
    assert e.what_would_change == "It would drop to Watch below 40%."


def test_present_drr_uses_its_own_scheme_and_two_decimals(ctxs):
    r, e = run(ctxs, "drr", base={"drr_raw": 0.811, "drr_cat": 4.0, "drr_label": "High (0.8-1.0)"})
    assert r.status == P
    assert e.threshold_position == "At 0.81, drought risk is in Aqueduct's highest category (0.80 and above)."
    assert e.what_would_change is None  # no points-above figure and no separate change sentence at the top


def test_watch_sentences_and_future_not_crossing(ctxs):
    r, e = run(ctxs, "bws", base=bws(0.209, 2, "Medium - High (20-40%)"),
               future=ws_future(0.209, bau={2030: 0.29, 2050: 0.366, 2080: 0.39}))
    assert r.status == W
    assert e.threshold_position == ("At 20.9%, water stress is 0.9 points above the Watch line (20%) "
                                    "and 19.1 points below the High line (40%).")
    assert e.what_would_change == ("It becomes Present if it reaches 40%.")  # no crossing: nothing more


def test_watch_future_crossing(ctxs):
    r, e = run(ctxs, "bws", base=bws(0.209, 2, "Medium - High (20-40%)"),
               future=ws_future(0.209, bau={2030: 0.3, 2050: 0.41, 2080: 0.5}))
    assert e.what_would_change == ("It becomes Present if it reaches 40%. Under business as usual it is projected "
                                   "to cross the High line by 2050.")


def test_watch_crossing_only_under_pessimistic_scenario(ctxs):
    r, e = run(ctxs, "bws", base=bws(0.209, 2, "x"), future=ws_future(
        0.209, bau={2030: 0.25, 2050: 0.3, 2080: 0.35}, pes={2030: 0.3, 2050: 0.39, 2080: 0.45}))
    assert "business as usual" not in e.what_would_change
    assert e.what_would_change.endswith("Under the pessimistic scenario it is projected to cross the High line by 2080.")


def test_not_present_sentences_without_future_crossing(ctxs):
    r, e = run(ctxs, "bwd", base={"bwd_raw": 0.086, "bwd_cat": 1.0, "bwd_label": "Low - Medium (5-25%)"},
               future={"bau50_wd_x_r": 0.171, "bau50_wd_x_c": 1.0, "bau30_wd_x_r": 0.12, "bau30_wd_x_c": 1.0,
                       "bau80_wd_x_r": 0.2, "bau80_wd_x_c": 1.0})
    assert r.status == N
    assert e.threshold_position == ("At 8.6%, water depletion is 16.4 points below the Watch line (25%) "
                                    "and 41.4 points below the High line (50%).")
    assert e.what_would_change == ("It would move to Watch at 25%.")


@pytest.mark.parametrize("bau, expect", [
    ({2030: 0.15, 2050: 0.21, 2080: 0.3}, "Under business as usual it is projected to reach the Watch line by 2050."),
    ({2030: 0.15, 2050: 0.2, 2080: 0.3}, "Under business as usual it is projected to reach the Watch line by 2050."),  # exactly on the line
    ({2030: 0.15, 2050: 0.3, 2080: 0.35}, "Under business as usual it is projected to reach the Watch line by 2050."),
    ({2030: 0.15, 2050: 0.35, 2080: 0.41}, "Under business as usual it is projected to cross the High line by 2080."),
    ({2030: 0.45, 2050: 0.5, 2080: 0.6}, "Under business as usual it is projected to cross the High line by 2030."),
])
def test_not_present_future_crossings_are_explicit(ctxs, bau, expect):
    r, e = run(ctxs, "bws", base=bws(0.05, 0, "Low (<10%)"), future=ws_future(0.05, bau=bau))
    assert r.status == N and e.what_would_change.endswith(expect), e.what_would_change


def test_no_future_means_no_future_sentence(ctxs):
    r, e = run(ctxs, "udw", base={"udw_raw": 0.03, "udw_cat": 1.0, "udw_label": "Low - Medium (2.5-5%)"})
    assert e.what_would_change == "It would move to Watch at 5%."


def test_boundary_value_never_contradicts_label(ctxs):
    r, e = run(ctxs, "iav", base={"iav_raw": 0.4987, "iav_cat": 1.0, "iav_label": "Low - Medium (0.25-0.50)"})
    assert e.threshold_position.startswith("At 0.499, interannual variability is 0.001 below the Watch line (0.50)")
    assert "At 0.50," not in e.threshold_position  # 0.50 would read as the Watch line itself


def test_value_exactly_on_a_line(ctxs):
    r, e = run(ctxs, "bws", base=bws(0.4, 3, "High (40-80%)"))
    assert r.status == P and e.threshold_position == "At 40.0%, water stress is level with the High line (40%)."


def test_inconsistent_raw_and_category_gives_no_position(ctxs):
    r, e = run(ctxs, "bws", base=bws(0.45, 2, "Medium - High (20-40%)"))  # raw says High, category says Medium-High
    assert e.threshold_position is None and e.what_would_change.startswith("It becomes Present")


def test_flood_sentences_use_share_of_population_scale(ctxs):
    r, e = run(ctxs, "rfr", base={"rfr_raw": 0.0015, "rfr_cat": 1.0, "rfr_label": "Low - Medium (1 in 1,000 to 2 in 1,000)"})
    assert r.status == N
    assert e.threshold_position == ("At 0.15%, riverine flood risk is 0.15 points below the Watch line (0.3%) "
                                    "and 0.47 points below the High line (0.62%).")
    assert "probability" not in e.threshold_position and "return period" not in e.threshold_position


def test_gtd_present_keeps_direction_words(ctxs):
    r, e = run(ctxs, "gtd", base={"gtd_raw": 5.2, "gtd_cat": 3.0, "gtd_label": "High (4-8 cm/y)"})
    assert r.status == P
    assert e.threshold_position == "At +5.2 cm/yr (falling), groundwater table decline is 1.2 cm/yr above the High line (4 cm/yr)."


def test_rri_points(ctxs):
    r, e = run(ctxs, "rri", base={"rri_raw": 57.0, "rri_cat": 2.0, "rri_label": "Medium - High (50-60%)"}, country="India")
    assert r.status == W
    assert e.threshold_position == "At 57/100, country ESG risk is 7 points above the Watch line (50/100) and 3 points below the High line (60/100)."
    assert e.extra_notes == ["This value is the same for every site in India, so it does not distinguish this factory from others in the country."]


# ---- special cases ----------------------------------------------------------------------------------------------
def test_gtd_insignificant_trend(ctxs):
    r, e = run(ctxs, "gtd")  # fixture inland: Insignificant Trend
    assert r.status == N and e.threshold_position is None
    assert e.what_would_change == ("This would change only if a statistically significant declining trend were found. "
                                   "Aqueduct's model covers 1990–2014; recent local well data (e.g. CGWB) may show a different picture.")
    assert e.extra_notes == []  # the reason already says it


def test_cfr_no_risk(ctxs):
    r, e = run(ctxs, "cfr", site="arid")
    assert r.status == N
    assert e.threshold_position == "Aqueduct records no coastal flood risk for this basin; there is no threshold to compare against."
    assert e.what_would_change is None


@pytest.mark.parametrize("rid, noun", [("bws", "ratio"), ("bwd", "ratio")])
def test_arid_has_no_numeric_position(ctxs, rid, noun):
    r, e = run(ctxs, rid, site="arid")
    assert r.status == P and r.values.raw is None
    assert e.threshold_position == ("Aqueduct does not calculate a reliable ratio for very dry, low-use basins, "
                                    "so position against thresholds is not meaningful.")
    assert e.what_would_change is None and not re.search(r"\d", e.threshold_position)


def test_ucw_low_collection_and_country_scale(ctxs):
    r, e = run(ctxs, "ucw", site="arid", country="India")
    assert r.status == W and e.threshold_position is None and e.what_would_change is None
    assert e.extra_notes[0] == ("The indicator cannot measure pollution from uncollected sewage, so Watch reflects "
                                "missing sewer collection, not low pollution.")
    assert e.extra_notes[1].startswith("This value is the same for every site in India")


def test_country_note_falls_back_without_country(ctxs):
    _, e = run(ctxs, "ucw", site="arid")
    assert "every site in this country" in e.extra_notes[1]


def test_no_data_area(ctxs):
    r, e = run(ctxs, "cfr", site="inland")  # fixture inland: cfr NoData
    assert r.status == RiskStatus.NO_DATA and e.threshold_position is None and e.what_would_change is None
    assert e.extra_notes == ["Aqueduct has no value for this indicator in this area, so no status can be given. "
                             "This is a data gap, not evidence of low risk."]


def test_no_data_unmatched_site():
    from hydris_risk.models import BasinContext, MatchMethod
    ctx = BasinContext(factory=Factory(site_id="x", site_name="x", lat=0, lon=0), match_method=MatchMethod.UNMATCHED)
    r = REGISTRY["bws"](RULES).assess(ctx)
    e = explain(r, RULES)
    assert "could not be matched to an Aqueduct polygon" in e.extra_notes[0] and "data gap, not evidence of low risk" in e.extra_notes[0]


def test_error_result(ctxs):
    svc = REGISTRY["drr"](RULES)
    svc.extract = lambda ctx: (_ for _ in ()).throw(RuntimeError("boom"))
    r = svc.assess(ctxs["inland"])
    e = explain(r, RULES)
    assert r.status == RiskStatus.ERROR and e.threshold_position is None and e.what_would_change is None
    assert e.extra_notes == ["RuntimeError: boom. This risk could not be assessed; other results are unaffected."]


def test_impact_indicator_wording_is_about_downstream_waters(ctxs):
    r, e = run(ctxs, "cep", site="coast")  # fixture: Medium-High -> Watch
    assert r.kind == "impact" and r.status == W
    assert e.threshold_position == ("At an ICEP index of 0.50, coastal eutrophication potential is 0.50 above the Watch line (0.0) "
                                    "and 0.50 below the High line (1.0).")
    assert e.what_would_change == "The basin's contribution to downstream waters becomes Present if it reaches 1.0."
    assert "factory" not in (e.threshold_position + e.what_would_change).lower()


def test_overall_textile_has_no_position_sentence(ctxs):
    r, e = run(ctxs, "overall_textile")
    assert e.threshold_position is None and e.what_would_change is None and e.extra_notes == []


# ---- outlook ----------------------------------------------------------------------------------------------------
def outlook(ctxs, base_raw, bau):
    r, _ = run(ctxs, "bws", base=bws(base_raw, sum(t <= base_raw for t in (0.1, 0.2, 0.4, 0.8)), "x"),
               future=ws_future(base_raw, bau=bau))
    return outlook_sentence(r, RULES)


def test_outlook_monotonic_rise_and_fall(ctxs):
    assert outlook(ctxs, 0.209, {2030: 0.25, 2050: 0.366, 2080: 0.41}) == (
        "Under business as usual water stress rises from 20.9% today to 25.0% by 2030, 36.6% by 2050 and 41.0% by 2080.")
    assert outlook(ctxs, 0.4, {2030: 0.35, 2050: 0.3, 2080: 0.3}) == (
        "Under business as usual water stress falls from 40.0% today to 35.0% by 2030, 30.0% by 2050 and 30.0% by 2080.")


def test_outlook_describes_the_turn_instead_of_one_verb(ctxs):
    assert outlook(ctxs, 0.209, {2030: 0.21, 2050: 0.366, 2080: 0.351}) == (
        "Under business as usual water stress goes from 20.9% today to 21.0% by 2030 and 36.6% by 2050, "
        "then eases to 35.1% by 2080.")
    assert outlook(ctxs, 0.2, {2030: 0.3, 2050: 0.25, 2080: 0.22}) == (
        "Under business as usual water stress goes from 20.0% today to 30.0% by 2030, then eases to 25.0% by 2050 and 22.0% by 2080.")
    assert outlook(ctxs, 0.3, {2030: 0.2, 2050: 0.25, 2080: 0.41}) == (
        "Under business as usual water stress goes from 30.0% today to 20.0% by 2030, then climbs again to 25.0% by 2050 and 41.0% by 2080.")
    assert outlook(ctxs, 0.4, {2030: 0.3, 2050: 0.25, 2080: 0.3}) == (
        "Under business as usual water stress goes from 40.0% today to 30.0% by 2030 and 25.0% by 2050, then climbs again to 30.0% by 2080.")


def test_outlook_flat_and_irregular_and_missing(ctxs):
    assert "changes little" in outlook(ctxs, 0.209, {2030: 0.209, 2050: 0.21, 2080: 0.211})
    assert outlook(ctxs, 0.2, {2030: 0.3, 2050: 0.2, 2080: 0.3}).startswith("Under business as usual water stress goes from 20.0% today to 30.0% by 2030, 20.0% by 2050 and 30.0% by 2080.")
    none, _ = run(ctxs, "drr")
    assert outlook_sentence(none, RULES) is None


# ---- every service, every fixture site: no junk, sensible shape ------------------------------------------------------
@pytest.mark.parametrize("rid", list(REGISTRY))
@pytest.mark.parametrize("site", SITES)
def test_all_services_all_sites(ctxs, rid, site):
    r, e = run(ctxs, rid, site=site, country="Testland")
    no_junk(e.threshold_position, e.what_would_change, *e.extra_notes)
    if r.status in (P, W, N) and not r.drivers.get("case") and rid != "overall_textile":
        assert e.what_would_change, (rid, site)
        thr = RULES.risks[rid]["thresholds"]  # the fixtures' default values are not all consistent with real thresholds
        consistent = sum(t <= r.values.raw for t in thr) == r.values.category
        assert bool(e.threshold_position) == consistent, (rid, site)
    if r.status == RiskStatus.NO_DATA:
        assert e.extra_notes and not e.threshold_position


# ---- highest category: one sentence, no figures, no change sentence ------------------------------------------------
@pytest.mark.parametrize("rid, raw, label, expect", [
    ("ucw", 1.0, "Extremely High (100%)", "At 100.0%, untreated wastewater is in Aqueduct's highest category (99.96% and above)."),
    ("usa", 0.478, "Extremely High (>20%)", "At 47.8%, sanitation access gap is in Aqueduct's highest category (20% and above)."),
    ("drr", 0.9, "High (0.8-1.0)", "At 0.90, drought risk is in Aqueduct's highest category (0.80 and above)."),
])
def test_highest_category_is_a_single_sentence(ctxs, rid, raw, label, expect):
    cat = {"ucw": 4.0, "usa": 4.0, "drr": 4.0}[rid]
    r, e = run(ctxs, rid, base={f"{rid}_raw": raw, f"{rid}_cat": cat, f"{rid}_label": label})
    assert r.status == P and e.threshold_position == expect and e.what_would_change is None
    assert "above the" not in e.threshold_position and "points" not in e.threshold_position


def test_one_below_the_top_still_has_both_sentences(ctxs):
    r, e = run(ctxs, "usa", base={"usa_raw": 0.15, "usa_cat": 3.0, "usa_label": "High (10-20%)"})
    assert e.threshold_position == "At 15.0%, sanitation access gap is 5.0 points above the High line (10%)."
    assert e.what_would_change == "It would drop to Watch below 10%."


# ---- every scenario that crosses a line is named ---------------------------------------------------------------------
def test_optimistic_scenario_above_bau_is_not_skipped(ctxs):
    r, e = run(ctxs, "bws", base=bws(0.209, 2, "x"), future=ws_future(
        0.209, bau={2030: 0.25, 2050: 0.3, 2080: 0.35}, opt={2030: 0.3, 2050: 0.41, 2080: 0.5}))
    assert e.what_would_change == ("It becomes Present if it reaches 40%. Under the optimistic scenario it is projected to cross "
                                   "the High line by 2050.")


def test_all_three_scenarios_named_when_all_cross(ctxs):
    r, e = run(ctxs, "bws", base=bws(0.209, 2, "x"), future=ws_future(
        0.209, bau={2030: 0.3, 2050: 0.41, 2080: 0.5}, opt={2030: 0.3, 2050: 0.45, 2080: 0.5}, pes={2030: 0.41, 2050: 0.5, 2080: 0.6}))
    assert e.what_would_change.endswith(
        "Under business as usual it is projected to cross the High line by 2050. "
        "Under the optimistic scenario it is projected to cross the High line by 2050. "
        "Under the pessimistic scenario it is projected to cross the High line by 2030.")


def test_not_present_names_scenarios_reaching_watch_or_high(ctxs):
    r, e = run(ctxs, "bws", base=bws(0.05, 0, "Low (<10%)"), future=ws_future(
        0.05, bau={2030: 0.1, 2050: 0.15, 2080: 0.19}, opt={2030: 0.1, 2050: 0.2, 2080: 0.25}, pes={2030: 0.2, 2050: 0.45, 2080: 0.5}))
    assert e.what_would_change.endswith(
        "Under the optimistic scenario it is projected to reach the Watch line by 2050. "
        "Under the pessimistic scenario it is projected to cross the High line by 2050.")
