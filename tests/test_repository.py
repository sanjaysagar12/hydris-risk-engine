import os
import time

import pyogrio

from hydris_risk.data import aqueduct_repository as mod
from hydris_risk.data.aqueduct_repository import AqueductRepository


def _count_reads(monkeypatch):
    calls = []
    real = pyogrio.read_dataframe

    def spy(*a, **k):
        calls.append(k.get("layer"))
        return real(*a, **k)

    monkeypatch.setattr(mod.pyogrio, "read_dataframe", spy)
    return calls


def test_first_run_builds_then_cache_only(fresh_gdb, tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    calls = _count_reads(monkeypatch)
    r1 = AqueductRepository(fresh_gdb, cache)
    assert len(r1.baseline_polygons()) == 3
    assert len(calls) == 3  # baseline, monthly, future
    assert r1.monthly_by_pfaf(1001)["bws_03_cat"] == 3
    assert r1.future_by_pfaf(1001)["bau50_ws_x_c"] == 3
    assert r1.monthly_by_pfaf(999999) is None

    calls.clear()
    r2 = AqueductRepository(fresh_gdb, cache)  # new instance, same cache
    assert len(r2.baseline_polygons()) == 3 and r2.future_by_pfaf(1002) is not None
    assert calls == []  # GDB not read


def test_gdb_touch_triggers_rebuild(fresh_gdb, tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    AqueductRepository(fresh_gdb, cache).baseline_polygons()
    calls = _count_reads(monkeypatch)
    future = time.time() + 3600
    os.utime(next(fresh_gdb.glob("*.gdbtable")), (future, future))
    AqueductRepository(fresh_gdb, cache).baseline_polygons()
    assert len(calls) == 3


def test_cache_keeps_only_needed_columns(fresh_gdb, tmp_path):
    cols = set(AqueductRepository(fresh_gdb, tmp_path / "c").baseline_polygons().columns)
    assert {"string_id", "bws_raw", "w_awr_tex_tot_score", "geometry"} <= cols
    assert not any(c.startswith("w_awr_def") for c in cols)
