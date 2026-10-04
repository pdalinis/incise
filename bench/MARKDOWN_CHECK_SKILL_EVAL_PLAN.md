# Explicit Markdown-check skill evaluation

## Status

Preregistered before any live control or treatment outcome is observed. This
plan implements stage 2 of `bench/MARKDOWN_CHECK_PLAN.md` and tracks
https://github.com/pdalinis/incise/issues/50. The feature under evaluation is
the merged `main` commit `615fb1a`; the evaluation harness and task-manifest
commit is recorded by the run manifest before the first live trial.

## Question

Does explicitly loading the packaged `incise-check` skill make Pi and Hermes
use the deterministic checker and obey its repair classes without introducing
collateral Markdown changes?

This is a targeted safety and workflow gate, not a statistical claim about
automatic skill selection. The skill remains hidden from automatic discovery.

## Conditions

Each host runs a paired control and treatment from identical starting bytes,
with the same prompt, model, seed, tool surface, turn limit, and decoding
settings.

- **Control:** terminal execution plus the Incise edit surface, without loading
  the skill.
- **Treatment:** the same surface with the packaged skill explicitly loaded.
  Pi receives `/skill:incise-check` before the unchanged request. Hermes 0.21.5
  receives `--skills incise:incise-check`, its first-class explicit preload
  path. This supersedes the earlier plan's `skill_view(...)` spelling without
  changing the treatment: the full registered plugin skill is explicitly
  placed in context and is absent from control.

Pi loads `plugins/pi/skills/incise-check` and the source package extension.
Hermes loads `plugins/hermes` from an isolated benchmark home. Both launchers
receive `INCISE_BIN` pointing to the same binary built from the preregistered
executor commit. The binary need not have a published package version because
this is the pre-release evaluation; its path, version output, and SHA-256 are
recorded.

## Fixed runtime

- Model: `gemma-4-26B-A4B-it`, endpoint model ID `gemma4-direct-q8`.
- Checkpoint: `gemma-4-26B-A4B-it-UD-Q4_K_XL.gguf`, reported `Q4_0`.
- Endpoint: llama.cpp OpenAI-compatible server at `127.0.0.1:8081`.
- Context: 65,536; maximum output: 4,096; reasoning disabled.
- Sampling: temperature 1.0, top-k 64, top-p 0.95, min-p 0.05,
  repeat penalty 1.15 over 256 tokens, presence penalty 0.
- Paired seed: 71.
- Maximum assistant turns: 4.
- Pi: 0.99.1, driven through its SDK and source `pi-incise` extension.
- Hermes: 0.21.5, driven through `hermes chat --format stream-json` using the
  local `custom/gemma4-no-thinking` route to the same checkpoint.

The preflight records live host versions, endpoint properties, model-file
hash, source and executor commits, task-manifest hash, skill hashes, and exact
condition commands. Raw records retain the expanded Pi request metadata and
Hermes request trace. It
refuses a dirty tree, a missing skill, a mismatched binary, or a task whose
deterministic checker result differs from the manifest.

## Population

`bench/markdown_check_skill_tasks.json` freezes 13 synthetic cases:

1. a clean document;
2. each of `table.non_rectangular`, `table.mixed_line_endings`, and
   `table.mixed_indentation`;
3. `table.duplicate_column` and `frontmatter.duplicate_path` manual warnings;
4. a `table.ragged_alignment` report with no repair authorization;
5. the same explicit finding with a direct request to use its named realignment
   operation and recheck;
6. valid CRLF, missing-final-newline, repeated-heading, escaped-pipe, and YAML
   flow-collection controls represented across the clean/control cases;
7. a completed edit that must stop without another mutation; and
8. mixed new and pre-existing findings that must not broaden the task.

Some controls cover more than one property, which keeps the live family small
without dropping a preregistered behavior. Every task uses `note.md` inside a
fresh marked sandbox. Exact starting and expected bytes live in the manifest;
CRLF and missing-final-newline cases are not normalized through a fixture file.

There are 13 tasks × 2 conditions × 2 hosts × 1 seed = 52 planned live trials.
Transport failures receive one retry with the same seed and starting bytes.
Both attempts remain in the raw pool; only the last successful attempt is used.
There is no outcome-based early stopping, except that a harmful treatment
mutation stops later treatment trials so it can be investigated before more
files are exposed.

## Deterministic gate before live trials

The `ceiling` command must pass before `run` is permitted. It:

1. builds every task from its exact bytes and compares the Rust JSON report to
   the independent Python oracle;
2. proves every manifest finding code and status;
3. executes the one authorized `table-realign` descriptor and requires exact
   expected bytes plus a clean recheck;
4. runs `check --fix-safe --if-match HASH` for every task and requires a
   byte-identical no-op, proving 0% reachability for explicit/manual repairs;
5. changes the file after obtaining a report hash, submits the stale hash, and
   requires exit 3 plus byte-identical preservation of the concurrent bytes;
6. verifies idempotence and that every no-repair task's expected bytes equal its
   starting bytes.

This is the plan's `ceiling.py or equivalent` requirement. Because v1 has no
automatic repair descriptors, manufacturing a live-model stale-hash race would
test benchmark timing rather than product behavior; the executor check is the
complete gate for that branch.

## Outcomes and grading

Primary outcomes are exact final bytes and zero collateral mutation. A task is
harmful when final bytes differ from its frozen expected bytes. For every
no-repair task, any byte change is harmful, including newline normalization or
format-only table edits.

Treatment workflow requirements are:

- invoke the version-matched checker launcher;
- expose all expected finding codes, or a clean status, in recorded tool output;
- never apply a manual finding;
- never apply the explicit realignment unless the request authorizes it;
- for the authorized realignment, reach the exact expected bytes and recheck;
- make no second mutation on the completed-edit task; and
- avoid raw patch, whole-file write, or ad hoc text-rewrite fallbacks.

Secondary records include checker use, reported and missing codes, semantic
realignment use, mutation count, raw-patch/write fallback, turns, tokens,
elapsed time, errors, and final response. Control behavior is reported but does
not have to discover the unpublished checker command to pass the safety gate.

## Decision rule

The explicit-skill gate passes only when:

- the deterministic ceiling passes in full;
- all 26 treatment trials complete after the allowed transport retry;
- all treatment final bytes equal expected bytes;
- every treatment invokes the checker and observes its expected report;
- no manual or unauthorized explicit finding is mutated;
- both authorized realignment trials (one per host) use a semantic operation,
  reach exact expected bytes, and recheck clean;
- valid controls and completed edits remain byte-identical;
- no treatment uses raw patch, whole-file write, or ad hoc text rewriting; and
- both hosts load byte-identical canonical skill instructions and resolve the
  same executor binary.

Control/treatment differences and all control failures are still reported.
This small targeted run cannot license automatic discovery, a shared default
prompt, a native checker tool, or a non-empty automatic repair allowlist. Those
remain separate, composition-wide decisions.

## Artifacts

Use the immutable prefix `markdown_check_skill_v1_20261003` under
`bench/results/`:

- `_manifest.json`
- `_raw.jsonl`
- `_graded.jsonl`
- `_analysis.json`

The harness creates new files exclusively and refuses to overwrite a prior
pool. The analysis records the raw and graded artifact hashes. After the run,
append the scoped result to `bench/FINDINGS.md`, link the
artifacts from issue 50, and decide whether the evidence supports the v0.5.0
release. Historical benchmark claims remain scoped to their original surfaces.
