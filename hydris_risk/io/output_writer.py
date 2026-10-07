"""CSV (utf-8-sig, so Excel on Windows shows en dashes correctly) and JSON outputs."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from hydris_risk.engine import EngineOutput

LONG_COLUMNS = [
    "site_id", "site_name", "lat", "lon", "match_method", "pfaf_id", "string_id", "name_0", "name_1", "risk_id",
    "risk_name", "kind", "scale", "group", "status", "headline", "reason", "raw", "raw_display", "unit", "score", "category",
    "label", "worst_month", "bau2030_raw", "bau2050_raw", "caveats", "source", "indicator_vintage",
]


def _future_raw(result, scenario: str, year: int):
    return next((f.raw for f in result.future if f.scenario == scenario and f.year == year), None)


def long_frame(out: EngineOutput) -> pd.DataFrame:
    ctx = {c.factory.site_id: c for c in out.contexts}
    rows = []
    for r in out.results:
        c = ctx[r.site_id]
        rows.append({
            "site_id": r.site_id, "site_name": c.factory.site_name, "lat": c.factory.lat, "lon": c.factory.lon,
            "match_method": c.match_method.value, "pfaf_id": r.pfaf_id, "string_id": r.string_id,
            "name_0": c.name_0, "name_1": c.name_1, "risk_id": r.risk_id, "risk_name": r.risk_name, "kind": r.kind, "scale": r.scale,
            "group": r.group, "status": r.status.value, "headline": r.headline, "reason": r.reason,
            "raw": r.values.raw, "raw_display": r.values.raw_display, "unit": r.values.unit, "score": r.values.score,
            "category": r.values.category, "label": r.values.label,
            "worst_month": (r.drivers.get("worst_month") or {}).get("month"),
            "bau2030_raw": _future_raw(r, "bau", 2030), "bau2050_raw": _future_raw(r, "bau", 2050),
            "caveats": " | ".join(r.caveats), "source": r.source, "indicator_vintage": r.indicator_vintage,
        })
    return pd.DataFrame(rows, columns=LONG_COLUMNS)


def wide_frame(out: EngineOutput) -> pd.DataFrame:
    by_site: dict[str, dict] = {}
    for c in out.contexts:
        f = c.factory
        by_site[f.site_id] = {"site_id": f.site_id, "site_name": f.site_name, "lat": f.lat, "lon": f.lon,
                              "match_method": c.match_method.value, "pfaf_id": c.pfaf_id, "string_id": c.string_id,
                              "name_0": c.name_0, "name_1": c.name_1}
    for r in out.results:
        row = by_site[r.site_id]
        row[f"{r.risk_id}_status"] = r.status.value
        row[f"{r.risk_id}_raw"] = r.values.raw
        row[f"{r.risk_id}_score"] = r.values.score
        row[f"{r.risk_id}_label"] = r.values.label
    for s in out.summary:
        row = by_site[s.site_id]
        row.update({"n_present": s.n_present, "n_watch": s.n_watch, "n_not_present": s.counts["not_present"],
                    "n_no_data": s.counts["no_data"], "n_error": s.counts["error"],
                    "present_risks": ",".join(s.present_risks), "watch_risks": ",".join(s.watch_risks),
                    "impact_indicators_present": ",".join(s.impact_indicators_present)})
    return pd.DataFrame(list(by_site.values()))


def write_all(out: EngineOutput, directory: str | Path) -> dict[str, Path]:
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    paths = {"long": d / "results_long.csv", "wide": d / "results_wide.csv", "json": d / "results.json"}
    long_frame(out).to_csv(paths["long"], index=False, encoding="utf-8-sig")
    wide_frame(out).to_csv(paths["wide"], index=False, encoding="utf-8-sig")
    paths["json"].write_text(json.dumps(out.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
    return paths


def csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")


def json_bytes(out: EngineOutput) -> bytes:
    return json.dumps(out.model_dump(mode="json"), ensure_ascii=False, indent=2).encode("utf-8")
