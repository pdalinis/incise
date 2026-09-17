# Contributing

Thank you for helping improve incise. This project treats file-preservation behavior, agent-facing schemas, and benchmark claims as public interfaces. Contributions should preserve that distinction between deterministic correctness and model-measured behavior.

## Development setup

Use the toolchain and commands exercised by CI. The core crate must remain dependency-free. The CLI and plugins may take dependencies when the tradeoff is justified.

Run the following before submitting a code change:

```bash
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --locked -- -D warnings
cargo test --workspace --locked
python3 bench/test_incise_ops.py
python3 bench/difftest.py
python3 bench/schematest.py
python3 bench/replaycheck.py
python3 plugins/hermes/test_plugin.py
```

`replaycheck.py` is the least obvious of these. The two modules that replay recorded tool calls, `headroom.py` and `regrade_snapshot.py`, decide independently which calls are executable, and for a while both silently skipped every read; it compares the two routes over every recorded call and fails when they disagree about one that is not a listed exception.

The corpus is frozen because published findings refer to its exact bytes. Run experiments on copies or add purpose-built inputs under `bench/synthetic/`. Do not edit anything under `crates/` or `bench/` while `bench/mutate.py` is running.

## Keep changes focused

Open an issue before undertaking a large new operation family, public schema redesign, or benchmark campaign. Small fixes may go directly to a pull request. Explain the user-visible problem, keep unrelated cleanup separate, and add the narrowest test that would have caught the defect.

Preserve user work and repository history. Stage files explicitly; never use `git add -A`. Do not reformat frozen fixtures or regenerate recorded results as incidental cleanup.

## The benchmark contract

This repository contains two kinds of evidence. Deterministic tests establish what the implementation does. Model trials establish how a particular model behaves when shown a particular tool, prompt, result shape, task, and executor. Passing the first kind does not refresh or extend the second kind.

A behavior change includes more than Rust logic. Tool names, argument names, required fields, descriptions, refusal wording, success output, available tool composition, system prompts, retry limits, and result framing can all change model behavior. Treat those surfaces as measured interfaces.

## Classify benchmark impact

Every pull request that touches behavior or benchmarking should state one classification: no model-facing effect; replay or regrade only; targeted live remeasurement required; family-wide live remeasurement required; or composition-wide live remeasurement required.

Use no model-facing effect only when the bytes visible to the model and the executor behavior are unchanged. Replay or regrade is appropriate when stored calls can answer the question without asking the model to choose again. A live rerun is required whenever the change can alter which call the model emits or whether it continues to another turn. Changes to the published tool set or shared framing require composition-level consideration.

## GPU-backed measurements

Do not rerun the full GPU benchmark for every contribution. First establish reach: identify which recorded calls, tasks, refusal branches, or tool combinations can encounter the changed surface. Prefer deterministic tests, recorded-call replay, counterfactual regrading, and ceiling checks when they answer the question.

Before spending GPU time, record the hypothesis, affected population, control and treatment, seeds or pairing, primary endpoint, stopping condition, and decision rule. Commit that plan before inspecting new outcomes. Record the model and checkpoint, inference server and version, decoding parameters, prompt and schema identifiers, executor commit, task-set hash, and run timestamp with the results.

Never silently replace historical result files. Add a new named run, retain the prior evidence, and state which earlier claims are superseded, narrowed, or still valid. If a required live rerun has not happened, label the affected claim unverified rather than carrying the old number forward.

## Changing the core

`crates/incise-core` is one half of a byte-for-byte differential pair with `bench/incise_ops.py` and must not gain dependencies. Update both implementations deliberately, then run the differential suite. Refusal messages are product behavior and must match exactly.

Differential agreement alone is not enough because both implementations can share the same mistake. Add or update a property invariant for preservation, targeting, round trips, or refusal safety when the change affects one of those guarantees. Mutation testing is expected for new logic whose failure would not already be demonstrated by an existing mutation.

## Pull requests

A pull request should explain the problem, the chosen behavior, alternatives considered when relevant, and the tests run. For model-facing changes, include the benchmark-impact classification, the evidence supporting it, and links to any pre-registered plan and new result set. Call out intentionally deferred measurement.

CI must pass on supported platforms. Documentation and examples must describe the shipped names and commands. Contributions are accepted under the repository MIT license.

## Reporting problems

Use a GitHub issue for reproducible bugs, feature proposals, and benchmark-design discussion. Include a minimal input document, the exact command or tool call, expected behavior, actual output, platform, and version or commit. Remove secrets and private document content before posting.

For a vulnerability that could expose or destroy user data, follow [`SECURITY.md`](SECURITY.md) and contact the maintainers privately instead of publishing exploit details in an issue.
