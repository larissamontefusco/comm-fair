# ComFair M6 — Market-Anchored Coalition Repair

> **Public-release scope:** This is inherited method documentation. Commands
> mentioning `backend/`, Docker, platform modules or historical test suites refer
> to the original environment, which is not included here. For executable public
> workflows and regeneration blockers, use [the module README](../../README.md)
> and [dependency audit](../../DEPENDENCIES.md).

M6 measures the financial intervention needed to protect individuals and then
achieve the best possible coalition resilience. The unchanged M4 market settlement
is the only anchor. The exact M5 game is read from its frozen 512-record artifact;
M6 does not re-optimize dispatch, change prices, or use the M5 witness as an anchor.

## Financial contract

For each member, `B_i` is the M3 standalone bill, `C_market_i` the M4 bill and
`u0_i = B_i - C_market_i` the market benefit. A positive transfer `tau_i` means the
member pays into repair; a negative transfer means the member receives money:

```text
C_final_i = C_market_i + tau_i
u_i       = u0_i - tau_i
sum tau_i = 0
u_i >= 0
R(tau)    = 0.5 * sum |tau_i|
```

The factor one half counts transferred money once. LP auxiliaries satisfy
`z_i >= tau_i`, `z_i >= -tau_i`, `z_i >= 0`, with `R = 0.5 sum z_i`.
Every returned witness is independently checked against its actual transfers:
absolute values, zero-sum balance, bills, benefits, total cost, efficiency and
hard no-harm. Raw numeric results are retained without clipping or rounding.

## Diagnostic LPs

- **r_IR** minimizes R subject only to the financial contract. Under revenue
  adequacy and nonnegative total surplus, its independently checked identity is
  `sum max(0, -u0_i)`. Both the LP and formula are executed.
- **epsilon(r)** minimizes `epsilon >= 0` under the financial contract, `R <= r`
  and `sum(u_i for i in S) >= v(S) - epsilon` for all proper multi-member S.
- **epsilon_IR** is epsilon(r_IR), optimized independently of the particular
  minimum-IR witness. Both witnesses are stored; minimum-IR donor choice can be
  nonunique and matter for coalition deficits.
- **epsilon*** is loaded from M5 and independently checked by its tested least-core
  LP on the same fixed game. This small LP never calls physical optimisation.
- **r_CR** directly minimizes R with coalition target epsilon* + stability tolerance.
  It is not inferred from curve samples. A further epsilon(r_CR) solve checks the target.
- **CRP = r_CR - r_IR** measures additional repair needed for coalition resilience.
- **RSG = epsilon_IR - epsilon*** measures remaining instability after minimum IR.

For epsilon(r), the primary optimum is fixed exactly for a second LP minimizing R.
This ensures tight z=|tau| even on flat epsilon segments and returns the least
volume actually needed at that epsilon. It does not relax epsilon, spend the whole
budget unnecessarily, or select a fairness policy. Solver metadata records both
passes. Alternate optimal member allocations may still exist.

The returned coalition witness's `epsilon_aud` is its imposed target; the separate
`epsilon_at_r_CR_witness` contains the achieved optimal epsilon. Coalition deficits
in diagnostics are signed raw values; epsilon has a zero floor. Raw market deficits
are meaningful even when an epsilon(0) solve would be infeasible due to individual harm.

## Tolerances and curve

The official money/core tolerance remains M3/M5's **1e-5 AUD**. Repair equality,
no-harm, target relaxation and epsilon monotonicity all reuse it. HiGHS simplex
uses the existing one-thread, seed-zero configuration and feasibility tolerances
1e-8, recording installed versions. No concurrent threaded solver calls are supported.

The target is explicitly `epsilon_star_M5 + 1e-5 AUD`. A tolerated stability target
can shift r_CR relative to the symbolic exact target; the shift depends on the
curve slope. For synthetic test C, r_CR is `1 - 2*stability_tolerance`; for test D,
it is `2/3 - stability_tolerance`. Tests verify both these default conventions and
exact targets (`stability_tolerance=0`) producing 1 and 2/3 respectively. There is
no hidden normalization of r_CR, CRP or RSG. Numerical witness checks separately
allow the central monetary tolerance for solver residuals.

`generate_curve` samples 21 budgets by default between the directly solved
endpoints. Both endpoints are included. Equal endpoints give one point and
`degenerate_curve=true`. Near-equal but distinct raw endpoints are both retained
and marked degenerate. Arbitrary budgets remain available via epsilon(r).

Monotonicity compares epsilon differences to the money tolerance. Convexity
compares consecutive slopes; its tolerance is propagated from monetary errors:
`2*tol/gap_left + 2*tol/gap_right`. One-point shape checks are explicitly trivial.
Changes exceeding that uncertainty are recorded as sampled approximate breakpoints,
not exact parametric-LP breakpoints. Sampling is a diagnostic, not a symbolic proof.

## Public API

```python
from comfair.repair import (
    RepairProblem, solve_individual_repair, solve_epsilon_at_budget,
    solve_coalition_repair, generate_curve,
)

# Mapping keys: members 1..n, masks 0..2**n-1; n<=9. All money is AUD.
problem = RepairProblem(standalone, market_bills, u0, coalition_values, tolerance)
individual = solve_individual_repair(problem)
at_budget = solve_epsilon_at_budget(problem, repair_budget_r=1.0)
coalition = solve_coalition_repair(problem, individual, epsilon_star_m5)
curve = generate_curve(problem, individual, coalition)
```

Typed results expose `.to_dict()` and deterministic `.to_json()`. Witnesses include
transfers, benefits, bills, absolute transfers, actual repair volume, solver metadata
and reconstructed diagnostics. Input validation rejects inconsistent member IDs,
missing masks, nonfinite amounts, bill/benefit mismatch and inefficient anchors.
`RepairInfeasibleError` reports an infeasible hard-no-harm/budget/target LP; it never
returns a fake repair value. Other invalid inputs raise ValueError; nonoptimal
solver termination raises RuntimeError.

## Reproduce official M6

From the repository root:

```bash
docker compose build backend
docker compose run --rm --no-deps backend pytest tests/ -q --tb=short
mkdir -p /tmp/comfair-m6-run
docker compose run --rm --no-deps --user "$(id -u):$(id -g)" \
  -v /tmp/comfair-m6-run:/results backend \
  python -m comfair.repair.run_repair --output-dir /results
python3 backend/comfair/repair/audit.py \
  --artifact-dir /tmp/comfair-m6-run --upstream-dir backend/comfair/artifacts
```

Use a fresh output directory for each run. Canonical files are `m6_repair.json`
and `m6_repair_curve.json`; `m6.runtime.json` contains only runtime evidence and
canonical hashes. The repair artifact provides the member chain from standalone
to market, individual repair and coalition repair. The curve includes compact
financial witnesses; no hourly dispatch arrays are duplicated.

Upstream artifact hashes are pinned. Workbook, registry, physical/market/game
sources, installed solver settings and M5 provenance are checked before reuse.
The repair source hash and starting checkpoint `f0dcd8f` are recorded. Forecasting
is hashed only for preservation; it is not a computational input. All validations
finish before canonical writes; failures create `m6_failure.json` with BLOCKED
status. Writes are atomic per file, not an atomic multi-file transaction. After
interruption, regenerate in a fresh directory. Do not run competing writers in
the same output directory. Fixed inputs/source/solver settings must reproduce
canonical bytes; runtime is intentionally separate.

`audit.py` is a standalone stdlib-only reconstruction of final artifacts. It does
not import ComFair/Pyomo or trust aggregate summaries. Feasibility checks are not
by themselves an optimality proof: solver termination, the independent IR identity,
the M5 epsilon reference and analytical synthetic games provide that evidence.

## Interpretation and boundary

Zero repair is valid: if the approved annual perfect-foresight market already
protects individuals and reaches the best coalition resilience, no financial
intervention is necessary. The general LPs still run and derive that outcome.
Positive-IR, positive-CRP and empty-core synthetic tests establish generality.

Repair necessity is separate from later fairness/governance. M6 does not claim its
possibly nonunique witness is a final fair allocation and does not implement M7,
Shapley, nucleolus, forecasting adapters or frontend/API functionality.
