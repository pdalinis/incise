# Incise for Hermes

This plugin gives Hermes Agent eight structure-aware Markdown tools backed by the `incise` binary. Models can inspect and edit tables, lists, sections, and YAML frontmatter without reconstructing the surrounding document.

The adapter stays intentionally thin: Hermes handles tool registration and filesystem policy, while Incise performs the parse, semantic lookup, byte-preserving splice, and atomic write.

## Requirements

Hermes Agent 0.21.3 or newer is required. Incise currently supports Linux and macOS; Windows is not supported or tested.

The plugin has no Python package dependencies, but it requires an `incise` binary from the same release or checkout. Keeping the plugin and CLI together prevents tool schemas and executable behavior from drifting.

## Installation

Install the CLI and plugin from the same Incise release so their schemas and behavior stay in sync.

**1. Install the CLI.**

```bash
cargo install incise-cli --locked
incise --version
```

Ensure the Cargo bin directory is on `PATH`, normally `$HOME/.cargo/bin`. Alternatively, set `INCISE_BIN` to an absolute binary path in the environment that launches Hermes. Prebuilt Linux and macOS binaries are also available from [GitHub Releases](https://github.com/pdalinis/incise/releases).

**2. Install the matching Hermes plugin bundle.**

```bash
release="v$(incise --version | awk '{print $2}')"
mkdir -p "$HOME/.hermes/plugins"
curl --fail --location --silent --show-error \
  "https://github.com/pdalinis/incise/releases/download/$release/incise-hermes-$release.tar.gz" \
  | tar -xz -C "$HOME/.hermes/plugins"
```

The archive creates `$HOME/.hermes/plugins/incise`. The installed directory must be named `incise`.

For development or a source-based installation, clone the matching tag and link the plugin directory instead:

```bash
release="v$(incise --version | awk '{print $2}')"
git clone --branch "$release" --depth 1 \
  https://github.com/pdalinis/incise.git incise-source
mkdir -p "$HOME/.hermes/plugins"
ln -s "$PWD/incise-source/plugins/hermes" "$HOME/.hermes/plugins/incise"
```

**3. Enable the plugin and its CLI toolset.**

```bash
hermes plugins enable --no-allow-tool-override incise
hermes tools enable --platform cli incise
```

Incise does not replace built-in tools, so tool-override permission is unnecessary.

**4. Verify the installation.**

```bash
hermes plugins list --plain --no-bundled
hermes tools list --platform cli
hermes plugins doctor --ci incise
```

The output should show `incise` enabled and doctor should report eight registered tools. These commands maintain `~/.hermes/config.yaml`; manual configuration is normally unnecessary. Any identifier left as `fastmd` is stale and should be changed to `incise`.

## Tools exposed

**Structural reads.** `md_outline` lists headings, `md_tables` lists tables and their ordinals, `md_lists` summarizes lists, and `table_get` returns rows from one addressed table. Read results include a content hash for stale-read protection.

**Semantic edits.** `table_edit`, `list_edit`, `section_edit`, and `frontmatter_edit` expose the measured Incise schemas. They address content by heading, cell value, item text, key, and ordinal rather than by line number.

The plugin toolset is intentionally limited to those eight tools. Ordinary paragraph edits and initial file creation still belong to general file tools.

## How it works

At registration, the plugin asks the binary for the five measured schemas: `table_edit`, `list_edit`, `section_edit`, `frontmatter_edit`, and `table_get`. It adds three narrow structural reads—`md_tables`, `md_lists`, and `md_outline`—and registers all eight as the `incise` toolset.

For each call, the adapter checks the path with Hermes file-safety rules, maps the tool action to an Incise subcommand, and passes the argument object to the binary. It does not parse Markdown or maintain a second implementation of the edit rules. Successful writes return a short description and content hash; refusals preserve the actionable message produced by Incise.

The separate read tools are intentional. A previous combined read tool introduced an enum that models confused with edit actions, while the retired `md_rows` interface could not address repeated tables by ordinal. The detailed measurements and design history remain in [`bench/FINDINGS.md`](https://github.com/pdalinis/incise/blob/main/bench/FINDINGS.md).

## Agent guidance

Hermes will expose Incise tools when the toolset is enabled, but repository guidance helps the model choose them consistently. Add a rule like this to the relevant `AGENTS.md`:

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

## Safety

Every path is checked through `agent.file_safety` before the binary runs, using the same read blocks, write denylist, safe-root policy, and approval checks as the built-in Hermes file tools. If those host guards cannot be imported, the plugin fails closed and refuses all paths.

Writes targeting the same resolved file are serialized inside the Hermes process. Calls for different files may run concurrently. The CLI also performs atomic replacement and optional stale-read protection through the content hash and `if_match` argument.

Incise refusals are safety behavior. Follow the remedy in the returned error instead of falling back to a whole-file rewrite.

## Troubleshooting

**The plugin is not listed.** Confirm that `~/.hermes/plugins/incise` exists and contains `plugin.yaml`. The installed directory and every configuration reference must use `incise`, not the retired `fastmd` name.

**The plugin is enabled but its tools are missing.** Run `hermes tools enable --platform cli incise`, then inspect `hermes tools list --platform cli`. Restart an already-running Hermes session after configuration changes.

**Doctor reports that the binary is unavailable.** The lookup order is `INCISE_BIN`, `PATH`, then `target/release/incise` and `target/debug/incise` relative to a source checkout. Install the released binary with `cargo install incise-cli --locked` or set `INCISE_BIN` explicitly.

**Tools refuse every path.** The plugin intentionally fails closed when Hermes file-safety guards cannot load. Run `hermes plugins doctor --ci incise` under the same environment that launches Hermes and confirm the installed Hermes version is at least 0.21.3.

**After upgrading.** Reinstall the CLI with `cargo install incise-cli --locked --force`, then extract the matching `incise-hermes-vX.Y.Z.tar.gz` over the plugin directory and restart Hermes. For a source-linked installation, check out the matching Incise tag instead. Run doctor again after either upgrade path.

## Development and tests

Build the debug binary and run the standalone adapter suite with:

```bash
cargo build -p incise-cli --locked
INCISE_TEST_NO_HERMES=1 INCISE_BIN="$PWD/target/debug/incise" \
  python3 plugins/hermes/test_plugin.py
```

When Hermes is installed locally, omit `INCISE_TEST_NO_HERMES` to exercise the real host file-safety integration. Validate the installed plugin separately with:

```bash
INCISE_BIN="$PWD/target/debug/incise" hermes plugins doctor --ci incise
```

The adapter tests cover registration, tool routing, schema identity, refusal passthrough, path safety, concurrency, and all published actions. Markdown edit semantics are tested in the Rust core and the independent Python differential suite.
