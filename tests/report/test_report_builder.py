import re
import tomllib
from datetime import datetime
from pathlib import Path

import pytest

from hydris_risk import __version__
from hydris_risk.config import ROOT, load_settings
from hydris_report.config import load_report_rules
from hydris_risk.engine import RiskEngine
from hydris_risk.models import Factory, RiskStatus
from hydris_report.builder import build_report, most_common_local, read_limitations, report_filename
from hydris_risk.services.registry import REGISTRY, get_services

RULES = load_report_rules()
NOW = datetime(2026, 10, 8, 9, 30)


def fac(sid, lat, lon, **kw):
    return Factory(site_id=sid, site_name=f"Site {sid}", lat=lat, lon=lon, **kw)


@pytest.fixture(scope="module")
def out(synthetic_repo):
    fs = [fac("inland", 10.5, 10.5, country="Inland"), fac("coast", 10.5, 11.5), fac("arid", 11.5, 10.5),
          fac("snap", 10.5, 9.98), fac("sea", -40, -120)]
    return RiskEngine(synthetic_repo, RULES, load_settings()).run(fs)


def blocks(fr):
    return [fr.overall, *fr.present, *fr.watch, *fr.not_present, *fr.no_data, *fr.impact]


def strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from strings(v)


# ---- every result exactly once -----------------------------------------------------------------------------
def test_every_risk_appears_exactly_once_per_factory(out):
    doc = build_report(out, RULES, "portfolio", None, NOW)
    assert len(doc.factories) == 5
    for fr in doc.factories:
        ids = [b.risk_id for b in blocks(fr)]
        assert sorted(ids) == sorted(REGISTRY) and len(ids) == 14


def test_sections_match_status_and_kind(out):
    fr = build_report(out, RULES, "factory", ["coast"], NOW).factories[0]
    assert all(b.status == RiskStatus.PRESENT for b in fr.present)
    assert all(b.status == RiskStatus.WATCH for b in fr.watch)
    assert all(b.status == RiskStatus.NOT_PRESENT for b in fr.not_present)
    assert [b.risk_id for b in fr.impact] == ["cep"]
    assert all(b.kind == "risk" for b in fr.present + fr.watch + fr.not_present)
    assert fr.overall.risk_id == "overall_textile" and fr.overall.kind == "composite"
    assert [b.risk_id for b in fr.watch] == ["cfr"]  # fixture: coastal flood Medium-High


def test_no_data_and_error_share_a_section(out):
    inland = build_report(out, RULES, "factory", ["inland"], NOW).factories[0]
    assert {b.risk_id for b in inland.no_data} == {"cfr"} and inland.no_data[0].status == RiskStatus.NO_DATA
    assert inland.impact[0].status == RiskStatus.NO_DATA  # cep is NoData here but still reported under impact


def test_counts_match_engine_summary_and_exclude_overall_and_impact(out):
    doc = build_report(out, RULES, "portfolio", None, NOW)
    for fr, s in zip(doc.factories, out.summary, strict=True):
        assert fr.counts == s.counts
        risk_blocks = [b for b in blocks(fr) if b.kind == "risk"]
        for status in ("present", "watch", "not_present", "no_data", "error"):
            assert fr.counts[status] == sum(b.status.value == status for b in risk_blocks)


def test_results_are_independent_of_any_ui_filter(out):
    """build_report has no filter inputs: all 14 results come straight from the engine output."""
    params = build_report.__code__.co_varnames[:build_report.__code__.co_argcount]
    assert params == ("out", "rules", "report_type", "site_ids", "generated_at")
    assert len(blocks(build_report(out, RULES, "factory", ["arid"], NOW).factories[0])) == 14


def test_deterministic_and_clock_injected(out):
    a = build_report(out, RULES, "portfolio", None, NOW)
    b = build_report(out, RULES, "portfolio", None, NOW)
    assert a.model_dump() == b.model_dump() and a.generated_at == NOW
    assert build_report(out, RULES, "portfolio", None, datetime(2030, 1, 1)).generated_at.year == 2030


# ---- content --------------------------------------------------------------------------------------------------
def test_block_carries_engine_text_unchanged_plus_new_sentences(out):
    fr = build_report(out, RULES, "factory", ["inland"], NOW).factories[0]
    bws = next(b for b in fr.present if b.risk_id == "bws")
    r = next(r for r in out.results if r.site_id == "inland" and r.risk_id == "bws")
    assert r.reason.startswith(bws.why) and bws.caveats == r.caveats and bws.headline == r.headline
    assert bws.threshold_position == "At 50.0%, water stress is 10.0 points above the High line (40%)."
    assert bws.what_would_change.startswith("It would drop to Watch below 40%.")
    assert bws.status_word == "Present" and bws.scale == "sub-basin" and bws.vintage == "4.0"
    assert len(bws.outlook_rows) == 9 and bws.outlook_sentence


def test_header_glance_and_framing(out):
    fr = build_report(out, RULES, "factory", ["inland"], NOW).factories[0]
    h = fr.context_header
    assert h["name"] == "Site inland" and h["pfaf_id"] == 1001 and h["state"] == "Highland" and h["country"] == "Inland"
    assert h["match_method"] == "within" and "match_warning" not in h
    assert fr.at_a_glance.startswith(
        "Site inland has 1 Present and 0 Watch risks out of 12 assessed. Present: Baseline water stress.")
    assert "No risk is on Watch." in fr.at_a_glance
    assert "The overall textile water risk score is 4.10 of 5, classed as High (3–4)." in fr.at_a_glance  # fixture label
    assert "1 risk has no data." in fr.at_a_glance
    assert fr.not_present_framing.startswith("Not present means the basin-level value is below Hydris's Watch threshold")
    assert "not a risk to the factory's own supply" in fr.impact_intro


def test_glance_mentions_watch_impact_separately(out):
    fr = build_report(out, RULES, "factory", ["coast"], NOW).factories[0]
    assert "Watch: Coastal flood risk." in fr.at_a_glance
    assert "Downstream impact, reported separately: coastal eutrophication potential is Watch." in fr.at_a_glance
    assert "Present: Coastal" not in fr.at_a_glance


def test_snapped_and_unmatched_headers(out):
    snap = build_report(out, RULES, "factory", ["snap"], NOW).factories[0]
    assert snap.context_header["match_method"] == "nearest"
    assert "outside the nearest Aqueduct polygon" in snap.context_header["match_warning"]
    sea = build_report(out, RULES, "factory", ["sea"], NOW).factories[0]
    assert sea.context_header["match_method"] == "unmatched" and "could not be matched" in sea.context_header["match_warning"]
    assert sea.at_a_glance == "Site sea could not be matched to an Aqueduct polygon, so no risk was assessed."
    assert len(sea.no_data) == 12 and [b.risk_id for b in sea.impact] == ["cep"] and not sea.present and sea.overall.status == RiskStatus.NO_DATA
    assert all("data gap, not evidence of low risk" in " ".join(b.extra_notes) for b in sea.no_data)


def test_country_mismatch_becomes_a_location_caveat(synthetic_repo):
    o = RiskEngine(synthetic_repo, RULES, load_settings()).run([fac("a", 10.5, 10.5, country="France")])
    fr = build_report(o, RULES, "factory", ["a"], NOW).factories[0]
    assert any("check that lat and lon are not swapped" in c for c in fr.location_caveats)


def test_summary_rows_cover_all_14_in_rule_order(out):
    fr = build_report(out, RULES, "factory", ["coast"], NOW).factories[0]
    assert [r["risk_id"] for r in fr.summary_rows] == list(RULES.risks) and len(fr.summary_rows) == 14
    row = next(r for r in fr.summary_rows if r["risk_id"] == "cfr")
    assert row["status_word"] == "Watch" and row["scale"] == "sub-basin" and row["label"] == "Medium - High (x)"


def test_no_junk_strings_anywhere(out):
    doc = build_report(out, RULES, "portfolio", None, NOW)
    for text in strings(doc.model_dump()):  # python mode keeps PNG bytes out of the string walk
        assert not re.search(r"\bNone\b|\bnan\b|\{[a-z_0-9]+\}", text), text


# ---- errors ---------------------------------------------------------------------------------------------------
def test_unknown_site_and_factory_report_with_many_ids(out):
    with pytest.raises(ValueError, match="Unknown site_id"):
        build_report(out, RULES, "factory", ["nope"], NOW)
    with pytest.raises(ValueError, match="exactly one"):
        build_report(out, RULES, "factory", ["inland", "coast"], NOW)


def test_failing_service_is_reported_not_hidden(synthetic_repo):
    services = get_services(RULES)
    next(s for s in services if s.meta.risk_id == "drr").extract = lambda ctx: (_ for _ in ()).throw(RuntimeError("boom"))
    o = RiskEngine(synthetic_repo, RULES, load_settings(), services=services).run([fac("a", 10.5, 10.5)])
    fr = build_report(o, RULES, "factory", ["a"], NOW).factories[0]
    err = next(b for b in fr.no_data if b.risk_id == "drr")
    assert err.status == RiskStatus.ERROR and "boom" in err.extra_notes[0]
    assert "other results are unaffected" in err.extra_notes[0]
    assert "1 risk has no data. 1 risk could not be assessed." in fr.at_a_glance and len(blocks(fr)) == 14


# ---- portfolio ------------------------------------------------------------------------------------------------
def test_portfolio_summary(out):
    doc = build_report(out, RULES, "portfolio", None, NOW)
    p = doc.portfolio
    assert doc.report_type == "portfolio" and doc.subtitle == "Portfolio report: 5 factories"
    assert p.kpis["factories"] == 5 and p.kpis["unmatched"] == 1
    assert [c["risk_id"] for c in p.columns] == [r for r in RULES.risks if r != "overall_textile"] and len(p.columns) == 13
    assert next(c for c in p.columns if c["risk_id"] == "cep")["kind"] == "impact"
    row = next(r for r in p.matrix if r["site_id"] == "inland")
    assert row["cells"]["bws"] == {"status": "present", "word": "Present"} and row["overall_score"] == pytest.approx(4.1)
    assert len(row["cells"]) == 13
    assert "do not distinguish between them" in p.paragraph and "untreated wastewater" in p.paragraph
    assert "1 of 5 sites could not be matched" in p.paragraph


def test_factory_report_has_no_portfolio_block(out):
    assert build_report(out, RULES, "factory", ["inland"], NOW).portfolio is None


def test_with_present_matches_engine(out):
    doc = build_report(out, RULES, "portfolio", None, NOW)
    assert doc.portfolio.kpis["with_present"] == sum(s.n_present > 0 for s in out.summary)


def test_most_common_local_excludes_country_and_composite(out):
    top = most_common_local(out.summary, RULES)
    assert top is not None and RULES.risks[top[0]]["scale"] in {"sub-basin", "aquifer"}
    doc = build_report(out, RULES, "portfolio", None, NOW)
    assert doc.portfolio.kpis["most_common_local"] == RULES.risks[top[0]]["name"]


def test_most_common_local_ignores_country_scale_even_when_it_is_the_most_frequent(out):
    sums = [s.model_copy(update={"present_risks": ["ucw", "rri", "bws"]}) for s in out.summary[:3]]
    sums += [out.summary[0].model_copy(update={"present_risks": ["ucw", "rri"]})]
    assert most_common_local(sums, RULES) == ("bws", 3)
    assert most_common_local([out.summary[0].model_copy(update={"present_risks": ["ucw"]})], RULES) is None


def test_portfolio_paragraph_names_most_common_local_risks(out):
    p = build_report(out, RULES, "portfolio", None, NOW).portfolio.paragraph
    assert p.startswith("The local risks most often Present are Baseline water stress (3 of 5 sites)")


# ---- appendix, names, single-source text ------------------------------------------------------------------------
def test_methodology_rows_and_notes(out):
    doc = build_report(out, RULES, "factory", ["inland"], NOW)
    assert len(doc.methodology) == 14
    bws = next(m for m in doc.methodology if m["risk_id"] == "bws")
    assert (bws["watch_line"], bws["present_line"], bws["scale"], bws["vintage"]) == ("20%", "40%", "sub-basin", "4.0")
    rfr = next(m for m in doc.methodology if m["risk_id"] == "rfr")
    assert (rfr["watch_line"], rfr["present_line"]) == ("0.3%", "0.62%")
    assert any("riverine flood label says 0.2% where the measured edge is 0.3%" in n for n in doc.methodology_notes)
    assert [d["status"] for d in doc.status_definitions] == ["present", "watch", "not_present", "no_data", "error", "impact"]
    assert doc.citation.startswith("Kuzma, S. et al. 2023") and "CC BY 4.0" in doc.data_license
    assert doc.disclaimer == "Basin-level screening data. Not a substitute for site-level assessment."


def test_report_filename():
    assert report_filename("factory", "F001", NOW, "pdf") == "hydris_risk_report_F001_20261008.pdf"
    assert report_filename("portfolio", None, NOW, "html") == "hydris_risk_report_portfolio_20261008.html"
    assert report_filename("factory", "a/b c", NOW, "pdf") == "hydris_risk_report_a_b_c_20261008.pdf"


def test_limitations_single_source_in_sync_with_readme():
    items = read_limitations()
    assert len(items) >= 10 and not any("**" in i or "`" in i for i in items)
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    block = re.search(r"<!-- limitations:start[^>]*-->\n(.*?)\n<!-- limitations:end -->", readme, re.S).group(1)
    assert block.strip() == (ROOT / "docs" / "limitations.md").read_text(encoding="utf-8").strip()


def test_version_matches_pyproject():
    meta = tomllib.loads(Path(ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert meta["project"]["version"] == __version__


# ---- one fact once per block; detail levels ---------------------------------------------------------------------
def sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])", text) if s.strip()]


def test_no_sentence_appears_twice_in_a_block(out):
    doc = build_report(out, RULES, "portfolio", None, NOW)
    for fr in doc.factories:
        for b in blocks(fr):
            parts = [b.why, b.threshold_position, b.what_would_change, b.outlook_sentence, *b.extra_notes, *b.caveats]
            found = [s for p in parts if p for s in sentences(p)]
            assert len(found) == len(set(found)), (b.risk_id, [s for s in found if found.count(s) > 1])


def test_why_has_no_trend_sentence_but_the_app_reason_keeps_it(out):
    r = next(r for r in out.results if r.site_id == "inland" and r.risk_id == "bws")
    fr = build_report(out, RULES, "factory", ["inland"], NOW).factories[0]
    b = next(b for b in fr.present if b.risk_id == "bws")
    assert "peaks in" in r.reason and "peaks in" not in b.why and "by 2050" not in b.why
    assert b.outlook_sentence and b.why.endswith(".") and "  " not in b.why


def test_detail_levels_and_overall_hides_raw(out):
    fr = build_report(out, RULES, "factory", ["coast"], NOW).factories[0]
    assert {b.detail for b in fr.present + fr.watch} <= {"full"}
    assert {b.detail for b in fr.not_present + fr.no_data} <= {"compact"}
    assert fr.overall.detail == "full" and fr.overall.values.raw is None and fr.overall.values.score is not None
    assert all("raw" in r for r in fr.summary_rows) and next(r for r in fr.summary_rows if r["risk_id"] == "overall_textile")["raw"] == ""
