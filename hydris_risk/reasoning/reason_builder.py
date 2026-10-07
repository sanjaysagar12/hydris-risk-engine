"""Deterministic headline + reason from templates in risk_rules.yaml. Every number comes from the data.

Reason = verdict, what it measures, value, rule, impact (Present/Watch only), trend. Caveats are NOT part of the
reason; they are returned separately by RiskService.caveats().
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from hydris_risk.config import RiskRules
from hydris_risk.models import BasinContext, FutureValue, IndicatorValues, MonthlyValue, RiskStatus
from hydris_risk.reasoning import formatters as F

if TYPE_CHECKING:
    from hydris_risk.services.base import RiskMeta


def _lower_first(s: str) -> str:
    return s[:1].lower() + s[1:]


class ReasonBuilder:
    def __init__(self, meta: RiskMeta, rules: RiskRules):
        self.meta, self.rules = meta, rules
        self.cfg = rules.for_risk(meta.risk_id)
        self.T = rules.templates

    def _present_name(self) -> str:
        """e.g. 'High (40%+)' from the configured thresholds, else 'High'."""
        cat = self.cfg["present_min_cat"]
        title = F.cat_titles(self.cfg)[cat]
        thr = self.cfg.get("thresholds")
        if thr and 0 < cat <= len(thr):
            t = thr[cat - 1]
            return f"{title} ({t * 100:g}%+)" if self.cfg.get("display") == "percent" else f"{title} ({self.cfg.get('thresholds_fmt', '{:g}').format(t)}+)"
        return title

    def _fields(self, status, values: IndicatorValues, ctx: BasinContext) -> dict[str, Any]:
        c, name = self.cfg, self.meta.name
        titles = F.cat_titles(c)
        short = c.get("short_name", name)
        fields = dict(
            status=self.T["status_word"][status.value], name=name, name_l=_lower_first(name),
            short_name_l=_lower_first(short), peak_noun=c.get("peak_noun", short.capitalize()),
            pfaf_id=ctx.pfaf_id, place=F.place(ctx.name_1, ctx.name_0),
            raw_display=values.raw_display, raw_short=F.fmt_value(values.score if c.get("display") == "score" else values.raw, c),
            per_people=F.per_people(values.raw) if c.get("per_people") else None,
            country=ctx.name_0 or "this country", label_clean=F.clean_label(values.label),
            cat=values.category, cat_name=F.cat_name(values.category, c), cat_title=titles.get(values.category),
            present_name=self._present_name(), present_title=titles[c["present_min_cat"]],
            watch_name=titles[c["watch_min_cat"]],
        )
        return {k: "" if v is None else v for k, v in fields.items()}  # never leak "None" into text

    def build(self, status: RiskStatus, values: IndicatorValues, monthly: list[MonthlyValue],
              future: list[FutureValue], drivers: dict[str, Any], ctx: BasinContext) -> tuple[str, str]:
        T, cfg = self.T, self.cfg
        f = self._fields(status, values, ctx)
        case = cfg.get("cases", {}).get(drivers.get("case"), {})

        if "headline" in case:
            headline = case["headline"].format(**f)
        elif values.raw_display and values.category is not None:
            headline = cfg.get("headline", T["headline"]).format(**f)
        elif values.label:
            headline = T["headline_no_raw"].format(**f)
        else:
            headline = T["headline_no_value"].format(**f)

        if "value" in case:
            value = case["value"].format(**f)
        elif values.raw_display and values.label:
            value = cfg.get("value", T["value"]).format(**f)
        elif values.label:
            value = T["value_no_raw"].format(**f)
        else:
            value = None

        if "rule" in case:
            rule = case["rule"].format(**f)
        elif status == RiskStatus.NO_DATA:
            rule = T["rule_no_data"]
        elif status in (RiskStatus.PRESENT, RiskStatus.WATCH, RiskStatus.NOT_PRESENT) and values.category is not None:
            rule = T[f"rule_{status.value}"].format(**f)
        else:
            rule = None

        impact = None
        if status in (RiskStatus.PRESENT, RiskStatus.WATCH):
            impact = case.get("impact", cfg[f"impact_{status.value}"]).format(**f)
        if cfg.get("kind") == "impact":
            headline = T["kind_prefix"] + headline
        parts = [f"{f['status']}.", cfg["what_it_measures"], cfg.get("impact_note"), value, rule, impact, self._trend(f, drivers),
                 *drivers.get("sentences", [])]
        return headline, " ".join(p for p in parts if p)

    def _trend(self, f: dict[str, Any], d: dict[str, Any]) -> str | None:
        """'Stress peaks in March at 33.3%, and under business as usual it reaches 36.6% by 2050, 3.4 points below the High line.'"""
        T, cfg, pieces = self.T, self.cfg, []
        if (w := d.get("worst_month")) and w.get("raw") is not None:
            s = T["peak"].format(**f, month=F.month_name(w["month"]), value=F.fmt_value(w["raw"], cfg))
            if d.get("months_high"):
                s += T["peak_months"].format(**f, n=d["months_high"])
            pieces.append(s)
        if (b := d.get("bau2050")) and b.get("raw") is not None:
            s = T["future"].format(**f, value=F.fmt_value(b["raw"], cfg))
            if b.get("gap") is not None:
                s += T["gap_below" if b["gap"] < 0 else "gap_above"].format(**f, amount=F.fmt_amount(b["gap"], cfg))
            if (delta := b.get("delta")) is not None:
                if delta == 0:
                    s += T["unchanged"]
                elif cfg.get("display") == "percent" and abs(delta) * 100 < 0.5:
                    s += T["same"]
            pieces.append(s)
        if not pieces:
            return None
        text = ", and ".join(pieces)
        return text[:1].upper() + text[1:] + "."

    def unmatched(self) -> tuple[str, str]:
        return (f"{self.T['status_word']['no_data']}: not matched to an Aqueduct polygon",
                f"{self.T['status_word']['no_data']}. {self.T['unmatched']}")

    def error(self, message: str) -> tuple[str, str]:
        return (f"{self.T['status_word']['error']}: assessment failed",
                f"{self.T['status_word']['error']}. {self.T['error'].format(message=message)}")
