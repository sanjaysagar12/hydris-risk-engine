"""Deterministic report sentences: where a value sits against the Watch/Present lines and what would change the status.

Every number comes from the RiskResult and the thresholds in risk_rules.yaml; all wording is in `report_templates`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from hydris_risk.config import RiskRules
from hydris_risk.models import FutureValue, RiskResult, RiskStatus
from hydris_risk.reasoning import formatters as F

SCENARIO_ORDER = ("bau", "opt", "pes")  # main sentence is bau; the others are added when they cross a line


@dataclass(frozen=True)
class Explanation:
    threshold_position: str | None = None
    what_would_change: str | None = None
    extra_notes: list[str] = field(default_factory=list)


# ---- number formatting -------------------------------------------------------------------------------------
def _unit_suffix(cfg: dict[str, Any]) -> str:
    unit = cfg.get("unit_display", cfg.get("unit"))
    return "" if unit in (None, "", "ratio") or cfg.get("display") in ("percent", "score") else unit


def fmt_line(line: float, cfg: dict[str, Any]) -> str:
    """A threshold as written in the rules: '40%', '0.80', '60/100', '4 cm/yr'."""
    if cfg.get("display") == "percent":  # `sig`: measured edges like 0.29867% are shown as 0.3%
        return f"{line * 100:.{cfg['sig']}g}%" if cfg.get("sig") else f"{line * 100:g}%"
    text = cfg.get("thresholds_fmt", "{:g}").format(line)
    unit = _unit_suffix(cfg)
    return f"{text}{unit}" if unit.startswith("/") else f"{text} {unit}" if unit else text


def fmt_gap(amount: float, cfg: dict[str, Any]) -> str:
    """Unsigned distance to a line: '16.4 points' for percentages, plain difference for indices."""
    amount = abs(amount)
    pct = cfg.get("display") == "percent"
    x = amount * 100 if pct else amount
    d = cfg.get("decimals", 1 if pct else 2)
    if cfg.get("sig") and x:  # small shares (flood): keep `sig` significant figures
        d = max(d, cfg["sig"] - 1 - math.floor(math.log10(x)))
    while round(x, d) == 0 and d < 12:  # never show "0.0 above" for a nonzero gap
        d += 1
    text = f"{x:.{d}f}"
    base = cfg.get("decimals", 1 if pct else 2)
    while d > base and text.endswith("0"):  # extra decimals were for significance, not padding
        text, d = text[:-1], d - 1
    unit = _unit_suffix(cfg)
    if pct or unit.startswith("/"):
        return f"{text} points"
    return f"{text} {unit}" if unit else text


def _gap_phrase(value: float, line: float, cfg: dict[str, Any], T: dict[str, Any]) -> str:
    if value == line:
        return T["gap_level"]
    return T["gap_above" if value > line else "gap_below"].format(amount=fmt_gap(value - line, cfg))


def _implied_category(raw: float, thresholds: list[float]) -> int:
    return sum(t <= raw for t in thresholds)


# ---- future crossings ----------------------------------------------------------------------------------------
def _usable(f: FutureValue) -> bool:
    return f.raw is not None and (f.category is None or f.category >= 0)


def _scenario_values(future: list[FutureValue], scenario: str) -> list[FutureValue]:
    return sorted((f for f in future if f.scenario == scenario and _usable(f)), key=lambda f: f.year)


def _crossing(values: list[FutureValue], watch: float, present: float) -> tuple[str | None, int | None]:
    """('present'|'watch'|None, first year) for the highest line reached by any projected year."""
    for level, line in (("present", present), ("watch", watch)):
        hit = next((f for f in values if f.raw >= line), None)
        if hit:
            return level, hit.year
    return None, None


_LEVEL = {None: 0, "watch": 1, "present": 2}


# ---- main entry points --------------------------------------------------------------------------------------
def explain(result: RiskResult, rules: RiskRules, country: str | None = None) -> Explanation:
    """Position sentence, what-would-change sentence and special-case notes for one result."""
    T, cfg = rules.report_templates, rules.for_risk(result.risk_id)
    status, case = result.status, result.drivers.get("case")
    notes: list[str] = []

    if status == RiskStatus.ERROR:
        return Explanation(extra_notes=[T["note_error"].format(message=result.drivers.get("error_message") or "Error")])
    if status == RiskStatus.NO_DATA:
        note = T["note_no_data_area" if result.pfaf_id is not None else "note_no_data_unmatched"]
        return Explanation(extra_notes=[note])

    if cfg.get("scale") == "country":
        notes.append(T["note_country_scale"].format(country=country or "this country"))

    position = change = None
    if case == "insignificant":
        change = T["change_gtd_insignificant"]
    elif case == "no_risk":
        position = T["position_no_risk"]
    elif case == "arid":
        position = T["position_arid"]
    elif case == "low_collection":
        notes.insert(0, T["note_low_collection"])
    elif result.risk_id != "overall_textile" and cfg.get("thresholds"):
        position, change = _generic(result, rules, cfg, T)
    return Explanation(position, change, notes)


def _val(raw: float, cfg: dict[str, Any]) -> str:
    """A value as written in report sentences: one decimal kept ('21.0%'), boundary-aware."""
    return F.fmt_value(raw, cfg, keep_decimals=True)


def _generic(result: RiskResult, rules: RiskRules, cfg: dict[str, Any], T: dict[str, Any]) -> tuple[str | None, str | None]:
    thr, status, v = cfg["thresholds"], result.status, result.values
    titles = F.cat_titles(cfg)
    watch, present = thr[cfg["watch_min_cat"] - 1], thr[cfg["present_min_cat"] - 1]
    is_impact = result.kind == "impact"
    subject = T["impact_subject"] if is_impact else "It"
    it = subject[:1].lower() + subject[1:] if is_impact else "it"
    fields = dict(
        subject=subject, it=it, present_title=titles[cfg["present_min_cat"]], watch_line=fmt_line(watch, cfg),
        present_line=fmt_line(present, cfg), top_line=fmt_line(thr[-1], cfg), name=cfg.get("short_name", result.risk_name),
    )

    consistent = v.raw is not None and v.category is not None and _implied_category(v.raw, thr) == v.category
    position = None
    top = status == RiskStatus.PRESENT and v.category is not None and v.category >= len(thr)
    if consistent:  # if the raw value and category disagree, say nothing rather than contradict the label
        fields["value_phrase"] = cfg.get("position_value", "{value}").format(value=_val(v.raw, cfg))
        fields["present_gap"] = _gap_phrase(v.raw, present, cfg, T)
        fields["watch_gap"] = _gap_phrase(v.raw, watch, cfg, T)
        key = "position_top" if top else "position_present" if status == RiskStatus.PRESENT else "position_two_lines"
        position = T[key].format(**fields)

    change = None
    if top:
        pass  # the position sentence already says it is the highest category
    elif status == RiskStatus.PRESENT:
        change = T["change_present"].format(**fields)
    elif status == RiskStatus.WATCH:
        change = T["change_watch"].format(**fields)
    elif status == RiskStatus.NOT_PRESENT:
        change = T["change_not_present"].format(**fields)
    if status in (RiskStatus.WATCH, RiskStatus.NOT_PRESENT):
        future = _future_sentences(result.future, status, watch, present, cfg, T, fields)
        if future:
            change = f"{change} {future}"
    return position, change


def _future_sentences(future: list[FutureValue], status: RiskStatus, watch: float, present: float,
                      cfg: dict[str, Any], T: dict[str, Any], fields: dict[str, Any]) -> str | None:
    """One sentence per scenario that crosses a line that matters, each named: Aqueduct's optimistic scenario can sit above
    business as usual. Scenarios that stay below say nothing (the Outlook shows their values)."""
    # a Watch site only cares about reaching Present; a Not-present site about reaching Watch or Present
    matters = (lambda lv: lv == "present") if status == RiskStatus.WATCH else (lambda lv: lv is not None)
    out = []
    for sc in SCENARIO_ORDER:
        values = _scenario_values(future, sc)
        if not values:
            continue
        level, year = _crossing(values, watch, present)
        if matters(level):
            key = "future_cross_present" if level == "present" else "future_reach_watch"
            out.append(T[key].format(**fields, scenario=T["scenario"][sc], year=year))
    return " ".join(out) or None


def outlook_sentence(result: RiskResult, rules: RiskRules) -> str | None:
    """The business-as-usual path in words. 'rises'/'falls' only when every step moves the same way; otherwise the turn is named."""
    cfg, T = rules.for_risk(result.risk_id), rules.report_templates
    bau = {f.year: f for f in _scenario_values(result.future, "bau")}
    base = result.values.raw
    if base is None or len(bau) < 3 or result.values.category == -1:
        return None
    series = [base, bau[2030].raw, bau[2050].raw, bau[2080].raw]
    span = (max(series) - min(series)) or 0
    fields = dict(name=cfg.get("short_name", result.risk_name), base=_val(base, cfg),
                  **{f"v{y % 100}": _val(bau[y].raw, cfg) for y in (2030, 2050, 2080)})
    steps = [b - a for a, b in zip(series, series[1:], strict=False)]
    if span / (abs(base) or 1) < 0.02:
        return T["outlook_flat"].format(**fields)
    if all(d >= 0 for d in steps):
        return T["outlook_up"].format(**fields)
    if all(d <= 0 for d in steps):
        return T["outlook_down"].format(**fields)
    sign = [d > 0 for d in steps]
    if sign[0] == sign[1] != sign[2]:  # turns after 2050
        return T["outlook_turn_late"].format(**fields, turn=T["outlook_turn"]["up" if sign[2] else "down"])
    if sign[0] != sign[1] == sign[2]:  # turns after 2030
        return T["outlook_turn_early"].format(**fields, turn=T["outlook_turn"]["up" if sign[1] else "down"])
    return T["outlook_irregular"].format(**fields)
