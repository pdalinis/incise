# No frontmatter

Purpose: `frontmatter-set` on this file must create the block from nothing,
inserting `---` delimiters at the very top and leaving the rest of the document
byte-identical — including the blank line between the new block and this H1.

The failure mode to guard against is inserting the block after the H1, or
eating the blank line, or emitting `\n---\n` with the wrong number of newlines.

## Content

Ordinary body text so the file is not trivially short.

- a list
- to make the body non-empty

`frontmatter-get` on this file must report "absent" distinctly from "present but
empty" — see `empty.md`.
