"""Streamlit AppTest on the real data (skipped without the GDB). The browser run is in tests/e2e/."""
import re
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from hydris_risk.config import load_settings

APP = Path(__file__).resolve().parents[2] / "web" / "streamlit_app.py"

# Tiruppur has present risks. Wellington (NZ) has none: 0 present, 0 watch in the real data.
CSV = (b"site_id,site_name,lat,lon,country\n"
       b"F001,Tiruppur Mill,11.1085,77.3411,India\n"
       b"W001,Wellington Knit Works,-41.29,174.78,New Zealand\n")


@pytest.fixture(scope="module")
def have_data():
    if load_settings().find_gdb() is None:
        pytest.skip("real Aqueduct GDB not present")


@pytest.fixture(scope="module")
def app(have_data):
    return AppTest.from_file(str(APP), default_timeout=180).run()


def test_loads_without_exceptions_and_lists_all_factories(app):
    assert not app.exception
    assert [(m.label, m.value) for m in app.metric[:4]] == [
        ("Factories", "6"), ("With 1 or more present risk", "6"), ("Most common local risk", "Sanitation access gap"),
        ("Unmatched factories", "0")]
    assert app.selectbox[0].value == "F001"


def test_tiruppur_cards_and_status_words(app):
    text = " ".join(m.value for m in app.markdown)
    words = re.findall(r">(Present|Watch|Not present|No data|Error|Not applicable)</span>", text)
    assert len(words) == 14  # one badge (word, not colour alone) per card
    assert "Downstream impact" in text and "Basin-level screening data" in " ".join(c.value for c in app.caption)


def test_selecting_another_factory(app):
    app.selectbox[0].set_value("F004").run()
    assert not app.exception and "Savar Garment Factory" in " ".join(h.value for h in app.header)


def test_present_risk_only_filter_removes_factory_without_present_risks(have_data):
    at = AppTest.from_file(str(APP), default_timeout=180).run()
    at.sidebar.file_uploader[0].set_value([("f.csv", CSV, "text/csv")]).run()
    assert not at.exception
    assert at.selectbox[0].options == ["F001 - Tiruppur Mill", "W001 - Wellington Knit Works"]
    assert [m.value for m in at.metric[:2]] == ["2", "1"]  # only Tiruppur has a present risk

    at.sidebar.checkbox[0].check().run()
    assert not at.exception
    assert at.selectbox[0].options == ["F001 - Tiruppur Mill"]  # Wellington removed from the list

    at.sidebar.checkbox[0].uncheck().run()
    assert len(at.selectbox[0].options) == 2


def test_local_risk_kpi_excludes_country_scale_risks(have_data):
    """Tiruppur alone: present risks are drr, ucw (country scale) and usa; the KPI may only name a local one."""
    at = AppTest.from_file(str(APP), default_timeout=180).run()
    at.sidebar.file_uploader[0].set_value([("f.csv", CSV.split(b"W001")[0], "text/csv")]).run()
    label, value = at.metric[2].label, at.metric[2].value
    assert label == "Most common local risk" and value in {"Drought risk", "Sanitation access gap"}


def test_new_upload_resets_the_selection(have_data):
    """Selection state is dropped when a new file arrives. (AppTest cannot click a dataframe row; the stale-row-index
    crash this guards against is reproduced by the browser tests, which select a row and then upload.)"""
    at = AppTest.from_file(str(APP), default_timeout=180).run()
    at.selectbox[0].set_value("F004").run()  # 6-factory sample, 4th factory selected
    at.sidebar.file_uploader[0].set_value([("f.csv", CSV, "text/csv")]).run()
    assert not at.exception
    assert at.selectbox[0].value == "F001" and len(at.selectbox[0].options) == 2


def test_report_download_buttons_exist(have_data):
    at = AppTest.from_file(str(APP), default_timeout=180).run()
    labels = [b.label for b in at.get("download_button")]
    for want in ("Download factory report (PDF)", "Download factory report (HTML)",
                 "Download portfolio report (PDF)", "Download portfolio report (HTML)"):
        assert want in labels, labels
    assert not at.exception
    assert any("all 14 results" in c.value for c in at.caption)
