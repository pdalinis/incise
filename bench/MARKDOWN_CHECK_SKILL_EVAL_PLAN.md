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

Use the immutable prefix `markdown_check_skill_v1_20261003_v3` under
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

The prefix has a `_v3` suffix because the first preflight-only manifest exposed
a sandbox-marker bug before any model request or raw/graded pool was created.
The `_v2` attempt then found the single model slot occupied by an unrelated
seed-1007, 8192-token request before its first result; it was interrupted with
zero-byte raw and graded pools. Both aborted manifests remain immutable. The
`_v3` executor requires an idle endpoint at preflight and immediately before
every trial, and is the first eligible live pool.

## V4 follow-up candidate

The immutable `_v3` pool failed after 21 completed Pi rows. All completed rows preserved their starting bytes, but explicit treatment reached the checker in only 3/8 cases. In the other five, Gemma ignored or lost Pi's absolute skill-wrapper `location`, searched relative to the sandbox, and never ran the launcher. The authorized realignment was omitted rather than applied incorrectly. Hermes did not run because the original grader classified any non-expected final bytes as harmful and triggered its fixed stop.

V4 is a post-failure candidate, not part of the untouched v3 hypothesis. It changes only the shared skill instructions and evaluator classification. The skill now directs the model to copy the wrapper's absolute `location`, remove `/SKILL.md`, append the launcher path, and never search from the working directory. The evaluator classifies byte-identical omission of an authorized required repair as `missed-repair`; `harmful` is reserved for an actual mutation to bytes other than the frozen expectation. Both remain gate failures, but only harmful mutation triggers early stopping.

The task manifest, model, seed, host versions, tool surfaces, deterministic ceiling, treatment requirements, and 52-trial population remain unchanged. V4 uses the immutable prefix `markdown_check_skill_v1_20261003_v4`. It passes only under the existing decision rule: 26/26 complete treatment trials, exact expected bytes, checker and report use, semantic authorized realignment with a clean recheck, no forbidden mutation or fallback, and host agreement. The model endpoint must be idle at preflight and before every trial.

## V5 native checker candidate

V4 failed the existing gate without harmful mutations: Pi treatment invoked the
launcher in 9/13 tasks, and the one attempted Hermes control exposed a
non-equivalent provider route. This is the preregistered post-failure candidate
allowed by the original plan's host-constraint clause. It does not change the
core checker, finding schema, repair allowlist, task population, or automatic
skill discovery.

Both integrations register one read-only `md_check(path)` adapter over
`incise check PATH --json`. The adapter returns the versioned report without
paraphrasing it. It is not added to the core measured schema. Ordinary requests
must have the same ordered provider-visible tool names and schemas as before:
Pi removes the tool from its active set, and Hermes removes it in request
middleware. Tests and preflight compare the ordinary surface byte for byte.

Explicit loading is the only activation signal. Pi recognizes the host-expanded
`<skill name="incise-check" ...>` wrapper in `before_agent_start`. Hermes
recognizes the exact session preload marker emitted by
`--skills incise:incise-check` in provider messages. The first treatment
request exposes only `md_check`, eliminating path rediscovery through terminal
tools. After a successful report, the adapter keeps `md_check` for rechecking
and exposes only the Incise semantic tool implied by repair operations in that
report; for v1, `table-realign` maps to `table_edit`. Manual-only and clean
reports expose no mutation tool. Pi restores the prior active surface when the
agent run ends. Hermes keys report state by session and task and clears it at
session end.

The live population remains 13 tasks × 2 conditions × 2 hosts × seed 71. V5
uses the immutable prefix `markdown_check_skill_v1_20261004_v5`. The existing
decision rule remains in force, plus two preflight requirements: ordinary
provider surfaces are unchanged, and treatment starts with exactly
`md_check`. The deterministic ceiling and host unit tests must pass before
live trials.

Hermes uses a fresh isolated home whose custom provider points directly to
`http://127.0.0.1:8081/v1`, not the user's LiteLLM hop. Preflight warms the
Hermes installation outside measured trials, records the effective provider
configuration hash, and verifies from the first request trace that model, seed
71, maximum output 4,096, and the expected treatment surface reached the direct
endpoint. Any mismatch aborts the pool before grading.

This candidate can license only explicit checker-skill activation. It cannot
license automatic discovery, a default `md_check` tool, a shared prompt,
automatic repairs, or changes to the core published edit schema.

## V6 lazy Pi registration correction

V5 was aborted before recording its first trial. Its provider audit observed the
first Pi control request and refused it because the ordinary tool surface was
`["bash"]`, not the historical `["bash", "table_edit"]`. Both v5 raw and
graded pools are zero bytes and remain immutable. No model output or document
mutation was accepted into the pool.

The cause was registration-time activation, not the native checker schema. Pi
activates a newly registered extension tool, and calling `setActiveTools`
while the resource loader was still constructing the session changed how the
later harness tool selection resolved `table_edit`. V6 registers `md_check`
lazily inside the already-supported `before_agent_start` hook only after the
host-expanded explicit `incise-check` wrapper is present. Ordinary sessions
therefore never register or activate the new tool. Treatment still starts with
exactly `md_check`, and the report-derived repair and end-of-run restoration
rules are unchanged.

V6 adds a real Pi SDK session probe to preflight, in addition to unit tests. The
probe must reproduce the historical ordinary active surface
`["bash", "table_edit"]` before any live request. The provider audit retains
that exact expectation. Hermes, tasks, model, seed, direct endpoint, grader,
decision rule, and 52-trial population are unchanged.

V6 uses the immutable prefix
`markdown_check_skill_v1_20261004_v6`.

## V7 Pi treatment allowlist correction

V6 recorded all 13 Pi control trials, then aborted before accepting the first
treatment trial. The controls reproduced the historical provider surface and
preserved bytes; the authorized-repair control omitted the repair as expected.
The first treatment provider audit saw an empty tool list and refused the
request before its output or bytes were graded.

The cause is specific to the benchmark SDK constructor. Its static `tools`
allowlist is resolved before `before_agent_start`; a tool registered lazily by
that hook remains unavailable unless its name was admitted to the constructor.
Interactive Pi does not impose this two-name benchmark allowlist, and adding
`md_check` to ordinary benchmark sessions would violate the preserved control
surface.

V7 therefore changes only treatment session construction: Pi receives the
historical `["bash", "table_edit"]` allowlist plus `"md_check"`. The explicit
skill hook still narrows the first provider request to exactly
`["md_check"]`; controls retain exactly `["bash", "table_edit"]`. The
provider audit enforces both. Integration code, skill instructions, Hermes,
tasks, model, seed, direct endpoint, grader, decision rule, and population are
unchanged.

V7 uses the immutable prefix
`markdown_check_skill_v1_20261004_v7`. The partial v6 raw and graded pools
remain immutable and are reported as an infrastructure abort, not a candidate
result.

## V8 Hermes control audit correction

V7 completed all 26 Pi trials: all 13 treatment workflows passed, including
semantic realignment and clean recheck, with no harmful mutation. It then
aborted before accepting the first Hermes control because the provider audit's
expected list omitted Hermes's built-in `process_manage` tool and ordered the
standard Incise tools differently.

The observed Hermes control surface was
`["process_manage", "terminal", "table_edit", "list_edit", "section_edit",
"md_tables", "md_lists", "md_outline", "frontmatter_edit", "table_get"]`.
That is byte-for-byte the first Hermes control surface recorded in immutable v4
evidence. The candidate did not add `md_check` to it.

V8 changes only the frozen Hermes control expectation to that historical list.
Treatment must still begin with exactly `["md_check"]`. Product code, session
construction, skill instructions, direct provider route, tasks, model, seed,
grader, decision rule, and 52-trial population are unchanged.

V8 uses the immutable prefix
`markdown_check_skill_v1_20261004_v8`. The partial v7 pools remain immutable
and are reported as an audit-spec abort, while their complete Pi results remain
useful supporting evidence.

## V9 disable unrelated Hermes auto-title traffic

V8 completed the 26 Pi trials and accepted the first Hermes control, which
passed. Before Hermes control trial 2, the idle guard detected a background
request with default seed and 8,192 output tokens. The request was Hermes's
automatic session-title upgrade, not an agent turn: its parameters differed
from the traced agent request, and it cleared shortly afterward.

Waiting for that request would prevent overlap but would still charge unrelated
model work and timing to the Hermes condition. V9 instead sets
`auxiliary.title_generation.enabled: false` and
`model_upgrade_enabled: false` in the isolated benchmark configuration.
This changes no Incise tool, skill, agent prompt, task, or graded output. It
removes an auxiliary product feature unrelated to the checker workflow and
allows the one-slot idle guard to audit only agent traffic.

The direct endpoint, main-request model, seed, token cap, tool surfaces, tasks,
grader, decision rule, and 52-trial population remain unchanged. V9 uses the
immutable prefix `markdown_check_skill_v1_20261004_v9`. The partial v8 pools
remain immutable and are reported as an auxiliary-traffic isolation abort.

## V10 recognize Hermes qualified plugin-skill identity

V9 completed all 26 Pi trials and all 13 Hermes controls. Every Pi treatment workflow passed with no harmful mutation, and the Hermes control surface remained unchanged. The run then aborted at the first Hermes treatment provider audit: the first request exposed the ordinary Hermes tools instead of only `md_check`.

Hermes records the successful preload as `incise:incise-check` and renders that canonical qualified identity in its API-time system prompt. The middleware detector required the unqualified `incise-check` marker, so it did not recognize the real plugin-skill preload. This is an integration-contract mismatch, not a model outcome.

V10 changes only the Hermes exact preload marker to the host canonical value `incise:incise-check`. The host contract adds coverage that the qualified marker activates the checker surface while the unqualified lookalike does not. Pi, the checker, semantic repairs, skill instructions, isolated Hermes configuration, direct endpoint, tasks, model, seed, token cap, grader, decision rule, and 52-trial population remain unchanged.

V10 uses the immutable prefix `markdown_check_skill_v1_20261004_v10`. The 39-row v9 raw and graded pools remain immutable and are reported as an activation-signal audit abort, while their complete Pi and Hermes-control results remain useful supporting evidence.

## V11 pin the Hermes subprocess binary inside its dotenv

The v10 preflight passed. Before opening the 52-trial pool, a host-real Hermes treatment probe confirmed that the first provider request contained exactly `md_check`; the qualified-skill fix therefore works. The model then called `md_check`, which exposed a separate harness-isolation fault: the handler reached an installed Incise binary that does not provide `check`.

The isolated Hermes home copies the source profile dotenv because Hermes needs that profile context. Hermes deliberately loads its home dotenv with `override=True`, so the copied `INCISE_BIN=/Users/peter/.local/bin/incise` replaced the evaluator process environment value. The v10 manifest identifies the intended checkout binary, but the plugin subprocess did not receive it. No v10 scored pool was opened.

V11 changes only isolated-home construction: after copying the dotenv, it replaces the complete `INCISE_BIN` assignment with the resolved preregistered checkout binary, or appends that assignment when absent. Preflight verifies the exact pinned line. This preserves all other profile values while making the manifest binary and plugin binary identical. Product code, tool surfaces, skill instructions, direct endpoint, tasks, model, seed, token cap, grader, decision rule, and 52-trial population remain unchanged.

V11 uses the immutable prefix `markdown_check_skill_v1_20261004_v11`. The v10 preflight manifest remains immutable and is reported as a pre-pool binary-isolation abort.
