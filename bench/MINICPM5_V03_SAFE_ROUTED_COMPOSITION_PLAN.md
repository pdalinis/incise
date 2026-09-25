# MiniCPM5 v0.3 safe-routed composition plan

Recorded 2026-09-25 after the v3 seed-0 gate and both retention arms completed,
and before sampling any seed 1–9 MiniCPM outcome. Tracking issue:
https://github.com/pdalinis/incise/issues/32.

## Evidence entering this gate

The immutable v2 MiniCPM arm was 43/48 correct. V3's existing raw seed-0 trace
is 48/48 correct after a deterministic grading correction: the inherited
routed-read whitelist initially omitted `get-ordinal-table`, even though the
raw trace contains one successful canonical `table_query`, the exact expected
row, and the exact correct answer. The original grade and failed analysis are
retained; the separately named regrade records the correction without
resampling.

The 17 affected tasks then passed 51/51 for Gemma and 51/51 for Ornith at
seeds 0 through 2. Across MiniCPM seed 0 and both retention arms, v3 is 150/150
correct with zero harmful outcomes, framing errors, multiple changed mutations,
reasoning leaks, or route-audit errors.

## Question

Does the complete shared `safe-routed` candidate make MiniCPM reliable across
the same 48-task, 10-seed composition used for the released Gemma and Ornith
claims, including the 31 tasks that intentionally retain the standard surface?

## Frozen treatment

Use commit `04cefdb` plus the result-recording commit that follows this plan.
Run MiniCPM5-2B Q8_0 through Pi with explicit `INCISE_PROFILE=safe-routed`,
thinking disabled, temperature 0.7, top-p 0.95, 8,192 output tokens, the frozen
48 tasks, and seeds 0 through 9. Do not change prompts, schemas, routing,
sampling, task order, turn limits, or grading after this plan.

The existing seed-0 raw trace may be reused byte-for-byte. Sample only its
missing seeds 1 through 9 into a new append-only composition pool. All grading
must recognize the five routed table-read tasks, including
`get-ordinal-table`.

## Gate

The candidate passes only if all of the following hold:

1. All 480 trials are usable and correct: tables 60/60, lists 100/100,
   sections 150/150, frontmatter 110/110, and table reads 60/60.
2. There are zero harmful document outcomes, provider-framing errors, visible
   reasoning leaks, or trials with more than one changed mutation.
3. All 170 affected trials expose exactly one expected route tool and produce
   exactly one successful canonical call with model-supplied `{}` arguments.
4. All 310 unaffected trials expose the unchanged standard eight-tool surface
   on the first provider request.

No retries or replacement seeds are allowed. Transport failures remain
transport outcomes and fail the gate.

## Decision rule

A complete pass licenses adoption of the v3 Pi routes and MiniCPM selection
under Pi's `auto` profile, followed by deterministic tests and documentation.
Any failure keeps MiniCPM opt-in through explicit `safe-routed`; classify the
failure before proposing another route.

This experiment does not license Hermes parity. Hermes needs an explicit port,
deterministic 48-task route-decision parity, and its own live integration gate.

New result names end in `_composition_v3_20260925`; no earlier pool is
overwritten.
