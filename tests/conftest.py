"""Synthetic Aqueduct-like .gdb (3 polygons) using the real column conventions and NoData forms found in Step 0."""
from __future__ import annotations

import warnings
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from hydris_risk.data.aqueduct_repository import INDICATORS, AqueductRepository

NODATA = -9999.0
# (raw, score, cat, label) used for every indicator unless overridden
DEFAULT = (0.1, 1.0, 1, "Low - Medium (10-20%)")

# pfaf_id -> (polygon, overrides). A: inland high stress. B: coastal low stress. C: arid.
POLYS = {
    1001: dict(
        geom=box(10, 10, 11, 11), string_id="1001-AAA.1_1-1", gid_1="AAA.1_1", aqid=11, name_0="Inland", name_1="Highland",
        over={"bws": (0.5, 3.2, 3, "High (40-80%)"), "gtd": (-2.0, 0.0, NODATA, "Insignificant Trend"),
              "cfr": (NODATA, NODATA, NODATA, "No Data"), "cep": (NODATA, NODATA, NODATA, "No Data")},
        tex=(4.1, 4.0),
    ),
    1002: dict(
        geom=box(11, 10, 12, 11), string_id="1002-BBB.1_1-2", gid_1="BBB.1_1", aqid=12, name_0="Coastland", name_1="Shore",
        over={"bws": (0.05, 0.5, 0, "Low (<10%)"), "cfr": (0.004, 2.5, 2, "Medium - High (x)"), "gtd": (0.5, 0.5, 1, "Low - Medium (0-2 cm/y)"),
              "cep": (0.5, 2.5, 2, "Medium - High (0 to 1)")},
        tex=(1.5, 1.5),
    ),
    1003: dict(
        geom=box(10, 11, 11, 12), string_id="1003-CCC.1_1-3", gid_1="CCC.1_1", aqid=13, name_0="Dryland", name_1="Desert",
        over={"bws": (1.0, 5.0, -1, "Arid and Low Water Use"), "bwd": (1.0, 5.0, -1, "Arid and Low Water Use"),
              "ucw": (0.0, 0.0, -1, "No to Low Wastewater Collected"),
              "cfr": (0.0, 0.0, -1, "No Risk"), "gtd": (0.5, 0.5, 1, "Low - Medium (0-2 cm/y)")},
        tex=(3.0, 3.0),
    ),
}


def _baseline() -> gpd.GeoDataFrame:
    rows = []
    for pfaf, p in POLYS.items():
        row = dict(string_id=p["string_id"], aq30_id=f"aq{pfaf}", pfaf_id=pfaf, gid_1=p["gid_1"], aqid=p["aqid"],
                   gid_0="XXX", name_0=p["name_0"], name_1=p["name_1"], area_km2=100.0)
        for code in INDICATORS:
            raw, score, cat, label = p["over"].get(code, DEFAULT)
            row.update({f"{code}_raw": raw, f"{code}_score": score, f"{code}_cat": cat, f"{code}_label": label})
        tot, grp = p["tex"]
        for g in ("qan", "qal", "rrr", "tot"):
            v = tot if g == "tot" else grp
            row.update({f"w_awr_tex_{g}_raw": v - 1.0, f"w_awr_tex_{g}_score": v, f"w_awr_tex_{g}_cat": int(v),
                        f"w_awr_tex_{g}_label": "High (3-4)"})
        row["w_awr_tex_tot_weight_fraction"] = 1.0
        rows.append(row)
    df = pd.DataFrame(rows).astype({"pfaf_id": "int32", "aqid": "int32"})
    return gpd.GeoDataFrame(df, geometry=[p["geom"] for p in POLYS.values()], crs=4326)


def _monthly() -> gpd.GeoDataFrame:
    rows = []
    for pfaf, p in POLYS.items():
        row = {"pfaf_id": pfaf}
        for m in range(1, 13):
            for code in ("bws", "bwd", "iav"):
                raw, score, cat, label = p["over"].get(code, DEFAULT)
                row.update({f"{code}_{m:02d}_raw": raw, f"{code}_{m:02d}_score": score,
                            f"{code}_{m:02d}_cat": cat, f"{code}_{m:02d}_label": label})
        rows.append(row)
    df = pd.DataFrame(rows).astype({"pfaf_id": "int32"})
    return gpd.GeoDataFrame(df, geometry=[p["geom"] for p in POLYS.values()], crs=4326)


def _future() -> gpd.GeoDataFrame:
    rows = []
    for pfaf, p in POLYS.items():
        row = {"pfaf_id": pfaf}
        for sc in ("bau", "opt", "pes"):
            for yy in (30, 50, 80):
                for ind, base in (("ws", "bws"), ("wd", "bwd"), ("iv", "iav"), ("sv", "sev")):
                    raw, _, cat, label = p["over"].get(base, DEFAULT)
                    row.update({f"{sc}{yy}_{ind}_x_r": raw, f"{sc}{yy}_{ind}_x_c": float(cat),
                                f"{sc}{yy}_{ind}_x_l": label, f"{sc}{yy}_{ind}_x_s": 1.0})
        rows.append(row)
    df = pd.DataFrame(rows).astype({"pfaf_id": "int32"})
    return gpd.GeoDataFrame(df, geometry=[p["geom"] for p in POLYS.values()], crs=4326)


def build_gdb(path: Path) -> Path:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for name, gdf in (("baseline_annual", _baseline()), ("baseline_monthly", _monthly()), ("future_annual", _future())):
            gdf.to_file(path, layer=name, driver="OpenFileGDB")
    return path


@pytest.fixture(scope="session")
def synthetic_gdb(tmp_path_factory) -> Path:
    return build_gdb(tmp_path_factory.mktemp("gdb") / "synthetic.gdb")


@pytest.fixture(scope="session")
def synthetic_repo(synthetic_gdb, tmp_path_factory) -> AqueductRepository:
    return AqueductRepository(synthetic_gdb, tmp_path_factory.mktemp("cache"))


@pytest.fixture
def fresh_gdb(tmp_path) -> Path:
    """Private copy for tests that modify the GDB or its cache."""
    return build_gdb(tmp_path / "fresh.gdb")
