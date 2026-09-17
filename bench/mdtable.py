#!/usr/bin/env python3
"""Markdown table parsing shared by the runner and the grader.

Deliberately small and strict: it only needs to handle the corpus fixtures used
by the targeted pass, and it must never silently mis-locate a table (a wrong
table index would make every downstream grade meaningless).
"""

from dataclasses import dataclass, field


def split_row(line):
    r"""Cells of one table row, between the outer pipes, escapes left intact.

    The obvious `line.split("|")` is wrong, and was wrong here for the whole of
    Tier 1. GFM lets a cell contain a literal pipe by escaping it, so the row

        | escaped pipe    | a \| b                   | literal pipe, backslashed  |

    from `corpus/tables/cell-edge-cases.md` has three cells, not four. Splitting
    naively read it as four, which had two consequences, both silent:

      * The table was classified **ragged** -- its rows disagreed with its
        header on cell count -- so it was excluded from the aligned re-pad path
        for a reason that does not exist.
      * `table-update-cell` on that row wrote into the wrong cell. `Note` is
        index 2, which under the naive split is the fragment `b` rather than the
        note, and the rebuilt row was emitted with four columns. The document
        said "Any operation on this table must round-trip every cell exactly";
        it did not.

    A backslash escapes the character after it, so `\|` is content and `\\|` is
    a literal backslash followed by a real separator. Consuming the pair is the
    only way to tell those apart, which is why this is a scan and not a regex.

    Identical to the naive split on any line without a backslash, which is every
    line in the corpus but two.
    """
    s = line.rstrip()
    cells, buf, i = [], [], 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            buf.append(s[i : i + 2])
            i += 2
        elif c == "|":
            cells.append("".join(buf))
            buf = []
            i += 1
        else:
            buf.append(c)
            i += 1
    cells.append("".join(buf))
    # Drop the fragments outside the outer pipes, as `split("|")[1:-1]` did.
    return cells[1:-1]


@dataclass
class Table:
    start: int                      # first line index (0-based, inclusive)
    end: int                        # last line index (inclusive)
    lines: list = field(default_factory=list)

    @property
    def header(self):
        return self.lines[0]

    @property
    def delimiter(self):
        return self.lines[1]

    @property
    def body(self):
        return self.lines[2:]

    def widths(self):
        """Character count between pipes, per row. Equal vectors == aligned."""
        return [tuple(len(c) for c in split_row(ln)) for ln in self.lines]

    def is_aligned(self):
        w = self.widths()
        return len(set(w)) == 1

    def cells(self, line):
        return tuple(c.strip() for c in split_row(line))

    def rows(self):
        return [self.cells(ln) for ln in self.body]


def _is_delimiter(line):
    s = line.strip()
    if not s.startswith("|"):
        return False
    # The same splitting rule as every other row, though here it can only ever
    # agree with the naive one: a delimiter cell holds nothing but `-` and `:`,
    # and a backslash disqualifies the line under either split. Shared anyway,
    # so there is exactly one answer in this file to "where are the cells".
    for cell in split_row(s):
        c = cell.strip()
        if not c or not set(c) <= set("-:"):
            return False
        if "-" not in c:
            return False
    return True


def find_tables(content):
    """Return every GFM table in `content`, skipping fenced and indented code.

    A table is a header line, a delimiter line, and zero or more body lines,
    all starting with '|' at an indent of less than four spaces (four or more
    would make it an indented code block).
    """
    lines = content.split("\n")
    tables, i = [], 0
    fence_char, fence_len = None, 0
    while i < len(lines):
        stripped = lines[i].lstrip()
        if fence_char:
            # Only a fence of the same character and at least the opening
            # length closes it -- otherwise a ``` inside a ```` block would
            # terminate early and expose inert content as real.
            if stripped.startswith(fence_char):
                run = len(stripped) - len(stripped.lstrip(fence_char))
                if run >= fence_len:
                    fence_char, fence_len = None, 0
            i += 1
            continue
        if stripped[:3] in ("```", "~~~"):
            fence_char = stripped[0]
            fence_len = len(stripped) - len(stripped.lstrip(fence_char))
            i += 1
            continue
        indent = len(lines[i]) - len(stripped)
        if (
            indent < 4
            and stripped.startswith("|")
            and i + 1 < len(lines)
            and _is_delimiter(lines[i + 1])
            and (len(lines[i + 1]) - len(lines[i + 1].lstrip())) < 4
        ):
            start = i
            i += 2
            while i < len(lines):
                nxt = lines[i].lstrip()
                if not nxt.startswith("|") or (len(lines[i]) - len(nxt)) >= 4:
                    break
                i += 1
            tables.append(Table(start=start, end=i - 1, lines=lines[start:i]))
            continue
        i += 1
    return tables


def outside_table(content, table):
    """Everything except the table's own lines, for byte-identity checks."""
    lines = content.split("\n")
    return "\n".join(lines[: table.start] + lines[table.end + 1 :])


if __name__ == "__main__":
    import sys

    for path in sys.argv[1:]:
        c = open(path).read()
        print(f"\n=== {path}")
        for n, t in enumerate(find_tables(c)):
            print(
                f"  [{n}] lines {t.start+1}-{t.end+1}  cols={len(t.cells(t.header))} "
                f"rows={len(t.body)}  aligned={t.is_aligned()}  header={t.cells(t.header)}"
            )
