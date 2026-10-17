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
pricing, bidding, or historical bi-level optimisation implementation is bundled
with the site.

Coalition masks preserve the canonical member IDs. The existing core and
least-core routines consume the published `mask -> v(S)` mapping unchanged.
