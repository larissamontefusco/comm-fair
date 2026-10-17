# ComFair coalition game — bi-level evaluator

> **Public-release scope:** This is inherited method documentation. Commands
> mentioning `backend/`, Docker, platform modules or historical test suites refer
> to the original environment, which is not included here. For executable public
> workflows and regeneration blockers, use [the module README](../../README.md)
> and [dependency audit](../../DEPENDENCIES.md).

> This later operational runner is **not** the annual physical cost oracle that
> generated the five published canonical artifacts. Its required forecasting
> adapter and bi-level pipeline are not distributed in this module.

Coalition values are evaluated with the same legacy ComFair mechanism used by
the market run. The game package no longer calls the simplified M3 physical
dispatch as its cost oracle.

For coalition `S` the evaluator uses:

```text
one pre-issued 24 h forecast bundle
  -> select S by original owner_id
  -> C0(S) Household
  -> C0(S) EC/common site
  -> pricing_model_v1 for S
  -> C1(S)
  -> selected C2/C3/C4/C5(S)
  -> Household-2(S)
  -> final Operational Cost per member
```

`community_model=c0` is a baseline/debug mode and returns the C0 result
directly. C1 bidding costs are never used as realised coalition costs.

## Cooperative-game definition

Each outside option `B_i` is solved with Grid-only C0 for member `i` using the
same forecast and tariffs. The characteristic function remains:

```text
C(S) = sum of final Household-2 member costs in S
v(S) = sum(B_i for i in S) - C(S)
```

EC-manager revenue/cost is retained as separate diagnostics and is not added to
`C(S)`. Empty coalition cost/value are exactly zero and require no solver call.
Singleton records reuse their own C0 result, so their value is zero within the
declared monetary tolerance.

## Forecast, pricing and member IDs

`LegacyBilevelCoalitionEvaluator` receives or issues one canonical forecast for
the origin. Every request retains that same immutable bundle and exposes only
the selected owner columns to the pipeline. A coalition does not retrain or
reforecast.

Each non-singleton coalition runs its own C0 and therefore has its own
`pricing_model_v1.price_arrays()` provenance. Results are rejected unless the
pricing provenance names exactly the evaluated coalition and the final economic
stage is Household-2.

Masks use bit positions internally, but `member_universe`, `mask_to_members` and
`members_to_mask` preserve original IDs such as `(1, 3, 8)` in every output.

## Checkpoint identity and execution

The checkpoint context binds all result-changing inputs:

- original member set;
- selected community model;
- forecast origin and content hash;
- Grid-tariff file hash;
- pricing configuration;
- optimiser configuration and solver;
- standalone C0 costs and caller provenance.

Enumeration is intentionally serial (`jobs=1`) until nested legacy solver calls
are proven deterministic. Atomic per-mask checkpoint/resume remains available.

Example:

```bash
PYTHONPATH=backend:backend/src LEGACY_RESULTS_ROOT=/tmp/comfair-legacy-results \
  venv/bin/python -m comfair.game.run_game \
  --output-dir /tmp/comfair-m5 \
  --checkpoint /tmp/comfair-m5-checkpoint \
  --forecast-origin 7008 \
  --community-model c2 \
  --solver scip \
  --members 1,3,8 \
  --resume
```

The existing core/least-core routines still consume the unchanged `mask -> v(S)`
mapping. Governance/allocation policy code is outside this integration.
