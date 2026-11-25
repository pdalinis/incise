# LFM3 research close-out

Decision, 25 November 2026: defer advertised LFM3 support and keep the research goal paused. Close this research cycle without more model runs, default changes or a runtime release. The Hermes adapter is outside this close-out.

## What the evidence supports

The latest live stage used two tasks, one seed and four fresh sessions. The assertion/compact-metadata candidate completed one of two workflows; control completed zero of two. Both failed the Parent checkbox task. Control eventually made the exact table edit but failed to finish its answer before the deadline. These are completion counts for this small cohort, not an overall accuracy comparison or an update to the earlier approximately 71% result.

The tool returned Parent and Child as distinct source lines. The model repeatedly combined them into one selector and failed to recover after refusal. All 39 complete native tool calls preserved their arguments through parsing; all 41 requests fit the specified context budget. This pool points to item interpretation and recovery rather than parser corruption. It does not establish a general diagnosis. The candidate bundled assertions with compact metadata, and no assertion-mismatch refusal was exercised.

No harmful or unrequested file states were observed in this small pool. Candidate median elapsed time was 127.7 seconds, above the 60-second gate. Deterministic V80 qualification passed, but neither those tests nor this small live pool qualify model efficacy, speed or safety. The review was not blinded or an independent human safety review. The [evidence summary](bench/results/lfm3_closeout_20261125_summary.json) records individual attempts, conditions, limitations and source-report hashes; full reports and raw traces remain in local research checkouts.

## Compatibility fix retained separately

Canonical item selection and grouped mutations were incompatible on mixed checkbox/plain lists: canonical declarations narrowed member target enums differently, so grouping correctly refused unequal constraints. The isolated fix retains each incoming source-bound target set in grouped mode. It never unions unequal input sets, and the owned callback still independently checks the exact item against its selected current target. Standalone canonical declarations retain their previous behavior.

The fix and regression tests are retained on local branch `fix/lfm3-canonical-grouped-closeout`, based on research commit `01c12dfaa6eb09fd988689497bc252b4a3340465`. They are not included in this documentation PR: both components depend on unpublished experimental runtime code. Passing compatibility tests does not establish that LFM3 will choose the correct item. The assertion workflow and larger prototypes remain isolated.

The retained patch is commit `558e9474f970d53bfbf2923de5eed66ac7868e04`. Close-out validation passed 15 focused regressions, the full 1,766-test Pi suite with the frozen-predecessor comparison enabled, typechecking, package validation, Rust formatting/lint/tests, Python invariants, 127,974 differential cases, schema checks, recorded-call replay and Hermes tests. Reverting the fix makes the new mixed-list regression fail with the original refusal. These are local deterministic checks; supported-platform CI and model efficacy are separate gates.

## Conditions for reopening

Reopen only as a separately scoped decision with an owner, a fixed time/inference budget, one preregistered comparison and a stopping rule. Qualify the full intended composition before making support claims. Existing gates remain: at least 19/20 on the original cohort including every required edit and guard, zero harm, no category regression, median at most 60 seconds and P95 at most 180 seconds, replication, broader task families, the non-adapter Hermes host, independent human safety review and supported-platform CI.

No failed pool is overwritten or rescued by reseeding. Historical results remain valid only within their original conditions. This close-out is documentation with no model-facing effect; the retained runtime fix would require composition-wide live remeasurement before any efficacy claim. No such trial is part of this close-out.
