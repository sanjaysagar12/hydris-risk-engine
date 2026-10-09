"""The `hydris` command line: composes the risk-engine commands and the report command."""
from __future__ import annotations

import typer

from hydris_cli.report_commands import report_cmd
from hydris_cli.risk_commands import build_cache_cmd, inspect_cmd, run_cmd

app = typer.Typer(add_completion=False, help="Hydris water-risk engine (WRI Aqueduct 4.0).")
app.command("inspect")(inspect_cmd)
app.command("build-cache")(build_cache_cmd)
app.command("run")(run_cmd)
app.command("report")(report_cmd)

if __name__ == "__main__":
    app()
