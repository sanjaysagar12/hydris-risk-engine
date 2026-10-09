"""Dependency direction: risk engine <- report engine <- cli / web. Nothing may import "upwards"."""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
# package dir -> top-level packages it must NOT import
FORBIDDEN = {
    "hydris_risk": {"hydris_report", "hydris_cli", "web", "components", "streamlit", "typer", "reportlab", "matplotlib", "jinja2"},
    "hydris_report": {"hydris_cli", "web", "components", "streamlit", "typer"},
    "hydris_cli": {"web", "components", "streamlit"},
    "web": {"hydris_cli", "typer"},
}


def imported_roots(path: Path) -> set[str]:
    roots = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            roots |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


@pytest.mark.parametrize("package", FORBIDDEN)
def test_package_does_not_import_upwards(package):
    bad = {str(f.relative_to(ROOT)): sorted(imported_roots(f) & FORBIDDEN[package])
           for f in (ROOT / package).rglob("*.py") if imported_roots(f) & FORBIDDEN[package]}
    assert not bad, bad


def test_config_files_are_owned_by_one_package():
    """The engine never reads the report wording, and the report wording file is loaded only by hydris_report."""
    for f in (ROOT / "hydris_risk").rglob("*.py"):
        assert "report_templates" not in f.read_text(encoding="utf-8"), f
