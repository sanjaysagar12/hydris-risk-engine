from __future__ import annotations

from collections import Counter
from typing import Any

from pydantic import BaseModel

from hydris_risk.config import RiskRules, Settings, load_settings
from hydris_risk.data.aqueduct_repository import AqueductRepository
from hydris_risk.geo.locator import Locator
from hydris_risk.models import BasinContext, Factory, MatchMethod, RiskResult, RiskStatus
from hydris_risk.services.base import RiskService
from hydris_risk.services.registry import get_services

OVERALL = "overall_textile"


class FactorySummary(BaseModel):
    site_id: str
    match_method: MatchMethod
    counts: dict[str, int]  # by status, risks only (overall_textile and kind: impact excluded)
    n_present: int
    n_watch: int
    present_risks: list[str]
    watch_risks: list[str]
    impact_indicators_present: list[str] = []  # kind: impact, reported separately
    overall_textile_score: float | None = None
    overall_textile_label: str | None = None
    overall_textile_status: RiskStatus | None = None


class EngineOutput(BaseModel):
    contexts: list[BasinContext]
    results: list[RiskResult]
    summary: list[FactorySummary]
    errors: list[str]  # services that raised (status=error)


def _country_note(ctx: BasinContext) -> str | None:
    """Warn if the CSV's country disagrees with the polygon's country (a common sign of swapped lat/lon)."""
    given = (ctx.factory.country or "").strip().lower()
    if not given or ctx.match_method == MatchMethod.UNMATCHED:
        return None
    if given in {str(ctx.name_0 or "").lower(), str(ctx.baseline.get("gid_0") or "").lower()}:
        return None
    return (f"Input country '{ctx.factory.country}' differs from the Aqueduct country '{ctx.name_0}' at these "
            "coordinates; check that lat and lon are not swapped.")


class RiskEngine:
    def __init__(self, repo: AqueductRepository, rules: RiskRules, settings: Settings | None = None,
                 enabled: list[str] | None = None, services: list[RiskService] | None = None):
        s = settings or load_settings()
        self.locator = Locator(repo, s.nearest_tolerance_km, s.metric_crs)
        self.services = services if services is not None else get_services(rules, enabled)

    def run(self, factories: list[Factory]) -> EngineOutput:
        contexts = self.locator.locate(factories)
        for ctx in contexts:
            if note := _country_note(ctx):
                ctx.caveats.append(note)
        results = [self._assess(svc, ctx) for ctx in contexts for svc in self.services]
        by_site: dict[str, list[RiskResult]] = {}
        for r in results:
            by_site.setdefault(r.site_id, []).append(r)
        summary = [self._summarise(ctx, by_site.get(ctx.factory.site_id, [])) for ctx in contexts]
        errors = [f"{r.site_id}/{r.risk_id}: {r.reason}" for r in results if r.status == RiskStatus.ERROR]
        return EngineOutput(contexts=contexts, results=results, summary=summary, errors=errors)

    @staticmethod
    def _assess(svc: RiskService, ctx: BasinContext) -> RiskResult:
        return svc.assess(ctx)  # assess() converts exceptions to status=error for this risk only

    @staticmethod
    def _summarise(ctx: BasinContext, results: list[RiskResult]) -> FactorySummary:
        risks = [r for r in results if r.kind == "risk" and r.risk_id != OVERALL]
        count: Counter[str] = Counter(r.status.value for r in risks)
        overall: Any = next((r for r in results if r.risk_id == OVERALL), None)
        return FactorySummary(
            site_id=ctx.factory.site_id, match_method=ctx.match_method,
            counts={s.value: count.get(s.value, 0) for s in RiskStatus},
            n_present=count["present"], n_watch=count["watch"],
            present_risks=[r.risk_id for r in risks if r.status == RiskStatus.PRESENT],
            watch_risks=[r.risk_id for r in risks if r.status == RiskStatus.WATCH],
            impact_indicators_present=[r.risk_id for r in results if r.kind == "impact" and r.status == RiskStatus.PRESENT],
            overall_textile_score=overall.values.score if overall else None,
            overall_textile_label=overall.values.label if overall else None,
            overall_textile_status=overall.status if overall else None,
        )
