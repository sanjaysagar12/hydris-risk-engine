from hydris_risk.data.aqueduct_repository import INDICATORS
from hydris_risk.reasoning import formatters as F
from hydris_risk.services.base import RiskService, _num

GROUPS = ("qan", "qal", "rrr")


class OverallTextile(RiskService):
    """Reads w_awr_tex_tot_*; explains the score from the three group scores and the top indicators."""

    risk_id = "overall_textile"
    col_prefix = "w_awr_tex_tot"

    def extract(self, ctx):
        v = super().extract(ctx)
        v.raw_display = F.fmt_value(v.score, self.cfg)  # show the 0-5 score, not the pre-remap composite
        return v

    def drivers(self, values, monthly, future, ctx):
        b, d = ctx.baseline, {}
        groups = {}
        for g in GROUPS:
            score, cat = _num(b, f"w_awr_tex_{g}_score"), _num(b, f"w_awr_tex_{g}_cat")
            if score is not None:
                groups[g] = {"score": score, "category": None if cat is None else int(cat), "label": b.get(f"w_awr_tex_{g}_label")}
        top = sorted(
            ((i, s) for i in INDICATORS if (s := _num(b, f"{i}_score")) is not None and s >= 0), key=lambda x: -x[1]
        )[:3]
        d["groups"] = groups
        d["weight_fraction"] = _num(b, "w_awr_tex_tot_weight_fraction")
        d["top_indicators"] = [
            {"risk_id": i, "name": self.rules.risks[i]["name"], "score": s, "category": int(_num(b, f"{i}_cat") or -1)}
            for i, s in top
        ]
        d["sentences"] = self._sentences(values, d, b)
        return d

    def _sentences(self, values, d, b) -> list[str]:
        cfg, names, groups = self.cfg, self.cfg["group_names"], d["groups"]

        def fmt(score, cat):
            title = F.CAT_TITLES.get(cat)
            return f"{score:.2f}, {title}" if title else f"{score:.2f}"

        out = []
        if groups:
            parts = [f"{names[g]} ({fmt(x['score'], x['category'])})" for g, x in groups.items()]
            out.append(cfg["breakdown"].format(parts=", ".join(parts[:-1]) + " and " + parts[-1] if len(parts) > 1 else parts[0]))
        bws_cat, bws_label, qan = _num(b, "bws_cat"), F.clean_label(b.get("bws_label")), groups.get("qan")
        if qan and bws_label and bws_cat is not None and bws_cat >= 0 and values.category is not None and values.category > bws_cat:
            higher = [names[g] for g, x in groups.items() if x["score"] > qan["score"]]
            if higher:
                out.append(cfg["explain"].format(
                    tot=f"{values.score:.2f}", bws_label=bws_label, higher=" and ".join(higher),
                    verb="score" if len(higher) > 1 else "scores", qan=f"{qan['score']:.2f}"))
        if d["top_indicators"]:
            items = []
            for t in d["top_indicators"]:
                rc = self.rules.for_risk(t["risk_id"])
                title = F.cat_titles(rc).get(t["category"])
                items.append(f"{rc.get('short_name', t['name'])} ({t['score']:.2f}{', ' + title if title else ''})")
            out.append(cfg["top_indicators"].format(items=", ".join(items)))
        return out

    def extra_caveats(self, values, ctx):
        wf = _num(ctx.baseline, "w_awr_tex_tot_weight_fraction")
        if wf is None or wf >= 1:
            return []
        pct = round((1 - wf) * 100)
        return [self.cfg["incomplete_caveat"].format(pct=pct)]
