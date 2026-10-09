"""Report download buttons: the web layer only wires the report engine to st.download_button."""
from __future__ import annotations

from datetime import datetime

import streamlit as st

from hydris_report.builder import report_filename
from hydris_report.config import load_report_rules
from hydris_report.export import MIME, render_report


@st.cache_resource
def _report_rules():
    return load_report_rules()


@st.cache_data(show_spinner="Rendering report...")
def _render(file_hash: str, report_type: str, site_id: str | None, fmt: str, day: str, _out):
    """Rendered bytes cached by (file, report type, site, format, day). Reports hold all 14 results: no UI filter applies."""
    return render_report(_out, _report_rules(), report_type, site_id, fmt, datetime.now())


def report_button(label: str, report_type: str, site_id: str | None, fmt: str, key: str, out, file_hash: str) -> None:
    """Rendering happens only when the button is clicked (callable data), then the bytes are cached."""
    now = datetime.now()
    st.download_button(label, data=lambda: _render(file_hash, report_type, site_id, fmt, now.strftime("%Y%m%d"), out)[1],
                       file_name=report_filename(report_type, site_id, now, fmt), mime=MIME[fmt], key=key, on_click="ignore")
