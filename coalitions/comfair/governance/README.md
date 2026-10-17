# M7 — Fixed-game fairness and governance comparison

> **Public-release scope:** This is inherited method documentation. Commands
> mentioning `backend/`, Docker, platform modules or historical test suites refer
> to the original environment, which is not included here. For executable public
> workflows and regeneration blockers, use [the module README](../../README.md)
> and [dependency audit](../../DEPENDENCIES.md).

M7 reuses immutable M3 physical results, M4 settlement quantities, all 512 M5
coalition values and M6 financial repair primitives. It never dispatches assets or
re-solves a physical coalition. All money is AUD. Workbook facts, approved M3
capacity assumptions and descriptive household metadata keep their prior meanings.

Run from the backend directory, using a fresh output directory:

```sh
python -m comfair.governance.run_governance --output-dir /results
python comfair/governance/audit.py --artifact-dir /results --upstream-dir comfair/artifacts
pytest tests/test_governance.py -q
```

The runner validates pinned upstream hashes, builds policies, repairs alternative
anchors, writes deterministic JSON, generates CSV/PNG/SVG, then runs the independent
stdlib audit before reporting DONE. Failures produce `m7_failure.json` and raise;
partial files from a failed run are not accepted results. Use a fresh directory to
retry. Runtimes and output hashes live in `m7.runtime.json`; timestamps never enter
canonical JSON/CSV. Source fingerprints and library versions are provenance, so a
source/environment change intentionally changes canonical bytes.

## Necessary repair and optional governance

For every efficient raw benefit vector a, bills are B-a. M6 is reused with a as
its alternative market anchor, without modifying canonical M6 artifacts:

- u = a - tau; sum(tau)=0; u>=0.
- Repair volume R = half the sum of absolute tau (AUD).
- r_IR is minimum individual repair. epsilon_IR is minimum instability within
  that minimum-repair budget; its witness is distinct from the initial IR witness.
- r_CR is minimum repair reaching the existing M6 target epsilon* + 1e-5 AUD.
- CRP=r_CR-r_IR; RSG=epsilon_IR-epsilon*.

The artifact separately records optional `governance_transfer_from_M4_aud`,
necessary `necessary_candidate_repair_tau_aud`, and their combined transfer.
Market distance is **full** L1, twice the corresponding transfer volume, and must
not be confused with r_CR. A5 also records its optional transfer from canonical A4.
A baseline being harmful or unstable is a measured result, not a pipeline failure.

## Price and allocation policies

Prices change only local financial settlement. Grid charges, export revenue,
fixed fees, import/export and local buy/sell quantities are fixed to M4. Local
payments are price*(buy-sell)*dt and cancel across members each hour.

| ID | Definition / normative interpretation |
|---|---|
| P0_protected_marginal | Exact authoritative M4 protected marginal price and member outcomes |
| P1_midpoint | (grid tariff + FIT)/2; midpoint price comparator |
| P2_lower_fit | FIT; buyer-favouring price extreme |
| P3_upper_grid | Grid tariff; seller-favouring price extreme |
| G0_market | Alias of P0, included in the allocation comparison |
| G1_equal_benefit | v(N)/9; equal absolute cooperative benefits |
| G2_contribution_proportional | v(N)*m_i/sum(m), m_i=v(N)-v(N without i) |
| G3_shapley | Exact factorial-weighted marginal contribution across all predecessor subsets |
| G4_nucleolus | Imputation nucleolus; lexicographically minimum sorted proper coalition excesses |
| fair_least_core_maxmin | Project-defined: exact epsilon*, then maximum minimum absolute benefit, then minimum full L1 distance to equal benefits |
| closest_core_l1_to_market | Efficiency, hard no-harm, exact epsilon*, minimum full L1 distance to M4 |
| maxmin_benefit | Exact epsilon*, maximum minimum absolute benefit, then minimum full L1 distance to M4 |
| A4_minimum_repair | Exact canonical M6 coalition-repair witness |

Negative leave-one-out marginals are retained. A near-zero sum of marginals makes
proportional allocation unavailable; it is never normalized by absolute values.
These grand-coalition marginals are different from Shapley contributions. Fair
Least-Core is explicitly a ComFair project comparator, not a claim of equivalence
to a named published mechanism. Remaining LP ties use canonical member/mask order
and deterministic HiGHS simplex; uniqueness is claimed only for the certified
nucleolus, not the L1 governance comparators.

All-member relative max-min is `not_applicable_official_benchmark`: member 3 has a
negative standalone bill. No abs(B), demographic denominator or silent positive-
member-only optimization is substituted. Absolute max-min remains available.

## Exact nucleolus and numerical certificate

Shapley enumerates every predecessor subset, without permutation sampling. The
nucleolus works on the imputation set sum(u)=v(N), u_i>=v({i}), including singleton
excesses. Its excess LP variable is free and may be negative; flooring it at zero
would collapse the interior-core lexicographic distinction.

Each iteration minimizes the largest remaining excess. At that optimum, auxiliary
LPs maximize each candidate-tight coalition's payoff over the entire optimal face.
Only universally tight constraints and universally fixed imputation bounds enter
an independent equality basis. Incidence-vector rank uses exact rational Gaussian
elimination. All normals in the fixed span are removed from later objectives.
The resulting full-rank system is reconstructed and checked against every stage.
Fixing all constraints tight at a single solver vertex would be incorrect.

This follows established iterative LP/optimal-face principles; see
[Finding and verifying the nucleolus of cooperative games](https://link.springer.com/article/10.1007/s10107-020-01527-9).
The implementation does not claim a new nucleolus algorithm. The certificate stores
levels, maximum-slack face checks, independent equalities, removed spans and solver
settings. Failure to increase rank or validate the final point blocks M7.

Monetary efficiency/budget checks and frontier monetary ties use the central
1e-5 AUD tolerance. Existing M5/M6 HiGHS settings are reused (primal/dual feasibility
1e-8). Nucleolus universal-tightness tolerance is 1e-7 AUD; synthetic tests repeat
at 1e-8, 1e-7 and 1e-6. Rank has no floating threshold. Share/Gini frontier ties use
1e-5/max(1,abs(v(N))). No arbitrary weighted fairness score exists.

Raw no-harm/core classification exposes a conservative arithmetic roundoff guard:
4*(n+1)*ulp(max(1,max(abs(v)),sum(abs(u)))). It is added to the central monetary
threshold only for classification. This handles subtraction at M6's exactly
1e-5 target (observed overrun 2.02e-13 AUD). It neither edits benefits nor changes
any LP constraint; raw signed deficits remain visible. Tests distinguish this
boundary from a substantive 1.1e-5 deficit. Nested M6 diagnostics retain M6's own
original tolerance, so boundary blocking counts can differ from M7 classification.

## Metrics and interpretation

- Efficiency is sum(u)-v(N); all 512 subset deficits v(S)-sum(u in S) are evaluated.
  Proper coalition statistics exclude empty/grand subsets and include singletons.
- Market/equal-benefit distances are full L1 in AUD.
- Contribution distance is **half** L1 between u/v(N) and m/sum(m). The convention
  is explicit even though the JSON key contains `L1`. Fidelity=1-distance is only
  defined when both are nonnegative probability vectors; signed shares preserve
  the distance but make fidelity null with a reason.
- Gini=sum_ij abs(u_i-u_j)/(2*n*sum(u)); Jain=sum(u)^2/(n*sum(u^2)). Negative
  benefits and near-zero totals produce null plus a reason. Even tiny negative
  numerical residuals are not silently clipped to enable a fairness score.
- Relative bill saving u_i/B_i is null with `nonpositive_standalone_cost` when
  B_i<=1e-5. Member 3's signed bill and absolute benefit remain visible.
- Energy burden is annual bill/annual household income; burden change is -u/income.
  Negative burden denotes net electricity revenue. Income and household type are
  descriptive KPIs only; no demographic weights enter any policy or selection LP.
- Member 5 gets a dedicated raw/repaired case-study table. Members 1/2 get individual
  leave-one-out and joint marginal values, compared to combined M4 benefit. These
  are descriptive game comparisons, not causal proof of PV/BESS complementarity.

## Ablation and governance

A0 standalone precedes any cooperative allocation. A1 physical cooperation creates
v(N) but has no member settlement. A2 is exact M4. A3/A4 reuse exact M6 witnesses.
A5 adds optional governance, separately from required repair. Undefined stage
fields use null/reason, never invented zero values. M6's repair curve is referenced
by immutable path/hash, including its honest one-point official case.

Each raw policy is measured; an admissible raw policy becomes a candidate directly,
otherwise its constitutionally repaired variant becomes the candidate. Both raw
and repaired outcomes remain available. The two discrete frontier views minimize
market distance against benefit Gini or contribution distance. Null metrics are
incomparable. These are candidate-allocation frontiers at fixed physical cost,
not a continuous Pareto frontier or physical efficiency experiment.

The minimal-intervention demo rule is lexicographic: constitutional admissibility,
minimum market L1, maximum minimum benefit, minimum contribution distance, then
lexical policy ID. Numeric ties are anchored to each stage's best value, not
chained pairwise. Every survivor and objective value is recorded in the trace.
The **default != universally fairest policy**. Other admissible policies expose
explicit competing normative choices.

## Output contracts and audit

`PolicyResult` holds identity, definition, normative metadata, raw metrics,
repair-to-constitution and method provenance; `to_dict()`/`to_json()` return no
solver objects. JSON member keys are strings, members ordered 1..9, masks 0..511,
and policy IDs lexical. Modules separate exact games, financial allocation,
repricing, descriptive metrics, selection, ablation, provenance and presentation.

- `m7_policy_comparison.json`: full raw/repaired policies, household and contribution data.
- `m7_price_comparison.json`: full four price series and fixed-quantity settlement checks.
- `m7_ablation.json`: A0–A5 and immutable M6 curve reference.
- `m7_governance.json`: candidates, rejected raw policies, frontiers, demo trace and cases.
- CSV: policy comparison, member outcomes, A0–A5, Member 5.
- PNG/SVG: member benefits, market-vs-Gini, market-vs-contribution.

The stdlib-only auditor independently reconstructs efficiency, bills, all coalition
deficits, no-harm, distances, Shapley, contributions, inequality, income KPIs,
repair witnesses, ranks, price settlements, candidate dominance and demo selection.
It validates upstream and source hashes and CSV member outcomes. The saved worst
coalition must maximize deficit within the explicit arithmetic guard; this allows
Python 3.11 versus 3.13 summation differences without accepting a money-sized tie. LP optimality is
supported by optimal solver terminations plus deterministic synthetic tests;
arithmetic auditing alone does not prove LP optimality. Matplotlib is the only
new direct dependency, using noninteractive Agg and fixed SVG metadata/hash seed.
