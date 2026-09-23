# Incise — semantic Markdown editing for AI agents

[![CI](https://github.com/pdalinis/incise/actions/workflows/ci.yml/badge.svg)](https://github.com/pdalinis/incise/actions/workflows/ci.yml)
[![crates.io](https://img.shields.io/crates/v/incise-cli.svg)](https://crates.io/crates/incise-cli)
[![npm](https://img.shields.io/npm/v/pi-incise.svg)](https://www.npmjs.com/package/pi-incise)
[![docs.rs](https://img.shields.io/docsrs/incise-core.svg)](https://docs.rs/incise-core)
[![license](https://img.shields.io/badge/license-MIT-76e0b5.svg)](LICENSE)

**Safe, semantic, byte-preserving Markdown edits for AI agents and automation.**

Incise is a CLI and agent-tool backend for precise updates to Markdown tables, lists, sections, and YAML frontmatter. The caller expresses what should change; deterministic code handles formatting, boundaries, and the smallest possible splice.

```text
Model intent:  In the Projects table, set Launch to done.
Incise:        Address the table, row, and column by content.
Result:        One targeted edit; unrelated bytes stay unchanged.
```

[Documentation](https://pdalinis.github.io/incise/) · [Install](#quick-start) · [Benchmarks](#measured-with-small-models) · [Releases](https://github.com/pdalinis/incise/releases)

## Why Incise?

Language models can identify the change a document needs but are less reliable at reproducing surrounding Markdown exactly. A one-cell table update can require pipe escaping, alignment arithmetic, line-ending preservation, and a byte-perfect rewrite of unrelated content.

Incise separates intent from mechanics:

* **Semantic addresses:** select headings, rows, items, and keys by content rather than line number.
* **Minimal edits:** change only the targeted structural range.
* **Actionable refusals:** ambiguous or unsafe requests fail loudly instead of choosing a plausible target.

It is built for AI-maintained documentation, Obsidian vaults, Markdown knowledge bases, and local models with limited context. Incise is not a WYSIWYG editor, knowledge graph, or vault index; it is the deterministic mutation layer used after an agent decides which file and fact to change.

## Quick start

### Install from crates.io

Install [`incise-cli` from crates.io](https://crates.io/crates/incise-cli):

```bash
cargo install incise-cli --locked
incise --version
```

Prebuilt Linux and macOS archives are available from [GitHub Releases](https://github.com/pdalinis/incise/releases).

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

For exact values after structural discovery, use `incise rows notes.md --table Components`, `incise items notes.md --list Tasks`, or `incise keys notes.md`. Their JSON forms carry the structured rows, list items, or flattened frontmatter keys together with the file hash.

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

## What Incise can edit

| Markdown structure   | Operations                                                            |
| -------------------- | --------------------------------------------------------------------- |
| **Tables**           | Add rows, update cells, delete rows, realign columns, query rows      |
| **Lists & tasks**    | Add/remove items, toggle checkboxes                                   |
| **Sections**         | Append, replace, insert, delete, rename, change heading levels        |
| **YAML frontmatter** | Read, set, and delete nested keys                                     |
| **Structure**        | Discover headings, tables, lists, frontmatter, rows, keys, and hashes |

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

Install the published [`pi-incise` package from npm](https://www.npmjs.com/package/pi-incise):

```bash
pi install npm:pi-incise
pi
```

The package provides native binaries for macOS arm64/x64 and glibc Linux arm64/x64. The default `standard` profile registers the three structural readers, `table_get`, and all four structured edit tools. Run `/incise-doctor` inside Pi to inspect the selected binary, schemas, tools, and profile decision.

For Gemma, the recommended Pi setup is `INCISE_PROFILE=auto pi`. Auto-detection enables the measured `safe-routed` capabilities for Gemma and stays on `standard` for model families without a validated general profile. The routed profile host-resolves exact section rename/body-replacement targets, explicit literal section insertions and quoted-sentence appends, explicit table predicates, typed existing-key frontmatter edits, guarded creation of `build.cache`, exact quoted list-item removals, and same-heading lists identified by an exact existing item before exposing one small action-specific tool; other requests retain the standard tools. In the latest full Pi evaluation, the treatment attempted all 480 trials and retained 479 paired rows after one persistent generation timeout. Correctness rose from 473/479 to 475/479 and harmful outcomes fell from 1 to 0; lists reached 100/100, sections 145/149 with only loud refusals, frontmatter 110/110, and tables plus table reads 60/60. All 200 routed trials were correct, and all 279 usable fallback trials retained the standard tool surface. The package default remains `standard` for compatibility. See [`plugins/pi/README.md`](plugins/pi/README.md) for model detection, overrides, and evaluation details.

## Safety model

Incise is designed around five guarantees:

* **Semantic addressing:** targets use heading paths, cell values, item text, keys, and ordinals—never line numbers.
* **Byte-preserving splices:** unrelated document bytes remain identical.
* **Loud ambiguity:** malformed, unsupported, or non-unique targets produce an actionable refusal.
* **Safe writes:** the CLI supports dry runs, atomic replacement, no-op detection, and content-hash preconditions.
* **Token-frugal results:** successful writes describe the change instead of returning the whole document.

An experimental `safe-small` profile is available with `INCISE_PROFILE=safe-small` in Hermes or Pi, and its schemas can be inspected with `incise schema --profile safe-small`. It adds structural reads, one-operation write tools, and omits destructive operations. It is **not recommended as a general profile**: a preregistered MiniCPM5 run improved list additions from 8/21 to 15/21 but regressed sections from 8/27 to 4/27 and frontmatter from 14/27 to 0/27.

A subsequent preregistered routed experiment constrained MiniCPM5 to action-specific tools and stopped after the first mutation. It improved the pooled result from 40/90 to 54/90 (`p = 0.0125`) while cutting mean generation from 247 to 109 tokens, but two wrong-key frontmatter overwrites violated the zero-data-loss gate. A preregistered stored-call replay then added host-owned create/update preconditions: both destructive calls became loud refusals and all 18 previously correct frontmatter results remained byte-identical. Merely exposing nested atomic section children remained 0/12 because MiniCPM ignored the field; moving structure into the host and using optional flat slots reached 6/12, while cardinality-routed micro-schemas with every requested slot required reached 12/12. The default remains unchanged: the result validates the architecture, but the classifier that must derive file, anchor, position, and child count from real requests is not yet measured.

The follow-up classifier is now measured: a two-phase MiniCPM planner recovered only 3/12 section insertions, versus 12/12 when the host already knew the structure. It remained safe, with no destructive or collateral edits, but the model confused executor placement terms and subsection counts. MiniCPM support therefore remains opt-in and host-routed; Gemma and the default schemas are unchanged.

A planner-only follow-up using request-language labels also failed (0/12 exact plans). MiniCPM copied section anchors reliably, but it did not reliably distinguish sibling placement from subsection placement or body text from named nested headings. Further schema-only section routing is therefore not planned.

List placement responds better to request-shaped routing. After `list_get`, requiring an exact returned anchor solved 3/3 explicit-after insertions; requiring both adjacent boundaries solved 3/3 between-item insertions. These are small, model-specific evaluation results, not default tool changes.

When both list-placement tools were exposed together, final edits reached 6/6, but MiniCPM always chose the after-style tool; the preregistered routing gate therefore failed. The result supports exact dynamic anchors, not autonomous relation routing.

For list selection, separately required `heading` and `ordinal` fields reached 6/6 correct addresses and edits, while a single serialized metadata handle reached only 1/6. MiniCPM integrations should prefer small required fields with host validation over compound string encodings.

A preregistered integrated MiniCPM list pipeline combined structured heading-and-ordinal selection, automatic list inspection, host-owned append/after/between routing, and exact validated anchors. It improved the full supported add-item population from **13/21 to 21/21** (eight treatment-only wins, no regressions, exact McNemar p = 0.0078), with zero destructive or collateral outcomes and mean completion reduced from 117 to 68 tokens. This supports an opt-in MiniCPM integration path; default Gemma tools and schemas remain unchanged.

The first real-Pi run of that profile reached **16/21**, not the direct arm’s 21/21. All 16 executed mutations were correct and no document was damaged, but MiniCPM sometimes answered in prose instead of calling Pi’s sole active tool. A preregistered forced-choice follow-up also scored 16/21: all 39 active-phase provider requests carried the exact advertised `tool_choice`, yet the local MiniCPM/llama.cpp path still returned prose on the same five phases. A compact profile prompt then reached 19/21 and eliminated every no-call failure, but regressed two previously correct nested-item edits by supplying the wrong new text. Both ineffective treatments were removed. The Pi profile remains experimental and is not enabled by default.

## Measured with small models

The recorded benchmark compares direct `patch` calls with Incise operations on the same tasks, model, seeds, and grader.

| Operation | Direct `patch` | Incise         | Mean Incise output |
| --------- | -------------: | -------------: | -----------------: |
| Tables    | 60.0% (36/60)  | 100% (60/60)   | 66 tokens          |
| Lists     | 63.0% (63/100) | 91.0% (91/100) | 58 tokens          |
| Sections  | 19.0% (19/100) | 74.0% (74/100) | 60 tokens          |

These results describe one small local model under recorded conditions, not every model. The useful result is the class of failure removed: character arithmetic, structural-boundary mistakes, and byte-for-byte reconstruction.

Read the [benchmark summary](https://pdalinis.github.io/incise/benchmarks/), the complete [`bench/FINDINGS.md`](bench/FINDINGS.md), or jump to the source findings for [tables](bench/FINDINGS.md#f1--alignment-maintenance-is-the-failure-isolated), [lists](bench/FINDINGS.md#lists--the-second-op-family), [sections](bench/FINDINGS.md#s7--the-sections-arm-a-baseline-19-correct-28-data-loss), and [frontmatter](bench/FINDINGS.md#f-frontmatter--the-fourth-family-and-the-verb-that-deleted-the-version).

The dependency-free Rust core is checked byte-for-byte against an independent Python oracle across **110,406 generated cases over 54 fixtures**. Property invariants and 212 injected mutations provide additional evidence that preservation failures are detected.

## Frequently asked questions

### What is byte-preserving Markdown editing?

Incise changes the smallest structural range required by an operation. Bytes outside that range remain identical, so an agent does not have to reproduce the rest of the document.

### Can Incise edit an Obsidian vault?

Yes. Incise works directly on Markdown files and leaves unrelated wikilinks, callouts, block IDs, embeds, comments, and prose untouched. It does not index or search the vault; another tool chooses the file to edit.

### How does an AI agent use Incise?

The agent first inspects document structure, then calls a semantic editor with a content-based address. Use `incise schema` for the function definitions or install the Hermes or Pi integration.

### How do I update YAML frontmatter without reformatting?

Inspect keys with `incise keys FILE`, then call `incise frontmatter-set FILE --key PATH --value VALUE`. Incise preserves unrelated key order, comments, scalar formatting, and document content. See the [frontmatter guide](https://pdalinis.github.io/incise/yaml-frontmatter-cli/).

## Documentation

The [Incise documentation site](https://pdalinis.github.io/incise/) covers installation and the core workflow, with focused guides for [Markdown tables](https://pdalinis.github.io/incise/markdown-table-editor-for-ai-agents/), [YAML frontmatter](https://pdalinis.github.io/incise/yaml-frontmatter-cli/), and [Obsidian vaults](https://pdalinis.github.io/incise/obsidian-ai-agent-editing/).

Run `incise --help` for every command or `incise <command> --help` for its arguments. Integration details live in the [Hermes guide](plugins/hermes/README.md) and [Pi package guide](plugins/pi/README.md).

## Project status

Incise uses 0.x versioning and is under active development. It currently supports tables, lists, sections, YAML frontmatter, structural reads, semantic addressing, dry runs, atomic writes, stale-read protection, and agent-tool schemas.

Linux and macOS are supported. Windows is not currently supported or tested. Scoped search and replace and multi-operation transactions remain planned.

Behavioral claims stay tied to the model, prompts, schemas, tasks, and executor that produced them. A tool-description or refusal change may require remeasurement even when deterministic tests still pass.

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
