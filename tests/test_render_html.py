import html as htmllib
import re
from datetime import datetime

import pytest

from hydris_risk.config import load_rules, load_settings
from hydris_risk.engine import RiskEngine
from hydris_risk.models import Factory
from hydris_risk.reporting.builder import build_report
from hydris_risk.reporting.render_html import render_html

RULES = load_rules()
NOW = datetime(2026, 10, 8, 9, 30)
NAMES = [c["name"] for c in RULES.risks.values()]


@pytest.fixture(scope="module")
def out(synthetic_repo):
    fs = [Factory(site_id="inland", site_name="Inland Mill", lat=10.5, lon=10.5), Factory(site_id="coast", site_name="Coast <Mill> & Co", lat=10.5, lon=11.5),
          Factory(site_id="arid", site_name="Arid Mill", lat=11.5, lon=10.5), Factory(site_id="sea", site_name="Sea Mill", lat=-40, lon=-120)]
    return RiskEngine(synthetic_repo, RULES, load_settings()).run(fs)


def html(out, kind="factory", ids=("inland",)):
    return render_html(build_report(out, RULES, kind, list(ids) if ids else None, NOW))


def test_single_self_contained_file_with_all_14_risks(out):
    h = html(out)
    assert h.startswith("<!doctype html>") and h.count("<html") == 1 and h.rstrip().endswith("</html>")
    for name in NAMES:
        assert name in h, name
    assert h.count("Why this status") == 14 and "Not present means the basin-level value is below Hydris's Watch threshold" in htmllib.unescape(h)
    assert "data:image/png;base64," in h and "–" in h and "Basin-level screening data. Not a substitute for site-level assessment." in h


def test_no_external_resources(out):
    h = html(out, "portfolio", None)
    urls = re.findall(r'(?:src|href)="(https?://[^"]+)"', h) + re.findall(r"url\((https?://[^)]+)\)", h)
    assert urls == ["https://doi.org/10.46830/writn.23.00061"]  # only the citation link
    assert "<script" not in h and "@import" not in h and "<link" not in h
    assert "@media print" in h and "page-break-before" in h


def test_html_is_escaped(out):
    h = html(out, ids=("coast",))
    assert "Coast &lt;Mill&gt; &amp; Co" in h and "<Mill>" not in h


def test_no_junk_and_no_empty_headings(out):
    h = html(out)
    text = re.sub(r"<style.*?</style>|<[^>]+>", " ", h, flags=re.S)
    assert not re.search(r"\bNone\b|\bnan\b|\{\{|\{%", text)
    assert "Risks on watch" not in h  # inland has none: no empty heading
    assert not re.search(r"<h3>[^<]*</h3>\s*<h3>", h)


def test_status_words_present_and_deterministic(out):
    h = html(out, ids=("coast",))
    for w in ("Present", "Watch", "Not present", "Downstream impact"):
        assert f">{w}<" in h or w in h
    assert h == html(out, ids=("coast",))


def test_portfolio_html(out):
    h = html(out, "portfolio", None)
    assert "Status matrix" in h and "Contents" in h and h.count("Why this status") == 14 * 4
    for name in ("Inland Mill", "Arid Mill", "Sea Mill"):
        assert name in h
    assert "do not distinguish between them" in h


def test_unmatched_factory_html(out):
    h = html(out, ids=("sea",))
    assert "could not be matched to an Aqueduct polygon" in h and "data gap, not evidence of low risk" in h
