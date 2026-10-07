## 1. Goal

Build a Python risk engine that takes a CSV of factories (lat/lon) and returns, for every factory, an assessment of **13 water risks plus 1 overall textile risk** using WRI Aqueduct 4.0 data. Each risk is a **separate service** behind a common interface. A **Streamlit** app lists all factories; selecting one shows every risk, whether it is **present at that location**, a **detailed reason**, and the **underlying values**.

No LLM calls and no paid APIs in this build. Reasons are generated deterministically from data and templates so every sentence is traceable to a number.

## 2. Data source (already downloaded by the user)

- Dataset: *Aqueduct 4.0 Current and Future Global Maps Data*, WRI, CC BY 4.0. A file geodatabase (`.gdb`) in `data/raw/`.
- Data dictionary: https://github.com/wri/Aqueduct40/blob/master/data_dictionary_water-risk-atlas.md
- Citation to show in the app footer: Kuzma, S. et al. 2023. "Aqueduct 4.0: Updated decision-relevant global water risk indicators." Technical Note. WRI. doi.org/10.46830/writn.23.00061

### Layers (names vary by release; detect by keyword, case-insensitive)

| Layer keyword | Geometry | Key | Contents |
|---|---|---|---|
| `baseline_annual` | Polygons (union of HydroBASINS L6 sub-basin × GADM province × WHYMAP aquifer) | `string_id` (also `pfaf_id`, `gid_1`, `aqid`) | 13 indicators + grouped scores |
| `monthly` | Table or polygons | `pfaf_id` (wide: `{ind}_{MM}_{type}`) | Monthly `bws`, `bwd`, `iav` |
| `future` | Table or polygons | `pfaf_id` | `{scenario}{yy}_{ind}_x_{type}` |

### Column conventions

Baseline annual, per indicator: `{code}_raw` (double), `{code}_score` (0–5), `{code}_cat` (int, −1..4), `{code}_label` (string).
Identifiers: `string_id, aq30_id, pfaf_id, gid_1, aqid, gid_0, name_0, name_1, area_km2`.
Grouped: `w_awr_{scheme}_{group}_{type}` with scheme in {`def`, `tex`, …}, group in {`qan`, `qal`, `rrr`, `tot`}, type in {`raw`, `score`, `label`, `cat`, `weight_fraction`}.
Future: scenarios `bau` (SSP3-RCP7.0), `opt` (SSP1-RCP2.6), `pes` (SSP5-RCP8.5); years `30` (2015–2045), `50` (2035–2065), `80` (2065–2095); indicators `ws, wd, iv, sv, ba, ww`; types `_r, _s, _l, _c`. Example: `bau50_ws_x_r`.

### The 13 indicators

| Code | Name | Group | Vintage | Monthly | Future code |
|---|---|---|---|---|---|
| bws | Baseline water stress | Physical: quantity | 4.0 | yes | ws |
| bwd | Baseline water depletion | Physical: quantity | 4.0 | yes | wd |
| iav | Interannual variability | Physical: quantity | 4.0 | yes | iv |
| sev | Seasonal variability | Physical: quantity | 4.0 | no | sv |
| gtd | Groundwater table decline | Physical: quantity | 3.0 | no | — |
| rfr | Riverine flood risk | Physical: quantity | 3.0 | no | — |
| cfr | Coastal flood risk | Physical: quantity | 3.0 | no | — |
| drr | Drought risk | Physical: quantity | 3.0 | no | — |
| ucw | Untreated connected wastewater | Physical: quality | 3.0 | no | — |
| cep | Coastal eutrophication potential | Physical: quality | 3.0 | no | — |
| udw | Unimproved / no drinking water | Regulatory & reputational | 3.0 | no | — |
| usa | Unimproved / no sanitation | Regulatory & reputational | 3.0 | no | — |
| rri | Peak RepRisk country ESG risk index | Regulatory & reputational | 3.0 | no | — |

Plus the composite service `overall_textile` reading `w_awr_tex_{qan,qal,rrr,tot}_*`.

**Do not hardcode units or thresholds from memory.** Units and category thresholds must come from (a) the `_label` strings in the data and (b) `config/risk_rules.yaml`, where each unit is marked `verified: false` until checked against the technical note.

### Known real result (golden test)

The user ran a site through the same data. Use it as an acceptance test (skip if the real GDB is absent):

```
site: Tiruppur Mill, lat 11.1085, lon 77.3411
pfaf_id 453803, name_1 Tamil Nadu
bws_raw 0.209484, bws_score 2.06684, bws_cat 2, bws_label "Medium - High (20-40%)"
w_awr_tex_tot_score 4.05094
worst bws month 3 (raw 0.333257)
bau50_ws_x_r 0.366078 (cat 2)
```

## 3. Step 0: inspect the data first (mandatory)

Before writing services, write `hydris_risk/data/inspect.py` and run it. It must print: layer names, row counts, CRS, geometry type, every column name per layer, distinct values of each `*_label` column, min/max of each `*_raw`, and how NoData appears (NaN, −9999, −32767, "No Data" label, cat −9999, etc.). Save the report to `data/cache/inspection_report.md`. **Then adapt all column mappings to what actually exists.** If anything in this spec conflicts with the real data, the real data wins; note the difference in `docs/DATA_NOTES.md`.

## 4. Architecture

```
factories.csv
   │
   ▼
InputLoader ──► validated Factory list
   │
   ▼
Locator (point-in-polygon on baseline_annual) ──► BasinContext per factory
   │                                              (ids + baseline row + monthly row + future row)
   ▼
RiskEngine ──► for each registered RiskService: service.assess(ctx) ──► RiskResult
   │
   ▼
OutputWriter ──► results_long.csv, results_wide.csv, results.json
   │
   ▼
Streamlit app (reads engine directly, or results.json)
```

Services are **independent**: each lives in its own module, depends only on `BasinContext` + its own config block, and can be run, tested and later deployed on its own. Adding a new risk (e.g. a CGWB groundwater service) means adding one file and one registry line; nothing else changes.

## 5. Project structure

```
hydris-risk-engine/
  pyproject.toml
  README.md
  SPEC.md
  config/
    settings.yaml          # data paths, cache paths, CRS, nearest-match tolerance
    risk_rules.yaml        # per-risk thresholds, units, display text
  data/raw/                # Aqueduct .gdb (user-provided, git-ignored)
  data/cache/              # GeoParquet cache + inspection report
  sample/factories.csv
  docs/DATA_NOTES.md
  hydris_risk/
    __init__.py
    models.py
    config.py
    io/input_loader.py
    io/output_writer.py
    data/inspect.py
    data/aqueduct_repository.py
    data/nodata.py
    geo/locator.py
    reasoning/formatters.py
    reasoning/reason_builder.py
    services/base.py
    services/registry.py
    services/baseline_water_stress.py
    services/water_depletion.py
    services/interannual_variability.py
    services/seasonal_variability.py
    services/groundwater_table_decline.py
    services/riverine_flood.py
    services/coastal_flood.py
    services/drought.py
    services/untreated_wastewater.py
    services/coastal_eutrophication.py
    services/drinking_water_access.py
    services/sanitation_access.py
    services/reprisk_esg.py
    services/overall_textile.py
    engine.py
    cli.py
    api/main.py            # optional FastAPI: one router per service
  app/
    streamlit_app.py
    components/factory_table.py
    components/factory_map.py
    components/risk_card.py
    components/charts.py
  tests/
    conftest.py            # builds a synthetic .gdb fixture
    test_input_loader.py
    test_locator.py
    test_services.py       # parametrised over all services
    test_reason_builder.py
    test_engine.py
    test_golden_tiruppur.py
```

Stack: Python 3.11+, pandas, geopandas, pyogrio, shapely 2, pyarrow, pydantic v2, pyyaml, typer, streamlit ≥1.35, plotly, pydeck, pytest. Optional: fastapi, uvicorn.

## 6. Data models (`models.py`, pydantic v2)

```python
class Factory(BaseModel):
    site_id: str
    site_name: str
    lat: float            # -90..90
    lon: float            # -180..180
    country: str | None = None
    sector: str | None = None
    address: str | None = None

class MatchMethod(str, Enum):
    WITHIN = "within"            # point inside polygon
    NEAREST = "nearest"          # snapped to nearest polygon within tolerance (coastal pins)
    UNMATCHED = "unmatched"

class BasinContext(BaseModel):
    factory: Factory
    match_method: MatchMethod
    snap_distance_km: float | None
    string_id: str | None
    pfaf_id: int | None
    gid_1: str | None
    aqid: int | None
    name_0: str | None
    name_1: str | None
    area_km2: float | None
    baseline: dict[str, Any]     # full baseline_annual row
    monthly: dict[str, Any] | None
    future: dict[str, Any] | None
    dataset_version: str         # e.g. GDB folder name

class RiskStatus(str, Enum):
    PRESENT = "present"              # risk is present at this location
    WATCH = "watch"                  # moderate; monitor
    NOT_PRESENT = "not_present"
    NOT_APPLICABLE = "not_applicable"  # e.g. coastal risk at an inland site
    NO_DATA = "no_data"
    ERROR = "error"

class IndicatorValues(BaseModel):
    raw: float | None
    raw_display: str | None      # formatted with unit, e.g. "20.9%"
    unit: str | None
    score: float | None          # 0-5
    category: int | None         # -1..4
    label: str | None

class FutureValue(BaseModel):
    scenario: Literal["bau", "opt", "pes"]
    year: Literal[2030, 2050, 2080]
    raw: float | None
    category: int | None
    label: str | None

class MonthlyValue(BaseModel):
    month: int
    raw: float | None
    category: int | None

class RiskResult(BaseModel):
    site_id: str
    risk_id: str                 # e.g. "bws"
    risk_name: str
    group: str
    status: RiskStatus
    headline: str                # one line, e.g. "Not present: medium-high water stress (20.9%)"
    reason: str                  # full multi-sentence explanation (section 9)
    values: IndicatorValues
    monthly: list[MonthlyValue] = []
    future: list[FutureValue] = []
    drivers: dict[str, Any] = {} # service-specific extras (worst month, trend, group fractions)
    caveats: list[str] = []
    source: str                  # "WRI Aqueduct 4.0 baseline_annual"
    indicator_vintage: str       # "4.0" or "3.0"
    pfaf_id: int | None
    string_id: str | None
```

## 7. Components

### 7.1 InputLoader (`io/input_loader.py`)
- Read CSV; required columns `site_id, site_name, lat, lon` (case-insensitive, trim whitespace; accept `latitude/longitude` aliases).
- Validate each row with `Factory`. Collect errors per row instead of failing the whole file; return `(factories, errors)`.
- Flag duplicates of `site_id` and identical coordinates.
- Warn if lat/lon look swapped (e.g. |lat| > 90 or a `country` given and the point falls in a different `gid_0`).

### 7.2 AqueductRepository (`data/aqueduct_repository.py`)
- On first run, read layers from the `.gdb` with pyogrio, keep only needed columns, convert baseline_annual to EPSG:4326, and write `data/cache/baseline_annual.parquet` (GeoParquet), `monthly.parquet`, `future.parquet`. Later runs load the cache. Rebuild if the GDB modification time changes.
- Build the spatial index once (`gdf.sindex`).
- Methods: `baseline_polygons()`, `monthly_by_pfaf(pfaf_id)`, `future_by_pfaf(pfaf_id)`, `dataset_version()`.
- Normalise NoData via `data/nodata.py` (`is_nodata(value)` handles NaN, None, ≤ −9000, and labels like "No Data"), using what Step 0 found.

### 7.3 Locator (`geo/locator.py`)
- Batch `gpd.sjoin(points, polygons, predicate="within")`.
- Points with no match: find nearest polygon (project to a metric CRS such as EPSG:6933 for distance). If within `settings.nearest_tolerance_km` (default 5 km), use it with `match_method=NEAREST` and record distance; else `UNMATCHED`.
- If a point matches more than one polygon (boundary), keep the first and add a caveat.
- Attach monthly and future rows by `pfaf_id`.

### 7.4 RiskService base (`services/base.py`)

```python
@dataclass(frozen=True)
class RiskMeta:
    risk_id: str            # aqueduct code, e.g. "bws"
    name: str
    group: str
    vintage: str            # "4.0" | "3.0"
    has_monthly: bool
    future_code: str | None # "ws", "wd", "iv", "sv" or None
    what_it_measures: str   # plain-language definition
    factory_impact: str     # what it means for a factory when present

class RiskService(ABC):
    meta: RiskMeta
    def __init__(self, rules: RiskRules): ...

    def assess(self, ctx: BasinContext) -> RiskResult:
        if ctx.match_method == MatchMethod.UNMATCHED:
            return self._unmatched(ctx)
        values = self.extract(ctx)
        status = self.classify(values, ctx)
        monthly = self.extract_monthly(ctx) if self.meta.has_monthly else []
        future = self.extract_future(ctx) if self.meta.future_code else []
        drivers = self.drivers(values, monthly, future, ctx)
        caveats = self.caveats(values, ctx)
        headline, reason = ReasonBuilder(self.meta, self.rules).build(
            status, values, monthly, future, drivers, caveats, ctx)
        return RiskResult(...)

    # default implementations, override where needed
    def extract(self, ctx) -> IndicatorValues
    def classify(self, values, ctx) -> RiskStatus
    def extract_monthly(self, ctx) -> list[MonthlyValue]
    def extract_future(self, ctx) -> list[FutureValue]   # all 3 scenarios × 2030/2050/2080
    def drivers(self, values, monthly, future, ctx) -> dict
    def caveats(self, values, ctx) -> list[str]
```

Every `assess` call must be wrapped so an exception in one service returns `status=ERROR` with the message, without stopping the other services.

### 7.5 Default classification rule (configurable per risk in `risk_rules.yaml`)

| Condition | Status |
|---|---|
| raw/cat is NoData | NO_DATA |
| category ≥ `present_min_cat` (default 3 = High) | PRESENT |
| category ≥ `watch_min_cat` (default 2 = Medium–high) | WATCH |
| otherwise | NOT_PRESENT |

### 7.6 Service-specific behaviour

| Service | Overrides |
|---|---|
| baseline_water_stress | cat −1 ("Arid and low water use") → status from config `arid_status` (default PRESENT) with caveat that the ratio is unreliable in arid basins and new withdrawals can quickly push it higher. Drivers: worst month and its raw value, months at High or above, 2050 BAU value and change vs baseline, distance to next threshold (e.g. "3.4 points below the 40% High line"). Also emit `reporting_flag_water_stressed = raw ≥ 0.40`. |
| water_depletion | Same arid handling as bws. Monthly + future (wd). |
| interannual_variability | Monthly + future (iv). |
| seasonal_variability | Future (sv). Factory impact text about storage sizing for dry season. |
| groundwater_table_decline | Vintage 3.0. Caveat: modelled, not measured; describes 1990–2014; recommend local well data (e.g. CGWB in India). Unit from config (expected cm/year; verify). |
| riverine_flood | Vintage 3.0. Caveat: measures share of population affected in an average year, not water depth at the site; pluvial/urban flooding not covered. |
| coastal_flood | NoData or zero for inland basins → NOT_APPLICABLE with reason "basin has no coastal flood exposure in Aqueduct". Same caveats as riverine. |
| drought | Vintage 3.0. Caveat: surface-water drought, not groundwater drought. |
| untreated_wastewater | Caveat: household sewage only; industrial effluent not included. |
| coastal_eutrophication | NoData/inland → NOT_APPLICABLE. |
| drinking_water_access, sanitation_access | Caveat: national/provincial statistic, not local. Factory impact: community sensitivity to factory water use. |
| reprisk_esg | Caveat: country-level snapshot, may not reflect current events. |
| overall_textile | Reads `w_awr_tex_tot_*`; drivers = the three group scores (`qan`, `qal`, `rrr`) and their `weight_fraction`, plus the top 3 individual indicators by score from the baseline row. Caveat: composite index, not validated by WRI; use for prioritisation, not as a measured value. |

### 7.7 ReasonBuilder (`reasoning/reason_builder.py`)
Produces `headline` and `reason` from templates in `risk_rules.yaml`. The reason must contain, in this order:

1. **Verdict**: whether the risk is present, watch, not present, not applicable or no data.
2. **Measurement**: what the indicator measures (from `what_it_measures`).
3. **Value**: the raw value with unit, the category label, and the sub-basin (`pfaf_id`, `name_1`, `name_0`).
4. **Rule**: why this status, e.g. "Hydris marks this risk present at High (category 3) or above; this site is category 2."
5. **Factory impact**: what it means for a factory (only for PRESENT and WATCH).
6. **Context** (where available): worst month, future trend, distance to next threshold.
7. **Caveats**: vintage, basin-average limitation, service-specific caveats, NEAREST snapping distance.

Example for the golden site (bws):

> **Watch.** Baseline water stress measures total water demand as a share of available renewable supply. In sub-basin 453803 (Tamil Nadu, India) demand is 20.9% of supply, which Aqueduct classes as Medium–High (20–40%). Hydris marks this risk present at High (40%+); this site is one category below, so it is flagged to watch. Stress peaks in March at 33.3%. Under business as usual it rises to 36.6% by 2050, 3.4 points below the High line. This is a basin average from Aqueduct 4.0 and does not reflect the factory's own water sources.

Number formatting lives in `reasoning/formatters.py` (percent for ratios, 1 decimal; month names; signed deltas).

### 7.8 Registry and engine
- `services/registry.py`: `REGISTRY: dict[str, type[RiskService]]` with all 14 services; `get_services(enabled: list[str] | None)`.
- `engine.py`: `RiskEngine(repo, rules).run(factories) -> EngineOutput` with `contexts`, `results` (list of RiskResult), `summary` per factory (counts by status, list of present risks, overall textile score), and `errors`.

### 7.9 OutputWriter
- `results_long.csv`: one row per factory × risk with: `site_id, site_name, lat, lon, match_method, pfaf_id, string_id, name_0, name_1, risk_id, risk_name, group, status, headline, reason, raw, raw_display, unit, score, category, label, worst_month, bau2030_raw, bau2050_raw, caveats, source, indicator_vintage`.
- `results_wide.csv`: one row per factory: ids + for each risk `{risk_id}_status, {risk_id}_raw, {risk_id}_score, {risk_id}_label` + summary counts.
- `results.json`: full `EngineOutput` (pydantic `model_dump`).

### 7.10 CLI (`cli.py`, typer)
```
python -m hydris_risk.cli inspect --data data/raw/<name>.gdb
python -m hydris_risk.cli build-cache --data data/raw/<name>.gdb
python -m hydris_risk.cli run --input sample/factories.csv --out outputs/ [--risks bws,gtd]
```

### 7.11 Optional API (`api/main.py`)
FastAPI with `POST /assess` (all risks for a list of factories) and `POST /risks/{risk_id}/assess` (one service), so each service can later be deployed separately. Build only after everything else passes.

## 8. Config (`config/risk_rules.yaml`)

```yaml
defaults:
  present_min_cat: 3
  watch_min_cat: 2
risks:
  bws:
    unit: ratio            # display as %
    unit_verified: false
    arid_status: present
    reporting_threshold: 0.40
    what_it_measures: "Total water demand as a share of available renewable surface and groundwater supply."
    factory_impact: "High competition for water: higher risk of supply cuts, rising costs and permit pressure."
  gtd:
    unit: cm/year
    unit_verified: false
    what_it_measures: "Average rate at which the groundwater table is falling."
    factory_impact: "Borewells may need deepening or may fail; pumping costs rise."
  # ...one block for every risk, including overall_textile
```

Fill in all 14 blocks. Use the plain-language descriptions in section 2 as a starting point.

## 9. Streamlit app (`app/streamlit_app.py`)

Run: `streamlit run app/streamlit_app.py`. Layout `wide`. Cache the repository with `st.cache_resource` and engine results with `st.cache_data` keyed by file hash.

**Sidebar**
- File uploader for factories CSV (or "Use sample").
- Show input validation errors in an expander.
- Filters: status (multi-select), group (multi-select), "Show only factories with ≥1 present risk".
- Download buttons: results_long.csv, results_wide.csv, results.json.

**Main page, top: all factories**
- KPI row: number of factories, factories with ≥1 present risk, most common present risk, unmatched factories.
- Map (pydeck): one point per factory, colour by number of PRESENT risks, tooltip with name and overall textile label.
- Factory table using `st.dataframe(..., on_select="rerun", selection_mode="single-row")`: site_id, name, state, country, # present, # watch, overall textile label, match method. Selecting a row selects the factory (also offer a selectbox fallback).

**Main page, bottom: selected factory**
- Header: name, coordinates, sub-basin `pfaf_id`, `string_id`, state/country, match method (show a warning if NEAREST or UNMATCHED).
- Overall textile card: score, label, group breakdown (bar of `qan`, `qal`, `rrr`), top 3 drivers.
- Risk grid grouped by "Physical: quantity", "Physical: quality", "Regulatory & reputational". One `risk_card` per risk:
  - Title + status badge (Present = red, Watch = amber, Not present = green, Not applicable = grey, No data = grey outline, Error = purple). Badge text must also say the status in words, not colour only.
  - Headline line.
  - Expander "Why" → full `reason` text.
  - Expander "Values" → table of raw, raw_display, unit, score, category, label, vintage, source, pfaf_id.
  - If monthly: Plotly bar chart of 12 months with category threshold lines (20%, 40%, 80% for bws/bwd).
  - If future: table and small line chart of baseline → 2030 → 2050 → 2080 for the three scenarios.
  - Caveats as a small bulleted note.
- A "Risk summary" table for the factory: risk, status, raw_display, label (sortable), above the grid.
- Footer: data citation and the note "Basin-level screening data. Not a substitute for site-level assessment."

## 10. Tests

- `conftest.py` builds a synthetic `.gdb` with pyogrio (`driver="OpenFileGDB"`): 3 polygons (one high-stress inland, one low-stress coastal, one arid), matching monthly and future layers, and NoData values in the form Step 0 found.
- `test_services.py`: parametrise over every registered service; assert each returns a valid `RiskResult` for each fixture polygon, correct status for known categories, NO_DATA handling, NOT_APPLICABLE for coastal services on the inland polygon, arid handling for bws/bwd.
- `test_locator.py`: within match, nearest match within tolerance, unmatched ocean point.
- `test_reason_builder.py`: reason contains the formatted raw value, label, pfaf_id and status word; no "None" or "nan" strings anywhere.
- `test_engine.py`: one failing service yields ERROR for that risk only.
- `test_golden_tiruppur.py`: with the real GDB, the Tiruppur site reproduces the golden values in section 2 (tolerance 1e-4); skip if real data is missing.

## 11. Acceptance criteria

1. `run` on `sample/factories.csv` produces all three output files with 14 rows per factory in the long file.
2. Every RiskResult has a non-empty reason with value, label, rule and source; no "nan"/"None" in user-facing text.
3. Golden Tiruppur test passes on real data.
4. The Streamlit app lists all factories; selecting one shows all 14 risks with status, reason, values, and monthly/future charts where available.
5. A bad row in the CSV is reported and skipped; the rest still run.
6. A failing service does not stop the others.
7. `pytest` passes; `ruff` clean.
8. README explains setup, where to put the GDB, commands, and the limitations listed in the caveats.

## 12. Out of scope (do not build)

LLM-generated reasons, non-Aqueduct data (CGWB, IMD, flood depth maps), site exposure/vulnerability inputs (source mix, storage), authentication, databases. Design so these can be added later as new services or new fields in `BasinContext`.

## 13. Build order

0. Step 0 inspection → show report → adapt mappings.
1. models, config, nodata, repository + cache.
2. locator + tests.
3. base service, reason builder, formatters + tests.
4. bws service end-to-end + golden test.
5. remaining 13 services + parametrised tests.
6. engine, output writer, CLI.
7. Streamlit app.
8. README, DATA_NOTES, optional API.