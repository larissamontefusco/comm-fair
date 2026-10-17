# CommFair — Community Energy Research

<div align="center">

<img src="assets/logos/tecnico-lisboa.png" alt="Técnico Lisboa" height="76" /> &nbsp;&nbsp;
<img src="assets/logos/inesc-id.png" alt="INESC-ID" height="76" /> &nbsp;&nbsp;
<img src="assets/logos/iti.png" alt="Interactive Technologies Institute (ITI)" height="76" />

<p><strong>Energy forecasting, cooperative stability and fair benefit allocation</strong></p>
<p><small>ComErgy Grand Challenge 2026 · Public scientific methods and verified research evidence</small></p>

</div>

CommFair is a research contribution to the **ComErgy Grand Challenge 2026**.
It separates the economic value created by coordinated energy operation from
market settlement, individual participation protection and coalition stability.
This repository publishes forecasting methods and annual coalition evidence;
it complements the deployed CommFair platform and Final Technical Report.
It does not contain or reproduce the web platform, user accounts or database.

## Scientific contributions

- **Forecasting:** leakage-aware hourly load and PV forecasting, historical
  baselines, model benchmarking and validation-based champion selection.
- **Cooperation:** a fixed nine-household, 8,760-hour physical benchmark,
  standalone counterfactuals and all 512 subset values.
- **Stability and distribution:** core/least-core evidence, market-anchored
  budget-balanced repair and comparison of 13 allocation/governance policies.
- **Fragmentation:** reconstruction of all 255 complementary bipartitions and
  their additional annual operating costs relative to the grand coalition.

The published annual evidence gives AUD 4,244.99 cooperative surplus (43.52%
less cost than independent operation) and a numerically nonempty core. These
are results for one fixed perfect-foresight benchmark, not universal guarantees
or forecasts of outcomes for registered operational communities.

## Repository map

```text
forecast/               Forecasting source, CLI, tests and data setup documentation
coalitions/             Coalition methods, verification scripts, evidence and figures
  comfair/artifacts/    Five immutable canonical annual research artifacts
  results/              Deterministically derived research snapshot
  scripts/              Verification, figure generation and bounded solver smoke test
  tests/                Scientific verification and release-boundary tests
assets/logos/           Existing institutional branding (not Apache-2.0 licensed)
examples/                Isolated CSV data and runnable forecast/coalition examples
requirements.txt        Forecasting dependencies only
Dockerfile              Reproducible Python 3.12 environment for all workflows
compose.yaml            Short Docker services for verification and examples
LICENSE, NOTICE         Code licence and attribution/third-party restrictions
```

## Docker quick start

The container packages the scientific command-line application; this repository
does not contain an HTTP server or expose a network port. Build the image once:

```bash
docker compose build
```

The included example CSVs can be tested immediately, without the private
benchmark workbook:

```bash
# Validate shape, timestamps and tariff relationships.
# This is a test command: it reports PASS/FAIL and does not create forecasts.
docker compose run --rm example-csv-tests

# Run both forecasting algorithms on the example consumption/production data.
docker compose run --rm example-forecast-champion
docker compose run --rm example-forecast-naive24

# Compare baseline and cooperative_pool costs using all three CSVs.
docker compose run --rm example-coalition
```

The forecast commands create these CSV files on the host:

```text
outputs/examples/forecast-champion/predictions.csv
outputs/examples/forecast-naive-24/predictions.csv
```

Each row contains the forecast origin, target hour, horizon, member, model,
predicted kW and actual kW. JSON metric summaries are stored beside the CSVs.
See the
[CSV examples guide](examples/README.md) for local commands, parameters and the
explicit no-battery assumption used by the coalition example.

Then run the workflows that need no private input data:

```bash
# Verify hashes, 512 coalition identities, core inequalities and policies.
docker compose run --rm verify

# Run the 15 public coalition/release tests.
docker compose run --rm coalition-tests

# Read one published cooperative-pool coalition (members 1, 3 and 8).
docker compose run --rm coalition-query

# Query other members/model without changing compose.yaml.
docker compose run --rm app \
  python coalitions/scripts/query_coalition.py --members 2,4,9 --model baseline

# Generate the fragmentation PDF and PNG under outputs/coalitions/figures.
docker compose run --rm figures

# Solve the bounded two-member/two-hour physical and market example.
docker compose run --rm solver-smoke
```

The same image can be used without Compose:

```bash
docker build -t commfair:local .
docker run --rm commfair:local
```

Compose mounts `outputs/` for generated files. It also mounts the ignored
`forecast/reader`, `forecast/inputs`, `coalitions/reader` and
`coalitions/inputs` directories read-only, so authorized private inputs remain
outside the image.

## Quick start: coalition evidence

From the repository root, with Python 3.11 or later (verified on 3.13.5):

```bash
python3 -m venv .venv-coalitions
. .venv-coalitions/bin/activate
python coalitions/scripts/verify_release.py
python -m unittest discover -s coalitions/tests -v
python -m pip install -r coalitions/requirements.txt
python coalitions/scripts/generate_coalition_fragmentation_figure.py --output-dir outputs/coalitions/figures
```

Verification and tests use only the Python standard library; Matplotlib/NumPy
are needed only for figures. No solver, private dataset, network service or
platform installation is needed for this path. See the
[Coalition Analysis README](coalitions/README.md) for the exact scientific
contract, hashes, expected results and limits of full regeneration.

## Quick start: forecasting

Use a separate environment. Both modules contain a package called `comfair`;
do not combine their import paths or install one over the other.

```bash
# From the repository root; exit another virtual environment first.
python3 -m venv .venv-forecast
. .venv-forecast/bin/activate
python -m pip install -r requirements.txt
cd forecast
# Supply the authorized workbook and two CSVs before the next commands.
python -m scripts.demo --origin-t 7008 --model champion --output-dir outputs/demo
python -m pytest tests -q
```

Read the existing [forecasting methodology](forecast/docs/FORECASTING_ORIGINAL.md)
and [dataset setup](forecast/docs/DATA_SETUP.md). There is no separate forecasting
README in this checkout; these are the existing module documents. Paths in the
setup guide are relative to `forecast/`, not the repository root. Historical
`backend/` examples in the methodology describe the original platform.

Inputs are not distributed. Forecasting dataset tests and inference therefore
require authorized external inputs; exhaustive forecasting experiments were
not rerun for this release review. The root dependency list is forecasting-only.
Custom split training is available as `python -m scripts.train_custom` from
`forecast/`; see its `--help` before running potentially expensive experiments.

### Forecasting algorithms in Docker

First place the authorized workbook and CSVs at the paths documented in
[Dataset setup](forecast/docs/DATA_SETUP.md). They are mounted read-only by
Compose and are never copied into the image. Then run commands from the
dedicated Compose services:

```bash
# 24-hour Ridge champion forecast.
docker compose run --rm forecast-demo-champion

# 24-hour seasonal naive forecast.
docker compose run --rm forecast-demo-naive24

# Configurable train/validation/test experiment using the default splits.
docker compose run --rm forecast-custom

# F0 persistence/naive-24/naive-168 benchmark.
docker compose run --rm forecast-f0

# F1 model-family benchmark. Run F0 first; Compose persists its output under
# outputs/forecast/f0 and mounts it at the path expected by F1.
docker compose run --rm forecast-f1

# Forecasting tests (dataset-dependent tests require all three input files).
docker compose run --rm forecast-tests
```

To use custom split dates, mount or place a JSON file under `outputs/` and pass
an overridden command:

```bash
docker compose run --rm forecast-custom \
  python -m scripts.train_custom \
  --splits-json /app/outputs/path/to/splits.json \
  --output-dir /app/outputs/forecast/custom-splits
```

## Algorithm and workflow reference

| Workflow | Command inside the container | Inputs | Status in this checkout |
| --- | --- | --- | --- |
| Published coalition verification | `python coalitions/scripts/verify_release.py` | Included JSON artifacts | Fully runnable |
| Baseline/cooperative-pool lookup | `python coalitions/scripts/query_coalition.py --members 1,3,8 --model cooperative_pool` | Included M3/M5 artifacts | Fully runnable; lookup, not a new solve |
| Public coalition tests | `python -m unittest discover -s coalitions/tests -v` | Included artifacts | Fully runnable |
| Fragmentation analysis | `python coalitions/scripts/generate_coalition_fragmentation_figure.py --output-dir outputs/coalitions/figures` | Included M5 artifact | Fully runnable |
| Deterministic insights snapshot | `PYTHONPATH=coalitions python -m comfair.presentation.insights --check` | Included five artifacts | Fully runnable |
| Physical/market smoke test | `python coalitions/scripts/smoke_physical.py` | Synthetic arrays created by the script | Fully runnable |
| Example CSV validation | `python -m unittest discover -s examples/tests -v` | Included example CSVs | Fully runnable |
| Example forecast: Ridge champion | See `examples/README.md` | Included consumption/production CSVs | Fully runnable; no workbook needed |
| Example forecast: naive-24 | See `examples/README.md` | Included consumption/production CSVs | Fully runnable; no workbook needed |
| Example coalition solve | `python examples/run_coalition_csv.py` | Included consumption/production/price CSVs | Fully runnable; assumes no batteries |
| Forecast demo: Ridge champion | `cd forecast && python -m scripts.demo --model champion` | Workbook + consumption/PV CSVs | Runnable with authorized inputs |
| Forecast demo: naive-24 | `cd forecast && python -m scripts.demo --model naive_24` | Same three files | Runnable with authorized inputs |
| Custom forecasting experiment | `cd forecast && python -m scripts.train_custom` | Same three files | Runnable with authorized inputs |
| F0 forecasting baselines | `cd forecast && python -m comfair.forecasting.benchmark --output-dir PATH` | Same three files | Runnable with authorized inputs |
| F1 forecasting benchmark | `cd forecast && python -m comfair.forecasting.model_benchmark --output-dir PATH` | Same inputs plus F0 at its expected path | Runnable with prerequisites |
| Full annual physical B0/B1 | `PYTHONPATH=coalitions python -m comfair.physical.run_baselines --output PATH --workbook PATH` | Authorized canonical workbook | Source available; exact regeneration environment required |
| Full annual M4 market | `PYTHONPATH=coalitions python -m comfair.market.run_market --output PATH --baseline PATH` | Workbook and matching M3 baseline | Source available; exact provenance required |
| Repair/governance regeneration | — | Missing historical intermediates/source manifest | Not runnable; published artifacts remain verifiable |

For commands not listed as Compose services, use the general form:

```bash
docker compose run --rm app <command>
```

## Reproducibility boundaries

**Level 1: verified artifact-based reproduction.** Hash checks, cost identities,
core witness feasibility, policy budget balance, the byte-identical snapshot,
255 bipartitions and fragmentation figures can be reproduced in this checkout.

**Level 2: partial, not a complete annual rerun.** The physical/market source
supports a small synthetic solver example. Full annual regeneration additionally
requires the benchmark workbook, missing intermediate artifacts and a coherent
historical source environment. The supplied later game runner targets the
platform's forecast-driven pipeline; it is not the historical annual cost oracle.
These incompatibilities are recorded in [the dependency audit](coalitions/DEPENDENCIES.md).
Compilation or successful artifact verification does not prove full regeneration.

## Licence and data rights

Original source and documentation are offered under [Apache-2.0](LICENSE), to
the extent the contributors have the necessary rights. Preserve [NOTICE](NOTICE).
Institutional logos, names and trademarks are excluded and imply no endorsement.
Third-party packages retain their own licences.

The private canonical workbook/CSVs are absent. The official competition CSV
dataset under `examples/data/comergy/` is included specifically for the
documented test workflows, but is not sufficient by itself for canonical
workbook-based regeneration. Derived artifacts contain benchmark household
profiles, incomes and energy summaries; permission to redistribute these derived
materials still requires confirmation. See [Coalition Analysis documentation](coalitions/README.md).
Do not infer dataset redistribution rights from the source-code licence.

## Authors and contact

| Author | Affiliation | Email | LinkedIn |
| --- | --- | --- | --- |
| **Larissa Montefusco** | Instituto Superior Técnico · INESC-ID | [larissa.montefusco@tecnico.ulisboa.pt](mailto:larissa.montefusco@tecnico.ulisboa.pt) | [LinkedIn](https://www.linkedin.com/in/larissa-montefusco/) |
| **Nicollas Nogueira** | Instituto Superior Técnico · ITI | [nicollas.nogueira@tecnico.ulisboa.pt](mailto:nicollas.nogueira@tecnico.ulisboa.pt) | [LinkedIn](https://www.linkedin.com/in/nicollas-nogueira-591232283/) |

Developed as part of the **ComErgy Grand Challenge 2026**.
