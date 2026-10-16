# ComFair forecasting — F0 foundation and F1 model benchmark

F0 provides audited targets, explicit information boundaries and three reproducible
reference forecasts. F1 adds bounded model benchmarking and validation-only
champion selection. M3/M4 remain unchanged. Optimiser adapters, rolling dispatch,
regret, repair and API integration belong to later milestones.

## Targets and sources

Discovered sources are `backend/reader/com_energy_consumption.csv` and
`backend/reader/com_energy_production.csv`: 8760 rows, synthetic timestamp plus
member_1..member_9. Consumption is checked exactly against validated workbook
A:I. The PV CSV reproduces the upstream reader's three-decimal output. Its maximum
difference from M3 is just below 0.0005 kW. The canonical `pv_available_kw` target
uses the **unchanged M3 proxy at full precision**, as required by section 6 of the
forecasting data contract; the rounded CSV remains an audited source/reference.
No source CSV, workbook, physical formula or assumption is changed.

`load_forecasting_data()` returns `ForecastDataset` plus an audit. Source and code
hashes, explicit conversion lineage, dimensions, invalid-value counts, member
mapping, alignment and source limitations are stored. Members 2,5,7 have no PV
and receive deterministic zero PV forecasts. The canonical logical row is
`(t, member_id, target, y)`; internal arrays are `(8760,9)` per target.

Missing, nonfinite or negative targets fail closed. No filling/interpolation.
CSV columns must match member IDs in order; time rows must be unique, hourly and
aligned. Repeated numeric vectors, including all-zero night PV rows, are valid
observations at different times and are reported separately from duplicate rows.

## Time, splits and availability

Canonical time is ordinal t=0..8759, hourly, without a verified year/timezone/DST
or interval-start/end label. CSV 2025 timestamps are synthetic display/transport
metadata only. No real weekday/month/holiday/season is inferred.

| Split | Inclusive ordinal range | Hours | Days |
|---|---|---:|---:|
| Train | 0..5255 | 5256 | 219 |
| Validation | 5256..7007 | 1752 | 73 |
| Test | 7008..8759 | 1752 | 73 |

`Split.stop` is exclusive. There are 73 daily origins per evaluation split. At
origin o, history contains t<o and public horizon steps are **1..24**, with
`target_t=o+horizon_step-1`. The last observed `as_of` coordinate is `o-1`, so
all targets are strictly after the as-of boundary. No origin is dropped.

`dataset.history(target,o)` copies only the observed prefix into `History`;
forecasters receive that bounded object, not the full future dataset. Validation
and test actuals become history only when their times precede a later origin.
Actuals for evaluation are read separately after predictions are issued. There
is no fitted preprocessing, scaler or imputer in F0.

## Features and weather

`features_at(history,target_t,member_id)` supports lags 1,2,3,24,48,72,168:
lag k is exactly y[target_t-k] **only if** 0<=target_t-k<origin. Otherwise it is
`None`, including unavailable short lags for later forecast horizons. No future
value is substituted. At target_t=origin this gives conventional shifted lags.
Rolling 24 mean/std/min/max and 168 mean/std use `[origin-window,origin)` only;
missing full history returns `None`. Standard deviation uses population ddof=0.
Periodic features use target_t mod 24/168 and sin/cos(2π phase/period), not dates.

`observed_weather` permits historical records only. Future realised weather
requests fail closed. No operational baseline accepts weather input, and no
oracle or external-weather experiment is implemented in F0. Realised weather is
used only to construct the canonical PV target for observation/evaluation.

## Baselines and schema

```python
from comfair.forecasting.data import load_forecasting_data
from comfair.forecasting import forecast

dataset, audit = load_forecasting_data()
result = forecast(dataset.history('load_kw', 5256),
                  target='load_kw', model_id='naive_24',
                  provenance=dataset.provenance)
json_text = result.to_json()
```

One `ForecastResult` covers one origin/target and all requested members; requesting
both targets means issuing one result for each target. It validates a complete
24-hour member grid and finite nonnegative predictions. Fields: schema_version,
model_id, target, origin_t, horizon_hours, member_ids, predictions, provenance,
diagnostics. Each prediction carries origin_t, target_t, horizon_step, member_id,
target and y_pred. `ForecastResult.from_json` validates a round trip. Ordering is
stable; no Pyomo/HiGHS or forecasting-library model objects are involved.

- Persistence: y[o-1] at all 24 horizons.
- Naive-24: y[target_t-24].
- Naive-168: y[target_t-168].

Unavailable seasonal history falls back to persistence; empty history falls back
to zero. Counts identify fallback and cold-start zeros separately. Zero-capacity
PV members bypass these baselines with explicit zeros. `clip_predictions` clips
negative predictions to zero and reports count and sum of correction magnitudes
in kW; nonfinite predictions are rejected. Forecast targets themselves are never
clipped: negative source targets are invalid.

These fallback, metric-threshold and ddof choices fill implementation details
left open by the contracts and are explicit in artifacts/docs. Seed=0 is recorded;
these baselines are deterministic and fit no parameters.

## Metrics and artifact interpretation

MAE and RMSE are in kW. WAPE=sum(abs(error))/sum(abs(actual)); it is null when
sum(abs(actual))<=n*1e-9 kW. sMAPE=mean(2*abs(error)/(abs(actual)+abs(predicted)))
over pairs with denominator>1e-9 kW. Excluded pairs are counted; if none remain,
sMAPE is null. In particular all-zero truth/prediction is not an artificial 0%
relative score. Nonzero predictions at zero actual contribute sMAPE=2.
Relative metrics are **ratios**, multiplied by 100 for displayed percentages.

Reports include per-member, per-target, per-horizon, pooled/micro and member macro.
Native aggregate metrics retain all nine members. PV relative aggregates use PV
owners only; undefined member relative scores are excluded with counts. Macro
RMSE is the mean member RMSE, not a pooled RMSE. Different denominators/weighting
are intentionally visible. Predictions are never rounded before metrics.

Validation and descriptive test results are separate. F0 does not select any
champion or use test outcomes for model changes. The frozen F1 test/selection
protocol is not exercised by these descriptive reference results.

## Reproduce

```bash
docker compose build backend
docker compose run --rm --no-deps backend pytest tests/ -q --tb=short
docker compose run --rm --no-deps backend pytest tests/test_forecasting.py -q
mkdir -p backend/comfair/artifacts/forecasting
docker compose run --rm --no-deps --user "$(id -u):$(id -g)" \
  -v "$PWD/backend/comfair/artifacts/forecasting:/results" backend \
  python -m comfair.forecasting.benchmark --output-dir /results
```

Outputs: `f0_data_audit.json`, `f0_baselines.json`, `f0_predictions.csv`,
`f0.runtime.json`. The CSV retains row-level predictions, truths and errors at
machine precision; JSON references its SHA-256. Row ordering is explicitly
recorded in baseline configuration. All canonical files exclude timestamps/runtime;
runtime is separate, linked to artifact hashes. Repeat in another directory and
compare canonical bytes. M3/M4 artifact hashes are checked before/after each run.


## F1 model benchmark

`python -m comfair.forecasting.model_benchmark --output-dir PATH` runs F1.
Only F1 outputs are created; F0 artifacts are verified against their frozen hashes.
A destination containing F1 artifacts is rejected to preserve a previous test run.

Fitted candidates: 24 configurations per target, plus three exact F0 baselines,
**54 validation entries** total. Explicit finite search (no AutoML/early stopping):

| Family | Strategy | Hyperparameters varied | Fixed parameters |
|---|---|---|---|
| AutoReg | local, recursive | dense lags 24 or 168 | constant trend |
| Ridge | local/global, direct | alpha 0.1, 1, 10 | SVD solver |
| RandomForest | local/global, direct | min_samples_leaf 1 or 4 | 64 trees, depth 12, max_features 1.0 |
| ExtraTrees | local/global, direct | min_samples_leaf 1 or 4 | 64 trees, depth 12, max_features 1.0 |
| LightGBM | local/global, direct | num_leaves 15 or 31 | 100 trees, learning_rate .05, min_child_samples 20, max_depth -1 |
| XGBoost CPU | local/global, direct | max_depth 3 or 6 | 100 trees, learning_rate .05, min_child_weight 1, subsample/colsample 1 |

RF uses its standard bootstrap=True; ExtraTrees bootstrap=False. Other library
settings retain the pinned version defaults. LightGBM uses deterministic=True,
force_col_wise=True, verbosity=-1. XGBoost uses hist and reg:squarederror. All
stochastic estimators use seed 0, CPU, n_jobs=1; threadpoolctl limits BLAS/OpenMP
inside fitting/inference to one thread. No GPU or future weather is used.

Local fits one model per active member; global fits one model across active
members with fixed canonical one-hot identity 1..9. PV members 2,5,7 are excluded
from fitting and receive zero. No demographic/static capacity features are added.
AutoReg is local only, fitting its own lagged series; recursive forecasts use its
raw predictions for subsequent lags, then clip final output with diagnostics.

Direct supervised rows are (origin, horizon_step, member). They use all seven F0
lags, six rolling statistics, four sin/cos periodic features and horizon_step
(18 numeric features); global adds nine identity columns. Origin feature assembly
reuses F0 `features_at` for rolling definitions and vectorises horizon-dependent
lags/phases; exhaustive synthetic tests compare against F0 for all 24x9 rows.
Unavailable target-relative short lags remain NaN and are filled by a median
imputer fitted on TRAIN only, with missing indicators. Ridge additionally uses a
TRAIN-only StandardScaler. No target values are filled or changed.

The first 168 hours supply lag warm-up. Training labels cover 168..5255, at 212
daily origins 168..5232. AutoReg uses all eligible original observations. Candidate
parameters/preprocessing are fitted once on TRAIN (explicit bounded-cost policy
allowed by the F1 request); observed feature history expands at all 73 validation
origins. No candidate is trained on validation labels. All candidates use the same
validation windows 5256..7007. There are no feature-set searches beyond this
common direct representation and AutoReg's two lag orders.

`fit_candidate(candidate, History, target, zero_pv_members)` returns a fitted
forecaster. Its `.forecast(History)` accepts only observed prefix data and returns
F0's Pyomo-independent `ForecastResult`, with training range, observed range,
configuration and clipping diagnostics. Model objects never enter that schema.
The optional `rows` argument caches internally generated training rows; callers
must use `supervised_rows` for feature construction, not external feature tables.

### Selection and test lock

`select_champion` accepts only typed `ValidationScore` records. It has no file,
dataset or test-metric interface. Rank by validation macro member WAPE, using
owners only for PV. Anchor the relative 1% tie band at the lowest WAPE; prefer
lowest validation MAE in that band (all-member native F0 MAE, equal to macro MAE
because sample counts are equal). If MAE differs by at most 1e-12 kW, compare total
fit+inference time; time differences <=1 microsecond use fewer fitted models,
then lexical model ID. This anchors the otherwise non-transitive pairwise tie
comparison and adds only explicit numerical tolerances, no weighted objective.
A naive baseline can win. The full score/tie trace is persisted. Runtime-based
ties, if reached, may be sensitive to machine timing; rerun comparison fails
rather than hiding any resulting change.

Both configurations and validation leaderboard are saved BEFORE any test
reference is requested or test forecast evaluated. Only selected configurations
are refitted on 0..7007, including train+validation; direct labels begin at 168.
Then evaluate the 73 locked test origins once. F0 test references are descriptive
comparators and are retrieved only after freeze. No other fitted candidate gets
a test evaluation. No model/hyperparameter changes follow test results.

Model binaries are not persisted: configuration plus source/data/library hashes
supports deterministic retraining without unsafe/version-fragile pickle files.
F1 does not implement F2 inference adapters.

### Artifacts and reproduction

- `f1_leaderboard.json`: every validation candidate, full per-member/horizon and
  micro/macro metrics, configuration, warnings, improvement versus each baseline.
- `f1_champions.json`: both frozen configurations, selection traces, provenance.
- `f1_test_results.json`: frozen champion test metrics and F0 references only.
- `f1_test_predictions.csv`: 31,536 rows, full precision, target/load then PV,
  origin, horizon, member; its SHA-256 is in test JSON.
- `f1.runtime.json`: variable training/inference times, family totals, slowest
  candidate, total execution and canonical hashes. Canonical JSON runtime fields
  are references into this file, not machine-dependent seconds. Fit timing for
  validation excludes shared feature-table construction; total run includes it.

```bash
docker compose build backend
docker compose run --rm --no-deps backend pytest tests/ -q --tb=short
docker compose run --rm --no-deps backend \
  pytest tests/test_forecasting.py tests/test_forecasting_models.py -q --tb=short
docker compose run --rm --no-deps --user "$(id -u):$(id -g)" \
  -v "$PWD/backend/comfair/artifacts/forecasting:/results" backend \
  python -m comfair.forecasting.model_benchmark --output-dir /results
# Repeat to a fresh directory; compares freeze/leaderboard BEFORE test reproduction.
mkdir -p /tmp/comfair-f1-repeat
docker compose run --rm --no-deps --user "$(id -u):$(id -g)" \
  -v /tmp/comfair-f1-repeat:/results \
  -v "$PWD/backend/comfair/artifacts/forecasting:/reference:ro" backend \
  python -m comfair.forecasting.model_benchmark --output-dir /results \
  --verify-against /reference
```

Reproduction repeats the frozen experiment solely to verify deterministic bytes;
it is not an opportunity to inspect test scores and retune. Non-runtime output
must match exactly; forecasts are never rounded to manufacture agreement.
