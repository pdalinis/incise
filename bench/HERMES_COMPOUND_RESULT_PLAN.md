# Hermes compound-result repair plan

Recorded 2026-09-24 after the first Hermes routed smoke and before changing the
Hermes adapter's tool-result framing or sampling a repaired treatment.

## Trigger

The immutable `hermes_route_smoke_20260924` pool completed 47/48 tasks
correctly with zero harmful edits, zero provider-surface mismatches, and zero
multiple mutations. The sole non-correct row was `release-bump`. On both the
original call and its one permitted identical retry:

- `frontmatter_release_target` was the only provider-visible Incise tool;
- Ornith called it once with `{}`;
- Incise correctly applied both guarded updates and produced the expected final
  bytes;
- the adapter removed Incise tools after success; and
- Ornith then returned empty content until Hermes exhausted its empty-response
  retries.

The tool result's structured `resolvedArguments` named both updates, but its
human-facing `description` was inherited from the final internal operation and
said only that `released` was added. This is incomplete agent-facing reporting
for a successful compound operation.

## Diagnostic replay

A non-benchmark replay used the dumped post-tool provider request and the same
local checkpoint, seed, token cap, and LiteLLM route. The original result text
returned empty content. Replacing only its description with an accurate
sentence stating that both guarded updates succeeded produced a normal final
assistant reply. Direct llama.cpp replay was also non-empty. These diagnostics
identify result framing at the integration boundary; they are not efficacy
samples and will not be pooled with the benchmark.

## Repair

For a routed request containing multiple host-owned operations, return one
combined success description after every operation succeeds. The description
must state that the compound request completed and summarize each successful
Incise operation. It must not claim success before the last operation, hide a
refusal, change structured details, or expose a second mutation opportunity.

Single-operation results remain byte-identical. Route selection, dynamic
schemas, prompts, provider settings, arguments, hashes, rollback, safety checks,
and the one-success latch remain unchanged.

## Deterministic gates

- A unit test must prove the compound result names both updates.
- A unit test must prove a second-operation refusal still returns the refusal
  and restores the original bytes rather than emitting the combined success.
- Existing standalone, installed-host, parity, schema, Rust, and packaging
  checks must remain green.

## Live evaluation

Run a new append-only 48-task smoke with the same Ornith checkpoint, Hermes
0.21.3, seed 40, reasoning off, 2,048-token cap, non-parallel calls, prompts,
routes, and graders. Artifacts use `hermes_route_smoke_v2_20260924`.

Proceed to the preregistered 480-row control and treatment arms only if v2 has
48/48 correct, zero harm, zero framing errors, exact route/fallback surfaces,
and no multiple mutation. The original smoke remains the before result and is
never overwritten.
