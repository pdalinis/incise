# Ornith 1.5 9B full Pi evaluation plan

Recorded 2026-09-23 before any outcome-bearing Ornith Incise trial. The earlier
single `echo` call was a transport-only check: it contained no Incise tool,
fixture, or frozen-task prompt and is not benchmark evidence. Tracking issue:
https://github.com/pdalinis/incise/issues/25.

## Question and target

Can `ornith-ai/Ornith-1.5-9B` Q8_0, using its native reasoning path through Pi,
match the released Gemma safe-routed result on Incise's frozen 48-task
population without weakening executor safety or changing Gemma or MiniCPM
behavior?

The comparison target is Gemma full-profile v8: 475/479 usable trials correct,
zero harmful outcomes, and family floors of table 57/60, list 100/100, section
140/149, frontmatter 105/110, and table-read 57/60. The aspirational target is
at least 99% correct among usable trials. A refusal or operation error is not
harmful when the file is unchanged; `wrong`, `destructive`,
`collateral:content`, and `collateral:formatting` are harmful. In addition to
the historical outcome, this campaign grades every changed final document
directly. A loud error elsewhere in the turn cannot mask a harmful final
document.

## Fixed environment

- Integration: Pi 0.85.1 and the production `plugins/pi/extension/index.ts`.
- Incise: 0.2.0 at tag commit `abc3674`.
- Model alias: `ornith-1.5-9b-q8`.
- Text weights: `Ornith-1.5-9B-Q8_0.gguf`, SHA-256
  `22086870b009dbe9815ee752c48a82de930118a7c5ce5599590892ae03b8b010`.
- Vision projector is loaded but unused; SHA-256
  `626f9f90627402a6bf4a999111d0fbd69b5fcca7aa8ba089d69e5f10e8858e1d`.
- Runtime: llama.cpp 0.4.0 build 10809, commit `5266f24da`, Metal.
- Runtime context: 65,536; one parallel slot; Q8_0 K/V cache; flash attention.
- Maximum completion: 8,192 tokens.
- Sampling: temperature 0.6, top-p 0.95, top-k 20, min-p 0,
  presence penalty 0, repeat penalty 1.0, with trial index as seed.
- Reasoning: enabled at Pi level `high`; OpenAI-compatible
  `qwen-chat-template` framing with `enable_thinking: true` and
  `preserve_thinking: true`.
- Each trial permits at most four assistant turns and has a 900-second worker
  timeout. The harness records reasoning text length, reported reasoning tokens,
  provider framing, active tools, calls, results, file hashes, latency, and final
  document.

The launch agent's defaults differ from the sampling values above. The Pi
request supplies the fixed evaluation values explicitly, so the manifest must
confirm them on the first provider request before a pool is accepted.

## Population and phases

The population is the unchanged 48 tasks in `bench/tasks/tables.json`,
`lists.json`, `sections.json`, `frontmatter.json`, and `tables_read.json`.
Fixtures and graders are unchanged.

1. Preflight is non-scoring. Verify model identity, active tools, reasoning
   framing, sampling payload, multi-turn tool-result replay, and that reasoning
   is not mixed into tool arguments or final answer text.
2. Smoke uses one task from each of the five task families at seed 0. It may
   invalidate the transport configuration, but it cannot justify product
   behavior or a performance claim.
3. Determinism clap runs all 48 tasks twice at seed 0 under `auto`. Differences
   are recorded; they do not permit deleting or replacing either pool.
4. Current-product baseline runs 10 trials per task, seeds 0 through 9, under
   `INCISE_PROFILE=auto`. Ornith is currently an unknown family, so the expected
   effective profile is `standard`. Any accidental routed tool activation
   invalidates the baseline.
5. Untuned transfer runs the same 480 pairs with the existing
   `INCISE_PROFILE=safe-routed`. This tests whether the already released Gemma
   router transfers to Ornith. It may run only after the baseline is complete
   and may not change router code first.
6. If neither condition reaches the target, diagnose failure clusters by task,
   family, call shape, refusal, reasoning length, and route eligibility. New
   changes require separate targeted plans and new result names. Do not tune by
   repeatedly replacing full-suite results.
7. Any changed Ornith profile receives a final 480-trial validation on seeds 10
   through 19. Only that held run can license Ornith auto-detection. Hermes is a
   later confirmation, not evidence for Pi.

## Decision rules

The baseline and transfer pools are reported independently and paired on task
and seed. A condition matches the released Gemma gate only if it has at least
478 usable trials, at least 472 correct trials, zero harmful outcomes, and meets
all five Gemma family floors. Exact achieved metrics are always reported even
when the binary gate passes.

Enabling Ornith in `auto` additionally requires a held full validation, no
multiple-successful-mutation event, no reasoning/tool serialization failure,
and unchanged Gemma and MiniCPM tests and benchmark behavior. Failure leaves
Ornith on the model-agnostic standard profile. Historical pools are immutable;
transport retries append records and the latest attempt is selected explicitly.

## Pre-baseline harness corrections

The first smoke dispatch failed before inference because two proposed smoke IDs
did not exist in the frozen task files. Commit `6d60d7d` corrected only those
IDs; it produced no result row.

The five-row smoke then exposed a grader blind spot before the clap or full
baseline: `set-build-target` ended with a wrong changed document, but the
historical aggregate outcome became `op_error` because a separate `table_get`
call also refused. The stricter changed-document safety audit above was added
after retaining that raw and graded smoke pool and before any clap or baseline
sample. This correction can only make the safety gate stricter; it does not
alter execution, historical grading, prompts, sampling, tasks, or the primary
correctness endpoint.
