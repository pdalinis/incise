# Incise

[![CI](https://github.com/pdalinis/incise/actions/workflows/ci.yml/badge.svg)](https://github.com/pdalinis/incise/actions/workflows/ci.yml)


**Safe, semantic Markdown editing for AI agents — purpose-built for small models that struggle to reliably modify Markdown documents.**

Incise is a CLI for making precise, structure-aware edits to Markdown files. Instead of asking an AI model to reproduce part of a document and hope it gets the formatting right, Incise lets the model express **what it wants to change** and lets deterministic code handle the mechanics.

This is particularly useful with **small language models and local LLMs**, which can understand a requested change but are often unreliable at mechanical tasks such as:

* updating a Markdown table without corrupting its formatting
* adding or removing list items while preserving indentation and numbering
* finding and modifying the correct section boundary
* changing YAML frontmatter without rewriting unrelated content
* making a small edit without reproducing the entire document

Incise separates **intent from mechanics**:

```text
Model intent:
    "In the Projects table, set Launch to done."
              │
              ▼
Incise:
    Find the table, row, and column by content.
              │
              ▼
Result:
    Change one cell. Leave everything else alone.
```

The result is a safer editing primitive for **AI agents, local LLMs, Obsidian vaults, documentation repositories, and Markdown knowledge bases**.

---

## Why Incise?

Language models are good at understanding what a document should say. They are much less dependable at the mechanical work required to change that document safely.

For example, changing one Markdown table cell may require the model to:

1. find the correct table
2. identify the correct row
3. identify the correct column
4. preserve escaped pipes
5. preserve alignment markers
6. calculate new padding
7. preserve line endings
8. avoid changing unrelated content

A model can understand the requested change and still get one of those mechanical details wrong.

The problem is especially visible with **small and local models**. More reasoning tokens do not make character counting deterministic, and loading an entire Markdown file into context just to change one cell wastes context that could be used for the actual task.

Incise moves the mechanical work out of the model.

**The model decides what to change. Incise determines how to change it safely.**

---

## Built for Markdown knowledge bases

Markdown files accumulate structure over time:

* tables
* nested lists
* task lists
* headings and sections
* YAML frontmatter
* Obsidian wikilinks
* block IDs
* callouts
* embeds
* comments
* carefully formatted prose

A routine agent update should not reconstruct all of that just to change one fact.

Incise operates directly on individual Markdown files and makes the smallest structural edit it can. Bytes outside the targeted range remain unchanged.

That makes Incise useful for:

* **LLM wikis**
* **Obsidian vaults**
* **Markdown knowledge bases**
* **documentation repositories**
* **AI-maintained notes**
* **agent-managed project files**

Incise is **not** a knowledge graph, vector database, or vault index. It is the safe mutation layer an AI agent can use after it has decided which file and information need to change.

---

## Quick start

### Install from crates.io

```bash
cargo install incise-cli --locked
incise --version
```

Prebuilt binary archives for Linux and macOS are attached to each [GitHub release](https://github.com/pdalinis/incise/releases).

Download the archive for your platform, verify it against `SHA256SUMS`, and place `incise` somewhere on your `PATH`.

### Build from source

```bash
git clone https://github.com/pdalinis/incise.git
cd incise
cargo install --locked --path crates/incise-cli
```

### Inspect a Markdown file

Before modifying a document, inspect only the structure the agent needs:

```bash
incise tables vault/Projects.md
incise outline vault/Projects.md
```

### Make a semantic edit

```bash
incise table-update-cell vault/Projects.md \
  --table Projects \
  --where Note=Launch \
  --column Status \
  --value done
```

The row is selected by **content**, not by a line number.

If the new value requires the table to widen, Incise re-pads the table correctly while leaving the rest of the file untouched.

---

## The agent editing loop

Incise is designed around a simple, repeatable workflow:

```text
1. Inspect
      ↓
2. Identify the target semantically
      ↓
3. Perform one structured operation
      ↓
4. Verify the result
```

The agent does not need to load and reproduce the entire Markdown document.

For example:

```bash
incise lists vault/Daily/2026-09-17.md

incise rows vault/Projects.md \
  --table Projects \
  --filter Status=active

incise keys vault/Projects.md
```

Then perform the requested operation:

```bash
incise table-add-row vault/Projects.md --args \
  '{"table":{"heading":"Projects"},"values":{"Note":"Launch","Status":"active"}}'
```

Writes can be previewed with:

```bash
--dry-run
```

When an agent may be operating on a stale read, use a content hash:

```bash
incise hash FILE
```

followed by:

```bash
--if-match HASH
```

This lets the agent detect that a file changed between its read and write instead of silently modifying a newer version.

---

## What Incise can edit

| Markdown structure   | Operations                                                            |
| -------------------- | --------------------------------------------------------------------- |
| **Tables**           | Add rows, update cells, delete rows, realign columns, query rows      |
| **Lists & tasks**    | Add/remove items, toggle checkboxes                                   |
| **Sections**         | Append, replace, insert, delete, rename, change heading levels        |
| **YAML frontmatter** | Read, set, and delete nested keys                                     |
| **Structure**        | Discover headings, tables, lists, frontmatter, rows, keys, and hashes |

### Tables

Incise can add rows, update cells, delete rows, realign columns, and query rows.

It preserves:

* alignment markers
* escaped pipes
* line endings
* surrounding content

### Lists and tasks

Incise can add or remove list items and toggle checkboxes while preserving:

* marker style
* indentation
* loose vs. tight spacing
* ordered-list numbering conventions

### Sections

Incise can:

* append or replace body text
* insert subsections
* delete a section subtree
* rename headings
* change heading levels

Section boundaries are identified structurally rather than guessed from line numbers.

### YAML frontmatter

Incise can read, set, and delete nested frontmatter keys while preserving:

* key order
* comments
* scalar formatting
* unrelated lines

### Structural reads

Incise can expose just the structure an agent needs:

```bash
incise tables FILE
incise lists FILE
incise outline FILE
incise rows FILE
incise keys FILE
```

This reduces the amount of Markdown that needs to enter the model's context window.

---

## Use Incise with an AI agent

Incise publishes the function schemas an agent should receive:

```bash
incise schema
```

Or inspect an individual tool:

```bash
incise schema --tool table_edit
```

These schemas are measured artifacts rather than handwritten approximations. A function-calling harness can pass the model's argument object to the corresponding Incise command and return stdout or stderr directly.

### Hermes Agent

Incise includes a Hermes adapter under [`plugins/hermes/`](plugins/hermes/).

For Markdown structures represented by Incise, give the agent an explicit preference for structured editing:

```markdown
## Editing Markdown

For Markdown tables, lists, sections, and frontmatter, prefer Incise tools over
generic patch, write, or shell tools.

Inspect structure first with `md_tables`, `md_lists`, or `md_outline`. Use
`table_get` when current table rows are needed. Make changes with `table_edit`,
`list_edit`, `section_edit`, or `frontmatter_edit`.

If Incise refuses an operation, follow the remedy in its response rather than
rewriting the document. Use raw editing only for prose changes that Incise does
not represent.
```

The Hermes adapter exposes the measured edit and table-read schemas together with structural reads. See [`plugins/hermes/README.md`](plugins/hermes/README.md) for installation and safety details.

Incise is deliberately scoped to Markdown structures it understands. Generic editing remains appropriate for ordinary prose and for creating the initial contents of a new document.

---

## Use with Pi

Install the current release candidate:

```bash
pi install npm:pi-incise@next
pi
```

After the live composition benchmark passes and that exact version is promoted, the stable package can be installed with:

```bash
pi install npm:pi-incise
```

The package provides prebuilt binaries for:

* macOS arm64
* macOS x64
* Linux arm64 (glibc)
* Linux x64 (glibc)

It registers:

* `md_tables`
* `md_lists`
* `md_outline`
* `table_get`
* the four structured edit tools

Run:

```text
/incise-doctor
```

inside Pi to inspect the selected binary and schema status.

Windows and musl Linux are not supported in v1.

---

## Safety model

Incise is designed around a few simple guarantees.

### Semantic addressing

Targets are identified by things such as:

* heading paths
* column values
* item text
* keys
* ordinals

**Line numbers are never part of the editing contract.**

This means an agent does not have to rely on a stale statement such as "change line 47."

### Byte-preserving edits

Incise changes the smallest structural range it can.

A table may widen when its content requires it, but unrelated document bytes remain unchanged.

That means an edit does not need to serialize and rewrite the entire Markdown document.

### Loud ambiguity

If Incise encounters:

* multiple matching targets
* malformed Markdown structures
* ambiguous addressing
* unsafe payloads

it refuses the operation rather than silently choosing a plausible target.

Refusals include actionable information that can be used to construct the next call.

### Safe writes

The CLI supports:

* `--dry-run`
* atomic replacement
* no-op detection
* content-hash preconditions
* stale-read protection

### Token-frugal results

A successful write returns a concise description of what changed.

It does not return the entire document and consume another chunk of model context unnecessarily.

---

## Measured with small models

Incise began with a specific question:

> Can deterministic, structure-aware Markdown operations make a small local model more reliable at document maintenance?

The benchmark compares direct `patch` calls with Incise operations on the same tasks, model, seeds, and grader.

| Operation | Mode           |       Accuracy | Mean output tokens | Mean model time |
| --------- | -------------- | -------------: | -----------------: | --------------: |
| Tables    | Direct `patch` |  60.0% (36/60) |                 77 |           2.4 s |
| Tables    | Incise         |   100% (60/60) |                 66 |           2.2 s |
| Lists     | Direct `patch` | 63.0% (63/100) |                 58 |           2.0 s |
| Lists     | Incise         | 91.0% (91/100) |                 58 |           2.0 s |
| Sections  | Direct `patch` | 19.0% (19/100) |                186 |           5.9 s |
| Sections  | Incise         | 74.0% (74/100) |                 60 |           2.0 s |

"Tokens" means completion/output tokens. "Time" is model-server wall time per trial and does not include local tool execution.

The table and list Incise rows use the adopted schemas. The section result uses the shared 10-task, single-turn `section_g` slice so it remains comparable with the direct-edit baseline.

The currently adopted `section_g_hpath` schema was later measured on a broader 15-task, four-turn arm at 86.7% accuracy (130/150); that result is not mixed into the comparison above.

Frontmatter is omitted because its recorded experiments compare Incise schemas but do not include a direct-edit control.

**These results are for one small local model under the recorded benchmark conditions. They are not a claim that every model will achieve the same rates.**

The important question is which failure modes deterministic operations remove:

* character-counting errors
* table-formatting errors
* structural-boundary mistakes
* list indentation mistakes
* byte-for-byte reconstruction errors

See the individual benchmark reports:

* [`tables`](bench/)
* [`lists`](bench/)
* [`sections`](bench/)
* [`frontmatter`](bench/)

The complete tasks, prompts, raw results, statistical comparisons, caveats, and reversed conclusions are recorded in [`bench/FINDINGS.md`](bench/FINDINGS.md).

---

## Engineering confidence

The Rust core is tested against an independent Python oracle across **110,406 generated cases and 54 fixtures**.

The comparison includes both edited documents and refusal messages.

Property invariants cover guarantees that two implementations could otherwise get wrong in the same way:

* unrelated bytes survive
* rows and sections are not silently lost
* operations round-trip where expected
* rendered reads preserve their cells

The differential and invariant suites are also exercised by mutation testing. The current test record contains **212 injected faults** used to demonstrate that protected behavior is actually covered.

`incise-core` deliberately has no dependencies. The CLI and integrations may take dependencies, but the core remains a small trust boundary.

---

## Project status

Incise currently uses **0.x versioning** and is under active development. Public interfaces may evolve before 1.0.

Currently implemented:

* Markdown tables
* Markdown lists
* task lists
* sections
* YAML frontmatter
* structural reads
* semantic addressing
* dry runs
* atomic writes
* stale-read protection
* content hashing
* AI-agent schemas
* Hermes integration
* Pi integration

Planned but not yet implemented:

* scoped search and replace
* multi-operation transactions

Incise intentionally refuses Markdown shapes it cannot edit while maintaining its preservation guarantees.

Benchmark results are tied to the specific model, prompts, schemas, tasks, and executor that produced them. Changes to a tool description or refusal behavior may require remeasurement even when the deterministic test suite still passes.

### Supported platforms

Currently supported:

* Linux
* macOS

Windows is not currently supported or tested.

---

## Development

Run the deterministic test suite before submitting a code change:

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

The benchmark corpus is frozen because published findings refer to its exact bytes.

Purpose-built coverage inputs belong under:

```text
bench/synthetic/
```

Experiments should run on copies of the corpus.

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the benchmark-impact policy and pull-request expectations.

Release maintainers should also see [`RELEASING.md`](RELEASING.md) for crate-publication order, tag checks, and post-release smoke tests.

---

## Contributing and security

Contributions are welcome.

Read [`CONTRIBUTING.md`](CONTRIBUTING.md) before changing measured behavior or benchmark artifacts.

Report ordinary bugs and feature ideas through GitHub issues.

Report potential vulnerabilities through GitHub private vulnerability reporting as described in [`SECURITY.md`](SECURITY.md).

---

## License

Incise is available under the MIT License. See [`LICENSE`](LICENSE).

