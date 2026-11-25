# LFM3 research close-out

Final decision, 25 November 2026: abandon planned LFM3-specific support and close the research effort as unsuccessful. The evaluations did not establish a usable overall accuracy/latency benefit. No LFM3 runtime, adapter, profile, default change or support release is planned. The research goal is cancelled by user decision; it was not achieved. Historical results and prototype commits are retained for audit.

## What the evidence supports

The latest live stage used two tasks, one seed and four fresh sessions. The assertion/compact-metadata candidate completed one of two workflows; control completed zero of two. Both failed the Parent checkbox task. Control eventually made the exact table edit but failed to finish its answer before the deadline. These are completion counts for this small cohort, not an overall accuracy comparison or an update to the earlier approximately 71% result.

The tool returned Parent and Child as distinct source lines. The model repeatedly combined them into one selector and failed to recover after refusal. All 39 complete native tool calls preserved their arguments through parsing; all 41 requests fit the specified context budget. This pool points to item interpretation and recovery rather than parser corruption. It does not establish a general diagnosis. The candidate bundled assertions with compact metadata, and no assertion-mismatch refusal was exercised.

No harmful or unrequested file states were observed in this small pool. Candidate median elapsed time was 127.7 seconds, above the 60-second gate. Deterministic V80 qualification passed, but neither those tests nor this small live pool qualify model efficacy, speed or safety. The review was not blinded or an independent human safety review. The [evidence summary](bench/results/lfm3_closeout_20261125_summary.json) records individual attempts, conditions, limitations and source-report hashes; full reports and raw traces remain in local research checkouts.

The original direct with/without comparison of released Incise 0.5.0 tools covered 41 usable editing pairs: both conditions scored 29/41 correct (70.7%). Mean elapsed time was 99.7 seconds without Incise versus 223.0 seconds with it; mean generated tokens were 1,177 versus 2,214. Eight pairs favored each condition, with exact McNemar p = 1.0. This exploratory single-seed smoke test excluded one pair after repeated baseline timeouts; the planned 960-trial comparison never started. Later prototype studies compared Incise variants and do not provide an updated with/without score.

## Compatibility fix retained separately

Canonical item selection and grouped mutations were incompatible on mixed checkbox/plain lists: canonical declarations narrowed member target enums differently, so grouping correctly refused unequal constraints. The isolated fix retains each incoming source-bound target set in grouped mode. It never unions unequal input sets, and the owned callback still independently checks the exact item against its selected current target. Standalone canonical declarations retain their previous behavior.

The fix and regression tests are retained on local branch `fix/lfm3-canonical-grouped-closeout`, based on research commit `01c12dfaa6eb09fd988689497bc252b4a3340465`. They are not included in this documentation PR: both components depend on unpublished experimental runtime code. Passing compatibility tests does not establish that LFM3 will choose the correct item. The assertion workflow and larger prototypes remain isolated.

The retained patch is commit `558e9474f970d53bfbf2923de5eed66ac7868e04`. Close-out validation passed 15 focused regressions, the full 1,766-test Pi suite with the frozen-predecessor comparison enabled, typechecking, package validation, Rust formatting/lint/tests, Python invariants, 127,974 differential cases, schema checks, recorded-call replay and Hermes tests. Reverting the fix makes the new mixed-list regression fail with the original refusal. These are local deterministic checks; supported-platform CI and model efficacy are separate gates.

## Final disposition

The user ended LFM3-specific development. The unreleased `lfm3-routed` and focus integrations are removed from the active source checkout, their activation instructions and package expectations are removed, and the dedicated LFM3 inference server is stopped. Previously validated model profiles remain available.

Historical reports, raw evidence and unpublished prototypes remain archived; no failed pool is overwritten or promoted into a support claim. The isolated compatibility patch is an archived experiment and has no planned merge or release. The original research checkpoint is retained on local Git branch `archive/lfm3-research-20261125`.

There are no remaining LFM3 implementation tasks, model runs or release gates being pursued. This final decision supersedes the earlier defer/reopen recommendation. This documentation PR has no model-facing effect; the local cleanup restores the shared released routing implementation and withdraws the unpublished LFM3-only composition.
