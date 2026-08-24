# PROJECT AUDIT

**Audit date:** 2026-08-24
**Scope:** full inspection of the workspace as it existed before this platform was built.
**Purpose:** establish exactly what data and ML work already exists, what it can and cannot
support, and what the platform is therefore allowed to claim.

---

## 1. Workspace as found

| File | Size | Type | Verdict |
|---|---|---|---|
| `New_IM_output.csv` | 3.83 MB | Half-hourly meter + weather readings, 47 columns | **Canonical dataset** |
| `merged_df.csv` | 1.44 MB | Half-hourly meter + weather readings, 8 columns | Strict subset of the above |
| `hosue_appliances_gt.csv` | 809 B | Appliance metadata (brand / star rating / count) | **Canonical metadata** |
| `energy_inefficiency_model_with_weather_integration_code.ipynb` | 466 KB | Weather-integrated inefficiency model | **Canonical ML pipeline** |
| `08_exp.ipynb` | 1.53 MB | Earlier experiment on `New_IM_output.csv` | Superseded, kept for reference |
| `Combined Weather Report.docx` | 247 KB | Narrative document | Not machine-readable input |

There was **no backend, no frontend, no API, no database, no test suite, no dependency
manifest, and no serialised model artefact** (`.pkl` / `.joblib` / booster JSON) anywhere in the
workspace. The ML "model" existed only as notebook code that retrains on every execution.

Files have been relocated (contents unchanged): CSVs to `data/raw/`, notebooks and the DOCX to
`notebooks/`.

---

## 2. Dataset: `New_IM_output.csv` (primary)

- **Rows:** 22,084
- **Time resolution:** 30 minutes
- **Timestamp column:** `date_time`, formatted `DD-MM-YYYY HH:MM` — day-first. Parsing it as
  month-first silently corrupts the series, so the loader pins `dayfirst=True`.
- **Ordering:** rows are not globally sorted by time; the loader sorts per site.
- **Missing values:** none in any numeric column. `*_name` columns use the literal string `NA`
  to mean "channel not present".

### Columns

| Group | Columns |
|---|---|
| Identity | `date_time`, `house_id` |
| Aggregate appliance | `ac_state`, `ac_power`, `geyser_state`, `geyser_power` |
| Weather | `Temperature` (degrees C), `Humidity` (% RH) |
| Sub-metered channels | `ac1..ac3`, `cell_tester1`, `chamber1..chamber9`, each with `_name`, `_state`, `_power` |

`*_power` is instantaneous **watts**; `*_state` is binary on/off. Energy for one 30-minute
interval is therefore `power_W * 0.5 / 1000` kWh, a conversion the notebook never performs
(see section 5).

### Sites present

| `house_id` | Rows | Date range | AC on-intervals | Geyser on-intervals | Notes |
|---|---|---|---|---|---|
| `House_1` | 1,065 | 2025-09-25 to 2025-10-23 | 0 | 76 | Geyser-active |
| `House_2` | 569 | 2025-10-11 to 2025-10-23 | 0 | 40 | Geyser-active, only 12 days |
| `House_4` | 5,215 | 2025-06-16 to 2025-10-12 | 1,314 | 0 | AC-active, longest series |
| `House1_Delhi` | 1,344 | 2025-06-04 to 2025-08-02 | 839 | 5 | AC-active |
| `House1_Hyderabad` | 2,058 | 2023-05-02 to 2023-06-13 | 0 | 0 | **All states 0** |
| `House2_Hyderabad` | 1,890 | 2023-05-02 to 2023-06-13 | 0 | 0 | **All states 0** |
| `House3_Hyderabad` | 2,037 | 2023-05-02 to 2023-06-13 | 0 | 0 | **All states 0** |
| `House4_Hyderabad` | 2,034 | 2023-05-02 to 2023-06-13 | 0 | 0 | **All states 0** |
| `House5_Hyderabad` | 2,062 | 2023-05-02 to 2023-06-13 | 0 | 0 | **All states 0** |
| `Singapore_2` | 3,810 | 2026-06-01 to 2026-07-31 | 0 | 0 | Industrial/lab site, sub-metered only |

**Critical finding — the five Hyderabad sites carry non-zero `*_power` but their `*_state`
columns are identically 0.** Every feature in the existing pipeline is computed over
`state == 1` rows only, so those sites produce all-zero feature vectors. The platform ingests
them and shows their consumption, but flags them `state_signal_missing` and excludes them from
inefficiency classification instead of scoring degenerate features.

**`Singapore_2`** has `ac_power = geyser_power = 0` throughout; all of its load sits in 13 named
sub-channels (`Singapore_3`, `Singapore_4`, `Singapore_7` ... `Singapore_20`) covering 3 ACs,
1 cell tester and 9 environmental chambers, peaking at 12.8 kW. That is a commercial/industrial
profile, not a household. `chamber2`, `chamber3` and `chamber9` are named and stateful but read
0 W for the entire period.

### Weather coverage

`Temperature` spans 18.5 to 44.0 degrees C and `Humidity` 12.6 to 100 % across the corpus.
Weather is attached to every reading, so weather-aware analysis is available for **all** sites.

---

## 3. Dataset: `merged_df.csv` (secondary)

18,274 rows, 8 columns, ISO `YYYY-MM-DD HH:MM:SS` timestamps. Row-for-row it is
`New_IM_output.csv` minus `Singapore_2` (18,274 + 3,810 = 22,084), with three sites under older
names:

```
House1_Jaipur -> House_1     House2_Jaipur -> House_2     House3_Jaipur -> House_4
```

The ingestion layer normalises these aliases. `merged_df.csv` is kept as a cross-check source,
not as a second source of truth.

---

## 4. Metadata: `hosue_appliances_gt.csv`

23 data rows plus 2 blank separator rows, which the loader drops. Covers **only** `House_1`,
`House_2` and `House_4`.

| Site | AC rows (units) | Geyser rows (units) | Brands |
|---|---|---|---|
| `House_1` | 6 rows (6 units) | 4 rows (5 units) | Daikin, Blue Star, Panasonic, Voltas x2, Hitachi / Haier, Indo x2, Crompton, Indo |
| `House_2` | 2 rows (5 units) | 3 rows (4 units) | Mitsubishi, Lloyd / Hindware, Indo, Hindware |
| `House_4` | 6 rows (7 units) | 2 rows (4 units) | LG, Panasonic x3, Samsung, Voltas / Venus, Pearl |

`star_rating` is `NA` for 5 of the 23 rows (`House_1` G5, `House_2` G4, and `House_4`
AC1, G1 and G4). `appliance_count` is a multiplier — one row can
represent 2 or 3 identical units. The house-level rating used by the pipeline is the
`appliance_count`-weighted mean of the non-null ratings, matching the notebook.

**No metadata exists for the Delhi, Hyderabad or Singapore sites.** Appliance-replacement
analysis and star-adjusted thresholds are therefore unavailable there, and the platform reports
that explicitly rather than substituting a default rating.

---

## 5. Existing ML pipeline

Source: `notebooks/energy_inefficiency_model_with_weather_integration_code.ipynb`.

### Shape

Per **(site, appliance)** pair: daily aggregation, residual-based labelling, then binary
classification of each *day* as efficient or inefficient.

The notebook runs exactly two pairs:

```python
appliance_map = {"ac": ("AC", ['House_4']), "geyser": ("Geyser", ['House_1','House_2'])}
```

which is precisely the set of (site, appliance) combinations that have both usable on-state
signal and appliance metadata.

### Stage 1 — daily feature extraction (20 features per appliance-day)

Computed over `state == 1` rows: `total_energy` (sum of watt samples, **not** kWh),
`on_duration` (count of 30-minute on-intervals), `energy_per_hour`, `duty_cycle`, `cycles`,
`std_power`, `power_range`, `cv_power`, `short_cycles` (runs under 10 intervals),
`long_run_ratio` (runs over 30 intervals), `power_gradient`, `peak_average_ratio`, plus the
weather block `temperature_mean`, `temperature_std`, `humidity_mean`, `humidity_std`,
`temp_runtime`, `humidity_runtime`, `runtime_per_degree`, and
`heat_index = temperature_mean + 0.1 * humidity_mean`.

### Stage 2 — expected-energy baseline (the "expected vs actual" engine)

`LinearRegression` fitted on **training active days only**:

```
expected_energy ~ on_duration + duty_cycle + cycles + heat_index
energy_residual = total_energy - expected_energy
```

This is where weather enters the baseline: `heat_index` lets expected energy rise with heat, so
a hot-day increase is *explained* rather than flagged.

### Stage 3 — star-adjusted labelling

```
base_threshold = 75th percentile of training-set residuals
adj_threshold  = base_threshold * (2 - star_rating / max_star_rating)
label          = 1 if residual > adj_threshold
```

A better-rated appliance gets a **lower** threshold, i.e. it is held to a higher standard.

### Stage 4 — classifier

`XGBClassifier(n_estimators=300, learning_rate=0.1, max_depth=4, min_child_weight=4, gamma=1,
reg_alpha=0.5, reg_lambda=2, scale_pos_weight=2.8, objective="binary:logistic",
random_state=42)` over **9 purely behavioural features**:

```
duty_cycle, std_power, power_range, cv_power, short_cycles,
temp_runtime, heat_index, peak_average_ratio, power_gradient
```

Energy, average power and the usage flag are deliberately **excluded** to avoid leaking the
label. The split is chronological, 70/30 over active days.

### Outputs available

`predict` gives 0/1, `predict_proba` gives the probability used as confidence, and
`feature_importances_` gives per-model attribution used to explain *why* a day was flagged.

### Documented limitations

1. **No ground truth.** Labels are self-generated from a residual percentile. The model learns
   to reproduce a statistical definition of "unusually high for its own runtime and weather",
   not an externally verified notion of inefficiency.
2. **Small samples.** `House_2` has only 12 days. The notebook itself skips folds with fewer
   than 5 training or 3 test active days, and warns when test positives are under 3.
3. **Day-level only.** No sub-daily detection and no per-physical-unit (AC1 vs AC2) attribution.
4. **Two appliance classes only** — `ac` and `geyser`.
5. **Units.** `total_energy` is a sum of watt samples, not kWh. Useful as a model feature,
   meaningless as a bill. The platform computes billing energy separately as
   `sum(power_W) * 0.5 / 1000`.
6. **Relative threshold.** By construction roughly 25 % of training days are labelled
   inefficient, so the positive rate is a property of the definition, not of the building.
7. **No persistence.** The notebook retrains end-to-end on every run.

---

## 6. What the data does *not* contain

Nothing in the workspace provides solar generation, battery state, EV charging, tariff
schedules, grid emission factors, occupancy, appliance-level cost, or real-time telemetry.

The platform therefore treats all of these as **configuration or integration points, never as
measurements**. Tariff and emission factor come from `.env`. Solar, battery and EV are typed,
disabled-by-default modules that report "no renewable asset configured" instead of rendering
invented numbers. Every figure the UI shows carries a provenance tag: `measured`, `predicted`,
`estimated`, `simulated`, or `unavailable`.

---

## 7. Decisions taken from this audit

1. `New_IM_output.csv` is the single ingestion source; `merged_df.csv` aliases are normalised
   into it.
2. The notebook pipeline is **ported, not rewritten** — feature maths, baseline regression,
   star-adjusted threshold and XGBoost hyperparameters are reproduced exactly, then persisted to
   `ml/artifacts/` so that serving never retrains.
3. Billing energy in kWh is computed separately from the model's `total_energy` feature.
4. Sites lacking on-state signal or metadata are surfaced with an explicit capability flag
   rather than being silently scored.
5. Forecasting cannot reuse the classifier, because it is a classifier. A separate, deliberately
   simple and back-tested daily-energy forecaster was added and is reported with its own
   measured error bars.
