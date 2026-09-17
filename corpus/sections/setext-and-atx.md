Setext H1 Title
===============

Purpose: heading syntaxes other than plain ATX. All of these are headings and
must be addressable by path identically. Operations that rewrite a heading must
preserve its original syntax.

Setext H2
---------

Setext only reaches two levels, so the document mixes syntaxes below.

### ATX level 3

Normal.

### Closed ATX level 3 ###

Trailing hashes are decoration, not part of the heading text. The address is
`Closed ATX level 3`, not `Closed ATX level 3 ###`.

###    Extra leading spaces in text

Interior whitespace after the marker is stripped for addressing purposes.

   ### Indented three spaces

Up to three spaces of indentation still makes a heading. Four would make it a
code block instead — see `hazards/code-fences.md`.

Ambiguity with thin rules
-------------------------

A `---` line directly under text is a setext H2. The same `---` line after a
blank line is a thematic break. Both appear below and must be classified
correctly.

---

That was a thematic break, not a heading.

# ATX H1 late in the document

Documents with more than one H1 are common. Path addressing must handle a
forest, not just a tree.
