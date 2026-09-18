# pi-incise

Structured, byte-preserving Markdown tools for [Pi](https://pi.dev). The package supplies eight tools backed by the native Incise CLI and does not download or compile code during installation.

## Install

Before promotion to `latest`, install the release candidate with:

```bash
pi install npm:pi-incise@next
```

After the live composition benchmark passes and that exact version is promoted, `pi install npm:pi-incise` installs the stable release.

Prebuilt binaries are provided for macOS arm64/x64 and glibc Linux arm64/x64. Windows and musl Linux are not supported in v1.

## Tools

The package registers `table_edit`, `list_edit`, `section_edit`, `frontmatter_edit`, `table_get`, `md_tables`, `md_lists`, and `md_outline`. Inspect document structure with the relevant read tool before editing, and follow the remedy in any Incise refusal.

## Binary resolution

The extension uses `INCISE_BIN` first, then the matching optional native package, then `incise` on `PATH`, and finally a release or debug binary from a development checkout. `/incise-doctor` reports the selected path, versions, schema status, and registered-tool count. Version mismatches from explicit overrides are warnings; a mismatched packaged binary disables the tools as an installation-integrity failure.

## Security

Pi extensions and their subprocesses run with the user’s full permissions. Review this package before installation and use OS- or container-level isolation for unattended execution. Incise performs atomic, byte-preserving edits, but it is not a filesystem sandbox.
