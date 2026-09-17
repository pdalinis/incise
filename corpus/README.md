# Corpus

Test data for incise. Twenty-five markdown files, each isolating one thing that
can go wrong, plus three realistic documents for end-to-end work.

The corpus serves two purposes at once:

1. **Fixtures** for the format-preservation tests required by §5.2 and §9.2 of
   `REQUIREMENTS.md` — for every operation, bytes outside the target range must
   be unchanged.
2. **Benchmark documents** for §9.5 — measuring whether a small model actually
   edits markdown more reliably through incise than directly.

## Rules

- **These files are fixtures, not documentation.** Their exact bytes are the
  test. Do not reformat, do not fix the deliberate raggedness, do not strip the
  trailing whitespace, do not add the missing final newline.
- Every file's own body explains what it is testing, so a failing test points
  at a file that describes its own purpose.
- Tests must operate on a copy. Nothing here is written to in place.
- `documents/api-reference.md` is generated — edit `tools/gen-api-reference.py`
  and regenerate. An unexplained diff means someone hand-edited it.

## tables/

| File | Isolates |
| ---- | -------- |
| `aligned.md` | Uniformly padded pipes — mutations must re-pad to keep alignment |
| `ragged.md` | Unpadded pipes, plus a near-aligned table — mutations must not prettify |
| `alignment-markers.md` | `:---`, `:---:`, `---:` must survive sort, reorder, add/remove column |
| `multiple-per-section.md` | Several tables under one heading — ordinal addressing and ambiguity errors |
| `cell-edge-cases.md` | Escaped pipes, pipes in code spans, empty cells, CJK width, emoji, ragged cell counts |
| `sortable.md` | Lexical vs numeric vs semver vs date sort modes, and sort stability |

## sections/

| File | Isolates |
| ---- | -------- |
| `deep-nesting.md` | Five heading levels; leaf names repeated under different parents |
| `duplicate-siblings.md` | Identical headings under the same parent — no path disambiguates, must fail with candidates |
| `setext-and-atx.md` | Setext headings, closed ATX, indented headings, setext-vs-thematic-break ambiguity, multiple H1s |

## lists/

| File | Isolates |
| ---- | -------- |
| `nested-mixed.md` | Marker styles, indent widths, tight vs loose, multi-paragraph items, continuation lines |
| `tasks.md` | Checkbox toggling, nesting, capital `[X]`, and GFM near-misses that are not tasks |
| `ordered-numbering.md` | Renumber-or-not: sequential, all-ones, `)` delimiter, non-one start, already non-sequential |

## frontmatter/

| File | Isolates |
| ---- | -------- |
| `rich.md` | Comments, key order, block scalars, nested maps, sequences of maps — all must survive a single-key edit |
| `absent.md` | No block at all — `set` must create one at the top without disturbing the body |
| `empty.md` | Delimiters present, no keys — distinct from absent, and deleting the last key must not remove the block |

## hazards/

Files where a naive implementation does damage.

| File | Isolates |
| ---- | -------- |
| `code-fences.md` | Tables, headings, lists and frontmatter inside fences — all inert. Tilde fences, nested fences, indented code, one unclosed fence |
| `html-blocks.md` | Raw HTML, an HTML table that is not a markdown table, markdown inside `<details>`, comment anchors |
| `nested-blocks.md` | Tables and lists inside list items and blockquotes — edits must carry the `> ` prefix and the indent |
| `whitespace.md` | Two-space hard breaks, backslash breaks, tabs, two-blank-line conventions, a blank line containing spaces, **no final newline** |
| `crlf.md` | Uniform CRLF endings — inserted lines must be CRLF too |
| `mixed-endings.md` | LF and CRLF in one file, including a CRLF table inside an LF document |
| `toml-frontmatter.md` | `+++` block — must fail clearly on frontmatter ops while still allowing table and section ops |

## documents/

Realistic documents, for end-to-end and benchmark use rather than unit tests.

| File | Lines | Role |
| ---- | ----- | ---- |
| `project-readme.md` | ~120 | The most common document an agent edits. Composite-key table rows, mixed content |
| `changelog.md` | ~85 | The insert-at-top pattern, plus link references at the foot of the file |
| `api-reference.md` | ~820 | Large-document fixture for acceptance criterion 9.1 — too big for a small context |

## tools/

`gen-api-reference.py` — deterministic generator for the large fixture. No
randomness, no timestamps; regenerating must produce a byte-identical file.

## Not yet covered

Gaps worth closing before the corpus is considered complete:

- Reference-style links and footnote definitions that move when a section moves
- Very wide tables (20+ columns) and very long tables (500+ rows)
- Non-UTF-8 and BOM-prefixed files
- Documents with no headings at all
- Deliberately malformed tables that should fail rather than parse
