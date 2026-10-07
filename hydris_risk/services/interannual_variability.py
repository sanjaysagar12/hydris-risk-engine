from hydris_risk.services.base import RiskService


class InterannualVariability(RiskService):
    risk_id = "iav"
    has_monthly = True
    future_code = "iv"
