## 1. Goal

Add an **exportable report** that contains **every risk** for each factory and explains **both why a risk is present and why a risk is not present** (and why it is on watch, has no data, or is a downstream impact). Users export from the Streamlit app or the CLI.

Two report types, one renderer:
- **Factory report:** one factory.
- **Portfolio report:** all factories in the current CSV, with a portfolio summary up front, then one section per factory.

Two formats from the same report model:
- **PDF** (primary, for sharing with management and buyers). Use **ReportLab** (pure Python, works on Windows; do not use WeasyPrint).
- **HTML** (single self-contained file, printable, same content). Use **Jinja2**.

The report includes **all 14 results regardless of UI filters**. Filters affect the screen only, never the export.

No LLM calls. All explanation text is deterministic, generated from engine results and templates in `config/risk_rules.yaml`, so every sentence traces to a value.

## 2. Report content

### 2.1 Cover
Title "Water Risk Screening Report", report type, factory name(s), generation date, Hydris version, dataset version (GDB folder name), and the disclaimer "Basin-level screening data. Not a substitute for site-level assessment."

### 2.2 Portfolio summary (portfolio report only)
- KPIs: number of factories, factories with at least 1 Present risk, most common local risk (sub-basin and aquifer scale only, same rule as the app), unmatched factories.
- **Status matrix:** factories as rows, the 13 risks as columns, each cell the status word with colour as a secondary cue. Overall textile score as the last column. Downstream impact indicators in a separate column group.
- A short templated paragraph: which local risks are most often Present, and a note that country-scale indicators (e.g. untreated wastewater) are identical for all sites in a country and do not distinguish between them.

### 2.3 Per-factory section
In this order:

1. **Header:** name, site_id, coordinates, sub-basin `pfaf_id`, `string_id`, state, country, match method (with snapping distance if NEAREST, warning if UNMATCHED), any location caveats.
2. **At a glance:** counts by status (excluding overall and impact, same as the engine summary), the overall textile score and label, and a one-paragraph templated summary naming the Present risks and the Watch risks.
3. **Risk summary table:** all 13 risks + overall, columns: risk, group, scale, status, value (raw_display), Aqueduct label.
4. **Overall textile risk:** score, label, the qan/qal/rrr group breakdown (bar chart), top 3 indicators, the existing reason, the weight_fraction caveat if present.
5. **Risks present:** one block per Present risk.
6. **Risks on watch:** one block per Watch risk.
7. **Risks not present:** one block per Not-present risk.
8. **No data / errors:** one block per risk with NO_DATA or ERROR.
9. **Downstream impact:** `kind: impact` indicators, clearly labelled as contribution to downstream waters, not risk to the factory.

Every one of the 14 results appears **exactly once** in sections 4–9.

### 2.4 Risk block (the core of this feature)

Each block has these parts. Parts with no data are omitted, never printed as "None", "nan" or empty headings.

| Part | Content | Source |
|---|---|---|
| Title line | Risk name, status word, scale tag, vintage tag | engine result + rules |
| **Why this status** | The existing `reason` text, unchanged | engine |
| **Where it sits against the thresholds** | New sentence: value vs Watch line and Present line, with gaps (see 2.5) | new `explain.py` |
| **What would change the status** | New sentence: what it would take to move up (or down) a level (see 2.5) | new `explain.py` |
| **Outlook** | Future values for indicators that have them (bau / opt / pes for 2030, 2050, 2080) as a small table, plus a one-line trend | engine `future` |
| **Seasonal pattern** | Monthly chart for bws, bwd, iav with threshold lines | engine `monthly` |
| **Values** | raw, raw_display, unit, score, category, verbatim label, scale, vintage, source, pfaf_id/string_id | engine `values` |
| **Caveats** | The existing caveats list, in the existing order | engine |

### 2.5 New explanation logic (`reporting/explain.py`)

Deterministic functions that take a `RiskResult` + the risk's rules and return sentences. All wording goes in a new `report_templates:` section of `risk_rules.yaml`.

**Threshold position**, for risks with numeric thresholds (already added to rules in Step 6):
- Present: "At 0.81, drought risk is 0.01 above the High line (0.80)."
- Watch: "At 20.9%, water stress is 0.9 points above the Watch line (20%) and 19.1 points below the High line (40%)."
- Not present: "At 8.6%, water depletion is 16.4 points below the Watch line (25%) and 41.4 points below the High line (50%)."
- Use percentage **points** for percent indicators and plain differences for indices. Reuse the existing boundary-aware rounding so a value never appears to contradict its label.

**What would change the status:**
- Present: "It would drop to Watch below 0.80." For the top category: "It is in Aqueduct's highest category."
- Watch: "It becomes Present if it reaches 40%." If a future value crosses the line: "Under business as usual it is projected to reach 36.6% by 2050, still below the High line." or "…projected to cross the High line by 2050."
- Not present: "It would move to Watch at 25%." If a future value reaches Watch or Present, say so explicitly; this is the most important "why not present yet" signal.

**Special cases (override the generic sentences):**
- **gtd insignificant trend:** threshold position omitted. What would change: "This would change only if a statistically significant declining trend were found. Aqueduct's model covers 1990–2014; recent local well data (e.g. CGWB) may show a different picture." Add the line "Not present here means no decline was detected in the model, not that groundwater is safe."
- **cfr "No Risk":** "Aqueduct records no coastal flood risk for this basin; there is no threshold to compare against."
- **Arid bws/bwd:** no numeric position. "Aqueduct does not calculate a reliable ratio for very dry, low-use basins, so position against thresholds is not meaningful."
- **ucw low collection (cat −1):** explain that the indicator cannot measure pollution from uncollected sewage, so Watch reflects missing collection, not low pollution.
- **Country-scale risks (ucw, rri):** add "This value is the same for every site in {country}, so it does not distinguish this factory from others in the country."
- **NO_DATA:** "Aqueduct has no value for this indicator in this area, so no status can be given. This is a data gap, not evidence of low risk."
- **ERROR:** the error message plus "This risk could not be assessed; other results are unaffected."
- **Impact indicators (cep):** position sentences allowed; what-would-change wording refers to contribution to downstream waters, not factory risk.
- **Overall textile:** no position sentence; explanation is the group breakdown and top indicators (already in its reason).

**Not-present framing rule:** every Not-present block must make clear it is a screening result. Add once per factory (at the top of section 7, not per block): "Not present means the basin-level value is below Hydris's Watch threshold in Aqueduct. It does not rule out site-level issues, which depend on the factory's own water sources and operations."

## 3. Architecture

```
EngineOutput (existing)
   │
   ▼
reporting/builder.py ── build_report(engine_output, rules, report_type, site_ids, generated_at)
   │                      → ReportDocument (pydantic)
   │   uses reporting/explain.py for new sentences
   │   uses reporting/charts.py for PNG charts (matplotlib, Agg backend)
   ▼
reporting/render_pdf.py   → bytes (ReportLab platypus)
reporting/render_html.py  → str  (Jinja2 template, charts embedded as base64 PNG)
```

New files:
```
hydris_risk/reporting/__init__.py
hydris_risk/reporting/models.py        # ReportDocument, FactoryReport, RiskBlock, PortfolioSummary
hydris_risk/reporting/explain.py
hydris_risk/reporting/builder.py
hydris_risk/reporting/charts.py
hydris_risk/reporting/render_pdf.py
hydris_risk/reporting/render_html.py
hydris_risk/reporting/templates/report.html.j2
hydris_risk/reporting/assets/fonts/DejaVuSans.ttf, DejaVuSans-Bold.ttf  (+ license file)
tests/test_explain.py
tests/test_report_builder.py
tests/test_render_pdf.py
tests/test_render_html.py
```

### 3.1 Models (`reporting/models.py`)

```python
class RiskBlock(BaseModel):
    risk_id: str
    risk_name: str
    group: str
    kind: Literal["risk", "impact", "composite"]
    scale: str
    vintage: str
    status: RiskStatus
    headline: str
    why: str                          # existing reason, unchanged
    threshold_position: str | None
    what_would_change: str | None
    extra_notes: list[str] = []       # special-case lines (gtd, country-scale, etc.)
    outlook_rows: list[FutureValue] = []
    outlook_sentence: str | None
    monthly_chart_png: bytes | None
    values: IndicatorValues
    caveats: list[str]

class FactoryReport(BaseModel):
    context_header: dict              # name, ids, coords, basin, match info
    location_caveats: list[str]
    counts: dict[str, int]
    at_a_glance: str
    summary_rows: list[dict]
    overall: RiskBlock
    overall_chart_png: bytes | None
    present: list[RiskBlock]
    watch: list[RiskBlock]
    not_present: list[RiskBlock]
    no_data: list[RiskBlock]
    impact: list[RiskBlock]

class PortfolioSummary(BaseModel):
    kpis: dict[str, Any]
    matrix: list[dict]
    paragraph: str

class ReportDocument(BaseModel):
    report_type: Literal["factory", "portfolio"]
    title: str
    generated_at: datetime            # injected, never datetime.now() inside builder
    hydris_version: str
    dataset_version: str
    disclaimer: str
    citation: str
    portfolio: PortfolioSummary | None
    factories: list[FactoryReport]
    methodology: list[dict]           # per-risk rule table for the appendix
```

### 3.2 Appendix: methodology and limitations
- Per-risk table generated from `risk_rules.yaml`: risk, what it measures, unit, scale, vintage, Watch line, Present line.
- Status definitions (Present, Watch, Not present, No data, Error, Downstream impact).
- Limitations: reuse the README Limitations content (single source: move it into a shared text block in `risk_rules.yaml` or a `docs/limitations.md` read by both).
- Data citation (Kuzma et al. 2023) and CC BY 4.0 attribution.

### 3.3 Rendering details
- **PDF:** A4, ReportLab platypus. Register DejaVu Sans so "–", "≥", "→" render. Running header with factory name, footer with page "x of y", report date and disclaimer. Keep each risk block together where possible (`KeepTogether`, fall back to splitting for long blocks). Status shown as a coloured pill **with the word**. Table of contents for portfolio reports.
- **HTML:** single file, inline CSS, charts as base64 PNG, print stylesheet (`@media print` page breaks before each factory). No external requests.
- **Charts:** matplotlib with the `Agg` backend (no Plotly/kaleido, which needs a browser). Monthly bars with Watch and Present threshold lines; overall group breakdown bars. Same colours as the app.
- **File names:** `hydris_risk_report_{site_id}_{YYYYMMDD}.pdf` / `.html`; portfolio: `hydris_risk_report_portfolio_{YYYYMMDD}.pdf`.

## 4. Entry points

**Streamlit (`app/`):**
- In the selected-factory view: buttons "Download factory report (PDF)" and "(HTML)".
- In the sidebar under downloads: "Download portfolio report (PDF)" and "(HTML)".
- Generate on click with `st.download_button` and a spinner; cache rendered bytes by (file hash, site_id, format). Note on screen that reports include all risks regardless of filters.

**CLI (`cli.py`):**
```
python -m hydris_risk.cli report --input sample/factories.csv --out outputs/ \
    --format pdf|html|both --type factory|portfolio [--site-id F001]
```
`--type factory` without `--site-id` writes one file per factory. Unknown site_id exits with code 2.

## 5. Tests

- **explain.py:** for each status and each special case, sentences are correct, numbers match the result, no contradiction with labels, no "None"/"nan". Watch/not-present future-crossing sentences tested with fixture future values that do and do not cross.
- **builder:** every risk appears exactly once across sections 4–9; counts match the engine summary; filters have no effect; `generated_at` is respected (deterministic output).
- **PDF:** renders for the fixture and (if the real GDB is present) for Tiruppur. Extract text with `pypdf` and assert: all 14 risk names present, the not-present framing sentence present, "–" survives, Tiruppur golden phrases present (e.g. "20.9%", "453803", "no significant trend"). Page count > 1, no exception for a portfolio of the 6 sample factories.
- **HTML:** valid single file, no `http://`/`https://` resource URLs except the citation link, contains all 14 risk names.
- **App:** AppTest confirms the download buttons exist; the e2e browser test downloads the factory PDF and checks it is non-empty and starts with `%PDF`.
- Performance: portfolio PDF for 6 factories in under 10 s; report it.

Pin new dependencies (`reportlab`, `matplotlib`, `jinja2`, `pypdf`) in `pyproject.toml`. Use `encoding="utf-8"` for all text files.

## 6. Build order and review points

1. `report_templates` in `risk_rules.yaml` + `explain.py` + tests.
   **Review point A:** print, for Tiruppur, the threshold-position and what-would-change sentences for all 14 risks. Stop for wording review.
2. Report models + builder + tests.
3. Charts.
4. PDF renderer.
   **Review point B:** generate the Tiruppur factory PDF, render pages 1–3 and one not-present page to PNG (pypdfium2), and show them. Stop for layout review.
5. HTML renderer.
6. Portfolio report, CLI command, Streamlit buttons, e2e download test.
7. README section "Reports", DATA_NOTES only if new data facts are found.

## 7. Acceptance criteria

1. Factory and portfolio reports export as PDF and HTML from both the app and the CLI.
2. Every factory section contains all 14 results exactly once, grouped by status, regardless of UI filters.
3. Every Present, Watch and Not-present block explains its status with: the existing reason, threshold position (where meaningful), and what would change the status.
4. Not-present blocks never imply safety; special cases (gtd insignificant trend, cfr No Risk, arid, ucw low collection, country-scale, no data) use their specific wording.
5. No "None", "nan", empty headings or label-contradicting numbers anywhere in the output.
6. The en dash and other symbols render in the PDF on Windows.
7. Existing 141 tests still pass; new tests pass; `ruff` clean.