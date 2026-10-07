import re



import pytest



from hydris_risk.config import load_rules

from hydris_risk.data.aqueduct_repository import AqueductRepository

from hydris_risk.geo.locator import Locator

from hydris_risk.models import Factory, RiskStatus

from hydris_risk.services.baseline_water_stress import BaselineWaterStress

from hydris_risk.services.groundwater_table_decline import GroundwaterTableDecline



RULES = load_rules()

SITES = {"inland": (10.5, 10.5), "coast": (10.5, 11.5), "arid": (11.5, 10.5)}





@pytest.fixture

def ctxs(synthetic_gdb, tmp_path):

    loc = Locator(AqueductRepository(synthetic_gdb, tmp_path / "c"))

    fs = [Factory(site_id=n, site_name=n, lat=la, lon=lo) for n, (la, lo) in SITES.items()]

    return dict(zip(SITES, loc.locate(fs), strict=True))





def clean(text):

    assert not re.search(r"\bNone\b|\bnan\b|\{|\}", text), text





@pytest.mark.parametrize("svc", [BaselineWaterStress, GroundwaterTableDecline])

@pytest.mark.parametrize("site", SITES)

def test_no_placeholder_leaks(svc, site, ctxs):

    r = svc(RULES).assess(ctxs[site])

    for text in (r.headline, r.reason, *r.caveats):

        clean(text)

    assert r.reason and str(r.pfaf_id) in r.reason

    assert any(c.startswith("Source: WRI Aqueduct 4.0") for c in r.caveats)





def test_reason_has_no_caveats_or_category_numbers(ctxs):

    for site in SITES:

        r = BaselineWaterStress(RULES).assess(ctxs[site])

        assert "Source:" not in r.reason and "Basin-level value" not in r.reason

        assert "category" not in r.reason.lower() and "What this means" not in r.reason





def test_bws_present_reason_parts(ctxs):

    r = BaselineWaterStress(RULES).assess(ctxs["inland"])

    assert r.status == RiskStatus.PRESENT and r.values.raw_display == "50%"

    assert r.headline == "Present: high water stress (50%)"

    for needle in ("Present. Baseline water stress compares", "demand is 50% of supply", "High (40–80%)", "1001 (Highland, Inland)",

                   "Present from High (40%+) and Watch from Medium–High, so this site, at High, is Present.",

                   "Factories here face strong competition", "Stress peaks in January at 50%, with 12 of 12 months at High or above",

                   "10.0 points above the High line", "no change from baseline"):

        assert needle in r.reason, needle

    assert r.drivers["reporting_flag_water_stressed"] is True

    assert r.caveats == ["Basin-level value; does not reflect the factory's own water sources.", "Source: WRI Aqueduct 4.0."]





def test_bws_not_present_has_no_impact(ctxs):

    r = BaselineWaterStress(RULES).assess(ctxs["coast"])

    assert r.status == RiskStatus.NOT_PRESENT and "Factories here" not in r.reason

    assert "is below the Watch level" in r.reason and "35.0 points below the High line" in r.reason





def test_arid_wording(ctxs):

    r = BaselineWaterStress(RULES).assess(ctxs["arid"])

    assert r.status == RiskStatus.PRESENT and r.values.raw is None and r.values.raw_display is None

    assert r.headline == "Present: very dry, low-use basin (no reliable stress ratio)"

    assert ("Aqueduct does not calculate a reliable stress ratio for very dry, low-use basins; Hydris treats them as Present "

            "because any new withdrawal can quickly raise stress.") in r.reason

    assert "100%" not in r.reason + r.headline and "Arid and Low Water Use" in r.reason and r.drivers["case"] == "arid"

    assert "peaks" not in r.reason





def test_gtd_insignificant_wording(ctxs):

    r = GroundwaterTableDecline(RULES).assess(ctxs["inland"])

    assert r.status == RiskStatus.NOT_PRESENT

    assert r.headline == "Not present: no significant groundwater trend detected"

    assert r.reason == (

        "Not present. Groundwater table decline measures how fast the groundwater table is falling where Aqueduct's model finds a "

        "statistically significant trend. For the aquifer beneath sub-basin 1001 (Highland, Inland), the model finds no significant trend, so Hydris marks "

        "this risk not present. This means no decline was detected in the model, not that groundwater here is safe."

    )

    assert r.values.raw_display == "-2.0 cm/yr (rising)"  # raw only in the values panel

    assert r.caveats[0] == "Modelled, not measured; check local well data such as CGWB."

    assert r.caveats[2] == "Source: WRI Aqueduct 4.0 dataset; this indicator was last updated in Aqueduct 3.0 (data 1990-2014)."





def test_gtd_direction_words(ctxs):

    r = GroundwaterTableDecline(RULES).assess(ctxs["coast"])

    assert r.values.raw_display == "+0.5 cm/yr (falling)" and "Low–Medium (0–2 cm/y)" in r.reason





def test_change_wording():

    from hydris_risk.reasoning.reason_builder import ReasonBuilder

    from hydris_risk.services.base import RiskMeta

    rb = ReasonBuilder(RiskMeta("bws", "Baseline water stress", "g", "4.0", True, "ws", "x", "y"), RULES)

    f = {"present_title": "High", "peak_noun": "Stress"}

    t = lambda d: rb._trend(f, {"bau2050": {"raw": 0.2, "delta": d, "gap": -0.2}})  # noqa: E731

    assert t(0.0).endswith("no change from baseline.")

    assert t(0.004).endswith("about the same as baseline.")

    assert t(0.01).endswith("below the High line.")

