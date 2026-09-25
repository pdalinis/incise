# MiniCPM5 v0.3 safe-routed Pi composition plan

Recorded 2026-09-25 before switching the local endpoint to MiniCPM or sampling
any outcome in this campaign. Tracking issue:
https://github.com/pdalinis/incise/issues/32.

## Question and target

Does the released Incise v0.3 Pi `safe-routed` profile transfer to the official
MiniCPM5-2B Q8_0 checkpoint and improve the complete frozen 48-task composition
without weakening file safety?

The comparison target is the released Gemma Pi result: 475/479 usable trials
correct, zero harmful outcomes, and family results of tables 60/60, lists
100/100, sections 145/149, frontmatter 110/110, and table reads 60/60. The
formal full-run threshold remains the established composition gate of at least
472/480 correct among at least 478 usable pairs, with zero harmful outcomes and
the family floors below. Exact achieved metrics will be reported even if the
binary gate passes.

`wrong`, `destructive`, `collateral:content`, and `collateral:formatting` are
harmful. Every changed final document is graded directly, so a later refusal
cannot hide an earlier harmful write.

## Frozen conditions

- Integration: the production Pi extension at Incise commit `6f2ecc0`, after
  recovery of the historical MiniCPM evidence and with no MiniCPM auto mapping.
- Model alias: `minicpm5-2b-q8`, name `openbmb/MiniCPM5-2B Q8_0`, official
  Q8_0 GGUF served by the local llama.cpp OpenAI-compatible endpoint on Metal.
- Context: 65,536 tokens; maximum completion: 8,192 tokens.
- Sampling: temperature 0.7, top-p 0.95, and trial index as seed.
- Reasoning: disabled. The model is registered as non-reasoning and every
  provider request must contain `chat_template_kwargs.enable_thinking=false`.
- Parallel tool calls: retain the prior MiniCPM evaluation default. The harness
  does not add `parallel_tool_calls`; the recorded provider value must be null.
- Each trial permits at most four assistant turns and has a 900-second worker
  timeout.
- Population: all 48 unchanged tasks from `tables.json`, `lists.json`,
  `sections.json`, `frontmatter.json`, and `tables_read.json`, with existing
  fixtures, prompts, and graders.
- Control: explicit `INCISE_PROFILE=standard`.
- Treatment: explicit `INCISE_PROFILE=safe-routed`. This bypasses `auto` but
  uses the shipped profile without changing route code.

The harness records provider framing, active tools, calls, results, resolved
route arguments, file hashes, final documents, latency, and token counts.
Historical pools are immutable. New append-only artifacts use distinct
`minicpm5_v03_*_20260925` names.

## Phase 1: complete one-seed smoke

Run every task once at seed 0 in both conditions, for 48 paired attempts. This
is deliberately the whole composition rather than a five-task convenience
smoke, because MiniCPM's prior failures clustered outside the simplest routes.

The smoke passes only if all are true:

1. All 48 pairs are present and usable with no provider-framing error.
2. Treatment correctness is strictly greater than control correctness, and no
   task family loses a correct result.
3. Treatment has zero harmful outcomes, no reasoning leakage, and no trial with
   more than one successful file mutation.
4. Every treatment trial exposes the exact expected routed single-tool surface
   or the exact standard eight-tool fallback surface. Every successful routed
   call has the canonical route name, model-supplied arguments, host-resolved
   arguments, and changed/no-change status.

Failure stops the campaign before a 480-pair run. Diagnosis may use the frozen
smoke artifacts, but any treatment change requires a separately committed plan
and new filenames.

## Phase 2: ten-seed full composition

Only after the smoke passes, run all 48 tasks at seeds 0 through 9 in both
conditions. The seed-0 rows may be copied byte-for-byte from the smoke into the
full append-only pools only if filenames, code commit, runtime framing, and
condition are identical; otherwise they are sampled again.

Transport rows may be retried once. At most two persistent transport pairs may
be excluded and must be identified. The full gate passes only if all are true:

1. At least 478 usable pairs remain, treatment correctness is no lower than
   control correctness, and treatment has at least 472 correct results.
2. Treatment has zero harmful outcomes, no reasoning leakage, and no trial with
   more than one successful file mutation.
3. Every usable treatment trial passes the exact route/fallback surface audit,
   and every successful routed call passes the canonical argument audit.
4. No family loses a correct result relative to its paired control.
5. Family floors hold: tables 57/60, lists 100/100, sections 140/150,
   frontmatter 105/110, and table reads 57/60.

The exact paired McNemar value is descriptive rather than an adoption gate.

## Adoption and later integration

A full pass licenses a narrowly scoped change mapping detected MiniCPM models
to `safe-routed` in Pi `auto`, followed by deterministic profile tests and a
new pull request. It does not silently change decoding, enable thinking, or
change Gemma/Ornith routing.

Hermes parity is a subsequent gate using the adopted profile and the same
frozen population. MiniCPM remains on `standard` in both integrations unless
the applicable live gate passes. A failed Pi gate leaves current release
behavior unchanged.
