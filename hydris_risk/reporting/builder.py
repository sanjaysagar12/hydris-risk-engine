"""EngineOutput -> ReportDocument. Pure: no clock, no I/O except reading docs/limitations.md."""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime

from hydris_risk import __version__
from hydris_risk.config import ROOT, RiskRules
from hydris_risk.engine import OVERALL, EngineOutput, FactorySummary
from hydris_risk.models import BasinContext, MatchMethod, RiskResult, RiskStatus
from hydris_risk.reasoning import formatters as F
from hydris_risk.reporting.charts import monthly_chart_png, overall_chart_png
from hydris_risk.reporting.explain import explain, fmt_line, outlook_sentence
from hydris_risk.reporting.models import FactoryReport, PortfolioSummary, ReportDocument, RiskBlock

LIMITATIONS_FILE = ROOT / "docs" / "limitations.md"
LOCAL_SCALES = {"sub-basin", "aquifer"}  # country-level and composite values say nothing local
STATUS_SECTIONS = {
    RiskStatus.PRESENT: "present", RiskStatus.WATCH: "watch", RiskStatus.NOT_PRESENT: "not_present",
    RiskStatus.NO_DATA: "no_data", RiskStatus.ERROR: "no_data", RiskStatus.NOT_APPLICABLE: "no_data",
}


def most_common_local(summary: list[FactorySummary], rules: RiskRules) -> tuple[str, int] | None:
    """(risk_id, number of sites) of the local risk most often Present; same rule as the app's KPI."""
    counts = Counter(r for s in summary for r in s.present_risks if rules.risks[r].get("scale") in LOCAL_SCALES)
    return counts.most_common(1)[0] if counts else None


def report_filename(report_type: str, site_id: str | None, generated_at: datetime, ext: str) -> str:
    stamp = generated_at.strftime("%Y%m%d")
    middle = "portfolio" if report_type == "portfolio" else re.sub(r"[^A-Za-z0-9_.-]+", "_", site_id or "factory")
    return f"hydris_risk_report_{middle}_{stamp}.{ext}"


def read_limitations(path=LIMITATIONS_FILE) -> list[str]:
    """Bullets of docs/limitations.md, one string each, with markdown bold markers removed."""
    out: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("- "):
            out.append(re.sub(r"\*\*|`", "", line[2:]).strip())
        elif line.strip() and out:  # continuation line
            out[-1] += " " + line.strip()
    return out


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1] if names else ""


def build_report(out: EngineOutput, rules: RiskRules, report_type: str, site_ids: list[str] | None,
                 generated_at: datetime) -> ReportDocument:
    """All 14 results of every selected factory, regardless of any UI filter."""
    T = rules.report_templates
    known = [c.factory.site_id for c in out.contexts]
    ids = list(site_ids) if site_ids else known
    if missing := [i for i in ids if i not in known]:
        raise ValueError(f"Unknown site_id(s): {missing}. Available: {known}")
    if report_type == "factory" and len(ids) != 1:
        raise ValueError("A factory report needs exactly one site_id; use report_type='portfolio' for several.")

    ctx_by = {c.factory.site_id: c for c in out.contexts}
    sum_by = {s.site_id: s for s in out.summary}
    res_by: dict[str, list[RiskResult]] = {}
    for r in out.results:
        res_by.setdefault(r.site_id, []).append(r)
    factories = [_factory(ctx_by[i], res_by[i], sum_by[i], rules) for i in ids]

    first = ctx_by[ids[0]]
    subtitle = (f"{T['report_type_label']['factory']}: {first.factory.site_name}" if report_type == "factory"
                else f"{T['report_type_label']['portfolio']}: {len(ids)} factories")
    portfolio = _portfolio([ctx_by[i] for i in ids], [sum_by[i] for i in ids], factories, rules) if report_type == "portfolio" else None
    return ReportDocument(
        report_type=report_type, title=T["title"], subtitle=subtitle, generated_at=generated_at,
        hydris_version=__version__, dataset_version=first.dataset_version, disclaimer=T["disclaimer"],
        citation=T["citation"], citation_url=T["citation_url"], data_license=T["data_license"],
        portfolio=portfolio, factories=factories, methodology=_methodology(rules), methodology_intro=T["methodology_intro"],
        methodology_notes=[T["methodology_threshold_note"], T["methodology_note_arid"]],
        status_definitions=[{"status": k, "text": v} for k, v in T["status_definitions"].items()],
        limitations=read_limitations(),
    )


# ---- one factory -------------------------------------------------------------------------------------------
def _block(r: RiskResult, rules: RiskRules, ctx: BasinContext) -> RiskBlock:
    e = explain(r, rules, ctx.name_0)
    trend = r.drivers.get("trend_sentence")
    why = r.reason.replace(trend, "").replace("  ", " ").strip() if trend else r.reason  # trend lives in Outlook
    composite = r.risk_id == OVERALL
    values = r.values.model_copy(update={"raw": None}) if composite else r.values  # composite raw is pre-remapping: score only
    return RiskBlock(
        risk_id=r.risk_id, risk_name=r.risk_name, group=r.group,
        kind="composite" if r.risk_id == OVERALL else r.kind, scale=r.scale or "", vintage=r.indicator_vintage,
        status=r.status, status_word=rules.templates["status_word"][r.status.value], headline=r.headline, why=why,
        detail="full" if composite or r.status in (RiskStatus.PRESENT, RiskStatus.WATCH) else "compact",
        threshold_position=e.threshold_position, what_would_change=e.what_would_change, extra_notes=e.extra_notes,
        outlook_rows=[f for f in r.future if f.raw is not None], outlook_table=_outlook_table(r, rules), outlook_sentence=outlook_sentence(r, rules),
        monthly_chart_png=monthly_chart_png(r.monthly, rules.for_risk(r.risk_id), f"{r.risk_name}: monthly") if r.monthly else None,
        values=values, source=r.source, pfaf_id=r.pfaf_id, string_id=r.string_id, caveats=r.caveats,
    )


def _outlook_table(r: RiskResult, rules: RiskRules) -> list[dict[str, str]]:
    """One row per scenario with values formatted for display; empty for indicators without future values."""
    T, cfg = rules.report_templates, rules.for_risk(r.risk_id)
    today = F.fmt_value(r.values.raw, cfg, keep_decimals=True) if r.values.raw is not None and r.values.category != -1 else ""
    rows = []
    for sc in ("bau", "opt", "pes"):
        by_year = {f.year: f.raw for f in r.future if f.scenario == sc and f.raw is not None}
        if by_year:
            rows.append({"scenario": T["scenario_long"][sc], "today": today,
                         **{str(y): F.fmt_value(by_year[y], cfg, keep_decimals=True) if y in by_year else "" for y in (2030, 2050, 2080)}})
    return rows


def _header(ctx: BasinContext, rules: RiskRules) -> tuple[dict, list[str]]:
    f, T = ctx.factory, rules.templates
    warning, caveats = None, list(ctx.caveats)
    if ctx.match_method == MatchMethod.UNMATCHED:
        warning = T["unmatched"]
    elif ctx.match_method == MatchMethod.NEAREST and ctx.snap_distance_km is not None:
        warning = T["snapped"].format(km=f"{ctx.snap_distance_km:.1f}")
    header = {
        "name": f.site_name, "site_id": f.site_id, "lat": f.lat, "lon": f.lon, "pfaf_id": ctx.pfaf_id,
        "string_id": ctx.string_id, "state": ctx.name_1, "country": ctx.name_0 or f.country,
        "match_method": ctx.match_method.value, "snap_distance_km": ctx.snap_distance_km, "match_warning": warning,
    }
    return {k: v for k, v in header.items() if v is not None}, caveats


def _glance(ctx: BasinContext, summ: FactorySummary, blocks: dict[str, RiskBlock], rules: RiskRules) -> str:
    T, name = rules.report_templates, ctx.factory.site_name
    if ctx.match_method == MatchMethod.UNMATCHED:
        return T["glance_unmatched"].format(name=name)
    names = lambda ids: _join([rules.risks[i]["name"] for i in ids])  # noqa: E731
    parts = [T["glance_counts"].format(name=name, n_present=summ.n_present, n_watch=summ.n_watch,
                                       n_assessed=sum(summ.counts.values()))]
    parts.append(T["glance_present"].format(names=names(summ.present_risks)) if summ.present_risks else T["glance_present_none"])
    parts.append(T["glance_watch"].format(names=names(summ.watch_risks)) if summ.watch_risks else T["glance_watch_none"])
    if summ.overall_textile_score is not None:
        parts.append(T["glance_overall"].format(score=f"{summ.overall_textile_score:.2f}", label=F.clean_label(summ.overall_textile_label)))
    for status, key in (("no_data", "glance_no_data"), ("error", "glance_error")):
        n = summ.counts.get(status, 0)
        if n:
            parts.append(T[f"{key}_one"] if n == 1 else T[f"{key}_many"].format(n=n))
    for b in blocks.values():
        if b.kind == "impact" and b.status in (RiskStatus.PRESENT, RiskStatus.WATCH):
            parts.append(T["glance_impact"].format(name=rules.risks[b.risk_id].get("short_name", b.risk_name), status=b.status_word))
    return " ".join(parts)


def _factory(ctx: BasinContext, results: list[RiskResult], summ: FactorySummary, rules: RiskRules) -> FactoryReport:
    order = {rid: i for i, rid in enumerate(rules.risks)}
    blocks = {r.risk_id: _block(r, rules, ctx) for r in sorted(results, key=lambda r: order[r.risk_id])}
    sections: dict[str, list[RiskBlock]] = {k: [] for k in ("present", "watch", "not_present", "no_data", "impact")}
    for b in blocks.values():
        if b.kind == "composite":
            continue
        sections["impact" if b.kind == "impact" else STATUS_SECTIONS[b.status]].append(b)
    header, caveats = _header(ctx, rules)
    summary_rows = [{
        "risk_id": b.risk_id, "risk": b.risk_name, "group": b.group, "scale": b.scale, "status": b.status.value,
        "status_word": b.status_word, "kind": b.kind, "value": b.values.raw_display or "", "label": b.values.label or "",
        "raw": f"{b.values.raw:.6g}" if b.values.raw is not None else "", "unit": b.values.unit or "",
        "score": f"{b.values.score:.2f}" if b.values.score is not None else "",
        "category": str(b.values.category) if b.values.category is not None else "", "vintage": b.vintage,
    } for b in blocks.values()]
    T = rules.report_templates
    ov = next(r for r in results if r.risk_id == OVERALL)
    return FactoryReport(
        context_header=header, location_caveats=caveats, counts=summ.counts, at_a_glance=_glance(ctx, summ, blocks, rules),
        summary_rows=summary_rows, overall=blocks[OVERALL],
        overall_chart_png=overall_chart_png(ov.drivers.get("groups", {}), rules.risks[OVERALL]["group_names"]), present=sections["present"], watch=sections["watch"],
        not_present=sections["not_present"], no_data=sections["no_data"], impact=sections["impact"],
        not_present_framing=T["not_present_framing"], impact_intro=T["impact_intro"],
    )


# ---- portfolio ---------------------------------------------------------------------------------------------
def _portfolio(ctxs: list[BasinContext], sums: list[FactorySummary], factories: list[FactoryReport],
               rules: RiskRules) -> PortfolioSummary:
    T = rules.report_templates
    columns = [{"risk_id": rid, "name": c["name"], "short_name": c.get("short_name", c["name"]), "group": c["group"],
                "kind": c.get("kind", rules.defaults["kind"])} for rid, c in rules.risks.items() if rid != OVERALL]
    matrix = []
    for ctx, fr in zip(ctxs, factories, strict=True):
        by_id = {r["risk_id"]: r for r in fr.summary_rows}
        overall = fr.overall
        matrix.append({
            "site_id": ctx.factory.site_id, "site_name": ctx.factory.site_name, "state": ctx.name_1 or "", "country": ctx.name_0 or "",
            "cells": {c["risk_id"]: {"status": by_id[c["risk_id"]]["status"], "word": by_id[c["risk_id"]]["status_word"]} for c in columns},
            "overall_score": overall.values.score, "overall_label": F.clean_label(overall.values.label) or "",
            "overall_status": overall.status.value,
        })
    n = len(sums)
    top = most_common_local(sums, rules)
    unmatched = sum(s.match_method == MatchMethod.UNMATCHED for s in sums)
    kpis = {
        "factories": n, "with_present": sum(s.n_present > 0 for s in sums), "unmatched": unmatched,
        "most_common_local": rules.risks[top[0]]["name"] if top else None, "most_common_local_sites": top[1] if top else 0,
    }
    local_counts = Counter(r for s in sums for r in s.present_risks if rules.risks[r].get("scale") in LOCAL_SCALES)
    parts = []
    if local_counts:
        items = [T["portfolio_local_item"].format(name=rules.risks[r]["name"], n=k, total=n) for r, k in local_counts.most_common(3)]
        parts.append(T["portfolio_local"].format(items=_join(items)))
    else:
        parts.append(T["portfolio_local_none"])
    country = [rules.risks[r].get("short_name", rules.risks[r]["name"]) for r, c in rules.risks.items() if c.get("scale") == "country"]
    parts.append(T["portfolio_country"].format(names=_join(country)))
    if unmatched:
        parts.append(T["portfolio_unmatched"].format(n=unmatched, total=n))
    return PortfolioSummary(kpis=kpis, columns=columns, matrix=matrix, paragraph=" ".join(parts))


# ---- appendix ------------------------------------------------------------------------------------------------
def _methodology(rules: RiskRules) -> list[dict]:
    rows = []
    for rid in rules.risks:
        c = rules.for_risk(rid)
        thr = c.get("thresholds")
        rows.append({
            "risk_id": rid, "risk": c["name"], "what_it_measures": c["what_it_measures"], "unit": c.get("unit", ""),
            "scale": c.get("scale", ""), "vintage": c["vintage"], "kind": c.get("kind", "risk"),
            "watch_line": fmt_line(thr[c["watch_min_cat"] - 1], c) if thr else "",
            "present_line": fmt_line(thr[c["present_min_cat"] - 1], c) if thr else "",
        })
    return rows
