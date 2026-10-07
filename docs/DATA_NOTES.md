# Data notes: how the real Aqueduct data differs from SPEC.md

Source: `Aq40_Y2023D07M05.gdb` (Aqueduct 4.0 download of 2023-07-05). The full Step 0 dump is in `data/cache/inspection_report.md` (regenerate with `python -m hydris_risk.cli inspect`). Where SPEC.md and the data disagree, the data wins. This file lists every such case and every measurement the code relies on.

## 1. Differences from SPEC.md at a glance
| SPEC says | Real data | What the code does |
|---|---|---|
| Layer keywords `baseline_annual`, `monthly`, `future` | Layers are `baseline_annual`, `baseline_monthly`, `future_annual` | Keyword match, case-insensitive |
| Baseline joins to monthly/future by `pfaf_id` | `pfaf_id` repeats in baseline (68,506 polygons, 16,397 ids); `string_id` is unique | Baseline values always come from the containing polygon (section 8) |
| NoData as NaN or -9999 | -9999 in baseline (also values >= 9000), NaN in monthly/future, labels "No Data" / "No data" | One rule in `data/nodata.py` (section 3) |
| Coastal indicators NOT_APPLICABLE for inland sites | cfr/cep NoData is not an inland marker | NoData gives NO_DATA; cfr "No Risk" gives NOT_PRESENT. `NOT_APPLICABLE` exists in the enum but no service returns it |
| Grouped columns `w_awr_tex_{qan,qal,rrr,tot}_*` with `weight_fraction` | `weight_fraction` exists only for `tot` | Group breakdown uses scores only (section 7) |
| Category 3 = High for every indicator | `drr` has five labels: cat 3 is Medium-High, cat 4 is High | `drr` uses `present_min_cat: 4`, `watch_min_cat: 3`, `cat_titles` (section 4) |
| Units "from memory" | Units come from the label strings; `cep` is the only one not confirmed | `unit_verified` flags in `config/risk_rules.yaml` |
| rfr/cfr labels like "1 in 100" read as probabilities | The values are the share of people affected in an average year | Wording and caveats say so (section 5) |
| One baseline-wide geographic scale | Scale differs per indicator: sub-basin, aquifer or country | `scale` per risk, shown in the app and the CSV (section 6) |
| `factory_impact` text per risk | Replaced by `impact_present` and `impact_watch` | Two templates per risk in the rules file |

## 2. Layers and columns
- `baseline_annual`: 68,506 polygons; `baseline_monthly`: 16,395; `future_annual`: 16,395. All EPSG:4326 MultiPolygon.
- Monthly and future have one row per `pfaf_id` and join one-to-one.
- Join leftovers (`string_id_1`, `aq30_id_1`, `Shape_Leng`, `fid`, `fid_1`, `pfaf_id_1`) are dropped when the cache is built.
- Ten composite schemes exist (`def, agr, che, con, elp, fnb, min, ong, smc, tex`). Only `tex` is cached.
- Monthly values exist only for `bws`, `bwd`, `iav`. Future values (`bau|opt|pes` x `30|50|80`) exist only for `ws, wd, iv, sv`. The future layer also holds `ba` and `ww`, which are not cached. **There are no future values for rfr, cfr, drr, gtd, ucw, cep, udw, usa or rri.** `sev` has future values but no monthly values.

## 3. NoData
A value is missing if it is NaN or None, -9999, >= 9000 (`bws_raw` and `bwd_raw` reach 9999), or its label equals "no data" in any case.
- Category numbers drive logic. Labels are display only (future-layer labels are spelled differently, e.g. "Medium-high (20-40%)" vs "Medium - High (20-40%)").
- Code: `hydris_risk/data/nodata.py`.

## 4. Special categories (real values, not NoData)
| Case | Data | Treatment |
|---|---|---|
| Arid bws/bwd | `cat = -1`, `raw = 1.0` (a placeholder), label "Arid and Low Water Use" | Present (`arid_status`). The raw value is hidden, so "100%" is never shown. Own impact sentence: low use means a new factory can quickly create competition |
| gtd "Insignificant Trend" | `cat = -9999`, raw usually valid | Not present. Reason: the model finds no significant trend, which means no decline was detected, not that groundwater is safe. Raw shown only in the values panel |
| cfr "No Risk" | `cat = -1`, raw 0 | Not present: "Aqueduct records no coastal flood risk for this basin" (inland and protected coast cannot be told apart) |
| ucw "No to Low Wastewater Collected" | `cat = -1` | Watch: very little wastewater is collected by sewers, so the indicator misses uncollected sewage |

Category schemes: all indicators use cat 0-4 = Low, Low-Medium, Medium-High, High, Extremely High, **except `drr`**: Low, Low-Medium, Medium, Medium-High, High. Hydris applies its rule by label (Present from High, Watch from Medium-High).

NoData coverage: cfr NoData is the same 5,161 polygons as rfr NoData, and cep has valid values for most inland basins (cfr = -1), so neither marks "inland".

## 5. Units (from the labels; see `config/risk_rules.yaml`)
- `bws`, `bwd`, `udw`, `usa`, `ucw`: 0-1 fractions, shown as %.
- `rri`: raw is 0-100, shown as "57/100".
- `iav`, `sev`, `drr`: unitless. `gtd`: cm/y. `cep`: "ICEP index", **unverified**.
- **`rfr` / `cfr`: the share of the population expected to be affected by flooding in an average year.** A label such as "1 in 1,000" means 0.1% of people. It is not an annual probability or a return period, and reasons never say "1-in-100-year flood". Values are shown as a percentage and as "about 1.5 in every 1,000 people".
- Rounding never contradicts the label: when the rounded number would fall in a different category than the true value, decimals are added (0.2487 shows as 0.249, not 0.25, next to "Low (<0.25)").

## 6. Geographic scale of each indicator
Measured as the share of groups in which the indicator takes a single value:

| Indicator | within country | within state (gid_1) | within sub-basin (pfaf_id) | within aquifer (aqid) | Scale |
|---|---|---|---|---|---|
| bws, bwd, iav, sev, rfr, cfr, drr, cep | 11-25% | 22-59% | 100% | 9-35% | sub-basin |
| udw, usa | 12% | 23-24% | 100% | 12% | sub-basin |
| gtd | 8% | 24% | 41% | 100% | aquifer |
| ucw, rri | 100% | 100% | 68-70% | 25% | country |
| overall_textile | n/a | n/a | n/a | n/a | composite |

- **udw / usa are not national or state statistics in this dataset.** In India they take 352 distinct values and 33 of 36 states hold more than one. They are constant within a sub-basin, so they are described as sub-basin estimates.
- **ucw and rri are country-level** (identical for every polygon in a country).
- **gtd is aquifer-level.**
- The KPI "Most common local risk" counts sub-basin and aquifer risks only.

## 7. Overall textile (`w_awr_tex_*`)
- `_raw` is the weighted composite and `_score` is the 0-5 value after quantile remapping, so the score is not a simple average of the group scores. At Tiruppur raw is 2.80 and the score is 4.05, with group scores 2.61 / 4.69 / 3.44. **Headlines, cards and tables use the score, never the raw value.**
- `weight_fraction` exists only for `tot` (0.918 at Tiruppur). Per the data dictionary NoData is excluded from the weights, so it can be below 1. When it is, the result carries a caveat such as "About 8% of the weighting had no data here".
- The textile weights themselves are not in the data (they are in Kuzma et al. 2023). The reason text explains the overall score only from the published group scores and the top-3 indicator scores.

## 8. gtd sign convention (measured on the 58,675 rows with a valid raw)
**Positive raw = groundwater table falling; negative raw = rising** (`decline_sign: positive`).

| gtd_cat | label | n | min | median | max |
|---|---|---|---|---|---|
| 0 | Low (<0 cm/y) | 2,317 | -10.14 | -0.59 | -0.007 |
| 1 | Low - Medium (0-2 cm/y) | 4,609 | 8e-12 | 0.31 | 1.89 |
| 2 | Medium - High (2-4 cm/y) | 907 | 2.05 | 2.94 | 3.86 |
| 3 | High (4-8 cm/y) | 285 | 4.60 | 5.19 | 6.78 |
| 4 | Extremely High (>8 cm/y) | 148 | 8.84 | 12.86 | 44.10 |
| Insignificant Trend (cat -9999) | | 50,409 valid raw (+9,831 with raw also NoData) | -33.7 | 0.0009 | 18.5 |

"Insignificant Trend" rows have raw values on both sides of zero and no category, so the raw value carries no meaning there. Tiruppur's `gtd_raw` of -2.64 is a statistically insignificant **rise**.

## 9. Locator rule: baseline values are not all basin-level
`baseline_annual` is a union of sub-basin x province x aquifer polygons. The locator uses the **containing polygon** (`string_id`) for every baseline value and never looks baseline values up by `pfaf_id`. Only the monthly and future layers are keyed by `pfaf_id`.

Example, `pfaf_id` 453803 (5 polygons): the only columns that differ are the ids, `name_1`, `area_km2` and `gtd_raw` (-1.04, -1.75, -2.64, following the aquifer). `udw`, `usa`, the other indicators and `w_awr_tex_*` are identical for this basin. They can differ elsewhere, which is why the rule holds everywhere.

## 10. Impact indicators
`cep` (coastal eutrophication potential) has `kind: impact`. It measures pollution the basin contributes to coastal waters, not a risk to the factory's own supply. It keeps its status but is labelled "Downstream impact", is reported in its own section, and is excluded from present/watch counts, the map colour and the "local risk" KPI.

## 11. Golden site
Tiruppur (11.1085, 77.3411) falls in exactly one polygon, `453803-IND.31_1-2050` (Tamil Nadu, aqid 2050):
- Basin values: `bws_raw` 0.209484, `bws_cat` 2, label "Medium - High (20-40%)", `w_awr_tex_tot_score` 4.05094, worst `bws` month March (0.333257), `bau50_ws_x_r` 0.366078 (cat 2).
- Polygon values: `gtd_raw` -2.63896, `udw_raw` 0.087757, `usa_raw` 0.478314.

Asserted in `tests/test_golden_tiruppur.py` and `tests/test_locator.py` (both skip when the real GDB is absent).
