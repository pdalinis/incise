# Ornith single-tool-call protocol experiment

Recorded 2026-09-23 before sending any request with
`parallel_tool_calls: false`.

## Problem and hypothesis

The target-route treatment was 30/30 correct with zero harmful final documents,
but failed its latency gate on `insert-troubleshooting` seed 1. With a
2,048-token completion limit, Ornith emitted many identical zero-argument
`section_insert_target` calls in one assistant message. Pi rejected the calls
while the response was length-truncated; a later turn eventually made one
successful call. The trial took 186.6 seconds. At 8,192 tokens the same seed
previously exceeded the 900-second worker timeout.

The route permits exactly one tool call. The OpenAI-compatible request field
`parallel_tool_calls: false` directly expresses that constraint and should stop
the repeated-call burst without changing Incise routing, arguments, execution,
or result framing.

## Paired experiment

Treatment reruns `insert-troubleshooting` at seeds 0 through 9 with the same
changed router, Pi 0.85.1, Ornith-1.5-9B Q8_0, reasoning off, official coding
sampling values, four turns, 2,048 maximum completion tokens, and 900-second
worker timeout. The only changed provider field is
`parallel_tool_calls: false`.

The paired control is the ten `insert-troubleshooting` rows in
`ornith_target_routes_treatment_20260923`. The harness must record the provider
field exactly; missing or true values invalidate a treatment row.

## Gate

Adopt the field for the Ornith evaluation configuration only if treatment has:

- 10/10 correct final documents;
- zero harmful, transport, framing, or reasoning-leak outcomes;
- exactly one successful mutation and no rejected duplicate tool calls per
  trial;
- mean elapsed time at most 20 seconds and maximum at most 45 seconds; and
- no paired correctness regression.

This experiment cannot add the field to Gemma, MiniCPM, or a model-agnostic
default. A pass licenses the planned full Ornith safe-routed validation using
the measured Ornith-specific provider setting.
