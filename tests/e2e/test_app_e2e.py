"""Browser test of the Streamlit app (Playwright + headless Chromium). Excluded from the default run.

    pip install -e ".[dev,e2e]" && python -m playwright install chromium
    pytest -m e2e

Needs the real Aqueduct GDB. It starts its own Streamlit server on a free port, so nothing needs to be running.
"""
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from hydris_risk.config import load_settings

pytestmark = pytest.mark.e2e

ROOT = Path(__file__).resolve().parents[2]
RISKS = ["bws", "bwd", "iav", "sev", "gtd", "rfr", "cfr", "drr", "ucw", "cep", "udw", "usa", "rri", "overall_textile"]
BAD_CSV = ("site_id,site_name,lat,lon,country\n"
           "G1,Good Mill,11.1085,77.3411,India\n"
           "G2,Bad Row,abc,77,India\n"
           "G3,Wrong Country,11.1085,77.3411,France\n")


@pytest.fixture(scope="module")
def server_url():
    if load_settings().find_gdb() is None:
        pytest.skip("real Aqueduct GDB not present")
    pytest.importorskip("playwright.sync_api")
    with socket.socket() as s:
        s.bind(("localhost", 0))
        port = s.getsockname()[1]
    log = open(ROOT / "outputs" / "e2e_streamlit.log", "wb") if (ROOT / "outputs").exists() else subprocess.DEVNULL
    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", str(ROOT / "app" / "streamlit_app.py"), "--server.headless", "true",
         "--server.port", str(port), "--browser.gatherUsageStats", "false"], stdout=log, stderr=subprocess.STDOUT, cwd=ROOT)
    url = f"http://localhost:{port}"
    try:
        for _ in range(60):
            try:
                if urllib.request.urlopen(f"{url}/_stcore/health", timeout=2).status == 200:
                    break
            except OSError:
                time.sleep(1)
        else:
            pytest.fail("Streamlit server did not start")
        yield url
    finally:
        proc.terminate()
        proc.wait(timeout=15)


@pytest.fixture(scope="module")
def page(server_url):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as e:  # browsers not installed
            pytest.skip(f"Chromium not available: {e}")
        pg = browser.new_page(viewport={"width": 1500, "height": 1400})
        pg.console_messages_seen = []
        pg.on("pageerror", lambda e: pg.console_messages_seen.append(str(e)))
        pg.goto(server_url)
        pg.wait_for_selector("text=Not a substitute for site-level assessment", timeout=180_000)  # footer = fully rendered
        pg.wait_for_timeout(1000)
        yield pg
        browser.close()


def no_exception(page):
    return page.locator('[data-testid="stException"]').count() == 0


def test_loads_with_tiruppur_and_all_14_cards(page):
    assert no_exception(page)
    body = page.inner_text("body")
    for label in ("Factories", "With 1 or more present risk", "Most common local risk", "Unmatched factories"):
        assert label in body
    assert "Tiruppur Mill" in page.locator("h2").all_inner_texts().__str__()
    for r in RISKS:
        assert page.locator(f".st-key-card_{r}").count() == 1, r
    assert page.locator(".st-key-card_overall_textile").inner_text().count("(4.05 of 5)") == 1  # score, never raw


def test_scale_tags_badges_and_sections(page):
    assert "aquifer" in page.locator(".st-key-card_gtd").inner_text()
    assert "country" in page.locator(".st-key-card_ucw").inner_text()
    assert "sub-basin" in page.locator(".st-key-card_bws").inner_text()
    assert "composite" in page.locator(".st-key-card_overall_textile").inner_text()
    cards = " ".join(page.locator(f".st-key-card_{r}").inner_text() for r in ("bws", "drr", "bwd"))
    assert all(word in cards for word in ("Watch", "Present", "Not present"))  # status shown as a word
    assert "Downstream impact" in page.locator(".st-key-card_cep").inner_text()
    assert page.locator("text=Downstream impact").last.bounding_box()["y"] > page.locator("text=Regulatory & reputational").first.bounding_box()["y"]
    assert page.locator(".st-key-card_bws .js-plotly-plot").count() == 2  # monthly + future charts


def test_cards_are_ordered_present_first_within_a_group(page):
    order = page.eval_on_selector_all("[class*='st-key-card_']", "els => els.map(e => e.className.match(/st-key-card_(\\w+)/)[1])")
    assert order.index("drr") < order.index("bws") < order.index("bwd")  # Present, Watch, Not present
    assert order.index("usa") < order.index("udw") and order[-1] == "cep"  # impact section last


def click_table_row(page, row: int, expect_text: str) -> None:
    """Click a data row of the canvas-based st.dataframe; retry once because the grid can still be laying out on a slow machine."""
    grid = page.locator('[data-testid="stDataFrame"]').first
    for attempt in range(2):
        page.wait_for_timeout(1000)
        box = grid.bounding_box()
        page.mouse.click(box["x"] + 20, box["y"] + 35 + 35 * row + 17)  # 35 px header, 35 px rows
        try:
            page.wait_for_function(f"document.body.innerText.includes({expect_text!r})", timeout=15_000)
            return
        except Exception:
            if attempt:
                raise


def test_table_row_click_then_selectbox(page):
    click_table_row(page, 3, "Savar Garment Factory")  # 4th data row: F004
    page.wait_for_function(
        "[...document.querySelectorAll(\"[class*='st-key-card_']\")].length === 14", timeout=60_000)  # reruns re-render in stages
    assert no_exception(page)
    page.get_by_label("Selected factory").first.click()
    page.get_by_role("option", name=re.compile("F002")).click()
    page.wait_for_function("document.body.innerText.includes('Surat Dyeing Unit')", timeout=60_000)
    assert no_exception(page)


def test_upload_reports_bad_row_and_country_mismatch(page, tmp_path):
    csv = tmp_path / "bad.csv"
    csv.write_text(BAD_CSV, encoding="utf-8")
    page.set_input_files('input[type="file"]', str(csv))
    page.wait_for_selector("text=Input validation", timeout=120_000)
    page.wait_for_selector("text=must be numbers", timeout=60_000)
    body = page.inner_text("body")
    assert "1 error(s)" in body and "must be numbers" in body
    page.get_by_label("Selected factory").first.click()
    page.get_by_role("option", name=re.compile("G3")).click()
    page.wait_for_timeout(3000)
    assert page.get_by_text("check that lat and lon are not swapped", exact=False).count() >= 1
    assert no_exception(page)


def test_footer(page):
    body = page.inner_text("body")
    assert "doi.org/10.46830/writn.23.00061" in body and "Not a substitute for site-level assessment" in body
    assert not page.console_messages_seen
