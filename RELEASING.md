# Releasing Incise

Releases are tag-driven. A tag named `vX.Y.Z` must match the workspace version
in `Cargo.toml`; the release workflow refuses a mismatch.

## One-time repository setup

- Add a `CARGO_REGISTRY_TOKEN` Actions secret with permission to publish both
  `incise-core` and `incise-cli`.
- Keep GitHub private vulnerability reporting enabled.
- Protect the default branch and require the CI workflow once its first run is
  green.
- Require full-length commit SHAs for Actions after the first workflow files are present.

## Before tagging

1. Update the workspace version in `Cargo.toml`, the Hermes plugin version in
   `plugins/hermes/plugin.yaml`, and `Cargo.lock` together.
2. Run the commands in the Development section of `README.md`.
3. Verify both package file lists contain `README.md` and `LICENSE`:

   ```bash
   cargo package -p incise-core --locked --list
   cargo package -p incise-cli --locked --no-verify --list
   ```

4. Review the commit history that will become the generated release notes.
5. Push the release commit and wait for CI to pass on the default branch.

## Tag and publish

```bash
git tag -a v0.1.0 -m "Incise 0.1.0"
git push origin v0.1.0
```

The release workflow validates the pinned Rust 1.75 toolchain, runs the Rust,
Python, differential, schema, replay, and Hermes checks, and builds archives
for Linux x86-64 and ARM64, macOS x86-64 and ARM64, and Windows x86-64.

Publication is intentionally ordered: `incise-core` is published first, then
`incise-cli` retries while the registry index catches up. Each publish step
checks whether that exact version already exists, so rerunning a partially
completed workflow does not try to upload the same crate version twice.

After both crates and all five archives succeed, the workflow creates a GitHub
release with generated notes and `SHA256SUMS`.

## After release

- Install from crates.io with `cargo install incise-cli --locked` and run a
  smoke edit on a disposable Markdown file.
- Download one GitHub archive and verify it against `SHA256SUMS`.
- Confirm the crates.io and docs.rs pages link back to the repository.
- Confirm the Hermes plugin registers all eight tools against the installed
  binary.
