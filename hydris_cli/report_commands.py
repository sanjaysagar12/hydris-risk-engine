"""Report command: runs the risk engine, then hands its output to the report engine."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer

from hydris_cli._common import CacheDir, Data, Input, OutDir, open_repo, read_factories
from hydris_report.config import load_report_rules
from hydris_report.export import FORMATS, render_report
from hydris_risk.engine import RiskEngine


def report_cmd(
    input: Input,  # noqa: A002
    out: OutDir = Path("outputs"),
    format: Annotated[str, typer.Option(help="pdf, html or both.")] = "both",  # noqa: A002
    type: Annotated[str, typer.Option(help="factory (one file per factory unless --site-id) or portfolio.")] = "factory",  # noqa: A002
    site_id: Annotated[str | None, typer.Option(help="Only this factory (factory reports).")] = None,
    data: Data = None,
    cache_dir: CacheDir = None,
) -> None:
    """Write exportable PDF/HTML reports with all 14 results per factory."""
    if format not in (*FORMATS, "both") or type not in ("factory", "portfolio"):
        typer.echo("--format must be pdf, html or both; --type must be factory or portfolio.", err=True)
        raise typer.Exit(2)
    factories, _ = read_factories(input)
    if site_id and site_id not in {f.site_id for f in factories}:
        typer.echo(f"Unknown site_id {site_id!r}. Available: {', '.join(f.site_id for f in factories)}", err=True)
        raise typer.Exit(2)
    rules = load_report_rules()
    result = RiskEngine(open_repo(data, cache_dir), rules).run(factories)  # the report engine consumes the risk engine's output
    now = datetime.now()  # the only clock read: builders take the time as an argument
    targets = [None] if type == "portfolio" else [site_id] if site_id else [f.site_id for f in factories]
    out.mkdir(parents=True, exist_ok=True)
    for target in targets:
        for fmt in FORMATS if format == "both" else (format,):
            name, payload = render_report(result, rules, type, target, fmt, now)
            (out / name).write_bytes(payload)
            typer.echo(f"Wrote {out / name}")
