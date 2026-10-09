import json

import pandas as pd
import pytest

from hydris_risk.config import load_rules, load_settings
from hydris_risk.engine import RiskEngine
from hydris_risk.io.output_writer import write_all
from hydris_risk.models import Factory, RiskStatus
from hydris_risk.services.registry import REGISTRY, get_services

RULES = load_rules()


def fac(sid, lat, lon, **kw):
    return Factory(site_id=sid, site_name=f"Site {sid}", lat=lat, lon=lon, **kw)


@pytest.fixture
def factories():
    # inland high-stress, coastal, arid, and an ocean point (unmatched)
    return [fac("inland", 10.5, 10.5), fac("coast", 10.5, 11.5), fac("arid", 11.5, 10.5), fac("sea", -40, -120)]


@pytest.fixture
def engine(synthetic_repo):
    return RiskEngine(synthetic_repo, RULES, load_settings())


def test_14_results_per_factory(engine, factories):
    out = engine.run(factories)
    assert len(out.results) == 14 * len(factories) and not out.errors
    assert {r.risk_id for r in out.results} == set(REGISTRY)


def test_one_failing_service_yields_error_for_that_risk_only(synthetic_repo, factories):
    services = get_services(RULES)
    victim = next(s for s in services if s.meta.risk_id == "drr")

    def boom(ctx):
        raise RuntimeError("boom")

    victim.extract = boom
    out = RiskEngine(synthetic_repo, RULES, load_settings(), services=services).run(factories[:3])
    errs = [r for r in out.results if r.status == RiskStatus.ERROR]
    assert {r.risk_id for r in errs} == {"drr"} and len(errs) == 3
    assert "boom" in errs[0].reason and "RuntimeError" in errs[0].reason
    assert len(out.results) == 14 * 3 and len(out.errors) == 3
    assert all(r.status != RiskStatus.ERROR for r in out.results if r.risk_id != "drr")


def test_summary_excludes_overall_and_impact(engine, factories):
    s = {x.site_id: x for x in engine.run(factories).summary}
    # coast: cfr watch; cep is also watch but is an impact indicator, so it is not counted
    assert s["coast"].watch_risks == ["cfr"] and s["coast"].n_watch == 1 and s["coast"].n_present == 0
    # inland: bws present; overall_textile is present too but excluded
    assert s["inland"].present_risks == ["bws"] and s["inland"].overall_textile_status == RiskStatus.PRESENT
    assert sum(s["inland"].counts.values()) == 12  # 14 minus overall_textile and cep
    assert s["inland"].overall_textile_score == pytest.approx(4.1)
    assert s["arid"].present_risks == ["bws", "bwd"] and s["arid"].watch_risks == ["ucw"]


def test_cep_present_is_reported_as_impact_not_risk(synthetic_repo):
    engine = RiskEngine(synthetic_repo, RULES, load_settings())
    ctxs = engine.locator.locate([fac("c", 10.5, 11.5)])
    ctxs[0].baseline.update(cep_cat=3.0, cep_raw=2.0, cep_label="High (1 to 5)")
    engine.locator.locate = lambda fs: ctxs
    out = engine.run([fac("c", 10.5, 11.5)])
    assert out.summary[0].impact_indicators_present == ["cep"] and "cep" not in out.summary[0].present_risks


def test_unmatched_factory(engine, factories):
    out = engine.run(factories)
    sea = [r for r in out.results if r.site_id == "sea"]
    assert len(sea) == 14 and all(r.status == RiskStatus.NO_DATA for r in sea)
    assert next(x for x in out.summary if x.site_id == "sea").n_present == 0


def test_country_mismatch_warning(engine):
    out = engine.run([fac("a", 10.5, 10.5, country="Inland"), fac("b", 10.5, 10.5, country="France")])
    ok = next(r for r in out.results if r.site_id == "a" and r.risk_id == "bws")
    bad = next(r for r in out.results if r.site_id == "b" and r.risk_id == "bws")
    assert not any("differs" in c for c in ok.caveats)
    assert "check that lat and lon are not swapped" in bad.caveats[0]


def test_results_json_round_trips(engine, factories, tmp_path):
    paths = write_all(engine.run(factories), tmp_path)
    data = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert len(data["results"]) == 56 and len(data["summary"]) == 4 and len(data["contexts"]) == 4


def test_csv_utf8_sig_and_dash_intact(engine, factories, tmp_path):
    paths = write_all(engine.run(factories), tmp_path)
    for key in ("long", "wide"):
        assert paths[key].read_bytes().startswith(b"\xef\xbb\xbf")  # BOM so Excel shows the dashes
    long = pd.read_csv(paths["long"], encoding="utf-8-sig")
    assert len(long) == 14 * 4 and long["site_id"].nunique() == 4
    assert long.columns[0] == "site_id" and {"kind", "worst_month", "bau2050_raw", "caveats"} <= set(long.columns)
    coast_cfr = long[(long.site_id == "coast") & (long.risk_id == "cfr")].iloc[0]
    assert "medium–high" in coast_cfr["headline"] and "Medium–High" in coast_cfr["reason"]  # en dash survives the round trip
    wide = pd.read_csv(paths["wide"], encoding="utf-8-sig")
    assert len(wide) == 4 and {"bws_status", "bws_raw", "bws_score", "bws_label", "n_present", "n_watch"} <= set(wide.columns)
    assert wide.loc[wide.site_id == "arid", "present_risks"].iloc[0] == "bws,bwd"
