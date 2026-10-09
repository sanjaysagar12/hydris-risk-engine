import pandas as pd
from typer.testing import CliRunner

from hydris_cli.main import app

runner = CliRunner()


def _args(csv, tmp_path, gdb):
    return ["--input", str(csv), "--out", str(tmp_path / "out"), "--data", str(gdb), "--cache-dir", str(tmp_path / "cache")]


def test_cli_run_end_to_end_with_bad_row(synthetic_gdb, tmp_path):
    csv = tmp_path / "f.csv"
    csv.write_text("site_id,site_name,lat,lon\nA,Inland,10.5,10.5\nB,Bad,abc,1\nC,Coast,10.5,11.5\n", encoding="utf-8")
    res = runner.invoke(app, ["run", *_args(csv, tmp_path, synthetic_gdb)])
    assert res.exit_code == 0, res.output
    assert "Assessed 2 factories (1 row(s) skipped)" in res.output and "row 3" in res.output
    out = tmp_path / "out"
    long = pd.read_csv(out / "results_long.csv", encoding="utf-8-sig")
    assert len(long) == 28 and (out / "results_wide.csv").exists() and (out / "results.json").exists()


def test_cli_risk_filter_and_unknown_risk(synthetic_gdb, tmp_path):
    csv = tmp_path / "f.csv"
    csv.write_text("site_id,site_name,lat,lon\nA,Inland,10.5,10.5\n", encoding="utf-8")
    args = _args(csv, tmp_path, synthetic_gdb)
    ok = runner.invoke(app, ["run", *args, "--risks", "bws,gtd"])
    assert ok.exit_code == 0 and len(pd.read_csv(tmp_path / "out" / "results_long.csv", encoding="utf-8-sig")) == 2
    bad = runner.invoke(app, ["run", *args, "--risks", "nope"])
    assert bad.exit_code == 2 and "Unknown risk" in bad.output


def test_cli_no_valid_rows_exits_nonzero(synthetic_gdb, tmp_path):
    csv = tmp_path / "f.csv"
    csv.write_text("site_id,site_name,lat,lon\nB,Bad,abc,1\n", encoding="utf-8")
    assert runner.invoke(app, ["run", *_args(csv, tmp_path, synthetic_gdb)]).exit_code == 1


def test_cli_build_cache(synthetic_gdb, tmp_path):
    res = runner.invoke(app, ["build-cache", "--data", str(synthetic_gdb), "--cache-dir", str(tmp_path / "c")])
    assert res.exit_code == 0 and (tmp_path / "c" / "baseline_annual.parquet").exists()


def _report_csv(tmp_path):
    csv = tmp_path / "f.csv"
    csv.write_text("site_id,site_name,lat,lon\nA,Inland,10.5,10.5\nC,Coast,10.5,11.5\n", encoding="utf-8")
    return csv


def _report_args(synthetic_gdb, tmp_path, *extra):
    return ["report", "--input", str(_report_csv(tmp_path)), "--out", str(tmp_path / "rep"), "--data", str(synthetic_gdb),
            "--cache-dir", str(tmp_path / "cache"), *extra]


def test_cli_report_one_file_per_factory_in_both_formats(synthetic_gdb, tmp_path):
    res = runner.invoke(app, _report_args(synthetic_gdb, tmp_path))
    assert res.exit_code == 0, res.output
    names = sorted(p.name for p in (tmp_path / "rep").iterdir())
    assert len(names) == 4 and all(n.startswith("hydris_risk_report_") for n in names)
    assert sum(n.endswith(".pdf") for n in names) == 2 and any("_A_" in n for n in names) and any("_C_" in n for n in names)
    pdf = next((tmp_path / "rep").glob("*_A_*.pdf")).read_bytes()
    assert pdf.startswith(b"%PDF")


def test_cli_report_portfolio_and_site_id(synthetic_gdb, tmp_path):
    res = runner.invoke(app, _report_args(synthetic_gdb, tmp_path, "--type", "portfolio", "--format", "html"))
    assert res.exit_code == 0, res.output
    [f] = list((tmp_path / "rep").iterdir())
    assert "portfolio" in f.name and f.read_text(encoding="utf-8").count("Why this status") == 28
    res = runner.invoke(app, _report_args(synthetic_gdb, tmp_path, "--site-id", "C", "--format", "pdf"))
    assert res.exit_code == 0 and (tmp_path / "rep").glob("*_C_*.pdf")


def test_cli_report_unknown_site_and_bad_options(synthetic_gdb, tmp_path):
    bad = runner.invoke(app, _report_args(synthetic_gdb, tmp_path, "--site-id", "ZZZ"))
    assert bad.exit_code == 2 and "Unknown site_id" in bad.output and not (tmp_path / "rep").exists()
    assert runner.invoke(app, _report_args(synthetic_gdb, tmp_path, "--format", "docx")).exit_code == 2
    assert runner.invoke(app, _report_args(synthetic_gdb, tmp_path, "--type", "x")).exit_code == 2
