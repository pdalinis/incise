# MiniCPM5 exact list-boundaries experiment

Recorded 2026-09-22 before implementing the treatment or inspecting any treatment outcome.

## Question

The required exact-`after` arm improved six list pairs from 0/6 to 4/6. All three explicit "after beta-two" requests became correct. On the three "between second and third" requests, MiniCPM chose `after: "third"` twice and `after: "second"` once. Every value was real; the remaining error was collapsing two named boundaries into the wrong single boundary.

This experiment asks whether a request-shaped tool requiring both exact boundaries removes that translation.

## Population and control

Use the three `add-item-ordered-renumber` pairs with the same fixture, request, outline, seeds, prompt, MiniCPM5 Q8_0, temperature 0.7, and top-p 0.95.

The recorded required-`after` arm is the paired control at 1/3 correct. It is not resampled.

## Treatment

Phase 1 remains the same forced `list_get` with the same rendered response.

After a successful read, expose and force only `list_insert_between`:

- `text`: required new item text;
- `after`: required exact existing item that the new item follows;
- `before`: required exact existing item that the new item precedes;
- both boundary fields use the exact returned item texts as dynamic enums;
- the description says to copy the two boundary names in request order.

The host injects file and list addressing. Before execution it requires that `after` and `before` identify adjacent returned items with the same depth and parent. It then executes the existing canonical `list_add_item` with the validated `after` boundary. Missing, invented, reversed, non-adjacent, or structurally different boundaries refuse without writing. Success is terminal.

This treatment assumes an upstream router identified an explicit between-request. It does not change the executor contract or reinterpret generic `after` calls.

## Endpoints and gate

Primary endpoint: exact final-document correctness, paired against the recorded required-`after` result.

The treatment clears the gate only if all are true:

1. 3/3 final documents are correct;
2. no control-correct pair regresses;
3. no outcome is destructive or collateral;
4. every refusal leaves the fixture byte-identical;
5. every executed boundary pair came from the read result and passed adjacency, depth, and parent validation.

A pass supports separate host-routed after and between micro-schemas. A failure ends list-position schema tuning for this request shape.

## Artifacts and stopping

Write raw and graded rows to `bench/results/minicpm5_list_between_20260922{,_graded}.jsonl` and analysis to `bench/results/minicpm5_list_between_analysis_20260922.json`. Preserve phase calls, returned items, both selected boundaries, composed operation, hashes, model identity, tokens, and latency.

Run each fixed pair once. Resume only transport failures. Do not change fields, descriptions, validation, thresholds, or seeds after seeing outcomes. Restore Gemma after collection.
