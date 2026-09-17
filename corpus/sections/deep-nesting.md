# Deep heading nesting

Purpose: heading-path addressing through several levels, including a heading
name that repeats under different parents. `macOS` alone is ambiguous;
`Install > macOS` is not.

## Install

Preamble text belonging to Install itself, not to any subsection.

### macOS

Use Homebrew.

#### Apple Silicon

Native arm64 build.

#### Intel

Rosetta is not required.

### Linux

Use the package manager.

#### Debian

apt-based instructions.

#### Fedora

dnf-based instructions.

### Windows

Use winget.

## Upgrade

### macOS

Same repeated leaf name as under Install. Addressing by path must distinguish
these two; addressing by bare name must fail with both candidates listed.

### Linux

Repeated again.

## Uninstall

### macOS

And a third time.

## Reference

### API

#### Endpoints

##### Authentication

Level 5. Depth alone should not break path parsing.
