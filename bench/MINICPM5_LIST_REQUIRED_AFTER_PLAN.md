# MiniCPM5 required exact-list-anchor experiment

Recorded 2026-09-22 before implementing the treatment or inspecting any treatment outcome.

## Question

In the routed MiniCPM list arm, all six trials for `add-item-nested-asterisk` and `add-item-ordered-renumber` inspected the correct list and received its exact item texts. None produced the correct edit: five omitted `after`, while one copied the displayed index as `after: "[1]"` instead of copying the item text.

This experiment asks whether a host can turn a successful `list_get` into a small required-slot edit schema whose `after` field is constrained to actual item text.

## Population and control

Use the same six `(task_id, trial)` pairs for those two tasks, with the same fixtures, task wording, prompts, three seeds, MiniCPM5 Q8_0, temperature 0.7, and top-p 0.95.

The recorded routed list arm is the paired control at 0/6 correct. It is not resampled.

## Treatment

Phase 1 is unchanged from the routed arm: expose and force only `list_get`, using the existing schema and existing rendered response.

After a successful read, the host constructs and forces `list_insert_after`:

- publish only `text` and `after`;
- require both fields;
- make `after` a dynamic enum containing every exact item text returned by that `list_get`;
- describe `after` as the existing item after which the new item belongs, copied verbatim from the enum;
- keep the file path and list address out of the model-facing schema.

The host injects the exact file path and the list address from the successful read call, combines them with the model content, and executes one canonical `list_add_item`. If `after` is absent, not a string, or not one of the returned item texts, refuse without writing. Success is terminal. There is no retry, fuzzy match, index interpretation, or post-success model turn.

This treatment assumes an upstream router has already identified a request that requires insertion relative to an existing item. It measures the content-and-anchor micro-schema, not that router.

## Endpoints and gate

Primary endpoint: exact final-document correctness, paired against the recorded routed results.

The treatment clears the gate only if all are true:

1. at least 5/6 final documents are correct;
2. each task is correct in at least two seeds;
3. no correct control result regresses;
4. no outcome is destructive or collateral;
5. every refusal leaves the fixture byte-identical;
6. every executed `after` value came from the immediately preceding `list_get` result.

A pass supports a host-routed `list_insert_after` micro-schema for MiniCPM. A failure should be attributed to read selection, new item text, exact anchor selection, or execution before further schema changes.

## Artifacts and stopping

Write raw and graded rows to `bench/results/minicpm5_list_required_after_20260922{,_graded}.jsonl` and analysis to `bench/results/minicpm5_list_required_after_analysis_20260922.json`. Preserve both phase calls, the returned item enum, composed operation, model identity, token/latency splits, and input/schema hashes.

Run each fixed pair once. Resume only transport errors. Do not change the schema, renderer, thresholds, or seeds after seeing outcomes. Restore Gemma after collection.
