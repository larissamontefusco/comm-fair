# ComFair physical kernel — M3

> **Public-release scope:** This is inherited method documentation. Commands
> mentioning `backend/`, Docker, platform modules or historical test suites refer
> to the original environment, which is not included here. For executable public
> workflows and regeneration blockers, use [the module README](../../README.md)
> and [dependency audit](../../DEPENDENCIES.md).

`solve_physical(S, config) -> PhysicalResult` evaluates any subset of configured
member IDs (distinct Python integers in 1..9). The identical LP evaluates empty,
singleton, grand and intermediate coalitions. Empty coalitions cost zero without
importing or invoking Pyomo. This is a serial API; use separate processes for
concurrent jobs because HiGHS has a process-global thread scheduler. M3 releases
that scheduler around each solve so earlier/later sequential solver users can
select different thread counts.

```python
from comfair.data import load_benchmark
from comfair.physical import config_from_benchmark, solve_physical

config = config_from_benchmark(load_benchmark())
result = solve_physical({1, 3, 7}, config)
print(result.total_cost_aud)
json_text = result.to_json(include_runtime=False)
```

## Approved assumptions

The machine-readable source is `../config/assumptions.yaml`. The `workbook`
section contains source facts; `assumptions` contains explicit interpretations
approved by the user on 22 September 2026. M2 arrays, metadata and source-unit
ambiguities remain intact. Only the physical adapter adopts the interpretations.

| Quantity | Encoded baseline |
|---|---|
| Time/demand | dt=1 h; ordinal 0..8759; average demand kW; energy=power×dt |
| Calendar | 365 billing days; no official year/timezone/DST supplied; 2025 is not adopted |
| Tariffs | Raw import 0.15/0.25/0.55 and FIT 0.05 interpreted AUD/kWh, scale=1 |
| Connections | 1 AUD/day/member; every S retains all its connections; annual fixed cost=365×abs(S) AUD |
| PV | 0.440 kW/module, NMOT=44°C, gamma=-0.0033/°C, derating=1 |
| BESS energy | Modules×4.66 kWh |
| BESS power | Modules×44.8 V×30 A/1000 = modules×1.344 kW, charge and discharge |
| Efficiency | Conservative round trip=0.95; symmetric charge/discharge=sqrt(0.95) |
| SOC | 10–100% of nominal energy; initial=50%; final=initial |
| Degradation | 0 AUD/kWh; both AC-side charge/discharge throughputs reported |
| Exclusivity | LP without binaries; post-solve simultaneous-flow checks; no automatic MILP fallback |
| Numeric acceptance | 1e-6 kW flow/bounds, 1e-6 kWh balance/SOC, 1e-5 AUD objective/dominance |
| Solver | HiGHS simplex, one thread, seed 0; primal/dual tolerances 1e-8 |

PV availability is a module-output proxy, not a full AC plant model:

```text
Tcell = Tamb + (44 - 20) * GHI / 800
raw = n * .440 * GHI / 1000 * (1 - .0033 * (Tcell - 25))
available = clip(raw, 0, n * .440)
```

No rounding is applied. Device parameters are supplied by the approved user
instruction; the code does not imply independent manufacturer certification.
No additional network constraints, inverter losses or degradation sensitivities
are assumed. Synthetic cases may pass explicit power arrays, module counts,
prices and billing_days to `PhysicalConfig`; arrays are validated on every solve.

## Formulation and boundaries

For every period and active member, the internal Pyomo LP has aggregate grid
import/export, bounded PV use, bounded battery charge/discharge and T+1 SOC
states. Zero assets have zero outputs and no artificial capacity/asset variables.

```text
Gimp + sum(PVuse + Bdis) = Gexp + sum(demand + Bch)
SOC[t+1] = SOC[t] + (sqrt(.95)*Bch - Bdis/sqrt(.95))*dt
min sum_t (pgrid*Gimp - pfit*Gexp)*dt + abs(S)*billing_days*daily_fee
```

The implicit pool preserves aggregate physical clearing. It is unconstrained by
network topology, which the workbook does not specify. No local buy/sell,
member grid allocation, prices, demographic weights, fairness, repair or
forecasting are introduced. Member settlement belongs to M4. PV `used` means
energy admitted to the pool, including exports; it is not PV self-consumption.
Optimising energy cost does not optimise peak demand.

`PhysicalResult`/`MemberDispatch` contain only serializable domain values:
coalition and costs in AUD, grid/aggregate/member power arrays in kW, member SOC
in kWh (T+1), physical KPIs, per-period simultaneous-flow diagnostics, residuals,
solver status/termination/runtime, input/registry hashes and assumptions.
`to_dict()` and `to_json()` use stable ordering and reject NaN/Infinity JSON.
Measured runtime is optional because it varies across runs. Reproducibility of
particular dispatch among alternate optima depends on the recorded solver version
and options. Tests compare full synthetic dispatch under fixed configuration.

Invalid configuration/subsets raise `ValueError`; missing solver/nonoptimal
termination raise `RuntimeError`. Independent post-solve audits reconstruct
balances, SOC dynamics/endpoints/bounds, asset bounds and simultaneous flows.
Material simultaneous flows raise `ValueError` with member/period/magnitude and
halt the official runner. No binaries are added automatically.

## Reproduce and validate

From repository root:

```bash
docker compose build backend
docker compose run --rm --no-deps backend pytest tests/ -q --tb=short
docker compose run --rm --no-deps backend pytest tests/test_solver_availability.py tests/test_physical.py -q
mkdir -p backend/comfair/artifacts
docker compose run --rm --no-deps --user "$(id -u):$(id -g)" \
  -v "$PWD/backend/comfair/artifacts:/results" backend \
  python -m comfair.physical.run_baselines --output /results/m3_baselines.json
```

The rebuilt image provides source code and immutable workbook; only the results
directory is mounted for writing. `m3_baselines.json` contains all nine B0 costs,
B1, surplus, per-solve KPIs/audits and shared provenance. The runner constructs a
feasible grand-pool schedule by retaining singleton asset dispatch and netting
aggregate grid flows; it checks `B1 <= feasible aggregation <= sum(B0)`.
Full dispatch is returned by the API; the annual artifact keeps compact summaries.

`m3_baselines.runtime.json` records variable timings and the corresponding main
artifact SHA-256. This separation makes main artifact bytes reproducible while
retaining measured runtime evidence. The main artifact includes its schema/version;
source, input and registry fingerprints identify the exact configuration. The
runner checks workbook hashes before/after and writes artifacts only after all
solves/audits pass.
