# ComFair coalition game

This standalone site serves the published benchmark artifacts. It supports the
two scenarios represented by those artifacts:

- **baseline**: uncoordinated standalone-household operation from M3;
- **cooperative_pool**: the cooperative physical-pool game and stability certificate from M5.

`PrecomputedBenchmarkStore` validates and serves those immutable results. A
cache miss remains unavailable by default, so a web request never starts an
optimisation job or fabricates a result.

The package retains a small `CoalitionCostEvaluator` protocol for tests and for
callers that explicitly inject their own calculation backend. No forecasting,
pricing, bidding, or private multi-stage optimisation implementation is bundled
with the site.

Coalition masks preserve the canonical member IDs. The existing core and
least-core routines consume the published `mask -> v(S)` mapping unchanged.

For explicit custom evaluation backends, `CoalitionEvaluation` validates the
member-level costs and successful solver status. `pricing_provenance` is optional
for the physical pool, but its `coalition_members` field (when supplied) must
match the evaluated coalition. The `evaluation_stage` field is source metadata,
not the name of a private optimisation stage. Fresh M5 outputs are generated
only in a new output directory; published JSON artifacts remain immutable.
