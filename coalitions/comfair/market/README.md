# ComFair M4 — market anchor and baseline settlement

> **Public-release scope:** This is inherited method documentation. Commands
> mentioning `backend/`, Docker, platform modules or historical test suites refer
> to the original environment, which is not included here. For executable public
> workflows and regeneration blockers, use [the module README](../../README.md)
> and [dependency audit](../../DEPENDENCIES.md).

M4 decomposes an existing optimal M3 dispatch. It neither modifies that dispatch
nor adds repair, fairness or coalition-game constraints. The approved M3 code,
registry and baseline artifacts remain unchanged.

## Public interface

```python
from comfair.data import load_benchmark
from comfair.physical import config_from_benchmark, solve_physical
from comfair.market import match_local, price_physical, settle_market

config = config_from_benchmark(load_benchmark())
physical = solve_physical(config.member_ids, config)
# B_i must come from canonical singleton solves or a provenance-validated artifact.
B = {i: solve_physical({i}, config).total_cost_aud for i in config.member_ids}
market = settle_market(physical, config, B)
encoded = market.to_json(include_runtime=False)
```

`match_local(physical, config)` returns `MatchingResult` with member power positions
and clearing/grid reconstruction diagnostics. `price_physical(physical, config)`
returns `PricingResult` with raw duals, normalized/protected prices, clipping
metadata, objective comparison, solver information and a fingerprint of the
original dispatch. `settle_market` calls these functions and returns `MarketResult`;
a precomputed `pricing=` result is accepted only for the same physical fingerprint.
It checks objectives, normalization, protection and solver status before billing.

Inputs and physical bounds/dynamics/cyclic SOC are revalidated with the M3 audit.
Malformed, incompatible or nonfinite inputs and violated invariants raise
`ValueError`. Nonoptimal pricing raises `RuntimeError`. Material grid reconstruction
or revenue residuals stop execution with diagnostics; no balancing adjustment is
introduced. Zero-member settlement is undefined; M3 still handles the empty
physical coalition. APIs are serial; concurrent HiGHS jobs require separate
processes, as in M3.

## Matching and grid allocation

All hourly flows are average power in kW, converted to kWh by the M3 `dt_hours`.
For each member/period:

```text
r_i = demand_i + battery_charge_i - pv_used_i - battery_discharge_i
deficit_i = max(r_i, 0); surplus_i = max(-r_i, 0)
D = sum(deficit_i); S = sum(surplus_i); L = min(D, S)
local_buy_i  = L * deficit_i / D  if D > 0, else 0
local_sell_i = L * surplus_i / S  if S > 0, else 0
q_i = local_buy_i - local_sell_i
grid_import_i = deficit_i - local_buy_i
grid_export_i = surplus_i - local_sell_i
```

Positive `q` denotes a local buyer. Verify buys=sells=L, sum(q)=0, individual
balances and reconstruction of both M3 grid-flow series in every period. Raw
floating-point residuals are reported, without member balancing adjustments.

Classification/source: user-approved M4 baseline, 23 September 2026. Rationale:
the benchmark supplies no bilateral bids, trading priority or internal network
constraints. Proportional matching is a transparent decomposition, not a novelty
claim or an allocation of battery ownership/benefits.

## Marginal and protected price

The pricing pass imports the **unchanged** `comfair.physical.model.build_model`,
adds a Pyomo IMPORT dual suffix and resolves with the same HiGHS LP options.
It verifies the physical objective within the M3 monetary tolerance. Its primal
solution is not used for settlement; the original M3 member dispatch is retained.

For the M3 balance orientation (supply minus exports/charging equals demand),
the raw Pyomo/HiGHS dual represents `+d optimal_cost / d period_demand_kw`.
Thus the explicit sign multiplier is **+1**, and:

```text
lambda[t] = raw_dual[t] / dt_hours       [AUD/kWh]
p_bar[t] = min(p_grid[t], max(p_fit[t], lambda[t]))
```

No absolute-value normalization. Import-only and export-margin tests, including
finite differences, verify the sign; a half-hour synthetic test verifies units.
A battery case verifies an interior opportunity value `FIT / eta_rt`. Duals can
be nonunique at kinks/degeneracy: the deterministic solver configuration selects
a valid marginal price, without a normative interpretation.

Hourly output distinguishes actual clipping (`lambda < FIT` or `lambda > grid`)
from already being at a tariff boundary. `clipping_direction` is `none`, `to_fit`
or `to_grid`. No rounding precedes protection. Actual clipping counts include
machine-level differences; `materially_clipped` reports differences >1e-8 AUD/kWh.
The `at_fit`, `at_grid`, `interior` classification uses absolute tolerance 1e-8
AUD/kWh and partitions all periods. These bound counts are distinct from clipping
counts. This tolerance is an M4 engineering diagnostic choice, not a tariff
change; it is recorded in result provenance. Flow (1e-6 kW) and money (1e-5 AUD)
tolerances are inherited from the unchanged M3 registry.

## Bills, benefits and KPIs

```text
C_market_i = fixed_fee_i
  + dt * sum(p_grid * grid_import_i - p_fit * grid_export_i
             + p_bar * local_buy_i - p_bar * local_sell_i)
u0_i = B_i - C_market_i
```

Official fixed fee is 365 AUD/member; short synthetic cases use their explicit
M3 billing duration. `MemberSettlement` reports each nonnegative charge/revenue
component separately, volumes, total bill, B_i, u0 and harm flag. Negative u0
is retained; harm is classified at u0 < -1e-5 AUD. No transfer exists. Worst/best
member is ordered by benefit, with lowest ID breaking ties.

Verify annual and hourly internal-payment cancellation, sum(bills)=C*_N and
sum(u0)=sum(B_i)-C*_N. Signed residuals are recorded as computed minus target.
No community-manager profit/loss is introduced. Revenue adequacy does not itself
establish fairness or coalition stability; M5 coalition deficits are unavailable.

`MarketResult` contains member summaries, full member hourly positions, aggregate
hourly plots data (duals/prices/tariffs/L/D/S/M3 grid flows), KPIs, diagnostics,
solver/pricing information and physical provenance. JSON uses stable key/member
ordering with NaN/Infinity rejected. Monetary figures are not rounded in artifacts.

Local energy traded counts the matched volume once (not buy+sell). Its demand
fraction is traded kWh / demand kWh; it includes storage-related residual trade
and is **not** a direct PV self-consumption ratio. A zero demand denominator is
reported as null. Trading periods use L > inherited flow tolerance. Price mean
and median are unweighted across all periods, including periods without trading.

## Official runner and validation

From repository root:

```bash
docker compose build backend
docker compose run --rm --no-deps backend pytest tests/ -q --tb=short
docker compose run --rm --no-deps backend pytest tests/test_physical.py tests/test_market.py -q

docker compose run --rm --no-deps --user "$(id -u):$(id -g)" \
  -v "$PWD/backend/comfair/artifacts:/results" backend \
  python -m comfair.market.run_market --output /results/m4_market.json
```

The runner loads the official workbook, obtains the grand-coalition dispatch via
`solve_physical`, and validates committed M3 baseline schema, singleton costs,
input/registry/workbook/physical-source fingerprints, solver version/options,
B1 objective/KPIs and surplus before reusing B_i. It then settles the original
physical dispatch and checks workbook/baseline bytes again before writing.

`m4_market.json` is canonical, including hourly data and M3 provenance/fingerprint.
`m4_market.runtime.json` stores measured times linked to the canonical artifact
SHA-256. The main artifact excludes timings to support byte-identical repetition.
Physical/market source fingerprints cover sorted Python module names and bytes,
as in M3. Repeat with another output directory and the same basename to compare
bytes; the runtime artifact filename is part of the main artifact.

The M3 registry's market-price placeholder records its historical M3 state. M4's
implemented policy is documented here and in M4 result provenance; changing the
M3 registry merely to update that placeholder would invalidate its frozen hash.
