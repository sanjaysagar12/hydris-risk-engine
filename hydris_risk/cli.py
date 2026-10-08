from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer

from hydris_risk.config import load_rules, load_settings
from hydris_risk.data.aqueduct_repository import AqueductRepository
from hydris_risk.data.inspect_gdb import inspect_gdb
from hydris_risk.engine import RiskEngine
from hydris_risk.io.input_loader import load_factories
from hydris_risk.io.output_writer import write_all
from hydris_risk.reporting.export import FORMATS, render_report

app = typer.Typer(add_completion=False, help="Hydris water-risk engine (WRI Aqueduct 4.0).")
Data = Annotated[Path | None, typer.Option(help="Path to the Aqueduct .gdb (default: first .gdb under data/raw).")]
CacheDir = Annotated[Path | None, typer.Option("--cache-dir", help="Cache folder (default from settings.yaml).")]


def _repo(data: Path | None, cache: Path | None) -> AqueductRepository:
    s = load_settings()
    gdb = data or s.find_gdb()
    if gdb is None or not Path(gdb).exists():
        typer.echo("No Aqueduct .gdb found. Put it under data/raw/ or pass --data.", err=True)
        raise typer.Exit(2)
    return AqueductRepository(gdb, cache or s.cache_path)


@app.command("inspect")
def inspect_cmd(data: Data = None, out: Path = Path("data/cache/inspection_report.md")) -> None:
    """Write a report of the GDB's layers, columns, labels and NoData forms."""
    gdb = data or load_settings().find_gdb()
    if gdb is None:
        typer.echo("No Aqueduct .gdb found.", err=True)
        raise typer.Exit(2)
    inspect_gdb(gdb, out)
    typer.echo(f"Wrote {out}")


@app.command("build-cache")
def build_cache_cmd(data: Data = None, cache_dir: CacheDir = None) -> None:
    """Read the GDB and write the slim parquet cache."""
    _repo(data, cache_dir).build_cache()
    typer.echo("Cache built.")


@app.command("run")
def run_cmd(
    input: Annotated[Path, typer.Option(help="Factories CSV.")],  # noqa: A002
    out: Annotated[Path, typer.Option(help="Output folder.")] = Path("outputs"),
    risks: Annotated[str | None, typer.Option(help="Comma-separated risk ids, e.g. bws,gtd (default: all).")] = None,
    data: Data = None,
    cache_dir: CacheDir = None,
) -> None:
    """Assess every factory in the CSV and write results_long.csv, results_wide.csv and results.json."""
    factories, issues = load_factories(input)
    for i in issues:
        typer.echo(str(i), err=True)
    if not factories:
        typer.echo("No valid factories to assess.", err=True)
        raise typer.Exit(1)
    enabled = [r.strip() for r in risks.split(",") if r.strip()] if risks else None
    try:
        engine = RiskEngine(_repo(data, cache_dir), load_rules(), enabled=enabled)
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(2) from e
    result = engine.run(factories)
    paths = write_all(result, out)
    skipped = sum(i.level == "error" and i.row is not None for i in issues)
    typer.echo(f"Assessed {len(factories)} factories ({skipped} row(s) skipped), {len(result.results)} risk results.")
    for s in result.summary:
        typer.echo(f"  {s.site_id}: {s.n_present} present, {s.n_watch} watch ({s.match_method.value})")
    for e in result.errors:
        typer.echo(f"  service error: {e}", err=True)
    typer.echo("Wrote " + ", ".join(str(p) for p in paths.values()))


@app.command("report")
def report_cmd(
    input: Annotated[Path, typer.Option(help="Factories CSV.")],  # noqa: A002
    out: Annotated[Path, typer.Option(help="Output folder.")] = Path("outputs"),
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
    factories, issues = load_factories(input)
    for i in issues:
        typer.echo(str(i), err=True)
    if not factories:
        typer.echo("No valid factories to assess.", err=True)
        raise typer.Exit(1)
    if site_id and site_id not in {f.site_id for f in factories}:
        typer.echo(f"Unknown site_id {site_id!r}. Available: {', '.join(f.site_id for f in factories)}", err=True)
        raise typer.Exit(2)
    rules = load_rules()
    result = RiskEngine(_repo(data, cache_dir), rules).run(factories)
    now = datetime.now()  # the only clock read: builders take the time as an argument
    targets = [None] if type == "portfolio" else [site_id] if site_id else [f.site_id for f in factories]
    out.mkdir(parents=True, exist_ok=True)
    for target in targets:
        for fmt in FORMATS if format == "both" else (format,):
            name, payload = render_report(result, rules, type, target, fmt, now)
            (out / name).write_bytes(payload)
            typer.echo(f"Wrote {out / name}")


if __name__ == "__main__":
    app()
