---
title: Shapes
tags:
- flat
- unindented
empty_string: ""
empty_null:
spaced:   value with a comment   # trailing comment, wide gap
url: https://example.com/page#fragment
hashish: "a # b"
colonish: 'time: 10:30'
"dotted.key": unreachable

# a comment between two keys, with a blank line on each side

deep:
    level:
        leaf: four-space
        other: sibling
    sequence:
        - one
        - two
list_of_maps:
- name: first
  role: alpha
- name: second
  role: beta
---

# Shapes

Purpose: the YAML shapes `corpus/frontmatter/rich.md` does not contain. See
`bench/synthetic/README.md.txt`.
