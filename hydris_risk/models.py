from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class Factory(BaseModel):
    site_id: str
    site_name: str
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    country: str | None = None
    sector: str | None = None
    address: str | None = None


class MatchMethod(str, Enum):
    WITHIN = "within"
    NEAREST = "nearest"
    UNMATCHED = "unmatched"


class BasinContext(BaseModel):
    factory: Factory
    match_method: MatchMethod
    snap_distance_km: float | None = None
    string_id: str | None = None
    pfaf_id: int | None = None
    gid_1: str | None = None
    aqid: int | None = None
    name_0: str | None = None
    name_1: str | None = None
    area_km2: float | None = None
    baseline: dict[str, Any] = {}
    monthly: dict[str, Any] | None = None
    future: dict[str, Any] | None = None
    dataset_version: str = ""
    caveats: list[str] = []  # locator-level notes (e.g. boundary match)


class RiskStatus(str, Enum):
    PRESENT = "present"
    WATCH = "watch"
    NOT_PRESENT = "not_present"
    NOT_APPLICABLE = "not_applicable"
    NO_DATA = "no_data"
    ERROR = "error"


class IndicatorValues(BaseModel):
    raw: float | None = None
    raw_display: str | None = None
    unit: str | None = None
    score: float | None = None
    category: int | None = None
    label: str | None = None


class FutureValue(BaseModel):
    scenario: Literal["bau", "opt", "pes"]
    year: Literal[2030, 2050, 2080]
    raw: float | None = None
    category: int | None = None
    label: str | None = None


class MonthlyValue(BaseModel):
    month: int
    raw: float | None = None
    category: int | None = None


class RiskResult(BaseModel):
    site_id: str
    risk_id: str
    risk_name: str
    group: str
    kind: Literal["risk", "impact"] = "risk"
    scale: str | None = None
    status: RiskStatus
    headline: str
    reason: str
    values: IndicatorValues
    monthly: list[MonthlyValue] = []
    future: list[FutureValue] = []
    drivers: dict[str, Any] = {}
    caveats: list[str] = []
    source: str
    indicator_vintage: str
    pfaf_id: int | None = None
    string_id: str | None = None
