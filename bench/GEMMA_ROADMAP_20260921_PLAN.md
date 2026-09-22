# Gemma structural-accuracy roadmap experiment

Recorded 2026-09-21 before sampling any outcome from these conditions.

## Question

The published Pi 0.1.1 composition run measured Gemma 4 26B at 102/149
(68.5%) on sections, 88/110 (80.0%) on frontmatter, and 47/60 (78.3%)
on table reads. This campaign asks whether four narrowly scoped orchestration
changes recover the concentrated failures without damaging already-correct
pairs.

The candidate tools are evaluation-only. The measured and safe-small schemas,
the production Pi extension, and historical result pools remain unchanged.

## Model and common condition

- Model: the locally served `gemma4-direct-q8` checkpoint.
- Runtime: the existing llama.cpp server at `127.0.0.1:8081`.
- Integration: Pi 0.85.1 and its normal prompt construction.
- Executor: the current checkout's `target/debug/incise` binary.
- Sampling: the server's Gemma defaults, with seed equal to trial index and
  thinking disabled, matching the published Pi harness.
- Fixtures, task wording, grader, and ten seeds come from the frozen benchmark.
- Every trial uses an isolated copied fixture.
- A candidate adapter permits at most one successful operation per trial.

Transport failures may be resumed under the harness's last-row rule. No other
pair is resampled. Raw pools are append-only and use the
`gemma_roadmap_20260921_*` prefix.

## Arm 1: current-checkout Pi baseline

Run all 48 frozen composition tasks at ten seeds through the current Pi
extension with its normal measured profile and three structural discovery
tools: 480 trials total. This refreshes the user-facing condition before any
candidate is interpreted. It is compared descriptively and pairwise with the
published Pi 0.1.1 treatment where both pairs completed, but it does not
retroactively replace that historical result.

This baseline is also the paired control for every targeted arm below.

## Arm 2: host-addressed atomic section insertion

Population: the 40 pairs from `insert-release-at-top`,
`insert-subsection-last`, `insert-nested-ratelimits`, and
`insert-troubleshooting`.

Expose only `section_insert_tree`. The adapter owns the fixture path. Its
`parent` is constrained to exact, uniquely addressable paths from the current
outline. The payload contains the new heading, optional body, and structured
child sections. The adapter converts it to one existing `section-insert` call
with `children`; heading levels are derived by Incise. No subsection may be
encoded as heading markup in `body`.

Gate: at least 32/40 correct, more correct than paired baseline, no destructive
or collateral result, and at most two regressions among baseline-correct pairs.

## Arm 3: literal-target section guards

Population: 20 pairs from `rename-closed-atx` and `replace-linux-body`, the two
published groups with wrong-target destructive outcomes.

The adapter resolves the explicit old target from the request before exposing
the tool. For rename this is the first quoted old heading; for replacement it
is the explicit heading path between `under` and `with`. Resolution must be
unique in the current outline. The model supplies only the new heading or new
body; the adapter supplies path, target, and overwrite acknowledgement.

Gate: at least 18/20 correct, more correct than paired baseline, zero
destructive or collateral outcomes, and no baseline-correct regression.

## Arm 4: typed existing-key frontmatter

Population: 50 pairs from `set-build-jobs`, `set-build-target`,
`set-dana-role`, `clear-title`, and `set-draft-true`.

Before inference the adapter reads flattened frontmatter paths, types, and
values and includes that compact read beside the structural summary. It then
exposes one routed setter whose `key` is an enum of existing scalar leaves and
whose value has the requested type: integer, string, Boolean, or an explicit
clear operation. The adapter owns the path and adds `must_exist: true`.

`add-build-cache` is deliberately excluded: choosing a new leaf name from
"caching" is a different, underdetermined create-key problem. Multi-key
`release-bump` is also excluded from this one-operation arm.

Gate: at least 45/50 correct, more correct than paired baseline, zero
destructive or collateral outcomes, and no baseline-correct regression.

## Arm 5: constrained one-shot table queries

Population: 20 pairs from `get-filter-two-columns` and
`get-filter-no-match`, which account for all 13 published table-read misses.

The adapter resolves the explicitly named table from `md_tables`. It exposes a
single `table_query` whose required properties are exactly the table columns
named in the request: `Priority` plus `Version` for the two-column task and
`Priority` for the no-match task. It performs one `table-get`; a valid empty
result is terminal, and query widening is unavailable.

Gate: at least 18/20 correct, more correct than paired baseline, zero
`unfiltered`, `misreported`, destructive, or collateral outcomes, and no
baseline-correct regression.

## Analysis and stopping

Report per-task outcomes, paired transitions, exact two-sided McNemar where
informative, destructive/collateral counts, transport exclusions, tool-call
counts, tokens, and elapsed time. An arm that misses its gate remains an
evaluation result; its components are not combined post hoc. A passing arm is
eligible for a separate production-profile integration and full Pi
remeasurement, not automatic default adoption.

