# Benchmark result index

This directory preserves raw model trials, derived grades, controls, replays, and snapshots used by the Incise benchmark record. Result files are evidence artifacts: keep prior runs immutable and add new evidence beside them.

## Authority and scope

This index is a map, not a second interpretation of the experiments. [`../FINDINGS.md`](../FINDINGS.md) is the authority for scores, statistical comparisons, caveats, adopted decisions, and conclusions that were later reversed. [`../PLAN.md`](../PLAN.md) records experiment design and chronology.

A filename is not proof that a condition ships. Read the finding that cites a pool before quoting it. Some files are controls, counterfactual regrades, or superseded schemes retained so later conclusions remain auditable.

## File conventions

A `.jsonl` file without `_graded` normally contains the model-facing trial record: task, seed or trial number, prompt condition, calls, responses, and run metadata available at the time it was recorded. Its `_graded.jsonl` sibling contains the derived outcome and grader detail keyed by condition or scheme, task, and trial.

A grade is reproducible analysis of a recorded run; it is not a new model trial. Regrading may correct a grader or evaluate an executor-side guard without spending GPU time, but it cannot show how a model would respond to a changed prompt, schema, refusal, or result.

Older pools do not all record turn caps, result shapes, or every provenance field now considered necessary. `FINDINGS.md` calls out those gaps where they affect comparison.

## Direct-edit baselines

The table baseline is [`trials.jsonl`](trials.jsonl) with grades in [`graded.jsonl`](graded.jsonl). It contains the reasoning-off, reasoning-on, and repeat-penalty control conditions behind the first table findings.

The list baseline is [`trials_lists.jsonl`](trials_lists.jsonl) with grades in [`graded_lists.jsonl`](graded_lists.jsonl).

The section baseline is [`arma_sections.jsonl`](arma_sections.jsonl) with grades in [`arma_sections_graded.jsonl`](arma_sections_graded.jsonl). These are Arm A raw-edit conditions, not Incise operation results.

## Adopted single-family interfaces

The table Arm B pool is [`armb.jsonl`](armb.jsonl) with [`armb_graded.jsonl`](armb_graded.jsonl). It contains multiple table schemes; `scheme_f` is the adopted interface, so aggregate rows across every scheme are not a shipping score.

The list pool is [`armb_lists.jsonl`](armb_lists.jsonl) with [`armb_lists_graded.jsonl`](armb_lists_graded.jsonl). `list_g` is the adopted list interface.

The adopted section-address condition is [`armb_s15_section_g_hpath.jsonl`](armb_s15_section_g_hpath.jsonl) with [`armb_s15_section_g_hpath_graded.jsonl`](armb_s15_section_g_hpath_graded.jsonl). Later section experiments compare against this pool; read S15, S16, F-compose, and subsequent section findings before treating a later variant as adopted.

The adopted frontmatter pool is [`armb_front_p_v3.jsonl`](armb_front_p_v3.jsonl) with [`armb_front_p_v3_graded.jsonl`](armb_front_p_v3_graded.jsonl).

The adopted table-read pool is [`armb_read_g.jsonl`](armb_read_g.jsonl) with [`armb_read_g_graded.jsonl`](armb_read_g_graded.jsonl). The `armb_read_naive` pair is its comparison condition.

## Real-binary and framing runs

Arm C executes recorded tasks through the compiled CLI against real temporary files rather than the Arm B mock. The primary family pools are [`armc_tables.jsonl`](armc_tables.jsonl), [`armc_lists.jsonl`](armc_lists.jsonl), and [`armc_sections.jsonl`](armc_sections.jsonl), each with a graded sibling.

The `armc_framing_*` pairs measure host result framing. The `armc_replay_path*` and `armc_ordinal*` pairs are targeted replays of specific addressing or recovery questions. They are not broader replacements for the family pools.

## Tool-composition runs

The composition experiment is split by family so each JSONL remains manageable. Files beginning with `compose_solo_` contain the adopted tool for the task family in isolation. `compose_3_`, `compose_4_`, and `compose_5_` contain successively wider published tool sets, with raw and graded files for each included family.

F-compose in `FINDINGS.md` is essential context. The pre-registered one-tool-versus-five comparison and the post-hoc three-tool-versus-five comparison answer different questions; neither should be quoted as the other. `anchor_control_compose_5.jsonl` is a control artifact, not a headline outcome pool.

## Retries, replays, and counterfactual grades

Names containing `retry`, `s6`, `s14`, `s15`, `s16`, `faddress`, or `remedy` belong to targeted investigations documented under the matching finding. Some contain new model turns, some replay a fixed prefix, and some are grader-only counterfactuals. Their method must be read from `FINDINGS.md` before reuse.

Files ending only in `_graded.jsonl` may intentionally have no raw sibling because they regrade an older immutable trial pool under a changed grader or executor guard. Do not infer a missing raw run or regenerate one under the old name.

## Snapshots and logs

[`snapshot_tier2b_base.json`](snapshot_tier2b_base.json) pins a historical replay baseline. [`reasoning_on.log`](reasoning_on.log) is a diagnostic log from the reasoning condition. Neither is a substitute for the raw JSONL pool it accompanies.

Temporary server logs, model caches, credentials, and local paths do not belong in this directory.

## Adding a result set

Choose a new descriptive run name; never replace a historical raw pool. Store raw trials first and write derived grades to a sibling whose name ends in `_graded.jsonl`. Record the hypothesis, affected population, pairing, endpoint, decision rule, and expected cost before a live run.

Every new live pool should record the model and checkpoint, inference server and version, decoding parameters, seed, prompt and schema identifiers, turn cap, result shape, executor commit, task-set identity, and timestamp. If the harness cannot record one of those fields, document the omission before drawing comparisons.

Add a corresponding section to `FINDINGS.md` that names the exact files, distinguishes pre-registered from exploratory analysis, and states which earlier claims remain current, become narrower, or are superseded.

## Current storage policy

Raw results are kept in Git because they make published claims regradable and auditable without another GPU run. The directory is currently small enough for ordinary Git hosting. If growth makes clones expensive, move closed campaigns to versioned release artifacts with checksums and keep this index plus the grading inputs in the repository; do not silently discard or rewrite the original evidence.
