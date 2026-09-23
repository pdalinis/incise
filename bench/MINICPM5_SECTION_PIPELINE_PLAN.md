# MiniCPM5 dynamic-plan section pipeline experiment

Recorded 2026-09-21 before implementing the pipeline or inspecting any pipeline outcome.

## Question

The cardinality-routed required-slot ceiling achieved 12/12 correct section insertions, but the host was given the benchmark's ideal anchor, position, and requested child count. This experiment replaces those oracle inputs with a MiniCPM planning phase over the real request and current outline.

It asks two questions: can MiniCPM select a small structural plan when no content fields compete for attention, and does the resulting two-phase pipeline retain the required-slot arm's edit accuracy and safety?

## Population and reference

Use the same 12 `(task_id, trial)` pairs for `insert-release-at-top`, `insert-subsection-last`, `insert-nested-ratelimits`, and `insert-troubleshooting`, with the same fixtures, outlines, task wording, and three seeds.

The host-routed required-slot ceiling is the reference at 12/12. The original routed insertion condition was 0/12. Neither is resampled.

## Treatment

Use MiniCPM5 Q8_0, temperature 0.7, top-p 0.95, and the existing section prompt and outline.

### Phase 1: structural plan

Expose and force only `section_insert_plan`, requiring:

- `anchor`: one exact existing section path from a dynamic JSON-schema enum built from the current outline;
- `position`: one of `before`, `after`, `first-child`, or `last-child`;
- `child_count`: integer 0, 1, or 2.

The file path and action are host-owned and absent from the schema. The description explains that "immediately above" means `before` the named existing target and that "under" or "at the end of" an existing section means `last-child`.

The expected plan is derived before sampling from the task's first ideal operation and requested subsection count. Plan accuracy requires all three fields to match exactly.

### Phase 2: required content

If phase 1 emits a syntactically valid plan, append its tool call and a short acceptance result to the conversation. Select the already-tested zero-, one-, or two-child required micro-schema from the model's `child_count`, expose and force only that content tool, and sample once.

The host injects the fixture path plus the model-selected anchor and position, converts flat child slots into structured children, and executes one atomic `section-insert`. A malformed or refused phase writes nothing. There is no retry or correction turn, and success is terminal.

## Endpoints and decision rule

Co-primary endpoints:

1. exact structural-plan accuracy across 12 pairs;
2. exact final-document correctness across the same pairs.

Report paired final correctness against the required-slot ceiling and against the original routed insertion result, plus phase-specific token and latency costs.

The pipeline clears the gate only if all are true:

1. at least 11/12 plans are exact;
2. at least 10/12 final documents are correct;
3. every task type is finally correct in at least two seeds;
4. no final outcome is destructive or collateral;
5. every refusal leaves the fixture byte-identical.

A pass supports implementing a model-specific section router. A failure must be attributed separately to anchor, position, child count, content, or execution before another schema change.

## Artifacts and stopping

Write raw and graded rows to `bench/results/minicpm5_section_pipeline_20260921{,_graded}.jsonl` and analysis to `bench/results/minicpm5_section_pipeline_analysis_20260921.json`. Preserve raw plan and content calls, expected and received plans, composed operation, source/schema hashes, and model identity.

Run each fixed pair once. Resume only transport errors. Do not alter enums, descriptions, tool results, thresholds, or seeds after seeing outcomes. Restore Gemma after collection.
