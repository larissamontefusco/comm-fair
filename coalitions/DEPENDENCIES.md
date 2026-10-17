# Dependency and historical compatibility audit

Audit date: 17 October 2026. Source baseline is recorded file by file in
[SOURCE_PROVENANCE.json](SOURCE_PROVENANCE.json). No algorithms, solver options,
function signatures, numerical artifacts or scientific assumptions were changed.

## Supported execution boundaries

| Workflow | Packages / inputs | Actual status |
| --- | --- | --- |
| Hashes, snapshot, 15 tests, identities/core witness | Python standard library, five published JSON files | PASS |
| Fragmentation PDF/PNG | Matplotlib 3.11.2, NumPy 2.4.6, canonical game JSON | PASS, all 255 partitions |
| Tiny physical + market example | NumPy, PyYAML, openpyxl, Pyomo 6.10.1, HiGHS 1.15.1 | PASS, synthetic two-hour inputs only |
| Full annual physical baseline | Same packages, exact workbook, historical environment | Not executed; workbook absent |
| Full annual market | Physical dispatch, workbook, matching baseline fingerprints | Not executed; workbook absent |
| Coalition benchmark API | Python standard library, published M3/M5 artifacts | PASS, precomputed baseline/cooperative-pool responses |
| Full repair/governance runners | Historical game API, market/repair intermediates and protected source manifest | BLOCKED: incompatible interface and missing inputs |
| Historical repair/governance independent audits | Additional JSON/CSV, workbook, all protected source files | BLOCKED: incomplete input bundle |

The lightweight `requirements.txt` is intentionally only for figures. The optional
`requirements-solver.txt` supports the bounded synthetic example, not the missing
platform. Installing more packages cannot fix absent project modules.

## Import and semantic compatibility findings

1. `comfair.game` is self-contained for the website's precomputed baseline and cooperative-pool
   benchmark responses. Live calculation is possible only when a caller
   explicitly injects an evaluator implementation.
2. `repair/provenance.py` imports `protected_hashes` from `game/run_game.py`,
   which no longer defines that name. It also reconstructs every current
   `CoalitionRecord` field from historical rows; the later record includes fields
   such as `community_model` and `member_costs` absent from those annual rows.
   These are additional static compatibility defects beyond the first import
   failure. They were not masked with stubs or relaxed provenance checks.
3. The historical physical and market Python aggregate source hashes **match**
   the annual evidence, as does the assumption registry. Their synthetic API
   integration works. Later game/repair/governance provenance nevertheless binds
   historical source trees, tests and files not supplied in this public package.
   Editorial docstring changes also change source bytes; an AST-equivalence
   check is not a substitute for frozen source fingerprints.
4. The inherited snapshot generator defaults to a frontend path outside its
   public module. All documented commands explicitly specify a destination;
   `scripts/verify_release.py` reads the public snapshot path directly. This
   avoids changing original API defaults or generated scientific content.
5. `forecast/` and `coalitions/` each own a separate `comfair` namespace and
   remain independent modules in this checkout.

## Missing data and intermediate evidence

The workbook is expected at `coalitions/reader/ComErgy Benchmark Dataset 2026.xlsx`
by the ingestion default, or via the physical runner's explicit `--workbook`.
It is not distributed. The published workbook hash is a reference only.

`game/provenance.py` pins missing `m4_market.json` and six forecasting files:
`forecasting/f0_data_audit.json`, `f0_baselines.json`, `f0_predictions.csv`,
`f1_champions.json`, `f1_leaderboard.json`, `f1_test_results.json` (all under the
`forecasting/` artifact subdirectory). Forecasting is a historical preservation
dependency there, not an input to the annual physical mathematical model.

Repair additionally expects `m5.runtime.json`, historical physical/market/game
tests and the full protected-file map. Governance additionally expects
`m6_repair.json`, `m6_repair_curve.json`, `m6.runtime.json` and historical repair
tests. Its full auditor also reads `m7_price_comparison.json`, `m7_ablation.json`,
CSV member outcomes, the workbook and protected source hashes. The five published
artifacts suffice for the supported verifier, not these full historical audits.

The derived `data/benchmark_summary.json` contains aggregate demand, tariffs,
asset counts and scenario household metadata. It cannot reconstruct the missing
8,760-hour input arrays. Canonical artifacts contain references/hashes to other
files; these are provenance, not a promise those files are distributed.

## Future full-regeneration prerequisites

Before claiming Level 2, obtain authorized exact inputs and intermediate artifacts,
recover the coherent historical annual source/test versions, and recreate the
recorded solver environment. Run into a fresh output
directory and compare numerical identities and required fingerprints. Do not
weaken hash checks, substitute the operational daily oracle or overwrite the
canonical artifacts. Restoring/changing the scientific execution chain requires
separate review; it is outside this editorial and verification release.

## Forecasting review boundary

No forecasting files were modified. The existing module documentation is
`forecast/docs/FORECASTING_ORIGINAL.md` and `forecast/docs/DATA_SETUP.md`; no
module README exists. The root README now uses the actual `forecast/` working
directory and links. The historical publication guide still describes an older
standalone ZIP layout and historical test success, not this checkout's validation.
Three required input files are absent. Forecasting's full dependency installation,
dataset tests, inference and exhaustive F0/F1 benchmarks were not repeated here.
This remains an explicit follow-up for its separate scientific review.
