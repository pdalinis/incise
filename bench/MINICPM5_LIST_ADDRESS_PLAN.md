# MiniCPM5 required list-address experiment

Recorded 2026-09-22 before implementing the treatment or inspecting any treatment outcome.

## Question

The composite exact-handle arm regressed final correctness to 1/6 because MiniCPM could not reproduce a long serialized enum exactly. Nevertheless, all six raw calls named the semantically correct heading and ordinal. This experiment tests that smaller representation directly.

## Population and references

Use the same six `(task_id, trial)` pairs from `add-item-loose` and `add-item-mixed-markers`, with unchanged fixtures, summaries, instructions, prompt, seeds, MiniCPM5 Q8_0, temperature 0.7, and top-p 0.95.

Recorded references are not resampled:

- generic routed list selection: 4/6 correct;
- composite handle treatment: 1/6 correct.

## Treatment

Phase 1 exposes and forces `list_select`, requiring two ordinary fields:

- `heading`: exact full heading path, constrained to the distinct headings returned by `list_lists`;
- `ordinal`: integer, constrained to the ordinals present in the file.

Both fields are always required. Existing list metadata remains in the user-visible summary rather than being copied into the call. The host validates the `(heading, ordinal)` pair against the actual `list_lists` entries; a cross-paired, missing, or invented address refuses without writing.

Phase 2 is identical to the composite arm: expose and force content-only `list_append_item`, inject the validated file and list address, execute one canonical end insertion, and stop.

## Endpoints and gate

Co-primary endpoints are exact list-address selection and exact final-document correctness.

The treatment clears the gate only if all are true:

1. at least 5/6 addresses are correct;
2. at least 5/6 final documents are correct;
3. each task is finally correct in at least two seeds;
4. no control-correct pair from the generic routed arm regresses;
5. no outcome is destructive or collateral;
6. every refusal leaves the fixture byte-identical;
7. every executed address is an actual `(heading, ordinal)` pair from `list_lists`.

A pass supports required structured list addresses in an opt-in MiniCPM route. A failure ends model-owned list-selection tuning under this architecture.

## Artifacts and stopping

Write raw and graded rows to `bench/results/minicpm5_list_address_20260922{,_graded}.jsonl` and analysis to `bench/results/minicpm5_list_address_analysis_20260922.json`. Preserve address enums, expected and selected addresses, both calls, composed operation, hashes, model identity, tokens, and latency.

Run each fixed pair once. Resume only transport failures. Do not change fields, descriptions, validation, thresholds, or seeds after seeing outcomes. Restore Gemma after collection.
