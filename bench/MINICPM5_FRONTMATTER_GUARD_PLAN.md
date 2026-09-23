# MiniCPM5 frontmatter existence-guard replay

Recorded 2026-09-21 before implementing the guard or inspecting any guarded replay outcome.

## Question

The routed MiniCPM5 arm improved pooled correctness from 40/90 to 54/90, but failed its safety gate because two `add-build-cache` calls overwrote the existing `build.target` leaf. Both calls were made for a create intent. This replay asks whether a host-supplied create/update precondition converts that failure class into a loud refusal without changing any previously correct edit.

This is an executor replay over stored calls. It does not measure how showing new tool names or schema fields changes model choice; that requires targeted live remeasurement later.

## Control

Use the 27 primary rows in `bench/results/minicpm5_routed_frontmatter_20260921.jsonl`, taking the last non-transport row for each `(task_id, trial)` exactly as the routed analysis does. Preserve its existing graded outcomes as the control.

## Treatment

Add optional `must_absent` and `must_exist` preconditions to `frontmatter-set`. Calls carrying neither retain the current behavior and refusal bytes. Supplying both refuses without writing.

Replay the routed mutation call with a host-owned precondition derived from the benchmark request's known intent:

- create intent (`add-build-cache`, `create-on-absent`, `fill-empty`) adds `must_absent: true`;
- update intent (`set-build-jobs`, `set-build-target`, `set-dana-role`, `clear-title`, `set-draft-true`, and the executed first mutation of `release-bump`) adds `must_exist: true`.

The model does not choose or emit these flags. The host adds them after routing and before execution. Reads, keys, values, fixtures, model outputs, and grader remain fixed.

For an existing addressed path with `must_absent`, refuse and leave the document byte-identical. For an absent addressed path with `must_exist`, refuse and leave it byte-identical. The refusal must identify the path and the violated existence condition. Normal `frontmatter-set` validation and preservation rules still apply after the precondition.

## Decision rule

The guard clears this replay gate only if all are true:

1. both previously destructive treatment calls become loud refusals with byte-identical documents;
2. every previously correct treatment row remains correct and byte-identical to its prior result;
3. no treatment outcome becomes destructive or collateral;
4. unguarded `frontmatter-set` calls and the measured default schemas remain byte-identical;
5. Rust and Python implementations agree across the differential suite.

The replay may justify implementing the guard in the routed harness and future MiniCPM adapters. It cannot make the earlier routed treatment pass retroactively, and it does not authorize publishing a changed model-facing profile without targeted live remeasurement.

## Artifacts and stopping

Write the replay to `bench/results/minicpm5_frontmatter_guard_replay_20260921.jsonl` and its summary to `bench/results/minicpm5_frontmatter_guard_analysis_20260921.json`. Record source hashes, outcome transitions, byte-identity checks, and the implementation commit or worktree hash.

Replay every fixed primary pair once. Do not resample the model, change task classification in response to outcomes, or overwrite the routed source pool.
