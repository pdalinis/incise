# Sortable table

Purpose: sort-mode coverage. Lexical, numeric, semver, and date sorts each
produce a different ordering of these same rows — which is the point.

## Packages

| Name    | Version | Released   | Downloads | Priority |
| ------- | ------- | ---------- | --------- | -------- |
| delta   | 1.10.0  | 2025-03-04 | 9         | high     |
| alpha   | 1.9.2   | 2024-11-30 | 1200      | low      |
| Charlie | 0.2.0   | 2026-01-15 | 87        | medium   |
| bravo   | 1.10.1  | 2025-12-01 | 100       | high     |
| echo    | 2.0.0   | 2024-02-29 | 1000      | low      |

Traps encoded above:

- `Version`: lexical sort puts `1.10.0` before `1.9.2`; semver sort does not.
- `Downloads`: lexical sort puts `1000` before `9`; numeric sort does not.
- `Name`: `Charlie` is capitalized, so case-sensitive and case-insensitive
  sorts differ.
- `Released`: ISO dates happen to sort correctly lexically — a date mode must
  still handle the leap day `2024-02-29`.
- `Priority`: has no natural order at all. Sorting it lexically is legal but
  probably not what a caller wants; a custom key order may be needed.

## Stability

| Group | Item |
| ----- | ---- |
| b     | 1    |
| a     | 2    |
| b     | 3    |
| a     | 4    |
| b     | 5    |

Sorting by `Group` must preserve the original relative order within each group
(1, 3, 5 and 2, 4). Unstable sorts will scramble this and the test will catch it.
