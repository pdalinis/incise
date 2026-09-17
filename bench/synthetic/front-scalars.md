---
chomp_strip: |-
  kept, no trailing newline
chomp_keep: >+
  folded and kept

indent_2: |2
    two-space indent indicator
indent_both: |2-
    both indicators, digit first
chomp_first: >-2
  both indicators, sign first
not_a_block: |x
also_not: ||
nor_this: >>
trailing_pipe: "|"
bare_items:
  -
  - 
  - after two empties
tabbed:
  -	tab after the dash
'single': quoted key
'it''s': doubled quote inside
"say \"hi\"": escaped quote inside
"back\\slash": escaped backslash
deep_seq:
  nested:
  - at the parent key's indent
  - and a second one
---

# Scalars

Purpose: the block scalar indicators, null items and key quotings
`corpus/frontmatter/rich.md` does not contain. See `bench/synthetic/README.md.txt`.

The third item under `bare_items` is preceded by two empty ones, the second of
which is written `-` followed by a space.
