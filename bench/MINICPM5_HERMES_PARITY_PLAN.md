# MiniCPM5 Hermes routed-parity plan

Recorded 2026-09-25 after Incise 0.3.1 was released with the measured MiniCPM5 Pi profile, and before changing the Hermes route adapter or sampling a MiniCPM treatment through Hermes.

## Evidence entering this gate

MiniCPM5 2B Q8_0 completed the frozen 48-task Pi composition at **480/480 correct** with zero harmful outcomes, framing errors, reasoning leaks, or multiple changed mutations. The final audit contained 470 routed trials and 10 standard fallbacks. Gemma and Ornith each retained 51/51 across the 17 Pi tasks affected by the final MiniCPM route work.

Hermes already has deterministic and live evidence for the earlier Gemma/Ornith route set: its route audit matched 36 routed and 12 fallback tasks, and both models completed 480/480 through Hermes. MiniCPM intentionally remains on Hermes's standard surface under `auto` because the adapter predates five Pi routes:

- named table-row addition;
- exact existing-row deletion;
- labelled-table cell update;
- guarded section-subtree deletion; and
- labelled ordinal table read.

The first four need registered Hermes handlers. Ordinal table reads reuse the existing `table_query` handler.

## Question

Can Hermes port those five host-resolved paths without changing the standard profile, weakening host safety, or regressing the previously measured Gemma and Ornith behavior? If so, can the real Hermes loop reproduce MiniCPM's 480/480 Pi result closely enough to enable MiniCPM under Hermes `auto`?

## Frozen implementation scope

Port the corresponding Pi intent parsers, structural preconditions, empty request schemas, canonical arguments, content-hash guards, and result metadata into `plugins/hermes/safe_routed.py`. Preserve:

- Hermes read and write policy checks;
- foreign provider tools;
- the byte-identical standard eight-tool fallback;
- same-file serialization and the one-successful-mutation latch;
- rollback behavior for compound routes; and
- existing Gemma and Ornith route schemas and arguments.

Do not change Incise core behavior, corpus fixtures, frozen task prompts, grading, retry policy, or provider sampling during this experiment. MiniCPM remains excluded from Hermes `auto` until every adoption gate passes.

## Deterministic gates

Before live sampling:

1. Add adapter tests for all five paths, including exact resolved arguments, empty model-supplied arguments, stale-hash refusal for a new mutation route, unique structural resolution, subtree confirmation, provider narrowing, and the success latch.
2. Audit Hermes against the final MiniCPM Pi pool over all 48 tasks. It must match exactly 47 routed decisions and one standard fallback, including tool name, route kind, and canonical resolved arguments.
3. Rerun the existing Ornith/Gemma parity audit. Its historical 36-route/12-fallback expectation may be superseded only where the final shared Pi profile intentionally routes one of the five added tasks; every other decision and argument must remain identical.
4. Pass the Hermes adapter suite, Rust tests, schema/replay/invariant suites, Pi tests, formatting, and lint checks.

Any deterministic mismatch blocks live sampling.

## Live conditions

Use the official local checkpoints through the existing OpenAI-compatible llama.cpp endpoint and Hermes Agent 0.21.3. Run on purpose-built copies under the marked temporary Hermes benchmark directories. MiniCPM uses thinking disabled, temperature 0.7, top-p 0.95, a 65,536-token context, an 8,192-token output cap, disabled parallel tool calls, and seeds 0 through 9. The harness records provider-visible tools, calls, results, resolved arguments, hashes, mutation count, final bytes, timing, and token usage.

The staged sequence is:

1. **MiniCPM route smoke:** explicit `safe-routed`, all 48 tasks at seed 0.
2. **Cross-model retention:** the five newly routed tasks at seeds 0 through 2 through Hermes for Gemma and Ornith.
3. **MiniCPM composition:** explicit `safe-routed`, all 48 tasks at seeds 0 through 9.
4. **Auto selector smoke:** only after the full gate passes, enable MiniCPM for Hermes `auto`, prove selector equivalence deterministically, and rerun the 48-task seed-0 smoke through `auto`.

One transport or ordinary-action timeout may be retried once with the identical task, seed, model, and settings; both attempts remain recorded. A harmful treatment result stops the current arm immediately. No route, prompt, schema, grader, or sampling setting changes after the first valid sample in an arm.

## Adoption gates

MiniCPM may be enabled under Hermes `auto` only if:

- deterministic parity is 47 routed tasks and one standard fallback with zero mismatches;
- the MiniCPM smoke is 48/48 correct;
- Gemma and Ornith each retain all 15 targeted trials with zero harmful outcomes or framing errors;
- the full MiniCPM composition has 480 usable and correct trials: tables 60/60, lists 100/100, sections 150/150, frontmatter 110/110, and table reads 60/60;
- all routed trials expose exactly one expected Incise tool and make exactly one successful canonical call with model-supplied `{}` arguments;
- the fallback trials retain the unchanged standard surface;
- there are zero harmful outcomes, framing errors, visible reasoning leaks, or multiple changed mutations; and
- the post-adoption `auto` smoke remains 48/48.

A failed gate keeps MiniCPM on Hermes's standard profile. Pi behavior and all existing model claims remain unchanged.

## Artifacts

New append-only artifacts use these prefixes:

- `minicpm5_hermes_route_parity_20260925`
- `minicpm5_hermes_route_smoke_20260925`
- `gemma_hermes_minicpm_retention_20260925`
- `ornith_hermes_minicpm_retention_20260925`
- `minicpm5_hermes_safe_routed_20260925`
- `minicpm5_hermes_auto_smoke_20260925`

Historical pools and analyses are never overwritten. A Hermes result is reported separately from the existing Pi result even when the frozen tasks and expected edits are identical.

## Pre-implementation scope correction

Before implementation, a counterfactual audit compared the unchanged Hermes adapter against the final MiniCPM Pi pool. It found 17 task-level mismatches, not five. This correction is based only on recorded calls and deterministic route planning; no Hermes treatment was sampled.

The five v3 paths remain missing, but parity also requires the earlier MiniCPM v2 behavior: four table-row additions, two exact list-ending requests, the hotfix release append, a host-owned quoted replacement body, and five host-owned typed frontmatter updates. The corrected implementation scope is therefore the complete 17-task v2+v3 set.

The deterministic gate remains 47 routed tasks and one fallback with exact tool, kind, and resolved arguments. Cross-model retention is corrected from five tasks to all 17 affected tasks, or 51 trials per retained model at seeds 0 through 2. Every later adoption gate is interpreted using this corrected scope.
