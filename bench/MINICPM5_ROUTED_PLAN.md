# MiniCPM5 routed single-mutation experiment

Recorded 2026-09-21 before implementing the treatment harness or inspecting any treatment outcome.

## Question

The broad `safe-small` composition did not improve MiniCPM5 overall, but its raw calls implicated orchestration rather than Markdown execution: the model selected unrelated tools, continued after successful writes, copied frontmatter type wrappers into scalar arguments, and occasionally generated thousands of tokens on unsupported actions.

This experiment asks whether a task-aware host can recover reliability by removing those decisions from the model. It measures a routing ceiling, not an end-to-end intent classifier: the harness receives the benchmark task family and requested action and is assumed to classify both perfectly.

## Control

Reuse the 90 primary `(task_id, trial)` pairs from the committed-roadmap run's `compose_5` pools:

- 15 table add/update pairs;
- 21 list-add pairs;
- 27 section insert/append pairs;
- 27 frontmatter-set pairs.

The control used three seeds, up to four turns, temperature 0.7, top-p 0.95, the five-tool measured composition, and the existing Arm B executor and grader. Reusing it preserves exact pairing and avoids re-spending model time on an unchanged condition.

## Treatment

Use the same model endpoint, prompts, task summaries, task fixtures, seeds, executor, and grader. Change only orchestration and the tool surface:

- **Tables:** expose and force exactly `table_add_row` or `table_update_cell`, selected from the requested action. No read turn; the existing task summary already contains table addresses and columns.
- **Lists:** first expose and force only `list_get`; return its exact items; then expose and force only `list_add_item`.
- **Sections:** expose and force exactly `section_insert` or `section_append`, selected from the requested action. No read turn; the initial prompt already contains the document outline.
- **Frontmatter:** first expose and force only `frontmatter_get`; then expose and force exactly one evaluation-only typed setter—string, integer, boolean, or null—selected from the requested value's type. Typed setters normalize to the existing `frontmatter-set` operation and accept no object value.

Each phase uses OpenAI-compatible forced function choice. A read refusal ends the trial. A mutation refusal or no-op ends the trial. The first successful mutation with `changed=true` ends the trial immediately; no success result is returned to the model and no verification or correction turn is sampled. There is therefore at most one executed mutation per trial.

The treatment retains temperature 0.7 and top-p 0.95 to isolate routing and stopping. Token caps, lower temperature, section handles, and compatibility normalization for typed wrappers are not part of this arm.

## Endpoints and decision rule

Primary endpoint: paired exact correctness over all 90 supported-operation pairs, with exact two-sided McNemar reported pooled and by family.

Safety endpoints: `wrong`, either collateral class, and `destructive`. Efficiency endpoints: completion tokens, elapsed time, tool-call count, and runaway generations above 1,000 tokens.

The treatment clears the gate only if all are true:

1. pooled exact correctness is significantly better at alpha 0.05;
2. no family loses more than one correct pair;
3. no treatment trial is destructive;
4. silent corruption does not increase in any family.

If the pooled gate fails but one family has a significant gain with no safety regression, that family may justify a separately named follow-up profile. No result from this three-seed routing ceiling changes the default product profile by itself.

## Artifacts and stopping

Raw and graded treatment pools use `bench/results/minicpm5_routed_{tables,lists,sections,frontmatter}_20260921{,_graded}.jsonl`. The analysis file records exact paired counts, input hashes, tool schemas, model identity, and artifact hashes.

Run each fixed treatment pair once. Resume only rows marked as transport errors by the existing harness rule; do not add seeds or change schemas in response to outcomes. Preserve invalid instrument attempts under new suffixes rather than overwriting them. Restore the previously running Gemma model after collection.
