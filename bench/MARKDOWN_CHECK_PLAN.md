# Markdown structural check and deterministic repair plan

## Status and benchmark classification

This is the pre-implementation plan for a parser-backed `incise check` command,
an allowlisted deterministic repair mode, portable agent guidance, and Hermes and
Pi packaging. It must be committed before implementation or live sampling. A new
GitHub feature issue should own the work; issue #38 remains the narrower, closed
flow-collection bug rather than becoming an umbrella issue.

The core and CLI work is not automatically model-facing. Publishing a new tool,
advertising a skill to the model, or changing shared agent instructions can alter
tool selection and continuation behavior and therefore requires composition-wide
consideration under `CONTRIBUTING.md`. The phases below keep those surfaces
separable so deterministic value can ship without carrying an unmeasured prompt
change.

## Objective

Give callers one deterministic way to answer two different questions:

1. Does this Markdown document contain a structural hazard Incise can identify?
2. Can Incise repair any reported hazard without asking a model to invent bytes or
   choose among plausible meanings?

The checker is not a style linter, formatter, vault index, or generic Markdown
validator. It reports hazards that affect Incise's ability to address or preserve
tables, lists, sections, and frontmatter. Vault policy such as required stamps,
index membership, ledger updates, naming conventions, and Git-history recovery
stays in the vault-specific layer.

## Product decisions

### Separate checking, automatic repair, and intentional repair

Every finding has one of three repair classes:

- `automatic`: Incise can prove one semantics-preserving, byte-scoped repair.
- `explicit`: Incise has a deterministic semantic operation, but applying it
  requires intent or confirmation.
- `manual`: the document is hazardous, but Incise cannot infer the intended bytes.

The word `automatic` is a proof obligation, not a convenience label. A repair is
automatic only when all of these conditions hold:

1. Exactly one output is valid under the rule.
2. No user content is deleted, invented, reordered, or reinterpreted.
3. Bytes outside the reported repair spans remain identical.
4. Applying the repair twice is byte-identical to applying it once.
5. The repair cannot turn one valid authorial formatting choice into another.
6. The independent Rust and Python implementations agree on the report, output,
   and refusal text.
7. Targeted mutations demonstrate that the tests fail when any condition above is
   weakened.

The initial automatic allowlist is empty until a concrete rule satisfies this
gate. This is intentional. Missing final newlines, CRLF, ragged table alignment,
duplicate headings, empty cells, and open-at-EOF fences are all valid or
potentially intentional Markdown. Easy automation does not make them safe.

`table-realign` remains an `explicit` repair. `REQUIREMENTS.md` already records
why Incise cannot distinguish a damaged table from a deliberately ragged one.
The checker may return a complete `table-realign` repair descriptor when the
operation is applicable, but `--fix-safe` must not invoke it.

### Stable CLI contract

The proposed commands are:

```text
incise check FILE --json
incise check FILE --fix-safe --if-match HASH --json
```

`incise check FILE` is read-only. `--fix-safe` is the only mutating form and must
be named at the call site; checking alone never writes. The existing `--if-match`
hash contract prevents a report generated from stale bytes from being applied to
a changed file.

The mutating form performs one transaction:

1. Read and hash the file once.
2. Generate the full report.
3. Select only allowlisted `automatic` findings.
4. Reject overlapping or internally inconsistent repair spans.
5. Apply the repairs in memory in deterministic order.
6. Recheck the candidate bytes.
7. Refuse the entire transaction if a selected finding remains, a new structural
   error appears, or any preservation assertion fails.
8. Atomically replace the file once and return the before and after hashes.

No partial repair is written. A successful result lists the finding codes and
semantic addresses repaired but does not echo the document.

### Report shape

JSON output is versioned from the first release. The exact spelling is frozen by
tests before integrations consume it. The intended shape is:

```json
{
  "schema_version": 1,
  "path": "notes.md",
  "hash": "...",
  "status": "error",
  "findings": [
    {
      "code": "table.non_rectangular",
      "severity": "error",
      "message": "...",
      "address": {"heading": "Projects", "ordinal": 2},
      "span": {"start": 120, "end": 184},
      "repair_class": "manual"
    }
  ]
}
```

Rules use stable codes. Human-readable messages remain actionable product
behavior, while callers branch on codes rather than parsing prose. Byte spans are
diagnostic and repair-scoping data, not public edit addresses. Semantic addresses
remain the only way callers request a structural mutation.

`status` is the maximum finding severity: `clean`, `info`, `warning`, or `error`.
The process exits successfully for a completed check even when findings exist;
JSON status and a documented optional strict-exit flag distinguish findings from
I/O, usage, or parser failures. This prevents integrations from confusing a valid
lint report with a crashed checker.

### Initial rule inventory

The first release should report existing Incise editability and preservation
hazards rather than create a broad style guide:

| Finding | Severity | Repair class |
| --- | --- | --- |
| Table rows disagree with the header cell count | error | manual |
| A table mixes line endings | error | manual |
| A table mixes structural indentation | error | manual |
| A table has duplicate addressable column names | warning | manual |
| A rectangular table is ragged but eligible for `table-realign` | info | explicit |
| A YAML frontmatter opener has no defensible closing delimiter | error | manual |
| A frontmatter path is structurally ambiguous to Incise | warning | manual |
| Repeated heading paths or repeated list text require an ordinal or stronger address | info | manual |

The implementation phase must validate each proposed rule against CommonMark/GFM
and Incise's actual parsers. A rule is removed from v1 if it cannot distinguish a
hazard from supported syntax without guessing. Unsupported TOML frontmatter,
flow-style YAML collections, CRLF, absent final newlines, Setext headings,
escaped table pipes, loose lists, and repeated headings are not findings merely
for existing.

The checker should reuse the same parsing and address-resolution primitives as
the operations. It must not grow a second Markdown parser or infer validity from
regular expressions in the CLI or plugins.

## Core and CLI implementation

### Rust trust boundary

Add a read-only report API to `incise-core` and a transaction API for allowlisted
repairs. The core crate remains dependency-free. Rule definitions own their code,
severity, evidence, semantic address, and optional repair descriptor.

The report should be deterministic for identical bytes. Finding order is source
order, then stable code, then semantic address. Messages and report fields are
constructed in the core so the CLI, Hermes, Pi, and the Python oracle cannot
silently diverge.

Do not route checking through the mutation dispatch merely to reuse its string
interface. Reuse parsers and validation helpers below dispatch, then expose an
explicit core report type from `lib.rs`.

### Independent Python oracle

Implement the same rules and `--fix-safe` transaction in `bench/incise_ops.py`.
Extend the differential harness to compare:

- finding codes, severities, order, addresses, spans, and repair classes;
- human-readable messages;
- fixed document bytes and before/after hashes;
- stale-hash, overlap, no-op, and rollback refusals.

The oracle must not call the Rust binary or share generated rule tables with it.
Agreement remains meaningful only while the implementations are independent.

### CLI behavior

Add `check` to `crates/incise-cli`. Human output should be concise and copyable;
JSON is the integration contract. The help text must distinguish a structural
hazard check from style linting and state that `--fix-safe` cannot apply
`explicit` or `manual` repairs.

The command respects existing home-path expansion, hashing, atomic-write,
line-ending preservation, JSON framing, and exit-code conventions. Read-only
checking must never require write permission. `--fix-safe` must use the same
write path and stale-read protection as other mutations.

## Integration and skill packaging

### One portable skill, two packages

Author one Agent Skills-compatible skill named `incise-check`. Its description
should trigger only for Markdown structural verification, repair of checker
findings, or an explicit request to validate an Incise edit. The full instructions
should teach this loop:

1. Run `incise check FILE --json`.
2. Stop successfully on `clean`.
3. For `automatic` findings, use `--fix-safe --if-match HASH`; never construct a
   raw patch from the prose message.
4. For `explicit` findings, invoke the named Incise semantic operation only when
   the user's request supplies the required intent or confirmation.
5. For `manual` findings, report the ambiguity or ask for intent; do not rewrite
   the file.
6. Recheck after any mutation and stop if the report makes no progress.

The skill must not contain a second checker script. It delegates all detection
and repair to the version-matched Incise binary. Keep one canonical `SKILL.md` in
the repository and copy it into each release artifact during packaging; add a
test that the packaged copies are byte-identical to the canonical source.

### Hermes

Package the skill under the native plugin archive and register it with
`ctx.register_skill`. It will be available as `incise:incise-check` through
Hermes skill discovery without copying it into `~/.hermes/skills`. Plugin update
and removal therefore update and remove the skill as one unit.

Hermes native plugin skills are listed by `skills_list` but are not inserted into
the initial `<available_skills>` prompt. That is a useful opt-in boundary for the
first release. Add plugin tests for registration, qualification, linked files,
archive contents, and behavior when the binary lacks the required check command.

The skill should use Hermes's terminal capability to invoke the CLI initially.
A native `md_check` or `md_fix_safe` tool would change the provider-visible tool
surface and is deferred until the skill/CLI path demonstrates a need that shell
execution cannot meet safely.

### Pi

Pi packages can declare skills directly. Add the packaged skill directory to the
`pi.skills` manifest and npm `files` allowlist. The package test must confirm the
npm tarball contains `SKILL.md` and that Pi discovers `/skill:incise-check` from
the packed artifact.

Initially set `disable-model-invocation: true`. This makes the skill available by
explicit command without advertising a new behavior-selection option in every Pi
turn. Enabling automatic model selection is a later, separately measured prompt
change. The Incise extension and skill must resolve the same version-matched
binary; the skill must not bypass package binary selection with an unrelated
`incise` earlier on `PATH`. If Pi does not expose the resolved path to skills, add
an extension command or a narrow check tool rather than duplicating resolution
logic in the skill.

### Recommended agent instructions

After deterministic and integration tests pass, extend the recommended
`AGENTS.md` snippet with guidance equivalent to:

```md
After changing a Markdown table, list, section, or frontmatter, run
`incise check PATH --json`. Apply only repairs classified `automatic` through
`incise check PATH --fix-safe --if-match HASH`; use the named semantic operation
for explicit repairs, and do not raw-patch manual findings.
```

This guidance is opt-in documentation first. Do not silently append it to every
host system prompt in the initial release. The repository's own `AGENTS.md` can
adopt it once the command exists and its exact names are stable.

## Scope controls and non-goals

- Do not port vault stamp, index, ledger, CSV, or Git-history checks into core.
- Do not normalize line endings, final newlines, whitespace, heading levels,
  list markers, table padding, or frontmatter style as generic safe fixes.
- Do not accept arbitrary patch text or shell commands in repair descriptors.
- Do not let plugins independently classify a finding as safe.
- Do not run repair merely because an agent inspected a file.
- Do not mask an Incise mutation bug by repairing its output. If an integration
  adds post-edit checking and an Incise operation introduces a new error, roll
  back and surface the defect.
- Do not promise whole-document Markdown validity. CommonMark intentionally
  accepts constructs that policy linters may dislike.

## Test plan

### Deterministic tests

Add purpose-built fixtures under `bench/synthetic/`; do not change the frozen
corpus merely to create findings. Cover clean documents and every rule across LF,
CRLF, absent-final-newline, escaped-pipe, nested-list, repeated-heading,
frontmatter, and adjacent-structure cases.

Required invariants:

1. Checking never mutates bytes.
2. Clean corpus documents remain byte-identical and do not acquire false error
   findings.
3. Every automatic repair is idempotent.
4. Bytes outside the union of repair spans are identical.
5. Every written repair corresponds to a finding in the pre-write report.
6. A failed recheck, overlap, stale hash, or injected write failure leaves the
   original file byte-identical.
7. Safe fixing never applies an `explicit` or `manual` descriptor.
8. Rust and Python agree byte-for-byte on reports, messages, and outputs.

Add targeted mutations for missed findings, false positives, wrong spans, changed
severity, unsafe class promotion, partial writes, skipped rechecks, unstable
ordering, and non-idempotent output. Run the full normal suite plus mutation tests
only after source editing is complete, as required by `AGENTS.md`.

### Host and package tests

Hermes tests cover skill registration and invocation through the installed-host
API. Pi tests load the packed npm artifact, discover the skill, force
`/skill:incise-check`, and exercise check, safe-fix no-op, stale hash, explicit
repair refusal, and recheck behavior. Both hosts must produce the core's exact
report rather than paraphrasing findings.

Release-archive tests verify that the skill and matching Incise binary are in the
same versioned artifact. Doctor output should report whether structural checking
is supported by the selected binary.

## Model-facing evaluation plan

### Hypothesis

For tasks that leave a detectable Markdown structural hazard, a deterministic
checker plus skill reduces raw-patch repair attempts and collateral changes
without causing agents to mutate valid author formatting or continue editing
after a correct result.

### Treatment stages

1. **CLI/core only:** deterministic tests and differential agreement; no live
   model claim.
2. **Explicit skill:** `/skill:incise-check` in Pi and explicit
   `skill_view("incise:incise-check")` in Hermes; targeted live evaluation only.
3. **Automatic skill discovery or shared prompt guidance:** composition-wide
   retention is required before adoption because every task sees a changed
   behavior-selection surface.

### Targeted population

Create a separately named synthetic verification family containing:

- clean edits that should stop without another mutation;
- each v1 error finding;
- an eligible but `explicit` table realignment finding;
- valid CRLF, missing-final-newline, ragged-table, repeated-heading, escaped-pipe,
  and flow-collection controls that must not be auto-fixed;
- stale-report and concurrent-change cases;
- a mixture of new and pre-existing findings so the agent does not broaden the
  user's requested edit.

Control receives the same edited file and existing Incise tools without the
skill. Treatment receives the explicit skill. Pair model, prompt, runtime,
decoding settings, seed, and starting bytes. Use a new result prefix and never
overwrite an earlier pool.

Primary endpoints are correct final bytes and zero collateral mutation.
Secondary endpoints are checker use, raw patch/write fallback, number of
mutations, turns, tokens, unresolved findings, and unnecessary changes to valid
controls.

### Gates

Before any live run, `ceiling.py` or an equivalent deterministic executor audit
must show 100% reachability for every intended repair and 0% reachability for
forbidden automatic repairs.

The explicit-skill candidate passes only if:

- all automatic repairs are correct and limited to their reported spans;
- no explicit or manual finding is auto-applied;
- valid controls remain byte-identical;
- clean successful edits do not trigger a second mutation;
- there are zero harmful or collateral outcomes;
- both hosts agree on the skill instructions and command behavior.

If the skill is later advertised automatically or the shared Pi/Hermes prompt is
changed, run the applicable full composition retention set. Existing benchmark
claims remain scoped to the prior prompt and skill surface until that gate
passes; deterministic success alone does not refresh them.

Record the model and checkpoint, server and version, host version, decoding
parameters, prompt and schema identifiers, executor commit, task manifest hash,
seeds, timestamps, raw and graded hashes, and exact control and treatment commits
before interpreting outcomes.

## Delivery sequence

1. Open the feature issue and link this committed plan.
2. Freeze report codes, JSON shape, severity semantics, and v1 rule inventory.
3. Implement Rust checking and the independent Python oracle.
4. Add CLI JSON/human output and transactional `--fix-safe`.
5. Complete differential, invariant, CLI, and mutation testing.
6. Author the single portable skill and package it explicitly in Hermes and Pi.
7. Add host, archive, npm-pack, and doctor tests.
8. Update `REQUIREMENTS.md`, README files, recommended agent instructions, and
   `bench/FINDINGS.md` with deterministic scope only.
9. Run the preregistered explicit-skill evaluation and record new artifacts.
10. Decide separately whether evidence supports automatic skill discovery,
    native check tools, or default post-edit guidance.

## Decisions to confirm before implementation

1. **Automatic allowlist:** keep it empty until an individual rule satisfies the
   proof gate. Recommended: yes. Do not relabel `table-realign` as automatic.
2. **Skill activation:** ship explicit-only first, especially in Pi where skill
   metadata otherwise enters every system prompt. Recommended: yes.
3. **Scope:** keep Incise structural and let `vault-lint` layer repository policy
   and Git-aware checks on top. Recommended: yes.
4. **Native agent tools:** start with the CLI-driven skill and add `md_check` or
   `md_fix_safe` only if host constraints or evaluation demonstrate a need.
   Recommended: yes.

