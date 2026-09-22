# MiniCPM5 exact list-handle experiment

Recorded 2026-09-22 before implementing the treatment or inspecting any treatment outcome.

## Question

After solving placement-sensitive list insertion with exact dynamic item anchors, two routed-list failures remain in the recorded primary population: one call selected an unrelated list, and one selected the right heading but omitted the ordinal distinguishing the star-marker list.

This experiment asks whether a single required dynamic handle containing all existing list metadata can make list selection copyable and unambiguous.

## Population and control

Use the six `(task_id, trial)` pairs from `add-item-loose` and `add-item-mixed-markers`, with unchanged fixtures, summaries, instructions, prompt, seeds, MiniCPM5 Q8_0, temperature 0.7, and top-p 0.95.

The recorded routed list arm is the paired control at 4/6 correct. It is not resampled.

## Treatment

Phase 1 exposes and forces only `list_select`, requiring one `handle` string. The handle enum is built from `list_lists` and contains one entry per actual list, preserving document order. Every handle includes:

- full heading path;
- ordinal;
- ordered or bullet kind;
- exact marker;
- item count;
- nesting level count;
- tight or loose state.

The description instructs the model to choose the one handle matching every constraint in the request. The host maps the exact enum value back to its heading and ordinal. Missing or non-enum handles refuse without writing.

Phase 2 exposes and forces only `list_append_item`, requiring only `text`. File and list addressing are host-owned. The host executes one canonical `list_add_item` at the end of the selected list and stops. This population contains only end-placement requests; the treatment does not generalize to relative insertion.

## Endpoints and gate

Co-primary endpoints:

1. exact list-handle selection;
2. exact final-document correctness.

The treatment clears the gate only if all are true:

1. at least 5/6 handles are correct;
2. at least 5/6 final documents are correct;
3. each task is finally correct in at least two seeds;
4. no control-correct pair regresses;
5. no outcome is destructive or collateral;
6. every refusal leaves the fixture byte-identical;
7. every executed list address came from the selected dynamic handle.

A pass supports dynamic exact list handles in an opt-in MiniCPM adapter. A failure means list selection must remain host-derived or use a stronger model.

## Artifacts and stopping

Write raw and graded rows to `bench/results/minicpm5_list_handle_20260922{,_graded}.jsonl` and analysis to `bench/results/minicpm5_list_handle_analysis_20260922.json`. Preserve the handle enum, expected and selected handles, both calls, composed operation, hashes, model identity, tokens, and latency.

Run each fixed pair once. Resume only transport failures. Do not change handle formatting, descriptions, validation, thresholds, or seeds after seeing outcomes. Restore Gemma after collection.
