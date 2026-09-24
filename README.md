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

Language models are often good at identifying the change a document needs and much less reliable at reproducing the surrounding Markdown exactly. A one-cell update can require pipe escaping, alignment arithmetic, line-ending preservation, and a byte-perfect rewrite of unrelated content.

> **Latest Ornith result:** the recommended Pi `auto` profile completed **480/480 trials (100%) with zero harmful outcomes**. Every family was perfect, and all 360 routed trials used the exact expected tool and host-resolved arguments.

> **Current Gemma result:** the same `auto` profile completed **475/479 usable trials (99.2%) with zero harmful outcomes**. Tables, lists, frontmatter, and table reads were perfect; the four remaining section outcomes were loud refusals.

Incise separates intent from mechanics:

* **Semantic addresses:** select headings, rows, items, and keys by content rather than line number.
* **Minimal edits:** change only the targeted structural range.
* **Actionable refusals:** ambiguous or unsafe requests fail loudly instead of choosing a plausible target.
* **Model-aware composition:** integrations can expose a smaller, safer action surface while retaining the standard tools as a fallback.

It is built for AI-maintained documentation, Obsidian vaults, Markdown knowledge bases, and local models with limited context. Incise is not a WYSIWYG editor, knowledge graph, or vault index; it is the deterministic mutation layer used after an agent decides which file and fact to change.

The figures come from preregistered 480-trial Pi evaluations and remain scoped to their recorded models, runtimes, task set, profile, and inference settings. Ornith used thinking off, a 2,048-token output cap, and disabled parallel tool calls; Gemma retained its normal provider defaults.

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

Install the version-matched plugin bundle, enable its `incise` toolset, and run `hermes plugins doctor --ci incise`. Doctor prints the exact binary it validated. See the [Hermes integration guide](plugins/hermes/README.md) for complete installation and safety details.

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

The adapter exposes the standard model-agnostic edit and read schemas behind Hermes’s native file-safety policy. The current release-candidate smoke completed all five representative tasks on both Gemma and MiniCPM with exact expected diffs. This is an integration check, not the Pi-specific Ornith or Gemma composition benchmark.

Incise remains deliberately scoped to Markdown structures it understands. Generic editing is appropriate for ordinary prose and initial document creation.

---

## Use with Pi

Install the published [`pi-incise` package from npm](https://www.npmjs.com/package/pi-incise):

```bash
pi install npm:pi-incise
```

For Gemma, start Pi with the measured automatic profile:

```bash
INCISE_PROFILE=auto pi
```

For Ornith 1.5 9B, use the same automatic profile with thinking disabled:

```bash
INCISE_PROFILE=auto pi --thinking off
```

Configure the Ornith model entry with `maxTokens: 2048` and `samplingParams.parallel_tool_calls: false`. The extension detects model IDs or names containing `ornith`. If a local provider exposes a generic model ID, add `INCISE_MODEL_FAMILY=ornith`.

`auto` enables the guarded `safe-routed` profile for measured Gemma and Ornith identities. Requests that can be resolved exactly receive one small action-specific tool; unsupported or ambiguous requests retain the standard Incise tools. Run `/incise-doctor` to see the detected model, effective profile, binary, schemas, registered tools, and last route.

For MiniCPM, use the standard profile for general editing:

```bash
INCISE_PROFILE=standard pi
```

An opt-in `minicpm-list` profile is available for the measured list-addition workflow only. It reached 16/21 through real Pi with every executed mutation correct, but it is not a general MiniCPM profile and remains experimental.

The package includes native binaries for macOS arm64/x64 and glibc Linux arm64/x64. Windows and musl Linux are not currently supported. See [the Pi integration guide](plugins/pi/README.md) for profile behavior, model overrides, inference settings, and exact evaluation scope.

## Safety model

Incise is designed around five guarantees:

* **Semantic addressing:** targets use heading paths, cell values, item text, keys, and ordinals—never line numbers.
* **Byte-preserving splices:** unrelated document bytes remain identical.
* **Loud ambiguity:** malformed, unsupported, or non-unique targets produce an actionable refusal.
* **Safe writes:** the CLI supports dry runs, atomic replacement, no-op detection, and content-hash preconditions.
* **Token-frugal results:** successful writes describe the change instead of returning the whole document.

The standard interface remains model-agnostic. Model-specific profiles are additive integration behavior: they narrow the active tool surface, validate current structure, retain content hashes, and stop after one successful routed mutation.

MiniCPM support is intentionally conservative. Core singleton-row compatibility passed 18/18 live table trials, including all 9 singleton-object-array calls. The opt-in list pipeline also shows strong targeted results, but broader MiniCPM profiles have not cleared the project’s zero-data-loss and no-regression gates. Incise therefore does not silently enable a general MiniCPM profile.

Refusals are part of the safety contract. If an operation cannot prove one target or preserve the requested structure, it reports the conflicting matches or missing requirement and writes nothing.

## Measured with small models

The strongest current result is Ornith 1.5 9B through Pi: **480/480 trials correct (100%) with zero harmful outcomes** under the recorded reasoning-off configuration. The current Gemma/Pi `auto` profile remains **475/479 usable trials correct (99.2%) with zero harmful outcomes**.

### Current Ornith/Pi profile

| Family | Correct | Safety result |
| --- | ---: | --- |
| Tables | **60/60** | Zero harmful outcomes |
| Lists | **100/100** | Zero harmful outcomes |
| Sections | **150/150** | Zero harmful outcomes |
| Frontmatter | **110/110** | Zero harmful outcomes |
| Table reads | **60/60** | Read-only |
| Routed subset | **360/360** | No route, argument, framing, or multiple-mutation errors |

The final preregistered holdout used Ornith 1.5 9B Q8 through llama.cpp and Pi with thinking off, `maxTokens: 2048`, `parallel_tool_calls: false`, and the measured `safe-routed` composition. All 480 trials were usable and correct. A preceding holdout stopped after one destructive fallback at 237/238; a narrow outline-verified route repaired that exact failure, passed 10/10 Ornith and 20/20 Gemma compatibility trials, and the complete holdout was then rerun from the beginning. The result is scoped to the recorded runtime, prompts, tasks, seeds, and settings.

### Current Gemma/Pi profile

| Family | Correct | Safety result |
| --- | ---: | --- |
| Tables | **60/60** | Zero harmful outcomes |
| Lists | **100/100** | Zero harmful outcomes |
| Sections | **145/149** | Four loud refusals; no wrong edits |
| Frontmatter | **110/110** | Zero harmful outcomes |
| Table reads | **60/60** | Read-only |
| Routed subset | **200/200** | No route, argument, filter, or multiple-mutation errors |

The preregistered run attempted 480 trials. One `rename-setext` pair hit the fixed generation timeout twice and was excluded under the frozen analysis rule, leaving 479 paired results. The latest incremental route moved correctness from 473/479 to 475/479 and harmful outcomes from one to zero; that incremental difference is descriptive (`p = 0.625`), while the zero-harm and targeted-repair gates passed.

### MiniCPM progress

MiniCPM is promising, but the supported surface is deliberately narrower:

* Singleton-object table rows passed **18/18** live trials, including **9/9** compatibility normalizations, with no corruption or data loss.
* An adapter-independent, host-routed list pipeline improved supported additions from **13/21 to 21/21** (`p = 0.0078`) with no regressions or harmful outcomes.
* The same opt-in pipeline reached **16/21** through real Pi. All 16 executed mutations were correct; five failures were no-call prose responses.
* Broader MiniCPM compositions remain experimental because they have not passed the project’s family and zero-data-loss gates.

### Structured operations versus direct patching

The original recorded benchmark compared direct `patch` calls with Incise operations on identical tasks, seeds, model, and grader:

| Operation | Direct `patch` | Incise | Mean Incise output |
| --- | ---: | ---: | ---: |
| Tables | 60.0% (36/60) | **100% (60/60)** | 66 tokens |
| Lists | 63.0% (63/100) | **91.0% (91/100)** | 58 tokens |
| Sections | 19.0% (19/100) | **74.0% (74/100)** | 60 tokens |

These are scoped model measurements, not promises about every model or runtime. The reusable result is the failure class removed: character arithmetic, structural-boundary guesses, ambiguous targeting, and byte-for-byte document reconstruction.

Read the [benchmark summary](https://pdalinis.github.io/incise/benchmarks/), the complete [`bench/FINDINGS.md`](bench/FINDINGS.md), or inspect the [Ornith final analysis](bench/results/ornith_final_v2_safe_routed_20260923_analysis.json), [exact-route audit](bench/results/ornith_final_v2_routes_20260923_analysis.json), and [Gemma v8 analysis](bench/results/gemma_safe_routed_full_v8_20260922_analysis.json).

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
