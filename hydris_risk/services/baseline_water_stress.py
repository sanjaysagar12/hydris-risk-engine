from hydris_risk.services.base import RiskService


class BaselineWaterStress(RiskService):
    risk_id = "bws"
    has_monthly = True
    future_code = "ws"

    def drivers(self, values, monthly, future, ctx):
        d = super().drivers(values, monthly, future, ctx)
        if values.raw is not None:
            d["reporting_flag_water_stressed"] = values.raw >= self.cfg["reporting_threshold"]
        return d
