"""Every registered service x every fixture polygon."""
import re

import pytest

from hydris_risk.config import load_rules
from hydris_risk.geo.locator import Locator
from hydris_risk.models import BasinContext, Factory, MatchMethod, RiskResult, RiskStatus
from hydris_risk.services.registry import REGISTRY, get_services

RULES = load_rules()
SITES = {"inland": (10.5, 10.5), "coast": (10.5, 11.5), "arid": (11.5, 10.5)}
P, W, N, ND = (RiskStatus.PRESENT, RiskStatus.WATCH, RiskStatus.NOT_PRESENT, RiskStatus.NO_DATA)

# expected status per (site, risk), from the fixture categories in conftest.py; unlisted risks are category 1 -> not present
EXPECTED = {
    ("inland", "bws"): P, ("inland", "cfr"): ND, ("inland", "cep"): ND, ("inland", "gtd"): N, ("inland", "overall_textile"): P,
    ("coast", "cfr"): W, ("coast", "cep"): W,
    ("arid", "bws"): P, ("arid", "bwd"): P, ("arid", "ucw"): W, ("arid", "cfr"): N, ("arid", "overall_textile"): P,
}


@pytest.fixture
def ctxs(synthetic_repo):
    loc = Locator(synthetic_repo)
    fs = [Factory(site_id=n, site_name=n, lat=la, lon=lo) for n, (la, lo) in SITES.items()]
    return dict(zip(SITES, loc.locate(fs), strict=True))


def test_registry_has_14():
    assert len(REGISTRY) == 14 and "overall_textile" in REGISTRY
    assert {s.meta.risk_id for s in get_services(RULES)} == set(REGISTRY)
    with pytest.raises(ValueError):
        get_services(RULES, ["nope"])


@pytest.mark.parametrize("risk_id", list(REGISTRY))
@pytest.mark.parametrize("site", SITES)
def test_valid_result_and_status(risk_id, site, ctxs):
    svc = REGISTRY[risk_id](RULES)
    r = svc.assess(ctxs[site])
    assert isinstance(r, RiskResult) and r.risk_id == risk_id and r.pfaf_id == ctxs[site].pfaf_id
    assert r.status == EXPECTED.get((site, risk_id), N), r.reason
    assert r.headline and r.reason and r.source and r.indicator_vintage in ("3.0", "4.0") and r.caveats
    for text in (r.headline, r.reason, *r.caveats):
        assert not re.search(r"\bNone\b|\bnan\b|[{}]", text), text
    assert len(r.monthly) == (12 if svc.meta.has_monthly else 0)
    assert len(r.future) == (9 if svc.meta.future_code else 0)


def test_nodata_has_no_value_but_a_reason(ctxs):
    r = REGISTRY["cfr"](RULES).assess(ctxs["inland"])
    assert r.status == ND and r.values.raw is None and r.values.category is None
    assert "no value" in r.reason


def test_arid_bws_bwd(ctxs):
    for rid, noun in (("bws", "stress"), ("bwd", "depletion")):
        r = REGISTRY[rid](RULES).assess(ctxs["arid"])
        assert r.status == P and r.values.raw is None and r.values.raw_display is None
        assert f"reliable {noun} ratio" in r.reason and "Water is scarce in absolute terms" in r.reason
        assert "competition for water, with higher risk of supply cuts" not in r.reason


def test_cfr_no_risk_and_ucw_low_collection(ctxs):
    cfr = REGISTRY["cfr"](RULES).assess(ctxs["arid"])
    assert cfr.status == N and "Aqueduct records no coastal flood risk for this basin" in cfr.reason
    ucw = REGISTRY["ucw"](RULES).assess(ctxs["arid"])
    assert ucw.status == W and "very little wastewater collected by sewers" in ucw.reason and "may still be polluted" in ucw.reason


def test_flood_wording_is_share_of_people(ctxs):
    for rid in ("rfr", "cfr"):
        r = REGISTRY[rid](RULES).assess(ctxs["coast"])
        text = " ".join([r.reason, *r.caveats]).lower()
        assert "share of the population" in r.reason and "share of people affected in an average year" in text
        assert "probability" not in r.reason.lower() and "return period" not in r.reason.lower().replace("not a flood return period", "")


def test_caveat_texts(ctxs):
    for rid in ("udw", "usa"):
        c = REGISTRY[rid](RULES).assess(ctxs["inland"]).caveats
        assert c[0] == "Sub-basin estimate; access near the factory may differ." and not any("Basin-level" in x for x in c)
    assert REGISTRY["rri"](RULES).assess(ctxs["inland"]).caveats[0] == "Country-level snapshot; may not reflect current events."


def test_caveat_order_location_first_source_last(synthetic_repo):
    loc = Locator(synthetic_repo)
    [ctx] = loc.locate([Factory(site_id="n", site_name="n", lat=10.5, lon=9.98)])  # snapped
    assert ctx.match_method == MatchMethod.NEAREST
    c = REGISTRY["gtd"](RULES).assess(ctx).caveats
    assert "outside the nearest Aqueduct polygon" in c[0] and c[1].startswith("Modelled, not measured")
    assert c[2].startswith("Aquifer-level") and c[3].startswith("Source: WRI Aqueduct 4.0 dataset") and len(c) == 4


def test_overall_textile_drivers(ctxs):
    r = REGISTRY["overall_textile"](RULES).assess(ctxs["inland"])
    assert set(r.drivers["groups"]) == {"qan", "qal", "rrr"} and r.drivers["weight_fraction"] == 1.0
    assert len(r.drivers["top_indicators"]) == 3 and r.values.raw_display == "4.10 of 5"
    assert "water quantity (4.00, Extremely High)" in r.reason


def test_unmatched_is_no_data():
    from hydris_risk.models import Factory
    ctx = BasinContext(factory=Factory(site_id="x", site_name="x", lat=0, lon=0), match_method=MatchMethod.UNMATCHED)
    for svc in get_services(RULES):
        r = svc.assess(ctx)
        assert r.status == ND and "could not be matched" in r.reason


def test_formatters_small_shares_and_units():
    from hydris_risk.reasoning.formatters import fmt_value
    rules = RULES
    assert fmt_value(0.00146, rules.for_risk("rfr")) == "0.15%"
    assert fmt_value(0.00005, rules.for_risk("cfr")) == "0.0050%"
    assert fmt_value(0.2094, rules.for_risk("bws")) == "20.9%"
    assert fmt_value(57.0, rules.for_risk("rri")) == "57/100"
    assert fmt_value(0.81, rules.for_risk("drr")) == "0.81"


def test_drr_uses_its_own_category_scheme(ctxs):
    ctx = ctxs["inland"].model_copy(deep=True)
    ctx.baseline.update(drr_cat=3.0, drr_raw=0.7, drr_label="Medium - High (0.6-0.8)")
    r = REGISTRY["drr"](RULES).assess(ctx)
    assert r.status == W and "Medium–High" in r.reason
    ctx.baseline.update(drr_cat=4.0, drr_raw=0.9, drr_label="High (0.8-1.0)")
    r = REGISTRY["drr"](RULES).assess(ctx)
    assert r.status == P and r.headline.startswith("Present: high drought risk") and "at High, is Present" in r.reason


# ---- rounding never contradicts the label -------------------------------------------------------
def _all_cat(x, thr):
    return sum(t <= x for t in thr)


@pytest.mark.parametrize("risk_id", [r for r in REGISTRY if RULES.risks[r].get("thresholds")])
def test_displayed_value_never_contradicts_category(risk_id):
    """For raw values just either side of every category boundary, the number shown falls in the same category."""
    from hydris_risk.reasoning.formatters import fmt_value
    cfg = RULES.for_risk(risk_id)
    thr, pct = cfg["thresholds"], cfg.get("display") == "percent"
    for t in thr:
        for rel in (1e-6, 1e-4, 1e-3, 3e-3, 1e-2):
            for raw in (t - rel * abs(t or 1), t + rel * abs(t or 1)):
                text = fmt_value(raw, cfg)
                shown = float(re.match(r"[+-]?\d+(?:\.\d+)?", text).group()) / (100 if pct else 1)
                assert _all_cat(shown, thr) == _all_cat(raw, thr), (risk_id, raw, text)


def test_near_boundary_shows_three_decimals():
    from hydris_risk.reasoning.formatters import fmt_value
    assert fmt_value(0.2487, RULES.for_risk("iav")) == "0.249"
    assert fmt_value(0.2494, RULES.for_risk("iav")) == "0.249"
    assert fmt_value(0.2513, RULES.for_risk("iav")) == "0.25"  # already consistent: 0.25 is category 1
    assert fmt_value(0.3996, RULES.for_risk("bws")) == "39.96%"


def test_reason_value_matches_its_label_end_to_end(ctxs):
    ctx = ctxs["inland"].model_copy(deep=True)
    ctx.baseline.update(iav_raw=0.2487, iav_cat=0.0, iav_label="Low (<0.25)")
    r = REGISTRY["iav"](RULES).assess(ctx)
    assert "interannual variability is 0.249" in r.reason and r.values.raw_display == "0.249" and "Low (<0.25)" in r.reason


# ---- formatting -----------------------------------------------------------------------------------
def test_per_people_and_whole_percent():
    from hydris_risk.reasoning.formatters import fmt_raw_display, fmt_value, per_people
    assert per_people(0.0015) == "about 1.5 in every 1,000 people"
    assert per_people(0.00005) == "about 5 in every 100,000 people"
    assert fmt_raw_display(0.0015, RULES.for_risk("rfr")) == "0.15% (about 1.5 in every 1,000 people)"
    assert fmt_value(1.0, RULES.for_risk("ucw")) == "100%" and fmt_value(0.5, RULES.for_risk("bws")) == "50%"
    assert fmt_value(0.209, RULES.for_risk("bws")) == "20.9%"


def test_flood_reason_has_percent_and_per_people(ctxs):
    r = REGISTRY["cfr"](RULES).assess(ctxs["coast"])
    assert "0.40% of the population (about 4 in every 1,000 people) is expected to be affected by coastal flooding" in r.reason
    assert r.values.raw_display == "0.40% (about 4 in every 1,000 people)" and r.headline.endswith("(0.40%)")


# ---- scale wording --------------------------------------------------------------------------------
def test_scale_wording(ctxs):
    ctx = ctxs["inland"].model_copy(deep=True)
    ctx.name_0 = "India"
    ctx.baseline.update(rri_raw=57.0, rri_cat=2.0, rri_label="Medium - High (50-60%)")
    assert "In India, the country's peak RepRisk ESG risk index is 57/100" in REGISTRY["rri"](RULES).assess(ctx).reason
    ucw = REGISTRY["ucw"](RULES).assess(ctx)
    assert "Based on country-level data for India" in ucw.reason and "sub-basin" not in ucw.reason
    assert "Country-level value, not local conditions." in ucw.caveats
    assert "For the aquifer beneath sub-basin" in REGISTRY["gtd"](RULES).assess(ctx).reason


# ---- cep is an impact indicator -----------------------------------------------------------------
def test_cep_is_downstream_impact(ctxs):
    r = REGISTRY["cep"](RULES).assess(ctxs["coast"])
    assert r.kind == "impact" and r.status == W
    assert r.headline.startswith("Downstream impact – Watch: medium–high coastal eutrophication potential (ICEP index 0.50)")
    assert "This measures pollution the basin contributes to coastal waters, not a risk to the factory's own supply." in r.reason
    assert "an ICEP index of 0.50" in r.reason
    assert all(REGISTRY[i](RULES).assess(ctxs["coast"]).kind == "risk" for i in REGISTRY if i != "cep")


# ---- overall: incomplete weighting -------------------------------------------------------------------
def test_overall_incomplete_weight_caveat(ctxs):
    svc = REGISTRY["overall_textile"](RULES)
    assert not any("no data here" in c for c in svc.assess(ctxs["inland"]).caveats)  # weight fraction 1.0
    ctx = ctxs["inland"].model_copy(deep=True)
    ctx.baseline["w_awr_tex_tot_weight_fraction"] = 0.918
    c = svc.assess(ctx).caveats
    assert "About 8% of the weighting had no data here, so the score rests on incomplete inputs." in c
    assert c.index("About 8% of the weighting had no data here, so the score rests on incomplete inputs.") < c.index(
        next(x for x in c if x.startswith("Basin-level")))


def test_overall_headline_and_value_use_the_score_not_raw(ctxs):
    r = REGISTRY["overall_textile"](RULES).assess(ctxs["inland"])
    assert r.values.raw == pytest.approx(3.1) and r.values.score == pytest.approx(4.1)  # fixture: raw = score - 1
    assert r.headline == "Present: extremely high overall textile water risk (4.10 of 5)"
    assert "4.10 of 5" in r.reason and "3.10" not in r.reason + r.headline
