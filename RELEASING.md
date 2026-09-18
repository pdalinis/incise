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
4. Add `.github/release-notes/vX.Y.Z.md` with the curated GitHub release body.
5. Push the release commit and wait for CI to pass on the default branch.

## Tag and publish

```bash
git tag -a v0.1.0 -m "Incise 0.1.0"
git push origin v0.1.0
```

The release workflow validates the pinned Rust 1.75 toolchain, runs the Rust, documentation, Python, differential, schema, replay, and Hermes checks, and verifies both crate packages.

It then builds four CLI archives—Linux x86-64 and ARM64, plus macOS x86-64 and ARM64—and a standalone version-matched Hermes plugin archive. Crate publication does not start unless every archive succeeds.

Publication is intentionally ordered: `incise-core` is published first, then `incise-cli` retries while the registry index catches up. Each publish step checks whether that exact version already exists, so rerunning a partially completed workflow does not try to upload the same crate version twice.

After both crates and all five archives succeed, the workflow creates a GitHub release with the curated notes and `SHA256SUMS`.

## After release

- Install from crates.io with `cargo install incise-cli --locked` and run a
  smoke edit on a disposable Markdown file.
- Download one GitHub archive and verify it against `SHA256SUMS`.
- Confirm the crates.io and docs.rs pages link back to the repository.
- Download and extract the version-matched Hermes plugin archive, then confirm that `hermes plugins doctor --ci incise` reports all eight tools.
