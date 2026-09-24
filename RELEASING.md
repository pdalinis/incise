# Releasing Incise

Releases are tag-driven. A tag named `vX.Y.Z` must match the workspace version
in `Cargo.toml`; the release workflow refuses a mismatch.

## One-time repository setup

- Add a `CARGO_REGISTRY_TOKEN` Actions secret with permission to publish both `incise-core` and `incise-cli`.
- Create and verify the `pdalinis` npm account and enable two-factor authentication.
- Keep GitHub private vulnerability reporting enabled.
- Protect the default branch and require the CI workflow once its first run is green.
- Require full-length commit SHAs for Actions after the first workflow files are present.

The first npm release is a bootstrap: the five packages must exist before npm trusted publishers can be configured. The first tagged workflow produces the tarballs; publish those once with the authenticated local npm account, configure each package to trust `.github/workflows/release.yml`, then rerun the failed release job. Later tags publish through OIDC without an npm token.

## Before tagging

1. Update the workspace version in `Cargo.toml`, the `incise-core` dependency in `crates/incise-cli/Cargo.toml`, the Hermes plugin version, all five npm package versions, and both lockfiles together.
2. Add `.github/release-notes/vX.Y.Z.md` with the curated GitHub release body.
3. Run the commands in the Development section of `README.md`, plus the Pi package checks:

   ```bash
   cargo build -p incise-cli --locked
   npm --prefix plugins/pi ci --omit=optional
   npm --prefix plugins/pi test
   npm --prefix plugins/pi run typecheck
   npm --prefix plugins/pi run pack:check
   ```

4. Verify both crate package file lists contain `README.md` and `LICENSE`:

   ```bash
   cargo package -p incise-core --locked --list
   cargo package -p incise-cli --locked --no-verify --list
   ```

5. Push the release commit and wait for CI to pass on the default branch.

## Tag and publish

For this release:

```bash
git tag -a v0.3.0 -m "Incise 0.3.0"
git push origin v0.3.0
```

The release workflow validates the pinned Rust toolchain, runs the Rust, documentation, Python, differential, schema, replay, Hermes, and Pi package checks, and verifies the crate and npm package contents.

It then builds four CLI archives and four native npm packages—Linux x86-64 and ARM64, plus macOS x86-64 and ARM64—and a standalone version-matched Hermes plugin archive. Publication does not start unless every archive succeeds.

Crate publication is ordered: `incise-core` is published first, then `incise-cli` retries while the registry index catches up. Npm publication is also ordered: the four exact-version native packages are published first under `next`, then `pi-incise` is published last. Every publish step skips an exact version that already exists, making a partial release rerunnable.

For the initial npm bootstrap, let the tagged workflow produce its artifacts. Download the four `pi-incise-npm-*` native artifacts and the `pi-incise-npm-main` artifact, then publish their `.tgz` files with the local authenticated account in native-first, main-last order using `npm publish <file> --access public --tag next`. Configure all five packages’ trusted publisher settings for this repository and `.github/workflows/release.yml`, then rerun the failed release jobs.

After the crates, npm packages, and all archives succeed, the workflow creates a GitHub release with the curated notes and `SHA256SUMS`.

## After release

- Install from crates.io with `cargo install incise-cli --version 0.3.0 --locked` and run a smoke edit on a disposable Markdown file.
- Download one GitHub archive and verify it against `SHA256SUMS`.
- Confirm the crates.io and docs.rs pages link back to the repository.
- Download and extract the version-matched Hermes plugin archive, then confirm that `hermes plugins doctor --ci incise` reports all eight tools.
- Install the Pi candidate with `pi install npm:pi-incise@next`, run `/incise-doctor`, and smoke-test a read and write on each supported platform family.
- For a model-facing behavior change, run the live composition benchmark before promotion. For a documentation- or metadata-only release, verify that the published extension and schema match the prior stable package. Then promote the exact version with `npm dist-tag add pi-incise@0.3.0 latest`; keep the native packages pinned by exact version.
