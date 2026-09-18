# Pi live composition benchmark

## Status

Pre-registered 2026-09-18, before any live-model outcome was collected. The plan and harness must be committed before the first preflight request. Results will use new names and will not overwrite any historical pool.

## Question and hypothesis

The release decision is whether adding the three structural reads and their Pi prompt guidance to the established five-tool surface changes task correctness.

Control: `pi-incise@0.1.1` with only `table_edit`, `list_edit`, `section_edit`, `frontmatter_edit`, and `table_get` active.

Treatment: the same package and the same five tools plus `md_tables`, `md_lists`, and `md_outline`, in package registration order.

Prediction: the treatment does not significantly reduce correctness. This is a composition-safety test, not a claim that every added read improves a task. The existing structural summary remains in each user prompt so the only changed inputs are the three active tools and the prompt metadata Pi adds for them.

## Population and pairing

Use the frozen 48-task population: 6 table edits, 10 list edits, 15 section edits, 11 frontmatter edits, and 6 table reads. Run 10 trials per task per condition, paired on `(task_id, trial)`, with seed equal to the trial index: 480 trials per condition and 960 in the primary comparison.

Task SHA-256 values:

- `tables.json`: `2ff4a06e819c3de5404b5873c029e9e208ba1ba0e94a28863dcc677c8d18a318`
- `lists.json`: `37732f805659a06a16a9fbe636a54aa5cd0046d37feaaf4f45f3efc3bc5c6f1f`
- `sections.json`: `e2c0a0ef1f45f8e3299670dad9d5cbcc9ee0d78ffbc49e87dff213fde220d7b2`
- `frontmatter.json`: `f1279fd405ed2fab140a6948881f7db9243a87dcd201d7e10efb86958f4c8989`
- `tables_read.json`: `97a6369c99e5a41ef630b3c0b83b359dc037e4fd621964ee68457fdae0ea3fce`

## Fixed conditions

Run through Pi 0.85.1 and the package extension, with built-in tools, skills, prompt templates, project context, persistence, compaction, and retries disabled. Use Pi default system-prompt construction so active `promptSnippet` and `promptGuidelines` text is part of the measured condition. Each trial receives the same family summary used by `armb.py`, followed by the frozen instruction.

Use `gemma-4-26B-A4B-it` as `gemma4-direct-q8` through llama.cpp server 0.4.0 build 10809 (`5266f24da`) at `127.0.0.1:8081`. Preserve the launch flags recorded in `bench/PLAN.md`: 65,536 context, parallel 1, all layers on GPU, q8 KV cache, flash attention, temperature 1.0, top-k 64, top-p 0.95, min-p 0.05, repeat penalty 1.15 over 256 tokens, reasoning budget 3000, DeepSeek reasoning format, and 8192 predicted tokens. Requests disable thinking and set only the paired seed.

Cap each trial at four assistant turns. Successful writes return the package binary description; structural reads and `table_get` return the package renderer text; thrown Pi validation or Incise refusal text returns as an error tool result. Copy each fixture into a fresh trial directory so no state crosses trials.

## Preflight and stopping

Before the primary run:

1. Capture and hash the eight registered tool definitions, active system prompt in each condition, package tarball integrity, source commit, task files, Pi version, binary version, model file, and server command. Refuse to run if the package is not exactly 0.1.1 or the five measured schemas differ from `incise schema`.
2. Execute every ideal task call through each condition. Both ceilings must be 48/48. The treatment may omit structural reads in this executor check because the ideal edit/read call already has its address; the check asks whether the package can express and execute every correct task outcome.
3. Run seed 0 for all 48 control tasks twice in fresh directories. Require trial-for-trial equality of graded outcomes and tool-call sequences. If this determinism clap fails, stop without inspecting a treatment outcome.

After the clap passes, run the full control and treatment pools. Retry transport failures only; keep every attempt in the raw record and use the last successful row per `(condition, task_id, trial)`. Do not stop early for an apparent win or loss.

## Endpoints and decision rule

Primary endpoint: graded `correct`, pooled over all 480 paired trials, compared with two-sided exact McNemar.

The package passes the live promotion gate only if pooled McNemar is not significant at 0.05 and no task family loses more than 5.0 percentage points from control to treatment. A significant win still passes and is recorded as a surprise. A significant pooled loss or a family loss above 5.0 points fails the gate. Transport failures are not model outcomes and are excluded pairwise after retry exhaustion.

Secondary endpoints are per-family correctness and Wilson intervals, silent corruption, calls and turns per trial, structural-read uptake, recovery after reads or refusals, cross-family calls, Pi validation failures, completion tokens, and elapsed time. They explain the primary result but do not replace the fixed decision rule.

## Records and interpretation

Write new immutable raw and graded pools under a `pi_0_1_1_` prefix, plus one manifest and one analysis report. The manifest records exact commands, hashes, versions, conditions, timestamps, counts, and exclusions. Raw prompts may be represented by hashes when their complete sources are pinned in the same manifest.

Historical F-compose remains current for the five-tool schema and its original prompt/executor condition. This run neither overwrites nor silently extends those pools: it answers the narrower release question about the Pi 0.1.1 surface and Pi prompt construction. A pass licenses calling 0.1.1 stable on this measured model and population; it is not evidence for other models, later Pi versions, unmeasured tools, or Windows.
