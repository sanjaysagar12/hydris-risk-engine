"""Commands that use only the risk engine: inspect, build-cache, run."""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from hydris_cli._common import CacheDir, Data, Input, OutDir, open_repo, read_factories
from hydris_risk.config import load_rules, load_settings
from hydris_risk.data.inspect_gdb import inspect_gdb
from hydris_risk.engine import RiskEngine
from hydris_risk.io.output_writer import write_all


def inspect_cmd(data: Data = None, out: Path = Path("data/cache/inspection_report.md")) -> None:
    """Write a report of the GDB's layers, columns, labels and NoData forms."""
    gdb = data or load_settings().find_gdb()
    if gdb is None:
        typer.echo("No Aqueduct .gdb found.", err=True)
        raise typer.Exit(2)
    inspect_gdb(gdb, out)
    typer.echo(f"Wrote {out}")


def build_cache_cmd(data: Data = None, cache_dir: CacheDir = None) -> None:
    """Read the GDB and write the slim parquet cache."""
    open_repo(data, cache_dir).build_cache()
    typer.echo("Cache built.")


def run_cmd(
    input: Input,  # noqa: A002
    out: OutDir = Path("outputs"),
    risks: Annotated[str | None, typer.Option(help="Comma-separated risk ids, e.g. bws,gtd (default: all).")] = None,
    data: Data = None,
    cache_dir: CacheDir = None,
) -> None:
    """Assess every factory in the CSV and write results_long.csv, results_wide.csv and results.json."""
    factories, issues = read_factories(input)
    enabled = [r.strip() for r in risks.split(",") if r.strip()] if risks else None
    try:
        engine = RiskEngine(open_repo(data, cache_dir), load_rules(), enabled=enabled)
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
