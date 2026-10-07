from __future__ import annotations

from hydris_risk.config import RiskRules
from hydris_risk.services.base import RiskService
from hydris_risk.services.baseline_water_stress import BaselineWaterStress
from hydris_risk.services.coastal_eutrophication import CoastalEutrophication
from hydris_risk.services.coastal_flood import CoastalFlood
from hydris_risk.services.drinking_water_access import DrinkingWaterAccess
from hydris_risk.services.drought import Drought
from hydris_risk.services.groundwater_table_decline import GroundwaterTableDecline
from hydris_risk.services.interannual_variability import InterannualVariability
from hydris_risk.services.overall_textile import OverallTextile
from hydris_risk.services.reprisk_esg import RepriskEsg
from hydris_risk.services.riverine_flood import RiverineFlood
from hydris_risk.services.sanitation_access import SanitationAccess
from hydris_risk.services.seasonal_variability import SeasonalVariability
from hydris_risk.services.untreated_wastewater import UntreatedWastewater
from hydris_risk.services.water_depletion import WaterDepletion

# One line per risk: adding a service means one new file plus one line here.
REGISTRY: dict[str, type[RiskService]] = {
    s.risk_id: s
    for s in (
        BaselineWaterStress, WaterDepletion, InterannualVariability, SeasonalVariability, GroundwaterTableDecline,
        RiverineFlood, CoastalFlood, Drought, UntreatedWastewater, CoastalEutrophication, DrinkingWaterAccess,
        SanitationAccess, RepriskEsg, OverallTextile,
    )
}


def get_services(rules: RiskRules, enabled: list[str] | None = None) -> list[RiskService]:
    ids = enabled or list(REGISTRY)
    if unknown := [i for i in ids if i not in REGISTRY]:
        raise ValueError(f"Unknown risk id(s): {unknown}. Available: {list(REGISTRY)}")
    return [REGISTRY[i](rules) for i in ids]
