# Mixed line endings

Purpose: this file mixes LF and CRLF. There is no single "file convention" to
match, so inserting a line requires a documented rule — match the line being
edited, match the majority, or fail. Whichever is chosen, it must be a decision
rather than an accident of the platform.

## LF section

This paragraph uses LF endings.

- lf item one
- lf item two

## CRLF section

This paragraph uses CRLF endings, as does the table below.

| Component | Status |
| --------- | ------ |
| widget    | active |

## LF again

Back to LF for the remainder of the file.

The table above is the interesting case: adding a row to a CRLF table in an
otherwise-LF file must produce a CRLF row.
