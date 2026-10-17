# Benchmark ingestion (M2)

> **Public-release scope:** This is inherited method documentation. Commands
> mentioning `backend/`, Docker, platform modules or historical test suites refer
> to the original environment, which is not included here. For executable public
> workflows and regeneration blockers, use [the module README](../../README.md)
> and [dependency audit](../../DEPENDENCIES.md).

`from comfair.data import load_benchmark; data = load_benchmark()` loads the
workbook relative to the installed backend package, independently of working
directory, at `backend/reader/ComErgy Benchmark Dataset 2026.xlsx`.
An explicit path is also accepted. Missing files raise
`FileNotFoundError`; invalid sheets, layout, values or metadata raise `ValueError`.
The workbook is opened without writes and closed on success or failure. Formula
cells in hourly input are rejected rather than relying on possibly stale caches.

`BenchmarkData`, `MemberData` and `DGSInstallation` are dataclasses containing
NumPy arrays and ordinary Python values, with no Pyomo dependency. Demand shape
is `(8760, 9)` and other hourly arrays have shape `(8760,)`. Column `i-1` maps to
member `i`. Tariff fields end in `_raw`: no cents/dollar conversion occurs.
`validate=False` skips domain validation only, not structural/parsing checks;
production callers should retain the default `True`. These objects are mutable;
call `validate()` after any edits. `summary()` also validates before reporting.

Period `t=0` maps to worksheet row 3; `t=8759` maps to row 8762. The hourly,
Jan–Dec label and member column order are checked. Extra populated hourly rows
are rejected, while trailing formatting is allowed. No timestamps are supplied,
so year, timezone, DST and undetectable reorderings of numeric rows cannot be
verified. No calendar timestamps are invented.

The data includes AUD currency metadata and a daily grid connection fee, while
J1/K1 say `c/kWh`. Ingestion preserves that source ambiguity and raw tariffs.
M3 explicitly adopts scale=1 AUD/kWh under the user-approved assumptions in
`../config/assumptions.yaml`; this interpretation is applied only by the
[physical adapter](../physical/README.md). Demand is labelled `kW or kWh`;
M2 summary sums and peaks retain raw units. P19/P20 module ratings are retained
verbatim as source notes; ingestion never converts counts to capacities.
PV/BESS conversions, operating parameters and connection-count accounting belong
to the physical model and do not change the workbook facts or M2 summary.

Generate a deterministic JSON artifact from the repository root with the existing
backend Docker image and the current working tree mounted read-only:

```bash
docker compose run --rm --no-deps -v "$PWD/backend:/app:ro" backend python3 -c 'import json; from comfair.data.summary import generate_summary; print(json.dumps(generate_summary(), indent=2, allow_nan=False))' > backend/comfair/data/benchmark_summary.json
```

With backend dependencies installed locally, an alternative is:

```bash
PYTHONPATH=backend python3 -m comfair.data.summary --output backend/comfair/data/benchmark_summary.json
```

The artifact excludes runtime paths/load timestamps and includes the workbook
filename and SHA-256. `load_timestamp` is available on the dataclass as UTC
runtime metadata. All numeric summary statistics are computed from source data;
no economic optimisation or annual cost calculation is performed.

Run all backend tests, including M2 ingestion and M1 regressions/HiGHS smoke:

```bash
docker compose run --rm --no-deps -v "$PWD/backend:/app:ro" backend python3 -m pytest -p no:cacheprovider tests/ -q
```
