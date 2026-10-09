from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseModel):
    gdb_glob: str = "data/raw/**/*.gdb"
    gdb_path: str | None = None
    cache_dir: str = "data/cache"
    metric_crs: str = "EPSG:6933"
    nearest_tolerance_km: float = 5

    def find_gdb(self) -> Path | None:
        if self.gdb_path:
            return ROOT / self.gdb_path
        return next(iter(sorted(ROOT.glob(self.gdb_glob))), None)

    @property
    def cache_path(self) -> Path:
        return ROOT / self.cache_dir


class RiskRules(BaseModel):
    defaults: dict[str, Any]
    risks: dict[str, dict[str, Any]]
    templates: dict[str, Any] = {}

    def for_risk(self, risk_id: str) -> dict[str, Any]:
        """Defaults overlaid with the risk's own block."""
        return {**self.defaults, **self.risks[risk_id]}


def load_settings(path: Path = ROOT / "config" / "settings.yaml") -> Settings:
    return Settings(**yaml.safe_load(path.read_text(encoding="utf-8")))


def load_rules(path: Path = ROOT / "config" / "risk_rules.yaml") -> RiskRules:
    return RiskRules(**yaml.safe_load(path.read_text(encoding="utf-8")))
