from __future__ import annotations

from abc import ABC
from dataclasses import dataclass
from typing import Any

from hydris_risk.config import RiskRules
from hydris_risk.data.nodata import is_nodata
from hydris_risk.models import (
    BasinContext, FutureValue, IndicatorValues, MatchMethod, MonthlyValue, RiskResult, RiskStatus,
)
from hydris_risk.reasoning import formatters as F
from hydris_risk.reasoning.reason_builder import ReasonBuilder

SCENARIOS = ("bau", "opt", "pes")
YEARS = (30, 50, 80)


@dataclass(frozen=True)
class RiskMeta:
    risk_id: str
    name: str
    group: str
    vintage: str
    has_monthly: bool
    future_code: str | None
    what_it_measures: str
    factory_impact: str


def _label(v: Any) -> str | None:
    return None if v is None or v != v or str(v).strip().lower() in ("", "no data") else str(v)


# special case -> rules key holding its status. Data-driven: a risk opts in by having the key in risk_rules.yaml.
CASE_STATUS = {"arid": "arid_status", "insignificant": "insignificant_status", "no_risk": "no_risk_status",
               "low_collection": "low_collection_status"}


def _num(row: dict[str, Any] | None, key: str) -> float | None:
    """Row value as float, or None if missing/NoData."""
    if row is None or is_nodata(row.get(key)):
        return None
    return float(row[key])


class RiskService(ABC):
    """One risk. Subclasses set the three class attributes; text, unit and thresholds come from risk_rules.yaml."""

    risk_id: str
    col_prefix: str | None = None  # baseline column prefix if not the risk_id (overall_textile)
    has_monthly: bool = False
    future_code: str | None = None

    def __init__(self, rules: RiskRules):
        self.rules = rules
        self.cfg = rules.for_risk(self.risk_id)
        self.meta = RiskMeta(
            risk_id=self.risk_id, name=self.cfg["name"], group=self.cfg["group"], vintage=self.cfg["vintage"],
            has_monthly=self.has_monthly, future_code=self.future_code,
            what_it_measures=self.cfg["what_it_measures"], factory_impact=self.cfg["impact_present"],
        )
        self.builder = ReasonBuilder(self.meta, rules)

    # -- public ---------------------------------------------------------------
    def assess(self, ctx: BasinContext) -> RiskResult:
        try:
            if ctx.match_method == MatchMethod.UNMATCHED:
                return self._result(ctx, RiskStatus.NO_DATA, *self.builder.unmatched(), IndicatorValues())
            values = self.extract(ctx)
            monthly = self.extract_monthly(ctx) if self.meta.has_monthly else []
            future = self.extract_future(ctx) if self.meta.future_code else []
            status = self.classify(values, ctx)
            drivers = self.drivers(values, monthly, future, ctx)
            caveats = self.caveats(values, ctx)
            headline, reason = self.builder.build(status, values, monthly, future, drivers, ctx)
            return self._result(ctx, status, headline, reason, values, monthly, future, drivers, caveats)
        except Exception as e:  # one failing service must not stop the others
            msg = f"{type(e).__name__}: {e}"
            return self._result(ctx, RiskStatus.ERROR, *self.builder.error(msg), IndicatorValues(), drivers={"error_message": msg})

    def _result(self, ctx, status, headline, reason, values, monthly=(), future=(), drivers=None, caveats=()):
        return RiskResult(
            site_id=ctx.factory.site_id, risk_id=self.meta.risk_id, risk_name=self.meta.name, group=self.meta.group, kind=self.cfg["kind"], scale=self.cfg.get("scale"),
            status=status, headline=headline, reason=reason, values=values, monthly=list(monthly), future=list(future),
            drivers=drivers or {}, caveats=list(caveats), source=self.cfg["source"],
            indicator_vintage=self.meta.vintage, pfaf_id=ctx.pfaf_id, string_id=ctx.string_id,
        )

    # -- overridable defaults ----------------------------------------------------
    def case(self, values: IndicatorValues, ctx: BasinContext) -> str | None:
        """Special case (see CASE_STATUS) that overrides the default status and wording, or None."""
        cat, label = values.category, (values.label or "").lower()
        if cat == -1:
            return next((c for c in ("arid", "no_risk", "low_collection") if CASE_STATUS[c] in self.cfg), None)
        if cat is None and label.startswith("insignificant") and "insignificant_status" in self.cfg:
            return "insignificant"
        return None

    def extract(self, ctx: BasinContext) -> IndicatorValues:
        b, rid = ctx.baseline, self.col_prefix or self.meta.risk_id
        raw, cat = _num(b, f"{rid}_raw"), _num(b, f"{rid}_cat")
        if cat == -1 and "arid_status" in self.cfg:
            raw = None  # raw 1.0 is a placeholder in arid basins; show the label, never "100%"
        return IndicatorValues(
            raw=raw, raw_display=F.fmt_raw_display(raw, self.cfg), unit=self.cfg.get("unit"),
            score=_num(b, f"{rid}_score"), category=None if cat is None else int(cat), label=_label(b.get(f"{rid}_label")),
        )

    def classify(self, values: IndicatorValues, ctx: BasinContext) -> RiskStatus:
        cat = values.category
        if case := self.case(values, ctx):
            return RiskStatus(self.cfg[CASE_STATUS[case]])
        if cat is None:
            return RiskStatus.NO_DATA
        if cat >= self.cfg["present_min_cat"]:
            return RiskStatus.PRESENT
        if cat >= self.cfg["watch_min_cat"]:
            return RiskStatus.WATCH
        return RiskStatus.NOT_PRESENT

    def extract_monthly(self, ctx: BasinContext) -> list[MonthlyValue]:
        rid = self.meta.risk_id
        out = []
        for m in range(1, 13):
            cat = _num(ctx.monthly, f"{rid}_{m:02d}_cat")
            out.append(MonthlyValue(month=m, raw=_num(ctx.monthly, f"{rid}_{m:02d}_raw"),
                                    category=None if cat is None else int(cat)))
        return out

    def extract_future(self, ctx: BasinContext) -> list[FutureValue]:
        fc, out = self.meta.future_code, []
        for sc in SCENARIOS:
            for yy in YEARS:
                key = f"{sc}{yy}_{fc}_x_"
                cat = _num(ctx.future, key + "c")
                out.append(FutureValue(
                    scenario=sc, year=2000 + yy, raw=_num(ctx.future, key + "r"),
                    category=None if cat is None else int(cat),
                    label=_label((ctx.future or {}).get(key + "l")),
                ))
        return out

    def drivers(self, values: IndicatorValues, monthly: list[MonthlyValue], future: list[FutureValue],
                ctx: BasinContext) -> dict[str, Any]:
        d: dict[str, Any] = {}
        if (case := self.case(values, ctx)):
            d["case"] = case
        if values.category == -1:  # arid placeholders: monthly/future values are not meaningful
            return d
        valid = [m for m in monthly if m.raw is not None and m.category is not None and m.category >= 0]
        if valid:
            w = max(valid, key=lambda m: m.raw)
            d["worst_month"] = {"month": w.month, "raw": w.raw, "category": w.category}
            d["months_high"] = sum(m.category >= self.cfg["present_min_cat"] for m in valid)
        bau = next((x for x in future if x.scenario == "bau" and x.year == 2050 and x.raw is not None), None)
        if bau and (bau.category is None or bau.category >= 0):
            thr = self.cfg.get("thresholds")
            line = thr[self.cfg["present_min_cat"] - 1] if thr else None
            d["bau2050"] = {
                "raw": bau.raw, "delta": None if values.raw is None else bau.raw - values.raw,
                "gap": None if line is None else bau.raw - line,
            }
        return d

    def extra_caveats(self, values: IndicatorValues, ctx: BasinContext) -> list[str]:
        """Data-dependent service-specific caveats (override)."""
        return []

    def caveats(self, values: IndicatorValues, ctx: BasinContext) -> list[str]:
        """Shown separately from the reason. Order: location notes, service-specific, basin-level, source."""
        T, cfg = self.rules.templates, self.cfg
        out = list(ctx.caveats)
        if ctx.match_method == MatchMethod.NEAREST and ctx.snap_distance_km is not None:
            out.insert(0, T["snapped"].format(km=f"{ctx.snap_distance_km:.1f}"))
        out += cfg.get("caveats", [])
        out += self.extra_caveats(values, ctx)
        if cfg.get("basin_caveat"):
            out.append(cfg["basin_caveat"])
        if self.meta.vintage == "3.0":
            period = f" (data {cfg['data_period']})" if cfg.get("data_period") else ""
            out.append(T["caveat_source_3_0"].format(period=period))
        else:
            out.append(T["caveat_source_4_0"])
        return out
