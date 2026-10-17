# Coalition Analysis — annual research evidence

## Overview and scientific objectives

This module studies the economic value of coordinated household PV and battery
operation, incentives to remain in a community, and the distribution of its
cooperative surplus. It publishes a fixed annual benchmark, scientific source
methods and an independent artifact-verification workflow.

**Verified:** Level 1 artifact-based reproduction. **Partial:** Level 2
experimental regeneration. The imported method tree combines historical physical
and market code with later game/repair/governance code. It is not a complete
standalone rerun of the historical experiment; see [dependencies](DEPENDENCIES.md).
No database, website, authentication service or platform deployment is required
for the supported verification path.

## Research methodology

### Physical operation and coalition value

The annual linear programme minimizes grid import cost less export revenue,
plus retained fixed connection fees. It enforces hourly energy balance, PV
availability, battery power/energy bounds and cyclic state of charge. It assumes
an unconstrained physical community pool; network constraints are not supplied.

For household i, B_i is its optimized standalone cost. For coalition S, C*_S is
its optimized coordinated physical cost using only its members' assets:

```text
v(S) = sum(i in S) B_i - C*_S
v(empty) = 0; v({i}) = 0
```

All 2^9 = 512 subsets are represented by masks 0–511 (bit i−1 denotes member i).
The historical enumeration reused nine singletons and the grand coalition,
solved 501 intermediate coalitions, and represented the empty set analytically.
This is not 512 new solver calls.

For each nontrivial complementary bipartition A and N\A, fragmentation costs
`C*_A + C*_(N\A) - C*_N`. Fixing member 1 in A removes symmetry, leaving 255
partitions: 9 of size 1+8, 36 of 2+7, 84 of 3+6 and 126 of 4+5. Their penalties
are nonnegative in this benchmark. This does not establish a universal empirical
claim about arbitrary communities or every pair of disjoint subcoalitions.

### Settlement, stability and allocation

The market layer decomposes physical dispatch into proportional local exchanges
and grid positions, using LP marginal prices clipped between FIT and grid tariff.
Member market bills sum to physical cost; benefits equal standalone minus bill.
These are separate quantities from an allocation chosen for fairness.

Core feasibility requires efficiency `sum(u_i)=v(N)` and `sum(i in S)u_i>=v(S)`
for all coalitions. This implementation's hard-no-harm least-core programme
minimizes **epsilon >= 0**, with `u_i>=0`; it is a minimum nonnegative violation
certificate, not an unrestricted signed least-core definition. The published
witness has epsilon=0 and eight proper coalition constraints binding within
1e-5 AUD. Binding at this witness does not mean those coalitions block the market
allocation, or that the witness is unique. The market's tightest proper-coalition
slack is approximately AUD 7.98.

Financial repair uses `C_final=C_market+tau`, `u=u0-tau`, `sum(tau)=0` and
transfer volume `0.5*sum(abs(tau))`. Required no-harm/coalition repair is separated
from optional governance redistribution. Raw policies requiring repair are not
presented as admissible final settlements. Negative benefits/bills and unavailable
metrics retain their scientific meanings.

Thirteen policies cover protected marginal, midpoint, FIT-floor and grid-ceiling
pricing; the market alias; equal benefit; leave-one-out contribution proportional;
Shapley; nucleolus; fair least-core max-min; closest core to market; max-min benefit;
and minimum necessary repair. See the preserved
[policy definitions and tolerances](comfair/governance/README.md).
Income-based burden indicators are descriptive, not demographic objective weights.
Member 5 is a benchmark distributional case, not a claim about an identified person.

## Research structure and provenance

| Path | Role |
| --- | --- |
| `comfair/config/`, `comfair/data/` | Assumption registry, workbook ingestion, typed data and historical summary |
| `comfair/physical/` | Annual physical LP, PV proxy, dispatch and independent residual checks |
| `comfair/market/` | Local matching, protected LP prices and budget-balanced settlement |
| `comfair/game/` | Coalition masks, enumeration, stability and later operational/cache adapters |
| `comfair/repair/` | Individual protection, coalition repair and repair-budget diagnostics |
| `comfair/governance/` | Allocation rules, metrics, policy comparison and independent audits |
| `comfair/presentation/` | Standard-library snapshot reconstruction and pinned artifact validation |
| `comfair/artifacts/` | Five canonical annual inputs: never overwrite |
| `results/` | Derived, byte-deterministic research snapshot |
| `scripts/`, `tests/` | Public verification, figures, bounded synthetic smoke and tests |
| `figures/` | Preserved published PDF/PNG; generate new copies under `outputs/` |

Physical and market source were imported from `f30cd22`; other `comfair/` files
from `e992c1e`. [SOURCE_PROVENANCE.json](SOURCE_PROVENANCE.json) records exact
commits, original paths and per-file import hashes. Editorial changes to two
docstrings and six inherited READMEs are listed in the release report; Python
AST equivalence was checked after excluding docstrings. Physical and market
Python files and the assumption registry still match the canonical source hashes.
Later game source does **not** match the historical game oracle.

## Reproduce Level 1

Run these commands **from the repository root**, not from `forecast/`.
Python 3.13.5 was tested. Verification uses the standard library only; no solver
packages are installed by the figure requirements.

```bash
python3 -m venv .venv-coalitions
. .venv-coalitions/bin/activate
python coalitions/scripts/verify_release.py
python -m unittest discover -s coalitions/tests -v
PYTHONPATH=coalitions python -m comfair.presentation.insights --output coalitions/results/coalition_insights_snapshot.json --check
python -m pip install -r coalitions/requirements.txt
python coalitions/scripts/generate_coalition_fragmentation_figure.py --output-dir outputs/coalitions/figures
```

Expected: **15 tests pass** (10 inherited scientific checks plus 5 release-boundary
tests); five SHA-256 matches; 512 cost identities; feasible core witness across
all subsets; balanced raw/repaired policy bills and benefits; 255 bipartitions.
The verifier requires the published snapshot to exist and match exactly.

To generate an independent snapshot copy without touching the published input:

```bash
PYTHONPATH=coalitions python -m comfair.presentation.insights --output outputs/coalitions/coalition_insights_snapshot.json
```

Always specify `--output`: the inherited generator's default still targets a
platform frontend path. The public verification script supplies its own explicit
read-only snapshot path. Source defaults were preserved for provenance.

The figure generator verifies its input hash and prints:

```text
Bipartitions plotted: 255
Min/Max penalty: 68.721493 2170.041713
```

The same seed fixes point jitter. PDF metadata (creation time), fonts and rendering
versions can alter image bytes; numerical reproduction is mandatory, cross-platform
PDF byte equality is not claimed. Existing published figures are preserved.

## Scientific evidence and expected values

| Evidence | Interpretation |
| --- | --- |
| `m3_baselines.json` | Nine standalone costs, grand physical optimum, KPIs and solver diagnostics |
| `m5_coalitions.json` | All 512 annual coalition costs/values and provenance |
| `m5_core.json` | Core/least-core witness, market allocation and stability diagnostics |
| `m7_governance.json` | Candidate governance policies, comparison frontiers and case studies |
| `m7_policy_comparison.json` | Raw/repaired allocations, households, metrics and method provenance |

| Quantity | Verified annual value |
| --- | ---: |
| Standalone cost sum | 9,754.639083892132 AUD |
| Grand-coalition cost | 5,509.653992063874 AUD |
| Cooperative surplus | 4,244.985091828258 AUD |
| Cost reduction | 43.52% (rounded) |
| Least-core violation epsilon | 0 AUD |
| Binding witness constraints | 8 |
| Fragmentation penalty range | 68.721493–2,170.041713 AUD (six decimals) |

These artifacts support the report topics of cooperative value, fragmentation,
stability and distributional equity. The Final Technical Report is not included
in this repository; no unverified report section numbers are asserted here.
Historical narrative/test literals use slightly different low-precision estimates
of fragmentation penalties. The table and figure output above use exact artifact
arithmetic; source values and snapshot text have not been rewritten.

SHA-256 pins (also enforced by `comfair/presentation/insights.py`):

| Artifact | SHA-256 |
| --- | --- |
| `m3_baselines.json` | `767c7c1538768d8db7840194597401bc133fd8ae5c23da3d497754d7cd8997aa` |
| `m5_coalitions.json` | `cca30380f74cb0579e3024b401095779ae88bee7dee39f41554944810156bbb8` |
| `m5_core.json` | `985f155b46c170dc1069790cd5bdd7dfc6b6678f4214089063692cb72193a5ee` |
| `m7_governance.json` | `dafc21444a21ab395da69b5a9f7f65b66d3933a0dee235e64d40cc88e769b7e2` |
| `m7_policy_comparison.json` | `b636aae9bda8d6c51f3bc1e0c8defaaac8d19d90cc63d0c42d9489b37c50e6a0` |

The workbook reference hash is
`c559bd7dc946b2f0c01c8cc96beea75c783f3b48bdd7fe6da855b2ef01f75370`.
The workbook is absent: checking artifact provenance does not re-hash or verify
an unavailable input workbook. Hash matching establishes byte identity, not data
redistribution rights or independent proof of every historical optimization.

## Experimental scope and limitations

- Fixed nine-household, 8,760-hour perfect-foresight scenario, hourly ordinal
  periods. No official year/timezone/DST is inferred from synthetic date labels.
- Raw tariffs are preserved by ingestion; the explicit modelling interpretation
  uses scale 1 AUD/kWh (import 0.15/0.25/0.55; FIT 0.05), despite ambiguous workbook
  unit labels. No silent cents conversion. Each member retains a 1 AUD/day
  connection fee for 365 days.
- PV: 0.440 kW/module, NMOT 44°C, gamma −0.0033/°C, derating 1; unrounded clipped
  GHI/temperature proxy, not a full AC plant model.
- BESS: 4.66 kWh/module, 1.344 kW/module, round-trip efficiency 0.95, SOC 10–100%,
  initial/final SOC 50%; zero degradation cost. These are explicit assumptions,
  not inferred from module counts or manufacturer certification.
- LP without exclusivity binaries; material simultaneous flows fail post-solve
  checks. No network topology, EVs, flexibility bids or carbon objective.
- This is distinct from the forecast-driven daily operational workflows of the
  original interactive platform, which are not included in this release.
- Market benefits, least-core witnesses and governance benefits are distinct.
  Nonempty core and zero required repair do not imply a universally fairest policy.

## Level 2: limited executable source

The physical/market APIs can run on supplied synthetic arrays. This bounded
example performs four tiny LP passes (two singletons, one grand coalition,
one pricing pass), writes no research artifacts and needs no workbook:

```bash
# From repository root, in the coalition environment.
python -m pip install -r coalitions/requirements-solver.txt
python coalitions/scripts/smoke_physical.py
```

Expected: HiGHS 1.15.1, optimal physical dispatch and validated settlement;
synthetic surplus approximately 0.2 AUD. **This is an integration check, not an
annual result.** Pyomo 6.10.1 and HiGHS 1.15.1 match historical solver provenance.
The historical environment also recorded Python 3.11.16; this check used 3.13.5.

Full annual regeneration is not validated. The workbook, market/repair/forecasting
intermediates and original source/test fingerprints are absent. Later game and
repair interfaces are incompatible as imported. Do not run the inherited annual
runners expecting the five canonical files; use [DEPENDENCIES.md](DEPENDENCIES.md)
to assess the missing historical environment before any future regeneration.

## References and attribution

- L. S. Shapley, [A Value for N-Person Games](https://www.rand.org/pubs/papers/P295.html),
  RAND P-295. Background for factorial-weighted marginal-contribution allocation.
- M. Benedek, J. Fliege and T.-D. Nguyen,
  [Finding and verifying the nucleolus of cooperative games](https://link.springer.com/article/10.1007/s10107-020-01527-9),
  Mathematical Programming 190, 135–170 (2021). Background on nucleolus computation
  and verification; the project does not claim a new nucleolus algorithm.
- [HiGHS](https://highs.dev/), used through Pyomo for linear optimization.
  NumPy, openpyxl and PyYAML support typed inputs; Matplotlib produces figures.
- Benchmark attribution is retained from the ComErgy 2026 evidence. Snapshot
  metadata attributes demand profiles to Ausgrid and demographic fields to
  benchmark scenarios. This release has not independently established the exact
  upstream data selection or permission to redistribute derived household data.

## Licence and usage

See [LICENSE](../LICENSE) and [NOTICE](../NOTICE). Original code/documentation are
Apache-2.0 subject to contributor rights; third-party software, datasets and
institutional branding retain their own rights. Source-code licensing does not
license the benchmark or its derived records. Confirm those permissions before
public release; do not delete or alter canonical evidence to conceal uncertainty.
