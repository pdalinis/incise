# MiniCPM5 host-routed flat section-slots experiment

Recorded 2026-09-21 before implementing the treatment harness or inspecting any treatment outcome.

## Question

The routed section-insert arm scored 0/12 on four tasks. Adding the core's nested `children` field also scored 0/12: MiniCPM never used it and continued confusing the file path, target section path, anchor, ordinal, and position. The calls nevertheless often contained the requested prose and subsection names.

This experiment measures a stronger routing ceiling: can MiniCPM supply correct section content when the host owns every structural argument and the payload is flat? It does not measure an end-to-end intent resolver. The harness uses the benchmark task's known ideal anchor and position, exactly as the earlier routed arm used its known family and action.

## Control

Reuse the same 12 `(task_id, trial)` pairs for `insert-release-at-top`, `insert-subsection-last`, `insert-nested-ratelimits`, and `insert-troubleshooting` from the original routed section pool. The control is 0/12 correct: seven `op_error` and five `wrong`.

The failed nested-children treatment is context, not the statistical control; it also scored 0/12.

## Treatment

Use the same MiniCPM5 checkpoint, endpoint, task prompts, fixtures, outlines, three seeds, temperature 0.7, top-p 0.95, grader, and terminal-after-first-mutation rule.

Expose and force one evaluation-only `section_insert_content` tool. The model sees only:

- required `new_heading`;
- optional `body`;
- optional flat `child_1_heading` and `child_1_body`;
- optional flat `child_2_heading` and `child_2_body`.

The description says to use child slots for requested subsections and never put subsection headings in `body`. The model does not see or emit the file path, anchor, ordinal, or position.

After the model responds, the host injects `path`, `section`, and `position` from the task's first ideal call, converts populated child slots into the core's structured `children` array, and executes one `section-insert`. Missing child headings do not create children; a body without its corresponding child heading refuses before execution. The composed operation is recorded separately from the raw emitted call.

There is no retry, outline-read turn, correction turn, second mutation, or fuzzy matching. A malformed or refused composition writes nothing.

## Endpoints and decision rule

Primary endpoint: paired exact correctness across the 12 insertion pairs, with transitions and exact two-sided McNemar reported.

Safety endpoints: `wrong`, either collateral class, and `destructive`. The treatment clears the gate only if all are true:

1. at least 8/12 pairs are exactly correct;
2. at least two of the three multi-section task types produce a correct result in two or more seeds;
3. no treatment pair is destructive or collateral;
4. every refusal leaves the fixture byte-identical.

A passing result supports building a real structural router with exact handles. It does not authorize hard-coding benchmark anchors or changing the default profile.

## Artifacts and stopping

Write raw and graded rows to `bench/results/minicpm5_section_slots_20260921{,_graded}.jsonl` and paired analysis to `bench/results/minicpm5_section_slots_analysis_20260921.json`. Record control, task, schema, harness, and artifact hashes plus all host-injected arguments.

Run each fixed pair once. Resume only transport errors under the existing last-row rule. Do not add seeds or change the schema, composition logic, or threshold after seeing outcomes. Restore Gemma after collection.
