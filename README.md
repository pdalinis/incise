# Incise

[![CI](https://github.com/pdalinis/incise/actions/workflows/ci.yml/badge.svg)](https://github.com/pdalinis/incise/actions/workflows/ci.yml)

**Safe, surgical Markdown edits for AI agents.**

Incise helps small language models work reliably with Markdown knowledge bases. Instead of asking a model to reproduce a table, renumber a list, or rewrite a section boundary correctly, give it a semantic operation and let deterministic code handle the structure.

It is designed for LLM wikis, Obsidian vaults, documentation repositories, and other living knowledge bases where a small edit should not risk unrelated notes.

```text
Model intent: In the Projects table, set Launch to done.
       ↓
Incise call: address the table, row, and column by content
       ↓
Result: one targeted edit; unrelated bytes stay unchanged
```

## Why Incise

Language models are good at understanding what a note should say. They are much less dependable at the mechanical work around that change: counting table padding, preserving list indentation, finding section boundaries, and reproducing nearby text exactly.

That gap matters most for small and local models. More reasoning tokens do not make character counting deterministic, and loading an entire note just to change one cell wastes scarce context.

Incise separates intent from mechanics. The model chooses the operation and identifies content semantically; Incise performs the exact splice.

## Built for LLM wikis, Obsidian vaults, and knowledge bases

A knowledge base is valuable because its files accumulate structure over time: links, tags, callouts, embeds, task lists, carefully formatted tables, and human edits. A routine agent update should not normalize or reconstruct all of that.

Incise operates on individual Markdown files and preserves bytes outside the targeted range. Unrelated Obsidian wikilinks, block IDs, callouts, frontmatter comments, and surrounding prose are not passed through a serializer and rewritten.

Incise is not a knowledge graph or a vault index. It is the safe mutation layer an agent can use after it has decided which file and fact need to change.

## Quick start

Install the current release from crates.io:

```bash
cargo install incise-cli --locked
incise --version
```

Prebuilt binary archives for Linux and macOS are attached to each [GitHub release](https://github.com/pdalinis/incise/releases). Download the archive for your platform, verify it against `SHA256SUMS`, and place `incise` somewhere on `PATH`.

To build the current development version from source:

```bash
git clone https://github.com/pdalinis/incise.git
cd incise
cargo install --locked --path crates/incise-cli
```

Inspect a note before changing it:

```bash
incise tables vault/Projects.md
incise outline vault/Projects.md
```

Then make a semantic edit:

```bash
incise table-update-cell vault/Projects.md \
  --table Projects \
  --where Note=Launch \
  --column Status \
  --value done
```

The row is selected by content, not by a line number. If the new value widens a column, Incise re-pads that table correctly and leaves the rest of the file alone.

## Use with Pi

Install the release candidate without a Rust toolchain:

```bash
pi install npm:pi-incise@next
pi
```

After the live composition benchmark passes and that exact version is promoted, `pi install npm:pi-incise` installs the stable release.

The package provides prebuilt binaries for macOS arm64/x64 and glibc Linux arm64/x64. It registers `md_tables`, `md_lists`, `md_outline`, `table_get`, and the four structured edit tools. Run `/incise-doctor` in Pi to inspect the selected binary and schema status. Windows and musl Linux are not supported in v1.

## A safer agent editing loop

Incise gives an agent a small, repeatable loop: inspect the relevant structure, issue one semantic operation, and act on either a precise success message or an actionable refusal.

Reads return only the structure the agent asks for instead of echoing the entire document:

```bash
incise lists vault/Daily/2026-09-17.md
incise rows vault/Projects.md --table Projects --filter Status=active
incise keys vault/Projects.md
```

Writes accept normal flags or a complete JSON argument object:

```bash
incise table-add-row vault/Projects.md --args \
  '{"table":{"heading":"Projects"},"values":{"Note":"Launch","Status":"active"}}'
```

Preview any write with `--dry-run`. Use `incise hash FILE` followed by `--if-match HASH` when an agent may be acting on a stale read.

## What Incise can edit

**Tables.** Add rows, update cells, delete rows, realign columns, and query rows. Incise preserves alignment markers, escaped pipes, line endings, and surrounding content.

**Lists and tasks.** Add or remove items and toggle checkboxes while preserving marker style, indentation, loose or tight spacing, and ordered-list numbering conventions.

**Sections.** Append or replace body text, insert subsections, delete a subtree, rename headings, and change heading levels without guessing section boundaries.

**YAML frontmatter.** Read, set, or delete nested keys while preserving key order, comments, scalar formatting, and unrelated lines.

**Structural reads.** Discover headings, tables, lists, frontmatter, rows, keys, and content hashes without loading the whole file into model context.

## Use Incise with an agent

The CLI publishes the function schemas a model should receive:

```bash
incise schema
incise schema --tool table_edit
```

These schemas are measured artifacts, not handwritten approximations. A function-calling harness can pass the model argument object to the corresponding Incise command and return stdout or stderr directly.

When using the Hermes plugin, add a rule like this to a project-level `AGENTS.md`:

```md
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

This preference is deliberately scoped to Markdown structures Incise represents. Generic editing remains appropriate for ordinary prose and for creating the initial contents of a new document.

The adapter under [`plugins/hermes/`](plugins/hermes/) exposes the measured edit and table-read schemas plus structural reads for Hermes Agent. Its [README](plugins/hermes/README.md) contains the installation and safety details.

## Safety model

**Semantic addressing.** Targets are identified by heading paths, column values, item text, keys, and ordinals. Line numbers are never part of the editing contract.

**Byte-preserving splices.** Incise changes the smallest structural range it can. A table may widen when its content requires it; unrelated document bytes remain identical.

**Loud ambiguity.** Multiple matches, malformed structures, and unsafe payloads produce refusals with near matches and a concrete next call. Incise does not silently pick a plausible target.

**Safe writes.** The CLI supports dry runs, atomic replacement, no-op detection, and content-hash preconditions for stale-read protection.

**Token-frugal results.** A successful write returns one sentence describing what changed. It does not return the document and invite an unnecessary second edit.

## Measured with small models

Incise began with a narrow question: can deterministic structure-aware operations make a small local model safer and more capable at Markdown maintenance?

The paired results below compare Hermes-style direct `patch` calls with Incise operations on the same tasks, model, seeds, and grader. “Tokens” means completion/output tokens, and “time” is model-server wall time per trial; neither includes local tool execution. Values are means rounded to the nearest token and tenth of a second.

| Operation | Mode | Accuracy | Mean output tokens | Mean model time |
| --- | --- | ---: | ---: | ---: |
| Tables | Without: direct `patch` | 60.0% (36/60) | 77 | 2.4 s |
| Tables | With: Incise (`scheme_f`) | 100% (60/60) | 66 | 2.2 s |
| Lists | Without: direct `patch` | 63.0% (63/100) | 58 | 2.0 s |
| Lists | With: Incise (`list_g`) | 91.0% (91/100) | 58 | 2.0 s |
| Sections | Without: direct `patch` | 19.0% (19/100) | 186 | 5.9 s |
| Sections | With: Incise (`section_g`) | 74.0% (74/100) | 60 | 2.0 s |

The table and list Incise rows use the adopted schemas. The section row uses the shared 10-task, single-turn `section_g` slice so it remains comparable with the direct-edit baseline. The currently adopted `section_g_hpath` schema was later measured on a broader 15-task, four-turn arm at 86.7% accuracy (130/150); that result is not mixed into the table. Frontmatter is omitted because its recorded experiments compare Incise schemas and do not include a direct-edit control.

These are results for one small local model under the recorded benchmark conditions, not a promise that every model will achieve the same rates. The useful result is the failure modes removed by deterministic operations: character arithmetic, structural-boundary mistakes, and byte-for-byte reconstruction.

Full benchmark reports by operation: [tables](bench/FINDINGS.md#headline--arm-a-baseline), [lists](bench/FINDINGS.md#lists--the-second-op-family), [sections](bench/FINDINGS.md#s1--sections-are-the-hardest-family-measured-and-the-first-arm-b-family-with-data-loss), and [frontmatter](bench/FINDINGS.md#f-frontmatter--the-fourth-family-and-the-verb-that-deleted-the-version). See also the [combined shipping-tool benchmark](bench/FINDINGS.md#f-compose--the-shipping-set-has-never-been-measured-as-a-set).

The complete tasks, prompts, raw results, statistical comparisons, caveats, and reversed conclusions are recorded in [`bench/FINDINGS.md`](bench/FINDINGS.md).

## Engineering confidence

The Rust core is checked byte-for-byte against an independent Python oracle across 110,406 generated cases over 54 fixtures. The comparison includes edited documents and refusal messages.

Property invariants cover guarantees that two implementations could get wrong in the same way: unrelated bytes survive, rows and sections are not silently lost, operations round-trip where expected, and rendered reads preserve their cells.

The differential and invariant suites are themselves exercised by mutation testing. The current record contains 212 injected faults used to demonstrate that the tests fail when protected behavior moves.

`incise-core` deliberately has no dependencies. The CLI and integrations may take dependencies; the core remains a small trust boundary.

## Project status

Incise uses 0.x versioning and is under active development; its public interfaces may still evolve before 1.0. Tables, lists, sections, YAML frontmatter, structural reads, dry runs, atomic writes, and stale-read protection are implemented.

Scoped search and replace and multi-operation transactions are planned but not built. Incise intentionally refuses Markdown shapes it cannot edit without keeping its preservation guarantees.

Behavioral claims are tied to the model, prompts, schemas, tasks, and executor that produced them. Changes to a tool description or refusal can require remeasurement even when deterministic tests still pass.

The currently supported platforms are Linux and macOS. Windows is not supported or tested at this stage.

## Development

Run the deterministic suite before submitting a code change:

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

The benchmark corpus is frozen because published findings refer to its exact bytes. Purpose-built coverage inputs belong under `bench/synthetic/`, and experiments should run on copies.

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the benchmark-impact policy and pull-request expectations.
Release maintainers should also follow [`RELEASING.md`](RELEASING.md) for the
crate-publication order, tag checks, and post-release smoke tests.

## Contributing and security

Contributions are welcome. Read [`CONTRIBUTING.md`](CONTRIBUTING.md) before changing measured behavior or benchmark artifacts.

Report ordinary bugs and feature ideas through GitHub issues. Report potential vulnerabilities through GitHub private vulnerability reporting as described in [`SECURITY.md`](SECURITY.md).

## License

Incise is available under the MIT License. See [`LICENSE`](LICENSE).
