from hydris_risk.services.base import RiskService


class WaterDepletion(RiskService):
    risk_id = "bwd"
    has_monthly = True
    future_code = "wd"
