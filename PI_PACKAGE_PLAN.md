# Plan to Publish Incise as a Pi Package

The recommended v1 is a `pi-incise` npm package containing a thin Pi extension plus prebuilt Incise binaries. Installation should require one command and no Rust toolchain, manual `PATH` setup, or install script.

## Proposed package

The package should expose the same eight tools as the existing Hermes integration:

- `table_edit`
- `list_edit`
- `section_edit`
- `frontmatter_edit`
- `table_get`
- `md_tables`
- `md_lists`
- `md_outline`

The extension remains a translator:

1. Load the five measured schemas from `incise schema`.
2. Register those schemas without rewriting their descriptions.
3. Register the three existing structural-read schemas.
4. Normalize calls exactly as the Hermes adapter does.
5. Run the native binary with `--json`.
6. Return write descriptions or read text without echoing entire documents.

Pi packages declare extensions in `package.json` and are installed through `pi install`; runtime imports belong in dependencies or peer dependencies. See the [Pi package documentation](https://pi.dev/docs/latest/packages).

## Phase 0: make the repository releasable

The Incise rename is complete across the executable, crates, integrations, and active documentation. Release automation still needs to build or download native artifacts before creating a GitHub release; a fresh release job cannot upload `target/release/incise` unless an earlier job produced and transferred it.

Before package work:

- Settle the public executable and crate names: preferably `incise`, `incise-cli`, and `incise-core`.
- Repair the crates.io and GitHub release workflow.
- Produce versioned binaries and checksums for macOS arm64/x64, Linux glibc arm64/x64, and Windows x64.
- Decide whether `INCISE_BIN` remains a temporary compatibility alias for the new `INCISE_BIN`.
- Reserve the npm names. `pi-incise` is preferred; use a scope if the unscoped name is unavailable.

Acceptance criterion: a release tag produces working native archives, crates, checksums, and a GitHub release from the same source revision.

## Phase 1: add the Pi extension

Create a package root such as:

```text
plugins/pi/
├── package.json
├── README.md
├── extension/
│   ├── index.ts
│   ├── binary.ts
│   ├── normalize.ts
│   ├── runner.ts
│   └── schemas.ts
└── test/
```

The manifest should include:

```json
{
  "name": "pi-incise",
  "keywords": ["pi-package", "markdown", "ai-agent"],
  "pi": {
    "extensions": ["./extension/index.ts"]
  },
  "peerDependencies": {
    "@earendil-works/pi-coding-agent": "*",
    "typebox": "*"
  }
}
```

Pi loads TypeScript extensions directly, so a compiled JavaScript bundle is unnecessary. See the [Pi extension documentation](https://pi.dev/docs/latest/extensions).

Port behavior from `plugins/hermes`, especially:

- Runtime schema discovery, with no vendored copy of the five measured schemas.
- Exact section argument normalization.
- No Markdown parsing in TypeScript.
- No independently worded refusals.
- Reads routed separately from writes.
- No tools registered when the binary or schema is unusable.

Add `/incise-doctor` to report the extension version, binary path and version, schema availability, and registered tools.

## Phase 2: package native binaries

Use platform-specific optional npm dependencies, following the standard native-CLI pattern:

```text
pi-incise
@scope/incise-darwin-arm64
@scope/incise-darwin-x64
@scope/incise-linux-arm64-gnu
@scope/incise-linux-x64-gnu
@scope/incise-win32-x64
```

Each native package should contain only its executable, license, metadata, and checksum information, with appropriate `os`, `cpu`, and where applicable `libc` constraints.

The main package resolves the binary in this order:

1. `INCISE_BIN`
2. Matching native optional dependency
3. `incise` on `PATH`
4. A development checkout's `target/release` or `target/debug`

Avoid `postinstall` downloads and source compilation. This gives users a lifecycle-script-free installation and does not require Cargo.

## Phase 3: integrate correctly with Pi

For each write:

- Remove a leading `@` from model-supplied paths, as Pi recommends for custom path tools.
- Resolve relative paths against `ctx.cwd`.
- Wrap the complete binary read-modify-write call in `withFileMutationQueue()`.
- Pass the model's argument object to the binary through `--args`.
- Return only the one-sentence description in model-visible content.
- Keep hash, path, and changed state in result `details`.

For reads:

- Return the renderer text unchanged.
- Keep hash and path in `details`.
- Pass `table_get` arguments through `--args` without translating them into flags.

For refusals:

- Throw an error containing only the binary's error text, since Pi requires thrown errors to set `isError`.
- Preserve distinct refusal, usage, and stale exit codes in result details or diagnostic logs.

Pi executes sibling tools in parallel by default, so participation in its file-mutation queue is required to avoid lost updates. See [Pi's custom-tool guidance](https://pi.dev/docs/latest/extensions#custom-tools).

Do not override or disable Pi's normal `edit` and `write` tools in v1. Incise is appropriate for structured Markdown changes, while raw editing is still needed for ordinary prose.

## Phase 4: handle the Pi validation divergence

Pi validates tool arguments against the advertised schema before calling `execute`. Incise deliberately prefers core-generated refusals, including their recovery advice. Pi currently offers no separate "advertise this schema but skip host validation" switch.

For v1:

- Publish the exact measured schemas.
- Accept that schema-invalid calls may receive Pi's validation error before Incise sees them.
- Do not weaken the schema merely to bypass Pi validation.
- Record this as an integration divergence, like the Hermes error-framing analysis.
- Run a focused benchmark comparing Pi validation errors with Incise refusals for missing and malformed arguments.

Valid calls and core refusals that pass schema validation must remain byte-for-byte equivalent to direct CLI behavior.

## Phase 5: make Pi actually use the tools

Add concise `promptSnippet` and `promptGuidelines` entries:

- Inspect with `md_tables`, `md_lists`, or `md_outline` before structured edits.
- Use the relevant Incise edit tool instead of reconstructing tables, lists, sections, or frontmatter.
- Follow an Incise refusal's remedy rather than falling back to whole-file replacement.

Keep this guidance short and tool-specific. Because prompt wording affects model behavior in this project, run it through the benchmark-impact policy rather than treating it as ordinary documentation.

Do not add extra frontmatter-read tools to v1. The measured five-tool composition plus the Hermes structural reads is the safest starting surface; additional tools should be evaluated separately.

## Phase 6: testing

Add four layers:

1. Adapter unit tests

   - Tool-to-subcommand mapping.
   - Section argument normalization.
   - Binary resolution.
   - Exit-code handling.
   - Leading-`@` and relative-path handling.
   - Timeout and cancellation behavior.

2. Contract tests

   - Registered five schemas equal `incise schema` exactly.
   - Structural-read outputs equal CLI outputs byte-for-byte.
   - Write success content contains only the description.
   - Refusal text is not prefixed or rewritten.

3. Pi integration tests

   - Load the packed extension through Pi.
   - Verify all eight tools are active.
   - Invoke reads and writes against temporary corpus copies.
   - Confirm two parallel writes to one file are serialized.
   - Exercise TUI-less print, JSON, and RPC modes.

4. Package tests

   - `npm pack --dry-run` includes only intended files.
   - A clean local `pi install <tarball>` succeeds.
   - `pi list` reports the package.
   - `/incise-doctor` passes.
   - Every supported OS and architecture receives a CI smoke test.

## Phase 7: publishing

Use one version across Rust crates, GitHub release, main npm package, and native npm packages.

Release order:

1. Run Rust, oracle, schema, Pi adapter, and package tests.
2. Build and sign or checksum the native artifacts.
3. Publish native npm packages.
4. Publish `pi-incise` last, initially under the `next` tag.
5. Install it through Pi on macOS, Linux, and Windows.
6. Promote the tested version to `latest`.
7. Publish the Pi gallery metadata and installation documentation.

Use npm trusted publishing with GitHub Actions provenance if the npm account supports it. Never overwrite a released binary package.

## Definition of done

A new user can run:

```bash
pi install npm:pi-incise
pi
```

They can then ask Pi to inspect and edit a Markdown table without installing Rust or configuring a binary. `pi list` shows the package, `/incise-doctor` passes, all eight tools are available, structured writes are serialized with Pi's native file queue, and valid tool behavior matches the Incise CLI.

Pi extensions and their subprocesses run with the user's full permissions; project trust is not a filesystem sandbox. The package README should state this clearly and point unattended users toward OS or container isolation. See the [Pi security model](https://pi.dev/docs/latest/security).
