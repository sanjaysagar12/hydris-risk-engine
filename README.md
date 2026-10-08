# Hydris risk engine

Screens factories (lat/lon) for **13 water risks plus one overall textile score** using WRI Aqueduct 4.0 data. Every risk is a separate service behind one interface. Each result has a status (Present, Watch, Not present, No data), a plain-language reason built from templates and data (no LLM, no paid APIs), the underlying values, and caveats. A Streamlit app lists all factories and shows every risk for the selected one.

> Basin-level screening data. Not a substitute for site-level assessment. See [Limitations](#limitations).

## Setup

Python 3.11 or newer (developed on 3.13).

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"                                 # runtime + pytest + ruff, versions pinned in pyproject.toml
```

### Where to put the Aqueduct data

1. Download *Aqueduct 4.0 Current and Future Global Maps Data* from WRI (CC BY 4.0) and unzip it.
2. Put the `.gdb` folder anywhere under `data/raw/`. The download unzips to `data/raw/Aqueduct40_waterrisk_download_.../GDB/Aq40_....gdb`, which works as is. The first `.gdb` found is used.
3. To use another location, set `gdb_path` (or `gdb_glob`) in `config/settings.yaml`, or pass `--data` to the CLI.

The first run reads the GDB once (about 20 seconds) and writes a slim cache to `data/cache/` (GeoParquet and Parquet). Later runs load the cache in about a second and rebuild it automatically if the GDB changes. `data/raw/` and the cache are git-ignored.

## Command line

```bash
python -m hydris_risk.cli inspect     [--data data/raw/.../X.gdb]          # layers, columns, labels, NoData report -> data/cache/inspection_report.md
python -m hydris_risk.cli build-cache [--data ...] [--cache-dir ...]       # build the cache without running anything
python -m hydris_risk.cli run --input sample/factories.csv --out outputs/ [--risks bws,gtd] [--data ...] [--cache-dir ...]
python -m hydris_risk.cli report --input sample/factories.csv --out outputs/ --format pdf|html|both --type factory|portfolio [--site-id F001]
```

`run` prints bad input rows (they are skipped, the rest still run), a per-factory summary, and any service errors. It exits with code 1 if no valid row remains and 2 for an unknown risk id or missing data.

### Input CSV

Required columns: `site_id, site_name, lat, lon` (case-insensitive, spaces trimmed; `latitude` and `longitude` are accepted). Optional: `country, sector, address`.

Reported and skipped: non-numeric or out-of-range coordinates, lat/lon that look swapped, missing or duplicate `site_id`. Warned but kept: identical coordinates. If `country` is given and differs from the Aqueduct country at the point, the results carry a caveat suggesting swapped coordinates.

A point outside every polygon is snapped to the nearest one within 5 km (`nearest_tolerance_km` in `config/settings.yaml`) and flagged; farther points are `unmatched` and get "No data" for every risk.

## The app

```bash
streamlit run app/streamlit_app.py
```

- **Sidebar:** upload a factories CSV or use the sample, see input validation messages, filter by status, group and "at least one present risk", download the three result files.
- **All factories:** KPIs, a map coloured by number of Present risks, and a table (# present, # watch, present risk names, overall textile score). Click a row or use the selectbox.
- **Selected factory:** location and match details, the overall textile card (score, group breakdown, top 3 drivers), a risk summary table, then one card per risk grouped as Physical: quantity, Physical: quality, Regulatory & reputational, ordered Present, Watch, Not present, No data, Error. Each card has a status badge (word, not just colour), a scale tag, the headline, "Why", "Values", monthly and future charts where the data has them, and caveats. Downstream-impact indicators sit in their own section.
- **Reports:** "Download factory report" (PDF or HTML) under the factory header, and "Download portfolio report" in the sidebar. Reports always contain all 14 results; the filters affect only the screen. Rendered files are cached per upload.
- **KPIs and counts** cover risks only. The overall score and downstream-impact indicators are not counted, and "Most common local risk" counts sub-basin and aquifer risks only.

## Reports

Two report types, two formats, one content model:

| | PDF (A4, share with management and buyers) | HTML (one self-contained file, printable) |
|---|---|---|
| **Factory report** | one factory | one factory |
| **Portfolio report** | summary and status matrix, then every factory | same |

```bash
python -m hydris_risk.cli report --input sample/factories.csv --out outputs/ --format both --type factory      # one file per factory
python -m hydris_risk.cli report --input sample/factories.csv --out outputs/ --type portfolio --format pdf
python -m hydris_risk.cli report --input sample/factories.csv --out outputs/ --site-id F001 --format html
```

`--format` is `pdf`, `html` or `both`; `--type factory` without `--site-id` writes one file per factory; an unknown `--site-id` exits with code 2. Files are named `hydris_risk_report_{site_id}_{YYYYMMDD}.pdf|html` and `hydris_risk_report_portfolio_{YYYYMMDD}.pdf|html`. The same buttons exist in the app.

**What a factory section contains, in order:** header (ids, coordinates, basin, match method and warnings), at a glance (counts and a templated summary), risk summary table for all 14 results, the overall textile block (score, group chart, top indicators), then one block per risk grouped as Risks present, Risks on watch, Risks not present, No data or errors, and Downstream impact. Every result appears exactly once. The appendix has the methodology table (Watch and Present line per indicator), an "All values" table per factory, status definitions, the Limitations (single source: `docs/limitations.md`, also embedded in this README) and the data citation.

**Each risk block** has the engine's reason ("Why this status"), where the value sits against the Watch and Present lines, what would change the status (including any scenario that crosses a line), an outlook with business-as-usual, optimistic and pessimistic values, a seasonal chart (water stress, depletion, interannual variability), values, and caveats. Present and Watch blocks are full; Not-present, No-data and Error blocks are compact. Each fact appears once per block: the reason in the report leaves out its trend sentence, which lives in the Outlook (the app keeps the full reason). Special cases use their own wording: groundwater "Insignificant Trend", coastal "No Risk", arid basins, low sewer collection, country-scale values and missing data. Not-present sections state once that "not present" is a screening result and not a site-level all-clear.

All sentences are deterministic: generated from the results and templates in `config/risk_rules.yaml` (`report_templates`), with no LLM. The Watch and Present lines are measured from the data because Aqueduct's labels round the category edges (see `docs/DATA_NOTES.md`, section 5b).

PDF text uses an embedded DejaVu Sans (licence in `hydris_risk/reporting/assets/fonts/`), so en dashes and symbols render on any machine. Charts are drawn with matplotlib (no browser needed). A 6-factory portfolio renders in a few seconds (about 55 pages). Reports are deterministic for a given time stamp: the builder takes `generated_at` as an argument.

Code: `hydris_risk/reporting/` (`explain.py` sentences, `builder.py` -> `ReportDocument`, `charts.py`, `render_pdf.py`, `render_html.py`, `export.py`).

## Tests

```bash
pytest                 # unit and app tests; the browser tests are excluded by default
ruff check .
```

Unit tests build a small synthetic `.gdb` (3 polygons with the real column conventions and NoData forms). Tests that need the real Aqueduct data (the Tiruppur golden test, locator checks on real polygons, the Streamlit app test) skip automatically when it is absent.

**Browser (e2e) tests** drive the real app in headless Chromium and are excluded by default (marker `e2e`):

```bash
pip install -e ".[dev,e2e]"
python -m playwright install chromium
pytest -m e2e
```

They start their own Streamlit server on a free port (log: `outputs/e2e_streamlit.log`) and check that the app loads without exceptions, all 14 cards render for Tiruppur, scale tags, badges and card order, table-row and selectbox selection, upload validation, download of a factory PDF (starts with %PDF) and HTML and of a portfolio PDF, and the footer. They need the real GDB and skip if Chromium is not installed.

## Output files

`run` writes three files to `--out`. The CSVs are UTF-8 with a BOM (`utf-8-sig`) so Excel on Windows shows en dashes correctly; read them with `encoding="utf-8-sig"`.

| File | Contents |
|---|---|
| `results_long.csv` | One row per factory x risk (14 per factory): `site_id, site_name, lat, lon, match_method, pfaf_id, string_id, name_0, name_1, risk_id, risk_name, kind, scale, group, status, headline, reason, raw, raw_display, unit, score, category, label, worst_month, bau2030_raw, bau2050_raw, caveats, source, indicator_vintage`. `caveats` are joined with ` \| `. `kind` is `risk` or `impact`; `scale` is `sub-basin`, `aquifer`, `country` or `composite`. |
| `results_wide.csv` | One row per factory: ids, then `{risk_id}_status, _raw, _score, _label` for each risk, then `n_present, n_watch, n_not_present, n_no_data, n_error, present_risks, watch_risks, impact_indicators_present`. Counts exclude `overall_textile` and impact indicators. For `overall_textile`, `_score` is the 0-5 value; `_raw` is the composite before Aqueduct's remapping. |
| `results.json` | The full engine output: `contexts` (factory, match method, basin ids, the full baseline, monthly and future rows), `results` (every `RiskResult`, including drivers and caveats), `summary` (per factory) and `errors`. |

`status` is one of `present`, `watch`, `not_present`, `no_data`, `error` (`not_applicable` exists in the model but no service currently returns it).

## How a result is decided

A risk is **Present** from category High (3, or 4 for drought risk, which has its own labels) and **Watch** from Medium-High. Special cases are configured in `config/risk_rules.yaml`: arid basins (Present), groundwater "Insignificant Trend" (Not present), coastal flood "No Risk" (Not present), and "No to Low Wastewater Collected" (Watch). All wording lives in that file; every number in a reason comes from the data. Units and scales are listed there with an `unit_verified` flag.

## Project layout

```
config/            settings.yaml (paths, tolerance), risk_rules.yaml (thresholds, units, scale, all text)
hydris_risk/       models, config, data/ (repository, NoData, inspect_gdb), geo/locator, reasoning/, services/, reporting/, engine, io/, cli
app/               Streamlit app and components
tests/             unit tests, tests/e2e (browser)
docs/limitations.md  Limitations text, shared by this README and the reports
docs/DATA_NOTES.md where the real data differs from SPEC.md, and every measurement the code relies on
sample/            sample factories
```

### Adding a risk, and API readiness

A service is one small file that sets `risk_id` (plus `has_monthly` / `future_code` if the data has them); its text, unit, thresholds and special cases come from its block in `risk_rules.yaml`. Add the file, one line in `hydris_risk/services/registry.py`, and a config block; nothing else changes.

Each service depends only on a `BasinContext` and its own config block, and `get_services(rules, enabled)` builds any subset, so the services are API-ready: a FastAPI app could expose one router per service without changing them. The optional FastAPI layer is **not built**.

## Limitations

<!-- limitations:start (generated from docs/limitations.md; edit that file) -->
- **Basin-level screening, not a site assessment.** Values describe the Aqueduct polygon the factory falls in. They do not reflect the factory's own water sources, abstraction, storage, discharge, or local conditions. Points are matched by polygon (or snapped up to 5 km); coordinates near polygon boundaries can land in a neighbouring polygon.
- **Older indicator vintages.** Only bws, bwd, iav and sev (and the overall composite) are Aqueduct 4.0 indicators. Groundwater table decline, riverine and coastal flood, drought risk, untreated wastewater, coastal eutrophication, drinking water, sanitation and the RepRisk index come from Aqueduct 3.0 and were not updated. Each result says which vintage it is, and the groundwater data describes 1990-2014.
- **Indicators have different geographic scales** (measured, see `docs/DATA_NOTES.md`): most are sub-basin; groundwater table decline is aquifer-level; untreated wastewater and the RepRisk index are country-level; the overall score is a composite. Every card shows its scale. Drinking-water and sanitation values vary by sub-basin but are estimates, not local measurements.
- **No future values** for flood, drought, groundwater, wastewater, eutrophication, drinking water, sanitation or RepRisk. Monthly values exist only for water stress, depletion and interannual variability; future values only for water stress, depletion, interannual and seasonal variability.
- **Groundwater "Insignificant Trend"** means Aqueduct's model found no statistically significant trend in 1990-2014. It does not mean groundwater is safe. Hydris marks it Not present and recommends checking local well data (for example CGWB in India). The raw number is shown only in the values panel; a negative value means the table is rising.
- **Flood indicators** are the share of people affected in an average year, not a flood depth or return period, and do not cover rain-driven or urban flooding. A "No Risk" coastal result cannot tell an inland basin from a protected coast.
- **Coastal eutrophication is an impact indicator.** It measures pollution the basin contributes to coastal waters, not a risk to the factory's own supply, so it is reported separately and not counted as a risk.
- **Country-level untreated wastewater** (and the RepRisk index) are identical for every site in a country and cover household sewage only (RepRisk is a snapshot that may not reflect current events).
- **The overall textile score** is a composite, not validated by WRI, and Aqueduct remaps it onto 0-5, so it is not an average of the group scores. Use it for prioritisation, not as a measured value. When some indicators have no data, a caveat gives the share of the weighting that is missing.
- **Arid basins:** Aqueduct does not calculate a reliable stress or depletion ratio for very dry, low-use basins. Hydris marks them Present because any new withdrawal can quickly raise stress.
- **Thresholds are Hydris's own rule** (Present from High, Watch from Medium-High) applied to Aqueduct's categories. They are screening cut-offs, not regulatory limits. The unit of coastal eutrophication ("ICEP index") is not confirmed (`unit_verified: false`).
<!-- limitations:end -->

## Citation

Kuzma, S. et al. 2023. "Aqueduct 4.0: Updated decision-relevant global water risk indicators." Technical Note. WRI. doi.org/10.46830/writn.23.00061. Data: WRI Aqueduct 4.0, CC BY 4.0.
