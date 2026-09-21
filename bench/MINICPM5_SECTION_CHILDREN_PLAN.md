# MiniCPM5 atomic section-children experiment

Recorded 2026-09-21 before changing the routed section schema or inspecting any treatment outcome.

## Question

The routed MiniCPM5 arm scored 9/27 on sections but 0/12 on the four insertion tasks. Nine of those pairs require a new section with one or two subsections. The current routed schema exposes only `body`, so MiniCPM places subsection names into prose; the executor correctly refuses headings or writes literal text. Incise already supports a structured `children` payload that derives heading levels and applies the whole subtree in one mutation.

This experiment asks whether exposing that existing atomic payload improves section insertion while retaining terminal one-mutation execution. It does not alter the measured default or Gemma tool schemas.

## Control

Reuse the 12 `(task_id, trial)` pairs for `insert-release-at-top`, `insert-subsection-last`, `insert-nested-ratelimits`, and `insert-troubleshooting` from `bench/results/minicpm5_routed_sections_20260921.jsonl` and its graded pool. The control is 0/12 correct: seven `op_error` and five `wrong`.

## Treatment

Use the same MiniCPM5 checkpoint, endpoint, prompts, fixtures, three seeds, temperature 0.7, top-p 0.95, forced `section_insert` choice, executor, grader, and terminal-after-first-mutation rule.

Change only the evaluation-only `section_insert` schema:

- retain `path`, `parent`, `position`, `new_heading`, and optional `body`;
- add optional `children`, an array of objects with required `heading`, optional `body`, and optional recursively structured `children`;
- state that requested subsections belong in `children`, never as heading-like text in `body`;
- keep the operation atomic: a malformed child refuses the entire call and writes nothing.

The host still selects and forces the action-specific tool. No outline read, retry, correction turn, fuzzy matching, or second mutation is added.

## Endpoints and decision rule

Primary endpoint: paired exact correctness across the 12 insertion pairs, with outcome transitions and exact two-sided McNemar reported.

Safety endpoints: `wrong`, either collateral class, and `destructive`. The treatment clears the gate only if all are true:

1. at least 4/12 insertion pairs are exactly correct;
2. no treatment pair is destructive or collateral;
3. the single-subsection task does not gain a new destructive or collateral outcome;
4. every refusal leaves the fixture byte-identical.

The threshold is deliberately absolute because the control has no correct pair and a significance-only rule would be uninformative at this sample size. A passing result justifies keeping structured children in a future MiniCPM-routed profile; it does not alter the default profile.

## Artifacts and stopping

Write raw and graded treatment rows to `bench/results/minicpm5_section_children_20260921{,_graded}.jsonl` and paired analysis to `bench/results/minicpm5_section_children_analysis_20260921.json`. Record source and schema hashes, model identity, outcome transitions, and gate fields.

Run each of the 12 fixed pairs once. Resume only transport errors under the existing last-row rule. Do not add seeds or revise the schema after seeing outcomes. Restore Gemma after collection.
