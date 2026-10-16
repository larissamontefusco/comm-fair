# CommFair Forecasting

<div align="center">

<img src="assets/logos/tecnico-lisboa.png" alt="Técnico Lisboa" height="76" /> &nbsp;&nbsp;
<img src="assets/logos/inesc-id.png" alt="INESC-ID" height="76" /> &nbsp;&nbsp;
<img src="assets/logos/iti.png" alt="Interactive Technologies Institute (ITI)" height="76" />

<p><strong>Independent, reproducible energy forecasting</strong></p>
<p><small>ComErgy Grand Challenge 2026 · Code-only research release</small></p>

</div>

This repository implements hourly 24-step forecasting of community electricity
consumption (`load_kw`) and available PV power (`pv_available_kw`) for the
nine-member ComErgy benchmark. It contains forecasting algorithms, data loading,
command-line experiments, reproducibility utilities and tests.

## Models and scientific protocol

- **F0:** persistence, naive-24 and naive-168 benchmarks, a strict 24-hour
  leakage boundary, and MAE/RMSE/WAPE/sMAPE evaluation.
- **F1:** `AutoReg`, `Ridge`, `RandomForest`, `ExtraTrees`, `LightGBM`,
  `XGBoost`, local/global alternatives, validation-only model selection and
  locked test evaluation.
- **Reference champions:** global Ridge (`alpha=0.1`) for load and naive-24
  for PV. Test dates are synthetic dataset labels, not real-time forecasts.
- **Configurable training:** contiguous train/validation/test intervals can be
  supplied through `scripts/train_custom.py`.

Features are constructed from observed history only; fitted scalers and
imputers use training data only. Reference splits, in hourly ordinals, are:
train `[0, 5256)`, validation `[5256, 7008)`, test `[7008, 8760)`.
Forecast origins are daily, with a 24-hour horizon and nine members.

## Repository structure

```text
assets/logos/           # Institutional logos (excluded from code licence)
comfair/
  forecasting/          # F0/F1 methods, features, splits, evaluation, custom engine
  data/                 # Benchmark loader and domain records
  physical/             # PV generation proxy
  config/assumptions.yaml
  artifacts/forecasting/ # F0 checkpoints generated locally (not tracked)
reader/                  # CSV generator scripts; supply benchmark workbook here
inputs/                  # Supply the two source CSV files here
scripts/                 # CLI: demo inference and custom split training
tests/                   # Tests with no external services
docs/                    # Dataset setup and historical F0/F1 specifications
LICENSE                  # Apache License 2.0
NOTICE                   # Attribution and third-party asset notices
```

## Install and run (Python 3.11/3.12)

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**Code-only submission:** the benchmark workbook and consumption/production
CSVs are not included. Follow [the dataset setup guide](docs/DATA_SETUP.md)
to prepare and place the required inputs under `reader/` and `inputs/`.

Run a 24-hour retrospective forecast using the frozen F1 champion
configurations, or compare against a naive baseline:

```bash
python -m scripts.demo --origin-t 7008 --model champion --output-dir outputs/demo
python -m scripts.demo --origin-t 7008 --model naive_24 --output-dir outputs/naive
python -m pytest tests -q
```

Outputs: `predictions.csv` (24 hours × 9 members × 2 targets) and
`summary.json` (metrics computed from held-out historical observations).
Valid `--origin-t` values are 7008, 7032, ..., 8736.

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

To reproduce the exhaustive F0 and F1 benchmarks:

```bash
python -m comfair.forecasting.benchmark --output-dir comfair/artifacts/forecasting
python -m comfair.forecasting.model_benchmark --output-dir outputs/full-f1
```

F1 fits many candidate configurations and can take substantial CPU time.
Use a new output directory for each F1 run. This standalone release checks
F0 source files and digests without depending on other research workflows.
The forecasting models, evaluation metrics and train/validation/test
boundaries have been retained. Runtime-dependent tiebreaks may select a
different model on different machines.

## Licence

The original source code and project documentation in this release are made
available under the **[Apache License, Version 2.0](LICENSE)**, subject to the
necessary rights and authorisations. Apache-2.0 requires preservation of
applicable notices and includes express patent terms and warranty disclaimers;
it is a permissive licence, including for commercial reuse.

**Institutional logos, names and trademarks are not covered by Apache-2.0.**
They remain the property of their respective owners; displaying affiliations
does not imply endorsement. The benchmark datasets are not included and are
subject to their own rights. See [NOTICE](NOTICE) for details.

## Authors and contact

| Author | Affiliation | Email | LinkedIn |
| --- | --- | --- | --- |
| **Larissa Montefusco** | Instituto Superior Técnico · INESC-ID | [larissa.montefusco@tecnico.ulisboa.pt](mailto:larissa.montefusco@tecnico.ulisboa.pt) | [LinkedIn](https://www.linkedin.com/in/larissa-montefusco/) |
| **Nicollas Nogueira** | Instituto Superior Técnico · ITI | [nicollas.nogueira@tecnico.ulisboa.pt](mailto:nicollas.nogueira@tecnico.ulisboa.pt) | [LinkedIn](https://www.linkedin.com/in/nicollas-nogueira-591232283/) |

Developed as part of the **ComErgy Grand Challenge 2026**.
