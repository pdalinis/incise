+++
title = "TOML frontmatter"
version = "0.1.0"

[build]
target = "release"
+++

# TOML frontmatter

Purpose: incise supports YAML frontmatter only (§8). This file must produce a
clear error on any frontmatter operation — naming the format it found and the
format it supports — and must never attempt to parse the block as YAML.

The failure to guard against is a YAML parser accepting some of this by
accident and writing back a mangled block.

Non-frontmatter operations on this file — tables, sections, lists — must work
normally. An unsupported frontmatter format is not a reason to refuse to touch
the document.

## Components

| Component | Status |
| --------- | ------ |
| widget    | active |
