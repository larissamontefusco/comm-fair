# CommFair Forecasting 

Independent, reproducible hourly 24-step forecasting of community electricity
consumption (`load_kw`) and available PV power (`pv_available_kw`) for the
nine-member ComErgy benchmark. No frontend, FastAPI, database, authentication,
optimisation solver, EV/EVSE management or deployment is included.

## Models and scientific protocol

- **F0:** persistence, naive-24 and naive-168 benchmarks, strict 24-hour leakage
  boundary and MAE/RMSE/WAPE/sMAPE evaluation.
- **F1:** `AutoReg`, `Ridge`, `RandomForest`, `ExtraTrees`, `LightGBM`,
  `XGBoost`, local/global alternatives, validation-only model selection and
  locked test evaluation (original F1 benchmarking methodology retained).
- **Reference champions:** global Ridge (alpha=0.1) for load, naive-24 for PV.
  Test dates are synthetic dataset labels, not real-time forecasts.
- **Configurable training:** optional different contiguous train/validation/test
  intervals through `scripts/train_custom.py`. It does **not** call the website.

Training features are constructed from observed history only. Fitted scalers
and imputers use train data only. Reference splits in hourly ordinals: train
`[0, 5256)`, validation `[5256, 7008)`, test `[7008, 8760)`. Forecast
origins are daily, with a 24-hour horizon and nine members.

## Structure

```text
comfair/
  forecasting/          # F0/F1 methods, features, splits, evaluation, custom engine
  data/                 # Official benchmark loader and domain records
  physical/             # PV generation proxy (not the optimisation model)
  config/assumptions.yaml
  artifacts/forecasting/ # F0 checkpoints generated locally (not tracked)
reader/                  # CSV generator scripts; supply official workbook here
inputs/                  # Supply two source CSV files here
scripts/                 # CLI: demo inference and custom split training
tests/                   # Direct tests with no server
docs/                    # Dataset setup and historical F0/F1 specifications
```

## Install and run (Python 3.11/3.12)

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**Code-only submission:** the benchmark workbook and consumption/production
CSVs are not included. See [docs/DATA_SETUP.md](docs/DATA_SETUP.md) for the
three required input files and redistribution guidance. Place the verified files
under `reader/` and `inputs/`. Or copy them from your original checkout:

```bash
python -m scripts.import_data --backend ../comm-energy-grand-challenge-inescid-main/backend
```

Run a 24-hour retrospective forecast using frozen F1 champion configurations:

```bash
python -m scripts.demo --origin-t 7008 --model champion --output-dir outputs/demo
python -m scripts.demo --origin-t 7008 --model naive_24 --output-dir outputs/naive
python -m pytest tests -q
```

Outputs: `predictions.csv` (24 hours × 9 members × 2 targets) and
`summary.json` (metrics for historical held-out actuals). `--origin-t` may
be 7008, 7032, ..., 8736.

Train and evaluate with the reference or custom synthetic-date splits:

```bash
python -m scripts.train_custom --output-dir outputs/custom
python -m scripts.train_custom --splits-json my_splits.json --output-dir outputs/other
```

Example `my_splits.json`:

```json
{
  "train": {"start_date": "2025-01-01", "end_date": "2025-07-31"},
  "validation": {"start_date": "2025-08-01", "end_date": "2025-08-31"},
  "test": {"start_date": "2025-09-01", "end_date": "2025-12-31"}
}
```

For the exhaustive F0 and F1 reproduction with the standalone provenance gates:

```bash
python -m comfair.forecasting.benchmark --output-dir comfair/artifacts/forecasting
python -m comfair.forecasting.model_benchmark --output-dir outputs/full-f1
```

F1 fits many model configurations and may take a substantial amount of CPU time.
Each F1 output directory must be new. The original integrated provenance gates
requiring M3/M4 optimiser results were intentionally replaced by F0-only source
checks and digest verification. The mathematical forecast models, evaluation and
validation/test boundaries are not altered by this packaging. This standalone
version must not be represented as byte-identical to the original full integrated
artifact provenance. The reference champion identities are not a guarantee
that runtime-based tiebreaks choose identical champions on every machine.

## Submission boundaries

No `/frontend`, `main.py`, `Dockerfile`, FastAPI routes, database tables or
credentials. Data, historical evidence and software licensing must be reviewed
before making the GitHub repository public. Commit this code-only tree to a
**new Git repository**, not as a fork requiring access to the private platform.
