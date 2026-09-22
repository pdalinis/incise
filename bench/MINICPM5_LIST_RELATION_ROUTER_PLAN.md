# MiniCPM5 list-relation router experiment

Recorded 2026-09-22 before implementing the treatment or inspecting any treatment outcome.

## Question

With oracle request-shape routing, MiniCPM scored 3/3 on explicit "after X" insertion and 3/3 on explicit "between A and B" insertion. Production still needs to choose which validated micro-schema applies.

This experiment asks whether MiniCPM can select between those two action-specific tools after seeing the existing list items.

## Population and references

Use the same six `(task_id, trial)` pairs from `add-item-nested-asterisk` and `add-item-ordered-renumber`, with the same fixtures, instructions, prompt, three seeds, MiniCPM5 Q8_0, temperature 0.7, and top-p 0.95.

Two recorded references are not resampled:

- generic routed `list_add_item`: 0/6 correct;
- oracle request-shape ceiling, combining the required-after treatment for the explicit-after task and exact-boundaries treatment for the between task: 6/6 correct.

## Treatment

Phase 1 remains the same forced `list_get` with the existing schema and rendered response.

After a successful read, expose both previously measured dynamic tools in one turn:

- `list_insert_after`, requiring `text` and one exact returned `after` item;
- `list_insert_between`, requiring `text`, exact returned `after` and `before` items.

Use automatic tool choice so MiniCPM must select the request shape. Tool descriptions state:

- use `list_insert_after` only when the request says the new item belongs after one named existing item;
- use `list_insert_between` only when the request names both surrounding items.

The host applies the same validations as the ceiling arms. File and list addressing come from the successful read. Between boundaries must be adjacent, ordered structural siblings. Every selected anchor must be exact returned item text. A missing, unknown, or invalid call refuses without writing. Success is terminal.

## Endpoints and gate

Co-primary endpoints:

1. correct relation-tool selection across six pairs;
2. exact final-document correctness across six pairs.

Report paired final correctness against both references. The treatment clears the gate only if all are true:

1. at least 5/6 relation choices are correct;
2. at least 5/6 final documents are correct;
3. each task is finally correct in at least two seeds;
4. no outcome is destructive or collateral;
5. every refusal leaves the fixture byte-identical;
6. every executed anchor or boundary was returned by the immediately preceding read and passed its existing validation.

A pass supports implementing these two tools in an opt-in MiniCPM adapter route. A failure means relation selection must be host-derived rather than delegated to MiniCPM.

## Artifacts and stopping

Write raw and graded rows to `bench/results/minicpm5_list_relation_router_20260922{,_graded}.jsonl` and analysis to `bench/results/minicpm5_list_relation_router_analysis_20260922.json`. Preserve both phase calls, expected and selected relation, returned items, validation result, composed operation, hashes, model identity, tokens, and latency.

Run each fixed pair once. Resume only transport failures. Do not change tool names, descriptions, validation, thresholds, or seeds after seeing outcomes. Restore Gemma after collection.
