# Changelog

Purpose in the corpus: the insert-at-top pattern. Almost every changelog edit
adds a new section immediately below this preamble and above the newest
existing release — an addressing case that "append to section" does not cover.

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Representative benchmark tasks against this file:

- add a new `## [1.5.0]` section above `## [1.4.2]`
- add a bullet under the existing `### Fixed` in the newest release
- add an `### Added` subsection to a release that has none
- add the corresponding link reference at the bottom of the file

## [Unreleased]

### Added

- Placeholder for the next release.

## [1.4.2] - 2026-08-14

### Fixed

- Resolved a panic when the config file was empty ([#622](https://github.com/acme/ctl/issues/622)).
- Corrected timeout handling for requests exceeding 30 seconds.

### Changed

- Improved error message when the remote is unreachable.

## [1.4.1] - 2026-07-30

### Fixed

- Restored `--dry-run` output on Windows.

## [1.4.0] - 2026-07-02

### Added

- `apply --diff` behind an experimental flag.
- FreeBSD amd64 builds.

### Changed

- `sync` now retries transient failures three times.
- Minimum Go version raised to 1.21.

### Deprecated

- `--legacy-format`, to be removed in 2.0.0.

## [1.3.0] - 2026-05-19

### Added

- Windows amd64 builds, in beta.

### Removed

- Support for config files written before 0.9.0.

## [1.2.0] - 2026-04-01

### Added

- `plan` command.

### Security

- Updated a transitive dependency with a known advisory.

[Unreleased]: https://github.com/acme/ctl/compare/v1.4.2...HEAD
[1.4.2]: https://github.com/acme/ctl/compare/v1.4.1...v1.4.2
[1.4.1]: https://github.com/acme/ctl/compare/v1.4.0...v1.4.1
[1.4.0]: https://github.com/acme/ctl/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/acme/ctl/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/acme/ctl/releases/tag/v1.2.0
