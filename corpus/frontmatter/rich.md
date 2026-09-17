---
# Build configuration for the example project
title: "Rich frontmatter"
version: 0.4.1
draft: false
tags:
  - markdown
  - tooling
  - rust
build:
  target: release        # inline comment, must survive a sibling edit
  features:
    - tables
    - lists
  jobs: 4
authors:
  - name: Peter
    role: maintainer
  - name: Dana
    role: contributor
empty_value:
quoted_key: "value: with a colon"
multiline: |
  A literal block scalar.
  Second line, newlines preserved.
folded: >
  A folded scalar that joins
  these lines with spaces.
"key with spaces": ok
nested:
  deeply:
    buried: true
---

# Rich frontmatter

Purpose: `frontmatter-set build.jobs 8` must change exactly that value. Key
order, the leading comment, the inline comment on `build.target`, the block
scalar styles, and the quoting of `quoted_key` must all be byte-identical
afterward.

Most YAML libraries destroy at least three of those on a load/dump round trip.
This file is the test that incise does not.

## Addressing

- `title` — top-level scalar
- `build.target` — nested scalar with a trailing comment
- `build.features` — nested sequence
- `authors[0].role` — sequence of maps, index addressing
- `nested.deeply.buried` — three levels down
- `empty_value` — null, distinct from absent and from empty string
