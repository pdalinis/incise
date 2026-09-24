# Shared fallback-route confirmation and second Ornith holdout

Recorded 2026-09-23 after the paired Ornith fallback treatment passed and
before either confirmation population was sampled.

## Gemma shared-profile confirmation

Run the same eleven affected tasks and seeds 0 through 9 against the historical
local `gemma4-direct-q8` endpoint, Pi 0.85.1, its normal provider defaults, and
the current shared `safe-routed` profile. Do not apply Ornith reasoning,
completion-cap, or parallel-call settings.

Pass only with 110/110 correct final documents, zero harmful, malformed, or
transport outcomes, exactly one successful agent-facing route per trial, exact
model-supplied and host-resolved arguments, and no excess mutations. This is a
targeted compatibility check and does not replace frozen Gemma full-v8.

## Second Ornith holdout

After Gemma passes, run all 48 frozen tasks ten times at previously unused seeds
20 through 29. Use the identical runtime and provider configuration from
`ORNITH_HELD_VALIDATION_PLAN.md`: Ornith-1.5-9B Q8_0, Pi 0.85.1, shared
`safe-routed`, reasoning off, 2,048 maximum completion tokens,
`parallel_tool_calls: false`, four turns, and a 900-second worker timeout.

Apply the original Gemma-comparison gate unchanged:

- at least 478/480 usable and at least 472 correct;
- zero harmful final documents;
- table mutations at least 57/60, lists 100/100, sections at least 140/150,
  frontmatter at least 105/110, and table reads at least 57/60;
- zero provider-framing errors, reasoning leaks, route-audit errors, or excess
  successful mutations.

The seeds 0 through 19 pools remain immutable and are excluded from the second
holdout gate.
