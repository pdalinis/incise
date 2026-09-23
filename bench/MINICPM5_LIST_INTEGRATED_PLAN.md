# MiniCPM5 integrated routed-list experiment

Recorded 2026-09-22 before implementing the treatment or inspecting any treatment outcome.

## Question

Component experiments addressed every failure in the 13/21 MiniCPM routed-list arm: required structured list addresses reached 6/6 on the two selection-sensitive tasks, while request-shaped exact item fields reached 6/6 on the two placement-sensitive tasks. These results came from separate samples and cannot be added into a product claim.

This experiment measures the components together over the full 21-pair supported list population.

## Population and control

Use all three seeds for the seven routed add-item tasks:

- `add-item-tight-dash`
- `add-item-nested-asterisk`
- `add-item-loose`
- `add-item-ordered-renumber`
- `add-item-ordered-all-ones`
- `add-item-paren-delimiter`
- `add-item-mixed-markers`

Keep fixtures, instructions, summaries, system prompt, MiniCPM5 Q8_0, temperature 0.7, and top-p 0.95 unchanged.

The recorded generic routed-list arm is the paired control at 13/21 correct. It is not resampled.

## Treatment

### Phase 1: exact structured address

Expose and force `list_select` with separately required `heading` and `ordinal`, dynamically constrained from `list_lists`. Validate the pair against an actual list. Missing, invented, or cross-paired addresses refuse without writing.

After selection, the host reads that list and returns the existing `list_get` rendering to the model. This is an automatic consequence of the validated selection, not another model choice.

### Host-owned request-shape routing

Classify the fixed request text deterministically before sampling phase 2:

- contains both standalone `insert` and `between` -> between route;
- otherwise contains `immediately after` -> after route;
- otherwise -> append route.

Record the route for every task. The classifier must produce between only for `add-item-ordered-renumber`, after only for `add-item-nested-asterisk`, and append for the other five tasks. This is a deliberately narrow integration contract for the measured request population, not a general natural-language parser.

### Phase 2: required mutation content

Expose and force exactly one tool:

- append: `list_append_item`, requiring only `text`;
- after: `list_insert_after`, requiring `text` and exact returned `after` item;
- between: `list_insert_between`, requiring `text` plus exact returned `after` and `before` items.

File and list addressing are host-owned. Between boundaries must be adjacent, ordered structural siblings. Every relative anchor must be exact returned item text. Execute one canonical `list_add_item` and stop. A malformed or invalid call writes nothing.

## Endpoints and gate

Primary endpoint: exact final-document correctness across 21 paired trials.

The integrated treatment clears the adoption gate only if all are true:

1. at least 19/21 final documents are correct;
2. every task is correct in at least two seeds;
3. no generic-control correct pair regresses;
4. no outcome is destructive or collateral;
5. every refusal leaves the fixture byte-identical;
6. all 21 deterministic request-shape routes match the preregistered task mapping;
7. every executed list address and relative anchor came from validated current-document structure.

A pass supports implementing this pipeline behind an opt-in MiniCPM list profile, followed by integration tests and a full cross-family remeasurement. A failure remains evaluation evidence and must be localized to address selection, routing, content, anchor selection, or execution.

## Artifacts and stopping

Write raw and graded rows to `bench/results/minicpm5_list_integrated_20260922{,_graded}.jsonl` and analysis to `bench/results/minicpm5_list_integrated_analysis_20260922.json`. Preserve address options, selected address, host route, returned items, phase calls, validation results, composed operation, hashes, model identity, token splits, and latency.

Run each fixed pair once. Resume only transport failures. Do not change routing phrases, schemas, descriptions, validation, thresholds, or seeds after seeing outcomes. Restore Gemma after collection.
