"""Report configuration: the engine's rules plus the report wording in config/report_templates.yaml."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from hydris_risk.config import ROOT, RiskRules, load_rules


class ReportRules(RiskRules):
    report_templates: dict[str, Any]


def load_report_rules(rules_path: Path = ROOT / "config" / "risk_rules.yaml",
                      templates_path: Path = ROOT / "config" / "report_templates.yaml") -> ReportRules:
    templates = yaml.safe_load(templates_path.read_text(encoding="utf-8"))["report_templates"]
    return ReportRules(**load_rules(rules_path).model_dump(), report_templates=templates)
