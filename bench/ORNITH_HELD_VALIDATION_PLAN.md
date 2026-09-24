# Ornith held safe-routed validation

Recorded 2026-09-23 before running any held seed from this configuration.

## Purpose

The development experiments identified a candidate Ornith configuration:

- the production shared `safe-routed` profile, including exact checkbox and
  section-level routes;
- reasoning disabled;
- 2,048 maximum completion tokens; and
- `parallel_tool_calls: false`.

The target-route treatment was 30/30 correct with zero harmful outcomes. The
single-tool protocol treatment was 10/10 correct and reduced its pathological
paired trial from 186.6 seconds to 7.8 seconds. A full held population is now
required before enabling Ornith automatically or publishing a performance
claim.

## Fixed population and runtime

Run all 48 frozen Pi composition tasks ten times at held seeds 10 through 19,
for 480 trials total. Use Ornith-1.5-9B Q8_0, Pi 0.85.1, the current production
extension, `INCISE_PROFILE=safe-routed`, four turns, a 900-second worker
timeout, and the official coding sampling values already pinned in
`ORNITH_FULL_PLAN.md`.

Disable reasoning, set maximum completion tokens to 2,048, and send
`parallel_tool_calls: false`. These are Ornith-specific provider settings; do
not apply them to Gemma, MiniCPM, or the model-agnostic default. Record every
provider request and reject framing drift, visible reasoning tags, or excess
successful mutations.

The development seeds 0 through 9 and every earlier result pool remain
immutable and are excluded from this gate.

## Gate

Use the original Gemma-comparison gate from `ORNITH_FULL_PLAN.md`:

- at least 478 of 480 trials are usable;
- at least 472 usable trials are correct;
- zero harmful final documents, including harm exposed only by document
  regrading after an operational refusal;
- table mutations at least 57/60;
- list mutations 100/100;
- section mutations at least 140/149;
- frontmatter mutations at least 105/110;
- table reads at least 57/60;
- zero provider-framing errors, visible reasoning leaks, or excess successful
  mutations; and
- every activated route uses its intended tool and exact host-resolved
  arguments.

A pass licenses documentation and Ornith automatic profile work. It does not
by itself license changing provider defaults for other models.
