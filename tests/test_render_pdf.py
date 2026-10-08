import re
import time
from datetime import datetime
from io import BytesIO

import pytest
from pypdf import PdfReader

from hydris_risk.config import load_rules, load_settings
from hydris_risk.data.aqueduct_repository import AqueductRepository
from hydris_risk.engine import RiskEngine
from hydris_risk.io.input_loader import load_factories
from hydris_risk.models import Factory
from hydris_risk.reporting.builder import build_report
from hydris_risk.reporting.render_pdf import render_pdf

RULES = load_rules()
NOW = datetime(2026, 10, 8, 9, 30)
NAMES = [c["name"] for c in RULES.risks.values()]
FRAMING = "Not present means the basin-level value is below Hydris's Watch threshold in Aqueduct."


def pdf_text(data: bytes) -> str:
    return re.sub(r"\s+", " ", " ".join(p.extract_text() or "" for p in PdfReader(BytesIO(data)).pages))


@pytest.fixture(scope="module")
def synthetic_out(synthetic_repo):
    fs = [Factory(site_id="inland", site_name="Inland Mill", lat=10.5, lon=10.5), Factory(site_id="coast", site_name="Coast Mill", lat=10.5, lon=11.5),
          Factory(site_id="arid", site_name="Arid Mill", lat=11.5, lon=10.5), Factory(site_id="sea", site_name="Sea Mill", lat=-40, lon=-120)]
    return RiskEngine(synthetic_repo, RULES, load_settings()).run(fs)


def test_factory_pdf_renders_with_everything_in_it(synthetic_out):
    pdf = render_pdf(build_report(synthetic_out, RULES, "factory", ["coast"], NOW))
    assert pdf.startswith(b"%PDF") and len(PdfReader(BytesIO(pdf)).pages) > 1
    text = pdf_text(pdf)
    for name in NAMES:
        assert name in text, name
    assert FRAMING in text and "Coast Mill" in text and "Water Risk Screening Report" in text
    assert "Basin-level screening data. Not a substitute for site-level assessment." in text
    assert "Medium–High" in text and "Watch from Medium–High" in text  # en dashes survive (DejaVu embedded)
    assert "Page 2 of" in text and "Generated 8 October 2026" in text
    for junk in ("None", "nan"):
        assert not re.search(rf"\b{junk}\b", text), junk


def test_pdf_has_a_block_for_every_risk_and_explanation_parts(synthetic_out):
    text = pdf_text(render_pdf(build_report(synthetic_out, RULES, "factory", ["inland"], NOW)))
    assert text.count("WHY THIS STATUS") == 14  # exactly one block per result
    assert "WHERE IT SITS AGAINST THE THRESHOLDS" in text and "WHAT WOULD CHANGE THE STATUS" in text
    assert "SEASONAL PATTERN" in text and "OUTLOOK" in text and "OVERALL BREAKDOWN" in text and "CAVEATS" in text
    assert "At 50.0%, water stress is 10.0 points above the High line (40%)." in text
    assert "Not present here means no decline was detected in the model, not that groundwater is safe." in text
    assert "Aqueduct's model covers 1990–2014" in text  # en dash inside a number range


def test_status_words_are_printed_not_just_coloured(synthetic_out):
    text = pdf_text(render_pdf(build_report(synthetic_out, RULES, "factory", ["coast"], NOW)))
    for word in ("Present", "Watch", "Not present", "Downstream impact"):
        assert word in text


def test_no_empty_headings_for_a_factory_without_watch_risks(synthetic_out):
    text = pdf_text(render_pdf(build_report(synthetic_out, RULES, "factory", ["inland"], NOW)))
    assert "Risks on watch" not in text and "Risks present (1)" in text


def test_unmatched_factory_pdf(synthetic_out):
    text = pdf_text(render_pdf(build_report(synthetic_out, RULES, "factory", ["sea"], NOW)))
    assert "could not be matched to an Aqueduct polygon" in text and "data gap, not evidence of low risk" in text
    assert "No data or errors (12)" in text


def test_pdf_is_deterministic(synthetic_out):
    doc = build_report(synthetic_out, RULES, "factory", ["inland"], NOW)
    assert render_pdf(doc) == render_pdf(doc)


def test_portfolio_pdf_has_contents_matrix_and_every_factory(synthetic_out):
    pdf = render_pdf(build_report(synthetic_out, RULES, "portfolio", None, NOW))
    reader = PdfReader(BytesIO(pdf))
    text = pdf_text(pdf)
    assert len(reader.pages) > 10 and "Contents" in text and "Portfolio summary" in text and "Status matrix" in text
    for name in ("Inland Mill", "Coast Mill", "Arid Mill", "Sea Mill", "Methodology and limitations"):
        assert text.count(name) >= 2  # contents entry + section
    assert "do not distinguish between them" in text and "Downstream impact" in text
    assert text.count("WHY THIS STATUS") == 14 * 4
    assert any(float(p.mediabox.width) > float(p.mediabox.height) for p in reader.pages)  # landscape matrix page


# ---- real data ---------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def real_out():
    s = load_settings()
    if s.find_gdb() is None:
        pytest.skip("real Aqueduct GDB not present")
    factories, _ = load_factories("sample/factories.csv")
    return RiskEngine(AqueductRepository(s.find_gdb(), s.cache_path), RULES, s).run(factories)


def test_tiruppur_golden_phrases_in_the_pdf(real_out):
    text = pdf_text(render_pdf(build_report(real_out, RULES, "factory", ["F001"], NOW)))
    for phrase in ("20.9%", "453803", "no significant trend", "Tamil Nadu", "453803-IND.31_1-2050", "4.05 of 5",
                   "At 20.9%, water stress is 0.9 points above the Watch line (20%) and 19.1 points below the High line (40%).",
                   "Under business as usual water stress goes from 20.9% today to 21.0% by 2030 and 36.6% by 2050, then eases to 35.1% by 2080.",
                   "This value is the same for every site in India"):
        assert phrase in text, phrase
    for name in NAMES:
        assert name in text


def test_portfolio_of_the_six_sample_factories_is_fast_enough(real_out):
    doc = build_report(real_out, RULES, "portfolio", None, NOW)
    t = time.perf_counter()
    pdf = render_pdf(doc)
    seconds = time.perf_counter() - t
    print(f"\nportfolio PDF render: {seconds:.2f}s, {len(PdfReader(BytesIO(pdf)).pages)} pages, {len(pdf) / 1024:.0f} KB")
    assert seconds < 10
