# MiniCPM5 compatibility-roadmap live plan

Recorded 2026-09-21 before inspecting any outcome from the runs named below.

## Question

Two model-facing changes need live evidence: the executor now accepts a singleton object array for `table-add-row`, and the optional `safe-small` composition exposes narrow edit tools plus structural reads. The subtree-delete confirmation and structured repair payloads are safety and recovery changes within the same roadmap.

This plan does not reconsider historical result pools. It creates new, named pools and leaves every earlier file unchanged.

## Fixed environment

- Model: the local `minicpm5-2b-q8` alias, backed by the installed official MiniCPM5 2B Q8_0 GGUF.
- Endpoint: `http://127.0.0.1:8081/v1/chat/completions`.
- Runtime and decoding: the endpoint's installed llama.cpp configuration; temperature 0.7 and top-p 0.95 as supplied by `bench/runner.py`.
- Executor: the working-tree `target/debug/incise`, whose source and binary hashes will be recorded with the run artifacts.
- Seeds: integer trial indices beginning at 0. Control and treatment use identical `(task_id, trial)` pairs.
- Grader: the existing `grade.check_result` path used by Arms B and C.

## Run 1: singleton-object executor confirmation

Run Arm C over `bench/tasks/tables.json`, `scheme_f`, three trials, one turn, and the real debug binary. This is 18 calls and preserves the table condition in which the reported MiniCPM behavior was observed.

Primary population: the 12 `table-add-row` pairs. Primary endpoints are exact correctness and the outcome of every emitted `values: [{...}]` call. Safety endpoints are silent corruption, collateral loss, and destructive change. The compatibility behavior passes this gate if at least 11 of 12 add-row pairs are correct, every syntactically valid singleton-object call executes as its named-row equivalent, and all three safety counts are zero. The six update/delete pairs are reported as a regression check, not folded into that gate.

Pools: `bench/results/minicpm5_roadmap_table_20260921.jsonl` and its `_graded` sibling.

## Run 2: safe-small paired composition

Run Arm B at four turns for both `compose_5` and `safe_small`, three trials each, over the existing table, list, section, and frontmatter task files. `safe_small` is loaded from the candidate binary with `INCISE_BENCH_SAFE_SMALL=1`; the control remains the recorded five-tool composition. Arm B is used because its table/list success result is consistent across multi-turn calls, while Arm C deliberately refuses that comparison.

The primary population contains only operations that the candidate intentionally publishes:

- tables: the four add-row tasks and `update-cell-multi-table`;
- lists: the seven `list-add-item` tasks;
- sections: the four `section-insert` and five `section-append` tasks;
- frontmatter: the nine `frontmatter-set` tasks.

That yields 30 tasks, 90 paired observations. The remaining task rows may be sampled to keep source task files intact, but are capability-negative controls and are excluded from the primary endpoint before grading.

Primary endpoint: paired exact correctness, pooled and by family. Safety endpoints: `wrong`, either collateral class, and `destructive`. Secondary endpoints: structural-read use, inspect-then-edit completion, tool-call count, completion tokens, refusal/recovery paths, and the frequency of singleton-object normalization.

The profile remains opt-in regardless of this small-model-only run. It is eligible for broader measurement if pooled correctness is not significantly worse by exact paired McNemar at alpha 0.05, no family loses more than one of its paired observations, and treatment adds no silent-corruption or data-loss event. Improvement is reported only if the paired direction and confidence interval support it; otherwise the result is neutral or inconclusive rather than rounded into a win.

Pools use the prefix `bench/results/minicpm5_roadmap_{tables,lists,sections,frontmatter}_{compose_5,safe_small}_20260921` and retain raw and graded forms.

## Run 3: deletion guard and repair observations

Within the section composition rows, report `delete-install-macos` separately for the `compose_5` control. The executor must refuse deletion of a parent with descendants unless the call explicitly carries `subtree: true`. Record whether MiniCPM repairs the call, stops, or attempts a broader deletion. Because there are only three paired seeds and `safe_small` intentionally has no delete tool, this is a diagnostic rather than an effectiveness gate.

Structured repair is similarly diagnostic in this run: count only repair paths naturally reached by the model. Adapter unit tests remain the evidence that the machine-readable payload is preserved. A dedicated live recovery A/B requires a separate preregistration that fixes the host framing and a refusal-prefix pool.

## Stopping and reporting

Each command runs its fixed trial count once. Transport errors are retried only through the harness's existing resume rule and remain in the raw pool. Do not add seeds in response to observed outcomes. Report model identity, timestamps, task and schema hashes, executor hash, raw/graded file hashes, full outcome counts, excluded negative-control rows, and any transport exclusions. Restore the previously running Gemma model after collection.
