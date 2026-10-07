import geopandas as gpd
import pytest
from shapely.geometry import box

from hydris_risk.config import load_settings
from hydris_risk.data.aqueduct_repository import AqueductRepository
from hydris_risk.geo.locator import Locator
from hydris_risk.models import Factory, MatchMethod


def fac(sid, lat, lon):
    return Factory(site_id=sid, site_name=sid, lat=lat, lon=lon)


@pytest.fixture
def loc(synthetic_repo):
    return Locator(synthetic_repo, nearest_tolerance_km=5)


def test_within(loc):
    [c] = loc.locate([fac("a", 10.5, 10.5)])
    assert c.match_method == MatchMethod.WITHIN and c.snap_distance_km is None
    assert c.pfaf_id == 1001 and c.string_id == "1001-AAA.1_1-1" and c.name_1 == "Highland"
    assert c.baseline["bws_cat"] == 3 and "geometry" not in c.baseline
    assert c.monthly["bws_03_cat"] == 3 and c.future["bau50_ws_x_c"] == 3


def test_nearest_within_tolerance(loc):
    # 0.02 deg east of polygon A's edge (lon 11 is B's edge, so use west edge lon 10 of A): ~2.2 km
    [c] = loc.locate([fac("n", 10.5, 9.98)])
    assert c.match_method == MatchMethod.NEAREST and c.pfaf_id == 1001
    assert 1.5 < c.snap_distance_km < 3.0


def test_beyond_tolerance_is_unmatched(loc):
    [c] = loc.locate([fac("far", 10.5, 9.90)])  # ~11 km out
    assert c.match_method == MatchMethod.UNMATCHED and c.pfaf_id is None and c.baseline == {}


def test_ocean_point_unmatched(loc):
    [c] = loc.locate([fac("sea", -40.0, -120.0)])
    assert c.match_method == MatchMethod.UNMATCHED


def test_order_preserved_and_mixed_batch(loc):
    cs = loc.locate([fac("sea", -40, -120), fac("b", 10.5, 11.5), fac("c", 11.5, 10.5)])
    assert [c.factory.site_id for c in cs] == ["sea", "b", "c"]
    assert [c.pfaf_id for c in cs] == [None, 1002, 1003]


def test_overlap_keeps_first_with_caveat():
    class Stub:
        def baseline_polygons(self):
            row = {"string_id": "s", "pfaf_id": 1, "gid_1": "g", "aqid": 1, "name_0": "n", "name_1": "m", "area_km2": 1.0}
            return gpd.GeoDataFrame([{**row, "string_id": "first"}, {**row, "string_id": "second"}],
                                    geometry=[box(0, 0, 2, 2), box(1, 1, 3, 3)], crs=4326)

        monthly_by_pfaf = future_by_pfaf = lambda self, p: None
        dataset_version = lambda self: "stub"  # noqa: E731

    [c] = Locator(Stub()).locate([fac("o", 1.5, 1.5)])
    assert c.string_id == "first" and any("overlap" in x for x in c.caveats)


# --- real data: baseline values follow the containing polygon, not the pfaf_id ----------------------
@pytest.fixture(scope="module")
def real_loc():
    s = load_settings()
    gdb = s.find_gdb()
    if gdb is None:
        pytest.skip("real Aqueduct GDB not present")
    return Locator(AqueductRepository(gdb, s.cache_path), s.nearest_tolerance_km, s.metric_crs)


def test_tiruppur_resolves_to_tamil_nadu_polygon(real_loc):
    [c] = real_loc.locate([fac("tiruppur", 11.1085, 77.3411)])
    assert c.match_method == MatchMethod.WITHIN
    assert c.pfaf_id == 453803 and c.name_1 == "Tamil Nadu" and c.string_id == "453803-IND.31_1-2050"
    b = c.baseline
    assert b["gtd_raw"] == pytest.approx(-2.63896, abs=1e-4)
    assert b["udw_raw"] == pytest.approx(0.087757, abs=1e-4)
    assert b["usa_raw"] == pytest.approx(0.478314, abs=1e-4)
    # the Kerala/other-aquifer polygons of the same pfaf_id carry a different gtd_raw
    siblings = real_loc.repo.baseline_polygons().query("pfaf_id == 453803 and string_id != @c.string_id")
    assert len(siblings) == 4 and (siblings["gtd_raw"] - b["gtd_raw"]).abs().min() > 0.1
    # shared basin values still match the golden test
    assert b["bws_raw"] == pytest.approx(0.209484, abs=1e-4) and b["w_awr_tex_tot_score"] == pytest.approx(4.05094, abs=1e-4)
    assert c.monthly["bws_03_raw"] == pytest.approx(0.333257, abs=1e-4)
    assert c.future["bau50_ws_x_r"] == pytest.approx(0.366078, abs=1e-4)
