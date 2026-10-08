import io

import pytest
from PIL import Image

from hydris_risk.config import load_rules, load_settings
from hydris_risk.engine import RiskEngine
from hydris_risk.models import Factory, MonthlyValue
from hydris_risk.reporting.charts import monthly_chart_png, overall_chart_png

RULES = load_rules()
PNG = b"\x89PNG\r\n\x1a\n"


def months(values, cat=2):
    return [MonthlyValue(month=i + 1, raw=v, category=cat) for i, v in enumerate(values)]


def image(png):
    return Image.open(io.BytesIO(png))


def test_monthly_chart_is_a_non_blank_png():
    png = monthly_chart_png(months([0.1, 0.2, 0.3, 0.33, 0.2, 0.1, 0.05, 0.04, 0.03, 0.02, 0.02, 0.05]), RULES.for_risk("bws"), "Water stress: monthly")
    assert png.startswith(PNG)
    im = image(png)
    assert im.size == (int(6.3 * 150), int(2.3 * 150)) and len(set(im.convert("RGB").get_flattened_data())) > 10


def test_monthly_chart_is_deterministic():
    m = months([0.1] * 12)
    assert monthly_chart_png(m, RULES.for_risk("bws"), "t") == monthly_chart_png(m, RULES.for_risk("bws"), "t")


def test_monthly_chart_none_without_usable_months():
    assert monthly_chart_png([], RULES.for_risk("bws"), "t") is None
    assert monthly_chart_png(months([1.0] * 12, cat=-1), RULES.for_risk("bws"), "t") is None  # arid placeholders
    assert monthly_chart_png([MonthlyValue(month=1, raw=None, category=None)], RULES.for_risk("bws"), "t") is None


def test_threshold_lines_use_the_watch_and_present_colours():
    """Lines are drawn: orange (Watch) and red (Present) pixels exist in the image."""
    im = image(monthly_chart_png(months([0.1] * 12, cat=0), RULES.for_risk("bws"), "t")).convert("RGB")
    colours = set(im.get_flattened_data())
    assert any(abs(r - 0xF7) < 12 and abs(g - 0x90) < 12 and abs(b - 0x09) < 12 for r, g, b in colours)
    assert any(abs(r - 0xB4) < 12 and abs(g - 0x23) < 12 and abs(b - 0x18) < 12 for r, g, b in colours)


def test_index_indicator_chart_uses_plain_numbers():
    assert monthly_chart_png(months([0.2, 0.3, 0.4] * 4, cat=0), RULES.for_risk("iav"), "iav").startswith(PNG)


def test_overall_chart():
    groups = {"qan": {"score": 2.61}, "qal": {"score": 4.69}, "rrr": {"score": 3.44}}
    png = overall_chart_png(groups, RULES.risks["overall_textile"]["group_names"])
    assert png.startswith(PNG) and image(png).size == (int(6.3 * 150), int(1.9 * 150))
    assert overall_chart_png({}, {}) is None


@pytest.fixture(scope="module")
def doc(synthetic_repo):
    from datetime import datetime

    from hydris_risk.reporting.builder import build_report
    out = RiskEngine(synthetic_repo, RULES, load_settings()).run(
        [Factory(site_id="a", site_name="A", lat=10.5, lon=10.5), Factory(site_id="b", site_name="B", lat=11.5, lon=10.5)])
    return build_report(out, RULES, "portfolio", None, datetime(2026, 10, 8))


def test_builder_attaches_charts_only_where_data_exists(doc):
    a, b = doc.factories
    blocks = [a.overall, *a.present, *a.watch, *a.not_present, *a.no_data, *a.impact]
    with_chart = {x.risk_id for x in blocks if x.monthly_chart_png}
    assert with_chart == {"bws", "bwd", "iav"} and a.overall_chart_png.startswith(PNG)
    arid = [x for x in [*b.present, *b.watch, *b.not_present] if x.risk_id in ("bws", "bwd")]
    assert arid and all(x.monthly_chart_png is None for x in arid)  # arid placeholders are not plotted
