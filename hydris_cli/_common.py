"""Options and helpers shared by the CLI commands."""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from hydris_risk.config import load_settings
from hydris_risk.data.aqueduct_repository import AqueductRepository
from hydris_risk.io.input_loader import load_factories

Data = Annotated[Path | None, typer.Option(help="Path to the Aqueduct .gdb (default: first .gdb under data/raw).")]
CacheDir = Annotated[Path | None, typer.Option("--cache-dir", help="Cache folder (default from settings.yaml).")]
Input = Annotated[Path, typer.Option(help="Factories CSV.")]
OutDir = Annotated[Path, typer.Option(help="Output folder.")]


def open_repo(data: Path | None, cache: Path | None) -> AqueductRepository:
    s = load_settings()
    gdb = data or s.find_gdb()
    if gdb is None or not Path(gdb).exists():
        typer.echo("No Aqueduct .gdb found. Put it under data/raw/ or pass --data.", err=True)
        raise typer.Exit(2)
    return AqueductRepository(gdb, cache or s.cache_path)


def read_factories(path: Path):
    """Valid factories and the issues found; bad rows are printed and skipped. Exits 1 if nothing valid remains."""
    factories, issues = load_factories(path)
    for i in issues:
        typer.echo(str(i), err=True)
    if not factories:
        typer.echo("No valid factories to assess.", err=True)
        raise typer.Exit(1)
    return factories, issues
