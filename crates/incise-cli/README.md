# `incise` — the command-line front end

Safe, semantic Markdown edits for AI agents and automation.

The `incise-cli` crate installs the `incise` command. It edits tables, lists, sections, and YAML frontmatter by content rather than line number while preserving unrelated document bytes.

## Install

Install the current release from crates.io:

```bash
cargo install incise-cli --locked
incise --version
```

Prebuilt Linux and macOS archives are attached to [GitHub Releases](https://github.com/pdalinis/incise/releases). To build from source instead:

```bash
git clone https://github.com/pdalinis/incise.git
cd incise
cargo install --locked --path crates/incise-cli
```

## Why Incise

Language models can identify the change a document needs but are less reliable at reproducing surrounding Markdown exactly. Incise lets the caller address structure by heading, column value, list-item text, frontmatter key, or ordinal, then performs the smallest deterministic splice.

It supports table row and cell changes, list and checkbox changes, section insertion and editing, nested frontmatter updates, and narrow structural reads. Ambiguous or unsafe requests refuse with an actionable message instead of choosing a plausible target.

## Quick start

Inspect the relevant structure first:

```bash
incise tables vault/Projects.md
incise outline vault/Projects.md
incise lists vault/Projects.md
```

Then issue a semantic edit:

```bash
incise table-update-cell vault/Projects.md \
  --table Projects \
  --where Note=Launch \
  --column Status \
  --value done
```

Run `incise --help` for every operation and `incise <operation> --help` for its arguments.

## Agent integrations

Incise publishes the function schemas intended for model tool use:

```bash
incise schema
incise schema --tool table_edit
```

A harness can pass the model argument object directly to the corresponding command through `--args`. The repository also ships a [Hermes Agent plugin](https://github.com/pdalinis/incise/tree/main/plugins/hermes) with host file-safety integration and measured automatic routing for Gemma and Ornith, plus the published [`pi-incise`](https://www.npmjs.com/package/pi-incise) extension for Pi. Both integrations retain the model-agnostic standard surface for unknown models and unsupported requests.

## Safety and compatibility

Use `--dry-run` to preview a write. Use `incise hash FILE` and pass the result through `--if-match HASH` when another process may have changed the file since it was read. Successful writes use atomic replacement, no-op edits leave modification times unchanged, and unrelated bytes remain untouched.

Incise currently supports Linux and macOS. Windows is not supported or tested. The minimum supported Rust version for source builds is 1.85.

## Documentation

The [project README](https://github.com/pdalinis/incise) covers the editing model, supported structures, agent guidance, evidence, and development workflow. The [Hermes plugin guide](https://github.com/pdalinis/incise/tree/main/plugins/hermes) covers installation and tool registration.

Incise is available under the [MIT License](https://github.com/pdalinis/incise/blob/main/LICENSE).
