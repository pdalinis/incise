# Incise for Hermes

This plugin gives Hermes Agent a model-agnostic eight-tool Markdown interface plus guarded request routing for measured Gemma and Ornith models. Models can inspect and edit tables, lists, sections, and YAML frontmatter without reconstructing the surrounding document.

The adapter keeps Markdown semantics in the `incise` binary. Hermes owns tool registration, model-request narrowing, filesystem policy, same-file serialization, rollback, and the one-successful-mutation turn guard.

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

**4. Select a profile.**

For measured Gemma and Ornith models, use the recommended automatic profile:

```bash
INCISE_PROFILE=auto hermes chat
```

`auto` recognizes model IDs or names containing `gemma` or `ornith`. If a provider uses a generic alias, identify the backend explicitly:

```bash
INCISE_PROFILE=auto INCISE_MODEL_FAMILY=ornith hermes chat --reasoning none
```

Use `INCISE_MODEL_FAMILY=gemma` for a generic Gemma alias. Unknown models and MiniCPM safely retain the standard eight-tool surface under `auto`. For the measured Ornith condition, also configure a 2,048-token output cap and disable parallel tool calls in the provider; the plugin does not silently alter normal inference settings.

Use `INCISE_PROFILE=standard` to force the model-agnostic eight-tool composition, or `INCISE_PROFILE=safe-routed` to force guarded routing regardless of detected identity. `safe-routed` is intended for controlled evaluation when the caller already knows the model family; `auto` is the normal recommendation.

**5. Verify the installation.**

```bash
hermes plugins list --plain --no-bundled
hermes tools list --platform cli
hermes plugins doctor --ci incise
```

The output should show `incise` enabled. Doctor registers eight tools for `standard`, twelve for `safe-small`, or twenty-four for `auto`/`safe-routed`; the latter includes sixteen route handlers that middleware narrows before each provider request. Doctor may warn that manifest-declared tools from inactive profiles are absent.

Verification prints the exact binary path and resolution source before the doctor report. Confirm that path belongs to the same release or source checkout as the plugin. For a source-linked plugin, build with `cargo build -p incise-cli --locked` or `cargo build --release -p incise-cli --locked`; Incise chooses the newest executable checkout build, with release winning only an exact timestamp tie.

## Tools exposed

**Standard structural reads.** `md_outline` lists headings, `md_tables` lists tables and their ordinals, `md_lists` summarizes lists, and `table_get` returns rows from one addressed table. Read results include a content hash for stale-read protection.

**Standard semantic edits.** `table_edit`, `list_edit`, `section_edit`, and `frontmatter_edit` expose the measured model-agnostic schemas. They address content by heading, cell value, item text, key, and ordinal rather than by line number.

**Guarded routing.** With `INCISE_PROFILE=auto`, detected Gemma and Ornith requests are inspected before inference. Exact supported requests receive one of sixteen action-specific route tools; the provider sees only that one Incise tool. Unsupported or ambiguous requests receive the byte-identical standard eight-tool surface. Foreign Hermes tools remain available in both cases. After a routed mutation succeeds, Incise mutation tools are removed from later provider calls in that turn.

The plugin registers the union needed by the selected profile, but registration is not the provider-visible surface. `auto` registers the eight standard handlers and sixteen route handlers, then its request hook narrows them dynamically. Ordinary paragraph edits and initial file creation still belong to general file tools.

Set `INCISE_PROFILE=safe-small` only to evaluate the experimental MiniCPM composition. It exposes `md_tables`, `table_get`, `table_add_row`, `table_update_cell`, `md_lists`, `list_get`, `list_add_item`, `md_outline`, `section_insert`, `section_append`, `frontmatter_get`, and `frontmatter_set`. It intentionally omits generic multi-action tools and destructive section/frontmatter operations. A preregistered MiniCPM5 run found a significant list-addition gain but section and frontmatter regressions, so this profile is not recommended for general use.

## How it works

At registration, the plugin asks the binary for the five measured schemas: `table_edit`, `list_edit`, `section_edit`, `frontmatter_edit`, and `table_get`. It adds three narrow structural reads—`md_tables`, `md_lists`, and `md_outline`—and registers the selected profile’s handlers as the `incise` toolset.

Under `standard`, calls pass through Hermes file-safety checks to the matching Incise command. Under `auto`, a turn-start hook classifies the model family and exact user request, inspects current document structure, retains the content hash, and either selects one guarded route or records a standard fallback. A request hook then exposes the exact Incise surface for that turn while preserving unrelated tools. Route handlers ignore model-supplied structural guesses and execute only the host-resolved arguments.

The adapter does not reimplement Markdown parsing or mutation semantics. Incise performs the semantic lookup, byte-preserving splice, and atomic write. Hermes adds its native read/write policy, same-file lock, stale-read protection, compound rollback, and a one-successful-mutation latch. Successful compound results name every completed operation so reasoning models can close the turn without issuing a redundant correction.

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

Every path is checked through `agent.file_safety` before the binary runs, using the same read blocks, write denylist, safe-root policy, and approval checks as Hermes’s built-in file tools. If those host guards cannot be imported, the plugin fails closed and refuses all paths.

Writes targeting the same resolved file are serialized inside the Hermes process. Calls for different files may run concurrently. The CLI performs atomic replacement and stale-read protection through content hashes. Routed compound operations roll back to the original bytes if any sub-operation fails, and a successful routed mutation removes further Incise mutation tools for that turn.

Routing is additive integration behavior, not a relaxed executor contract. Every host-resolved argument still passes through Incise’s normal address, type, ambiguity, and preservation checks. Unknown model families and unsupported requests keep the standard interface.

Incise refusals are safety behavior. Follow the remedy in the returned error instead of falling back to a whole-file rewrite.

## Validation

The adapter passes standalone and installed-host tests for registration, provider narrowing, schema identity, foreign-tool preservation, refusals, path safety, same-file locking, stale hashes, rollback, compound result framing, every route handler, and the one-success latch. Hermes Plugin Doctor loads the plugin and its two hooks under the real host. A deterministic parity audit matched all 48 frozen Pi route decisions, including exact route tool names and host-resolved arguments.

Two preregistered full-composition runs drove Hermes Agent 0.21.3 through its real stream-JSON loop. Ornith 1.5 9B Q8 completed **480/480 correct** and Gemma 4 26B completed **480/480 correct**. Each run contained 360 routed and 120 fallback trials, with zero harmful outcomes, zero framing errors, zero multiple mutations, and no retries. Every family was perfect: tables 60/60, lists 100/100, sections 150/150, frontmatter 110/110, and table reads 60/60.

The paired Ornith standard control scored 460/480. `auto` produced 20 treatment-only wins and no control-only wins (exact McNemar `p = 1.907×10⁻⁶`), repairing ten nested-frontmatter and ten filtered-read failures. Ornith used reasoning off, `max_tokens: 2048`, and `parallel_tool_calls: false`; Gemma retained its recorded provider defaults. Results are scoped to the recorded models, runtime, 48 tasks, seeds 40–49, and settings.

The earlier Gemma 5/5 and MiniCPM 5/5 standard-profile smoke remains valid for its narrow integration scope. MiniCPM has not cleared the full routed release gates and therefore stays on standard under `auto`.

## Troubleshooting

**The plugin is not listed.** Confirm that `~/.hermes/plugins/incise` exists and contains `plugin.yaml`. The installed directory and every configuration reference must use `incise`, not the retired `fastmd` name.

**The plugin is enabled but its tools are missing.** Run `hermes tools enable --platform cli incise`, then inspect `hermes tools list --platform cli`. Restart an already-running Hermes session after configuration changes.

**`auto` shows the standard tools for Gemma or Ornith.** Hermes may expose a generic provider alias. Set `INCISE_MODEL_FAMILY=gemma` or `INCISE_MODEL_FAMILY=ornith` in the environment that launches Hermes. Unknown identities intentionally fall back to standard.

**Doctor selected the wrong binary.** Read the `incise plugin: binary ...` line printed before the report. Resolution is `INCISE_BIN` first; for a source-linked checkout, the newest executable release/debug build comes next; an `incise` found on `PATH` is the final fallback. Rebuild the checkout or update the environment that launches Hermes, then restart it.

**Doctor warns about conditionally absent tools.** The manifest declares the union across profiles. Doctor may warn that inactive names were not registered. The expected registration count is eight for `standard`, twelve for `safe-small`, and twenty-four for `auto` or `safe-routed`. Provider requests under routing still receive exactly one Incise route tool or the standard eight, not all twenty-four.

**Tools refuse every path.** The plugin intentionally fails closed when Hermes file-safety guards cannot load. Run `hermes plugins doctor --ci incise` under the same environment that launches Hermes and confirm the installed Hermes version is at least 0.21.3.

**After upgrading.** Reinstall the CLI with `cargo install incise-cli --locked --force`, then extract the matching `incise-hermes-vX.Y.Z.tar.gz` over the plugin directory and restart Hermes. For a source-linked installation, check out the matching Incise tag and rebuild. Run doctor again after either upgrade path.

## Development and tests

Build the CLI and run the standalone adapter suite with:

```bash
cargo build -p incise-cli --locked
INCISE_TEST_NO_HERMES=1 INCISE_BIN="$PWD/target/debug/incise" \
  python3 plugins/hermes/test_plugin.py
```

When Hermes is installed locally, omit `INCISE_TEST_NO_HERMES` to exercise the real host file-safety integration. Validate the linked plugin separately:

```bash
hermes plugins doctor --ci incise
```

Doctor prints the selected binary. In a source checkout, rebuild immediately before validation; the plugin chooses whichever executable checkout build is newest. The adapter tests cover binary selection, every profile, registration, model detection and override, provider narrowing, foreign-tool preservation, schema identity, refusal passthrough, path safety, same-file serialization, stale hashes, rollback, compound results, every routed action, and the one-success latch. Markdown edit semantics are tested in the Rust core and the independent Python differential suite.
