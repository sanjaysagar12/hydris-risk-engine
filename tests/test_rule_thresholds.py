"""The thresholds in risk_rules.yaml must reproduce Aqueduct's own categories on the real data (skipped without it)."""
import numpy as np
import pytest

from hydris_risk.config import load_rules, load_settings
from hydris_risk.data.aqueduct_repository import AqueductRepository
from hydris_risk.data.nodata import SENTINEL_MAX

RULES = load_rules()


@pytest.fixture(scope="module")
def baseline():
    s = load_settings()
    if s.find_gdb() is None:
        pytest.skip("real Aqueduct GDB not present")
    return AqueductRepository(s.find_gdb(), s.cache_path).baseline_polygons().drop(columns="geometry")


@pytest.mark.parametrize("rid", list(RULES.risks))
def test_thresholds_reproduce_the_published_categories(baseline, rid):
    raw, cat = (f"{rid}_raw", f"{rid}_cat") if rid != "overall_textile" else ("w_awr_tex_tot_score", "w_awr_tex_tot_cat")
    d = baseline[(baseline[raw].abs() < SENTINEL_MAX) & (baseline[cat] >= 0)]
    implied = np.searchsorted(np.array(RULES.risks[rid]["thresholds"], dtype=float), d[raw].to_numpy(), side="right")
    assert int((implied != d[cat].to_numpy()).sum()) == 0
