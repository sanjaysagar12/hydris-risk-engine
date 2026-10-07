"""Acceptance test on the real Aqueduct GDB (skipped if absent). Golden values from SPEC.md section 2."""
import pytest

from hydris_risk.config import load_rules, load_settings
from hydris_risk.data.aqueduct_repository import AqueductRepository
from hydris_risk.geo.locator import Locator
from hydris_risk.models import Factory, MatchMethod, RiskStatus
from hydris_risk.services.baseline_water_stress import BaselineWaterStress

TOL = 1e-4


@pytest.fixture(scope="module")
def tiruppur():
    s = load_settings()
    gdb = s.find_gdb()
    if gdb is None:
        pytest.skip("real Aqueduct GDB not present")
    loc = Locator(AqueductRepository(gdb, s.cache_path), s.nearest_tolerance_km, s.metric_crs)
    [ctx] = loc.locate([Factory(site_id="t", site_name="Tiruppur Mill", lat=11.1085, lon=77.3411)])
    return ctx


def test_golden_values(tiruppur):
    c, b = tiruppur, tiruppur.baseline
    assert c.match_method == MatchMethod.WITHIN and c.pfaf_id == 453803 and c.name_1 == "Tamil Nadu"
    assert b["bws_raw"] == pytest.approx(0.209484, abs=TOL) and b["bws_score"] == pytest.approx(2.06684, abs=TOL)
    assert b["bws_cat"] == 2 and b["bws_label"] == "Medium - High (20-40%)"
    assert b["w_awr_tex_tot_score"] == pytest.approx(4.05094, abs=TOL)

    r = BaselineWaterStress(load_rules()).assess(c)
    assert r.status == RiskStatus.WATCH and r.headline == "Watch: medium–high water stress (20.9%)"
    assert r.values.raw == pytest.approx(0.209484, abs=TOL) and r.values.category == 2
    worst = r.drivers["worst_month"]
    assert worst["month"] == 3 and worst["raw"] == pytest.approx(0.333257, abs=TOL)
    bau50 = next(f for f in r.future if f.scenario == "bau" and f.year == 2050)
    assert bau50.raw == pytest.approx(0.366078, abs=TOL) and bau50.category == 2
    assert r.drivers["reporting_flag_water_stressed"] is False
    assert "Stress peaks in March at 33.3%, and under business as usual it reaches 36.6% by 2050, 3.4 points below the High line." in r.reason
    assert len(r.monthly) == 12 and len(r.future) == 9
