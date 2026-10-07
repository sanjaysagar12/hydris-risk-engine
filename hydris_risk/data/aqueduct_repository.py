"""Reads the Aqueduct GDB once, caches slim GeoParquet/Parquet, serves baseline polygons and by-pfaf rows."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
import pyogrio

IDS = ["string_id", "aq30_id", "pfaf_id", "gid_1", "aqid", "gid_0", "name_0", "name_1", "area_km2"]
INDICATORS = ["bws", "bwd", "iav", "sev", "gtd", "rfr", "cfr", "drr", "ucw", "cep", "udw", "usa", "rri"]
BASELINE_COL = re.compile(
    rf"^({'|'.join(INDICATORS)})_(raw|score|cat|label)$|^w_awr_tex_(qan|qal|rrr|tot)_(raw|score|cat|label)$"
    r"|^w_awr_tex_tot_weight_fraction$"
)
MONTHLY_COL = re.compile(r"^(bws|bwd|iav)_\d\d_(raw|score|cat|label)$")
FUTURE_COL = re.compile(r"^(bau|opt|pes)(30|50|80)_(ws|wd|iv|sv)_x_[rscl]$")


def _layer(layers: list[str], keyword: str) -> str:
    hits = [n for n in layers if keyword in n.lower()]
    if not hits:
        raise ValueError(f"No layer containing '{keyword}' in {layers}")
    return hits[0]


def _gdb_mtime(gdb: Path) -> float:
    return max(p.stat().st_mtime for p in [gdb, *gdb.rglob("*")])


class AqueductRepository:
    def __init__(self, gdb: str | Path, cache_dir: str | Path):
        self.gdb, self.cache = Path(gdb), Path(cache_dir)
        self.cache.mkdir(parents=True, exist_ok=True)
        self._baseline: gpd.GeoDataFrame | None = None
        self._monthly: pd.DataFrame | None = None
        self._future: pd.DataFrame | None = None

    # -- cache ---------------------------------------------------------------
    @property
    def _meta(self) -> Path:
        return self.cache / "cache_meta.json"

    def _fresh(self) -> bool:
        files = ["baseline_annual.parquet", "monthly.parquet", "future.parquet"]
        if not (self._meta.exists() and all((self.cache / f).exists() for f in files)):
            return False
        return json.loads(self._meta.read_text(encoding="utf-8")).get("gdb_mtime") == _gdb_mtime(self.gdb)

    def build_cache(self) -> None:
        names = [n for n, _ in pyogrio.list_layers(str(self.gdb))]

        def cols(layer: str, pat: re.Pattern, keep: list[str]) -> list[str]:
            have = pyogrio.read_info(str(self.gdb), layer=layer)["fields"]
            return [c for c in have if c in keep or pat.match(c)]

        b = _layer(names, "baseline_annual")
        gdf = pyogrio.read_dataframe(self.gdb, layer=b, columns=cols(b, BASELINE_COL, IDS))
        gdf.to_crs("EPSG:4326").to_parquet(self.cache / "baseline_annual.parquet")
        for key, pat, out in [("monthly", MONTHLY_COL, "monthly"), ("future", FUTURE_COL, "future")]:
            lyr = _layer(names, key)
            df = pyogrio.read_dataframe(
                self.gdb, layer=lyr, read_geometry=False, columns=cols(lyr, pat, ["pfaf_id"])
            )
            df.to_parquet(self.cache / f"{out}.parquet")
        self._meta.write_text(json.dumps({"gdb_mtime": _gdb_mtime(self.gdb), "version": self.gdb.name}), encoding="utf-8")
        self._baseline = self._monthly = self._future = None

    def _load(self) -> None:
        if self._baseline is not None:
            return
        if not self._fresh():
            self.build_cache()
        self._baseline = gpd.read_parquet(self.cache / "baseline_annual.parquet")
        self._baseline.sindex  # build the spatial index once
        self._monthly = pd.read_parquet(self.cache / "monthly.parquet").set_index("pfaf_id", drop=False)
        self._future = pd.read_parquet(self.cache / "future.parquet").set_index("pfaf_id", drop=False)

    # -- API -------------------------------------------------------------------
    def baseline_polygons(self) -> gpd.GeoDataFrame:
        self._load()
        return self._baseline

    def _row(self, df: pd.DataFrame, pfaf_id: int | None) -> dict[str, Any] | None:
        if pfaf_id is None or pfaf_id not in df.index:
            return None
        row = df.loc[pfaf_id]
        row = row.iloc[0] if isinstance(row, pd.DataFrame) else row
        # plain Python values, NaN -> None, so rows serialise to JSON
        return {k: None if pd.isna(v) else (v.item() if hasattr(v, "item") else v) for k, v in row.items()}

    def monthly_by_pfaf(self, pfaf_id: int | None) -> dict[str, Any] | None:
        self._load()
        return self._row(self._monthly, pfaf_id)

    def future_by_pfaf(self, pfaf_id: int | None) -> dict[str, Any] | None:
        self._load()
        return self._row(self._future, pfaf_id)

    def dataset_version(self) -> str:
        return self.gdb.name
