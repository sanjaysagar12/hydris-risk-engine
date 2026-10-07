"""Read and validate the factories CSV. Bad rows are reported and skipped; the rest still run."""
from __future__ import annotations

from pathlib import Path
from typing import IO, Literal

import pandas as pd
from pydantic import BaseModel, ValidationError

from hydris_risk.models import Factory

REQUIRED = ["site_id", "site_name", "lat", "lon"]
ALIASES = {"latitude": "lat", "longitude": "lon"}


class InputIssue(BaseModel):
    row: int | None  # CSV line number (header is line 1); None for file-level problems
    site_id: str | None = None
    level: Literal["error", "warning"]
    message: str

    def __str__(self) -> str:
        where = f"row {self.row}" if self.row else "file"
        return f"{self.level.upper()} ({where}{', ' + self.site_id if self.site_id else ''}): {self.message}"


def load_factories(path: str | Path | IO[bytes]) -> tuple[list[Factory], list[InputIssue]]:
    df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")  # -sig tolerates an Excel BOM
    df.columns = [ALIASES.get(c.strip().lower(), c.strip().lower()) for c in df.columns]
    if missing := [c for c in REQUIRED if c not in df.columns]:
        return [], [InputIssue(row=None, level="error", message=f"Missing required column(s): {', '.join(missing)}")]

    factories: list[Factory] = []
    issues: list[InputIssue] = []
    seen_ids: set[str] = set()
    seen_xy: dict[tuple[float, float], str] = {}
    for i, rec in enumerate(df.to_dict("records")):
        row = i + 2
        rec = {k: (v.strip() or None) for k, v in rec.items()}
        sid = rec.get("site_id")
        try:
            lat, lon = float(rec["lat"]), float(rec["lon"])
        except (TypeError, ValueError):
            issues.append(InputIssue(row=row, site_id=sid, level="error", message=f"lat/lon must be numbers (got {rec['lat']!r}, {rec['lon']!r})"))
            continue
        if abs(lat) > 90 and abs(lon) <= 90:
            issues.append(InputIssue(row=row, site_id=sid, level="error",
                                     message=f"lat={lat} is out of range but lon={lon} would be valid: lat/lon look swapped"))
            continue
        try:
            f = Factory(**{k: v for k, v in rec.items() if k in Factory.model_fields} | {"lat": lat, "lon": lon})
        except ValidationError as e:
            msg = "; ".join(f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors())
            issues.append(InputIssue(row=row, site_id=sid, level="error", message=msg))
            continue
        if f.site_id in seen_ids:
            issues.append(InputIssue(row=row, site_id=f.site_id, level="error", message="duplicate site_id; row skipped"))
            continue
        seen_ids.add(f.site_id)
        if (other := seen_xy.get((lat, lon))) is not None:
            issues.append(InputIssue(row=row, site_id=f.site_id, level="warning", message=f"same coordinates as site {other}"))
        seen_xy.setdefault((lat, lon), f.site_id)
        factories.append(f)
    return factories, issues
