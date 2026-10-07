"""Point-in-polygon on baseline_annual. Baseline values always come from the containing polygon row
(string_id), never from a pfaf_id lookup: some indicators follow province/aquifer boundaries."""
from __future__ import annotations

import math

import geopandas as gpd
import pandas as pd

from hydris_risk.data.aqueduct_repository import AqueductRepository
from hydris_risk.models import BasinContext, Factory, MatchMethod


def _none(v):
    if v is None or pd.isna(v):
        return None
    return v.item() if hasattr(v, "item") else v  # numpy scalar -> plain Python (JSON-safe)


class Locator:
    def __init__(self, repo: AqueductRepository, nearest_tolerance_km: float = 5, metric_crs: str = "EPSG:6933"):
        self.repo, self.tol, self.metric = repo, nearest_tolerance_km, metric_crs

    def locate(self, factories: list[Factory]) -> list[BasinContext]:
        polys = self.repo.baseline_polygons()
        pts = gpd.GeoDataFrame(
            {"i": range(len(factories))},
            geometry=gpd.points_from_xy([f.lon for f in factories], [f.lat for f in factories]),
            crs="EPSG:4326",
        )
        joined = pts.sjoin(polys[["geometry"]], predicate="within").sort_values(["i", "index_right"])
        within = joined.groupby("i")["index_right"].agg(list).to_dict()
        out = []
        for i, f in enumerate(factories):
            hits = within.get(i)
            if hits:
                caveats = ["Point lies on an overlap of several Aqueduct polygons; the first was used."] if len(hits) > 1 else []
                out.append(self._ctx(f, polys.iloc[hits[0]], MatchMethod.WITHIN, None, caveats))
            elif (near := self._nearest(pts.geometry.iloc[i], polys)) is not None:
                out.append(self._ctx(f, polys.loc[near[0]], MatchMethod.NEAREST, near[1], []))
            else:
                out.append(self._ctx(f, None, MatchMethod.UNMATCHED, None, []))
        return out

    def _nearest(self, point, polys: gpd.GeoDataFrame):
        """(polygon index, km) of the closest polygon within tolerance, else None. Only polygons whose
        bbox is near the point are projected, so we never reproject all 68k polygons."""
        deg = self.tol / 111 / max(0.2, abs(math.cos(math.radians(point.y)))) + 0.01
        cand = polys.iloc[polys.sindex.query(point.buffer(deg), predicate="intersects")]
        if cand.empty:
            return None
        d = cand.geometry.to_crs(self.metric).distance(gpd.GeoSeries([point], crs=4326).to_crs(self.metric).iloc[0]) / 1000
        # ponytail: EPSG:6933 distorts distance away from 30N/S; use a local UTM/azimuthal CRS if sub-km accuracy matters
        idx = d.idxmin()
        return (idx, float(d[idx])) if d[idx] <= self.tol else None

    def _ctx(self, f: Factory, row, method: MatchMethod, snap_km, caveats: list[str]) -> BasinContext:
        base = dict(factory=f, match_method=method, snap_distance_km=snap_km, dataset_version=self.repo.dataset_version(),
                    caveats=caveats)
        if row is None:
            return BasinContext(**base)
        baseline = {k: _none(v) for k, v in row.drop("geometry").items()}
        pfaf = _none(baseline["pfaf_id"])
        pfaf = int(pfaf) if pfaf is not None else None
        aqid = _none(baseline["aqid"])
        return BasinContext(
            **base, string_id=baseline["string_id"], pfaf_id=pfaf, gid_1=baseline["gid_1"],
            aqid=int(aqid) if aqid is not None else None, name_0=baseline["name_0"], name_1=baseline["name_1"],
            area_km2=baseline["area_km2"], baseline=baseline,
            monthly=self.repo.monthly_by_pfaf(pfaf), future=self.repo.future_by_pfaf(pfaf),
        )
