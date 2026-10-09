# Architecture

Hydris screens factories for water risk using WRI Aqueduct 4.0. The code is four packages with one-way dependencies. Each package can be installed, tested and used without the ones above it.

```
            ┌───────────────────────────────────────────────┐
            │  hydris_cli (typer)        web (Streamlit)    │   presentation: thin, no business logic
            └───────────────┬─────────────────┬─────────────┘
                            │                 │
                            ▼                 ▼
                    ┌─────────────────────────────────┐
                    │  hydris_report                  │   EngineOutput -> ReportDocument -> PDF / HTML
                    └───────────────┬─────────────────┘
                                    │ imports
                                    ▼
                    ┌─────────────────────────────────┐
                    │  hydris_risk                    │   CSV -> factories -> basin -> 14 risk results
                    └─────────────────────────────────┘
```

| Package | Responsibility | Imports | Extra install |
|---|---|---|---|
| `hydris_risk` | Risk engine: load factories, locate them in Aqueduct polygons, run the risk services, return `EngineOutput`. Writes the CSV/JSON results. | none of ours | none (core) |
| `hydris_report` | Report engine: turns an `EngineOutput` into a document model, then renders PDF or HTML. | `hydris_risk` | `[report]` |
| `hydris_cli` | Commands: `inspect`, `build-cache`, `run`, `report`. | both engines | `[cli]` |
| `web` | Streamlit app: factory list, map, risk cards, report downloads. | both engines | `[web]` |

The CLI and the web app never import each other. `tests/test_architecture.py` fails if a package imports upwards (for example the engine importing the report engine, or any UI library), or if the engine reads the report wording.

## 1. Risk engine (`hydris_risk`)

```
factories.csv
   │ io/input_loader.py        validate rows, collect errors per row            -> list[Factory], list[InputIssue]
   ▼
geo/locator.py                 point-in-polygon on baseline_annual              -> list[BasinContext]
   │   uses data/aqueduct_repository.py (GDB -> parquet cache, spatial index, monthly/future lookups)
   ▼
engine.py  RiskEngine          for each context x each service: service.assess(ctx)
   │   services/registry.py    REGISTRY of 14 services; get_services(rules, enabled)
   ▼
EngineOutput                   contexts, results (RiskResult), summary per factory, errors
   │
   ▼ io/output_writer.py       results_long.csv, results_wide.csv, results.json
```

```
hydris_risk/
  models.py                    Factory, BasinContext, RiskResult, IndicatorValues, FutureValue, MonthlyValue, enums
  config.py                    Settings (settings.yaml), RiskRules (risk_rules.yaml), ROOT
  engine.py                    RiskEngine, EngineOutput, FactorySummary
  data/    aqueduct_repository.py  nodata.py  inspect_gdb.py
  geo/     locator.py
  io/      input_loader.py  output_writer.py
  reasoning/  formatters.py  reason_builder.py      number formatting and the per-risk reason text
  services/   base.py  registry.py  + one file per risk (14)
```

**Key rules**
- **Baseline values come from the containing polygon** (`string_id`), never from a `pfaf_id` lookup, because some indicators follow province or aquifer boundaries. Monthly and future rows are keyed by `pfaf_id`.
- **NoData** is one rule in `data/nodata.py`: NaN, -9999, >= 9000, or a label equal to "no data" in any case. Category numbers drive logic; labels are for display.
- **A service is small.** `RiskService` (`services/base.py`) implements extract, classify, monthly, future, drivers and caveats from the config block of its `risk_id`. A concrete service file sets `risk_id`, `has_monthly` and `future_code`; `overall_textile` adds group drivers. Special cases (arid, insignificant trend, "No Risk", low collection) are data-driven from `risk_rules.yaml`.
- **Failures are contained.** `assess()` converts any exception into `status=error` for that risk only.
- **Statuses:** Present from High, Watch from Medium-High (configurable per risk; drought has its own scheme). Impact indicators (`kind: impact`, coastal eutrophication) and the overall score are not counted in risk totals.
- **Deterministic text.** Headlines and reasons are filled from templates in `config/risk_rules.yaml`; no LLM.

**Adding a risk:** one service file, one line in `services/registry.py`, one block in `config/risk_rules.yaml`.

## 2. Report engine (`hydris_report`)

```
EngineOutput  (from hydris_risk)
   │
   ▼ builder.py  build_report(out, rules, report_type, site_ids, generated_at)
   │     explain.py   threshold position, what would change, outlook, special-case notes
   │     charts.py    matplotlib (Agg) PNGs: monthly bars with Watch/Present lines, overall group bars
   ▼
ReportDocument  (models.py, pydantic)  ->  FactoryReport -> RiskBlock ...,  PortfolioSummary
   │
   ├─ render_pdf.py   ReportLab platypus, A4, embedded DejaVu Sans   -> bytes
   └─ render_html.py  Jinja2 template, inline CSS, base64 charts     -> str
   export.py          render_report(...) -> (file name, bytes): the single entry point for CLI and web
```

```
hydris_report/
  config.py       ReportRules = RiskRules + config/report_templates.yaml
  models.py       ReportDocument, FactoryReport, RiskBlock, PortfolioSummary
  explain.py  builder.py  charts.py  render_pdf.py  render_html.py  export.py
  templates/report.html.j2     assets/fonts/ (DejaVu Sans + licence)
```

**Key rules**
- **Pure and deterministic.** The builder takes `generated_at` as an argument and never reads the clock; the same input gives the same bytes.
- **Complete.** Every factory section contains all 14 results exactly once, grouped as Present, Watch, Not present, No data or errors, and Downstream impact. UI filters never reach the report.
- **One fact once per block.** The report's "Why" omits the trend sentence that the app keeps, because the trend appears in Outlook. Present and Watch blocks are full; the rest are compact. An "All values" appendix lists every value.
- **Special cases have their own wording** (gtd insignificant trend, cfr "No Risk", arid, low collection, country scale, no data, errors).
- **Wording lives in `config/report_templates.yaml`**, not in code. Watch and Present lines are the measured category edges from `risk_rules.yaml`.
- **Limitations text** is one file, `docs/limitations.md`, read by the report and embedded in the README.

## 3. CLI (`hydris_cli`)

```
hydris_cli/
  main.py              composes the commands into one typer app
  risk_commands.py     inspect, build-cache, run            (hydris_risk only)
  report_commands.py   report                               (runs RiskEngine, then hydris_report)
  _common.py           shared options, open_repo(), read_factories()
  __main__.py          python -m hydris_cli
```

Bad CSV rows are printed and skipped; exit code 1 if nothing valid remains, 2 for unknown ids or missing data. The CLI is the only place that reads the clock for reports (`datetime.now()`).

## 4. Web app (`web`)

```
web/
  streamlit_app.py            page flow: sidebar, KPIs, map, table, selected factory, footer
  components/  factory_table.py  factory_map.py  charts.py  risk_card.py  report_downloads.py
```

- `st.cache_resource` holds the repository and rules; `st.cache_data` holds engine results by file hash and rendered reports by (file hash, report type, site, format, day).
- The app calls the engines directly (not through `results.json`). Report buttons render on click.
- Filters change what is on screen only; KPIs and counts cover risks only, and "Most common local risk" counts sub-basin and aquifer scale risks.

Run: `streamlit run web/streamlit_app.py`.

## 5. Configuration and data

| File | Read by | Contents |
|---|---|---|
| `config/settings.yaml` | `hydris_risk` | GDB location, cache folder, metric CRS, snapping tolerance |
| `config/risk_rules.yaml` | `hydris_risk` (and the report engine) | per-risk name, scale, unit, thresholds, special cases, all engine text |
| `config/report_templates.yaml` | `hydris_report` only | report sentences, framing text, glance and portfolio templates |
| `data/raw/…gdb` | `hydris_risk` | user-provided Aqueduct file geodatabase (git-ignored) |
| `data/cache/*.parquet` | `hydris_risk` | slim cache built on first run, rebuilt if the GDB changes |
| `docs/DATA_NOTES.md` | humans | where the real data differs from `SPEC.md` and every measurement the code relies on |

## 6. Tests

```
tests/
  conftest.py            synthetic .gdb (3 polygons: inland high-stress, coastal, arid) shared by all suites
  risk/                  loader, NoData, repository, locator, services, reasons, engine, thresholds vs real data, golden Tiruppur
  report/                explain, builder, charts, PDF, HTML
  cli/                   run and report commands
  web/                   AppTest smoke tests;  web/e2e/ Playwright browser tests (marker e2e, excluded by default)
  test_architecture.py   import-direction rules
```

Tests that need the real Aqueduct data skip when it is absent. Run `pytest` (unit, no browser) and `pytest -m e2e` (browser).

## 7. Extension points

- **New risk or data source:** a service file plus a registry line and a config block. Non-Aqueduct data can arrive as new fields on `BasinContext`.
- **API:** services depend only on `BasinContext` and their config block, so `get_services(rules, enabled)` can back one endpoint per service. A FastAPI layer would sit beside `hydris_cli` and `web`, importing the engines. It is not built.
- **New report format:** add a `render_*.py` consuming `ReportDocument` and register it in `export.py`.
