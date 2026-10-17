# CSV algorithm examples

This directory provides an isolated test path for the official ComErgy
competition CSV dataset. All three input files are organised under
`data/comergy/`; there are no duplicate input CSVs at the repository root. The
published coalition artifacts and private-input paths are not changed. These
CSVs are official competition inputs, but they do not replace the private
workbook required for exact regeneration of the canonical benchmark artifacts.

The expected coverage is 8,760 consecutive hourly rows for 2025 and columns
`member_1` through `member_9`. Production is treated as available PV power in
kW. In `prices.csv`, `electricity_price` is the import tariff and
`feedin_tariff` is the export tariff, both in AUD/kWh.

## Forecasting

Run from the repository root after installing `requirements.txt`:

```bash
cd forecast
python -m scripts.demo \
  --load-csv ../examples/data/comergy/com_energy_consumption.csv \
  --pv-csv ../examples/data/comergy/com_energy_production.csv \
  --model champion --origin-t 7008 \
  --output-dir ../outputs/examples/forecast-champion

python -m scripts.demo \
  --load-csv ../examples/data/comergy/com_energy_consumption.csv \
  --pv-csv ../examples/data/comergy/com_energy_production.csv \
  --model naive_24 --origin-t 7008 \
  --output-dir ../outputs/examples/forecast-naive-24
```

The champion is Ridge for consumption and seasonal naive-24 for production;
the naive command uses naive-24 for both. Each command writes predictions and
held-out metrics without requiring the private workbook.

Docker equivalents:

```bash
docker compose run --rm example-forecast-champion
docker compose run --rm example-forecast-naive24
```

The generated forecast tables are regular CSV files on the host:

```text
outputs/examples/forecast-champion/predictions.csv
outputs/examples/forecast-naive-24/predictions.csv
```

`docker compose run --rm example-csv-tests` only validates the three input
files and prints PASS/FAIL; it intentionally does not generate a forecast.

## Coalitions

Install the coalition solver dependencies, then compare the sum of individual
`baseline` costs with one `cooperative_pool` solve:

```bash
python examples/run_coalition_csv.py \
  --members 1,3,8 --start 7008 --hours 24 \
  --output outputs/examples/coalition-1-3-8.json
```

Or use Docker:

```bash
docker compose run --rm example-coalition
```

The CSVs do not contain battery ownership/capacity, so this example explicitly
sets battery modules to zero for every member. Connection fees are prorated as
`hours / 24`. Change `--members`, `--start`, and `--hours` to test other subsets
and periods. A full year is possible with `--start 0 --hours 8760`, but is much
slower than the bounded default and still evaluates only the requested subset,
not every possible coalition.

These examples use realised production directly in the physical optimisation.
Forecast results and coalition costs are deliberately separate: substituting a
forecast into a perfect-foresight physical solve would define a new experiment
and requires an explicit operational-error policy.
