#!/usr/bin/env python3
"""Markdown list parsing shared by the ops and the grader.

The list counterpart of `mdtable.py`, and deliberately the same shape: small,
strict, and only obliged to handle the corpus fixtures. A wrong list boundary
would make every downstream grade meaningless, so ambiguous cases end a list
rather than absorb the next thing.

What a "list" is here follows CommonMark on the three points that matter for
editing, because each one is a place a hand-editing model can go wrong:

  * A **marker change ends the list.** `- a` followed by `* b` is two lists, not
    one list with two items (`corpus/lists/nested-mixed.md`). An op that
    appended to "the list" without knowing this would insert into the wrong one.
  * **Ordered delimiters are part of the marker.** `1.` and `1)` do not belong
    to the same list, and an inserted item must match the one it joins.
  * **Loose vs tight is a property of the list**, decided by whether a blank
    line separates any two of its items. Inserting into a loose list without the
    blank line changes how every item renders.

Nesting is represented by flattening: `MdList.items` holds every item in the
run, each carrying its `depth`. That is not a shortcut -- it is what makes the
op vocabulary content-addressed. An item inserted after `beta-two` takes
`beta-two`'s indent and marker, so "add a nested item" needs no depth argument
and no way to express an impossible one.
"""

import re
from dataclasses import dataclass, field

# A marker line: indent, bullet or number, at least one space, then content.
# `\d{1,9}` is CommonMark's limit. An empty item (`-` alone) is matched by the
# alternate branch so it is not silently treated as a paragraph.
ITEM_RE = re.compile(r"^([ \t]*)([-*+]|\d{1,9}[.)])(?:([ \t]+)(.*)|()$)")

# GFM task marker: exactly one of space/x/X in brackets, then a space. The
# near-miss forms in `corpus/lists/tasks.md` (`[]`, `[ ]no space`, `[y]`) must
# all fail to match here, so the pattern is anchored and spelled out rather
# than made permissive.
CHECKBOX_RE = re.compile(r"^\[([ xX])\](?: |$)")


def frontmatter_span(lines):
    """(start, end) line indices of leading YAML/TOML frontmatter, or None.

    Lives here, in the lowest layer, because both `find_lists` and
    `mdsection.find_sections` need it and this module imports nothing. A YAML
    sequence looks like a bullet list and a YAML comment looks like an H1, so
    both parsers are wrong on `corpus/frontmatter/rich.md` without it.

    An unterminated opening `---` is not frontmatter; it is a thematic break,
    and treating it as frontmatter would swallow the whole document.
    """
    if not lines or lines[0].strip() not in ("---", "+++"):
        return None
    close = lines[0].strip()
    for i in range(1, len(lines)):
        if lines[i].strip() in (close, "..."):
            return (0, i)
    return None


def fence_mask(lines):
    """One bool per line: is this line inside (or part of) a fenced code block?

    Run length is what makes nested fences work. A closing fence must be at
    least as long as the one that opened the block, so the three-backtick fence
    inside ````markdown does not close it. Naive matching terminates there and
    reads the remainder of `code-fences.md` as prose, which is exactly the
    corruption that fixture exists to catch.
    """
    mask = [False] * len(lines)
    char, need = None, 0
    for i, ln in enumerate(lines):
        s = ln.lstrip()
        if char:
            mask[i] = True
            if s.startswith(char):
                run = len(s) - len(s.lstrip(char))
                # A closing fence is only fence characters; an info string
                # (```markdown) can open a block but never closes one.
                if run >= need and not s[run:].strip():
                    char, need = None, 0
            continue
        if s[:3] in ("```", "~~~"):
            char = s[0]
            need = len(s) - len(s.lstrip(char))
            mask[i] = True
    return mask


@dataclass
class ListItem:
    start: int            # line index of the marker line
    own_end: int          # last line of this item's own content (excl. children)
    end: int              # last line of the item's subtree (incl. children)
    depth: int            # 0 for a top-level item of the run
    indent: str           # leading whitespace of the marker line, verbatim
    marker: str           # "-" / "*" / "+" / "3." / "3)"
    ordered: bool
    number: int = None    # ordered only
    delim: str = None     # "." or ")", ordered only
    checkbox: str = None  # " ", "x", "X", or None if not a task item
    text: str = ""        # content after the marker and checkbox
    parent: int = -1      # index into MdList.items, or -1

    @property
    def bullet(self):
        """The marker's identity for sibling-matching: char, or ordered delim."""
        return self.delim if self.ordered else self.marker


@dataclass
class MdList:
    start: int
    end: int
    ordered: bool
    bullet: str                       # "-" / "*" / "+" / "." / ")"
    indent: str
    loose: bool
    items: list = field(default_factory=list)
    lines: list = field(default_factory=list)

    def top(self):
        return [i for i in self.items if i.depth == 0]

    def children_of(self, idx):
        return [i for i, it in enumerate(self.items) if it.parent == idx]

    def siblings_of(self, idx):
        """Indices of every item sharing this item's parent, in document order."""
        p = self.items[idx].parent
        return [i for i, it in enumerate(self.items) if it.parent == p]

    def texts(self):
        return [it.text for it in self.items]


def _parse_marker(m):
    indent, marker, _, text = m.group(1), m.group(2), m.group(3), m.group(4)
    text = text if text is not None else ""
    ordered = marker[0].isdigit()
    number = int(marker[:-1]) if ordered else None
    delim = marker[-1] if ordered else None
    cb = CHECKBOX_RE.match(text)
    checkbox = cb.group(1) if cb else None
    if cb:
        text = text[cb.end():]
    return indent, marker, ordered, number, delim, checkbox, text.rstrip()


def _bullet_of(marker):
    return marker[-1] if marker[0].isdigit() else marker


def find_lists(content):
    """Every top-level list in `content`, skipping fenced code and frontmatter.

    Only runs that *start* at an indent of less than four are returned; a list
    nested inside another list is part of its parent's run, and a block indented
    four or more is code. Both are deliberate: the addressable unit is the
    top-level list, and nested items are reached through it.

    Frontmatter is skipped because a YAML block sequence is spelled exactly like
    a markdown bullet list:

        tags:
          - markdown
          - tooling

    Without the skip, `corpus/frontmatter/rich.md` reports two lists that are
    not lists, and `render_list_summary` offers the model an edit that would
    corrupt the document's metadata. Found while building `mdsection.py`; no
    task or golden used that fixture, so no measured result changed.
    """
    lines = content.split("\n")
    fm = frontmatter_span(lines)
    # The scan starts after the frontmatter, so a stray ``` inside a YAML value
    # cannot open a block over the rest of the document.
    out, start = [], (fm[1] + 1 if fm else 0)
    mask = fence_mask(lines[start:])
    i = start
    while i < len(lines):
        if mask[i - start]:
            i += 1
            continue
        m = ITEM_RE.match(lines[i])
        if not m or len(m.group(1).expandtabs(4)) >= 4:
            i += 1
            continue
        lst, i = _consume_run(lines, i)
        out.append(lst)
    return out


def _consume_run(lines, start):
    """Consume one list run beginning at `start`. Returns (MdList, next_index)."""
    m0 = ITEM_RE.match(lines[start])
    base_indent = m0.group(1)
    base_bullet = _bullet_of(m0.group(2))
    base_ordered = m0.group(2)[0].isdigit()

    marker_lines = []          # line indices of every item marker in the run
    end = start
    j, blanks = start, 0
    while j < len(lines):
        ln = lines[j]
        if not ln.strip():
            blanks += 1
            # Two blank lines end any list; one may separate loose items.
            if blanks >= 2:
                break
            j += 1
            continue
        indent = ln[: len(ln) - len(ln.lstrip())]
        m = ITEM_RE.match(ln)
        if len(indent) <= len(base_indent):
            # Back at (or outside) the run's own level: only a matching marker
            # continues it. A different bullet starts a NEW list, and a
            # non-marker line ends it.
            if not m or indent != base_indent:
                break
            if _bullet_of(m.group(2)) != base_bullet:
                break
            if m.group(2)[0].isdigit() != base_ordered:
                break
        if m:
            marker_lines.append(j)
        blanks, end = 0, j
        j += 1

    # `end` is the last non-blank line of the run; a trailing blank belongs to
    # the document, not the list.
    lst = MdList(start=start, end=end, ordered=base_ordered, bullet=base_bullet,
                 indent=base_indent, loose=False, lines=lines[start:end + 1])

    stack = []  # (indent_len, item_index)
    for n, li in enumerate(marker_lines):
        indent, marker, ordered, number, delim, checkbox, text = _parse_marker(
            ITEM_RE.match(lines[li]))
        ind = len(indent.expandtabs(4))
        while stack and stack[-1][0] >= ind:
            stack.pop()
        item = ListItem(
            start=li, own_end=li, end=li, depth=len(stack), indent=indent,
            marker=marker, ordered=ordered, number=number, delim=delim,
            checkbox=checkbox, text=text, parent=stack[-1][1] if stack else -1)
        stack.append((ind, len(lst.items)))
        lst.items.append(item)

    # Spans: own_end stops at the next marker of any depth; end stops at the
    # next marker at this depth or shallower, so it covers the subtree.
    for n, item in enumerate(lst.items):
        nxt = marker_lines[n + 1] if n + 1 < len(marker_lines) else end + 1
        item.own_end = _trim_blank(lines, item.start, nxt - 1)
        sub = end + 1
        for k in range(n + 1, len(lst.items)):
            if lst.items[k].depth <= item.depth:
                sub = lst.items[k].start
                break
        item.end = _trim_blank(lines, item.start, sub - 1)

    # Loose iff a blank line separates two items of the run.
    lst.loose = any(
        not lines[k].strip()
        for n in range(len(lst.items) - 1)
        for k in range(lst.items[n].end + 1, lst.items[n + 1].start)
    )
    return lst, end + 1


def _trim_blank(lines, lo, hi):
    while hi > lo and not lines[hi].strip():
        hi -= 1
    return hi


def outside_list(content, lst):
    """Everything except the list's own lines, for byte-identity checks."""
    lines = content.split("\n")
    return "\n".join(lines[: lst.start] + lines[lst.end + 1:])


if __name__ == "__main__":
    import sys

    for path in sys.argv[1:]:
        c = open(path).read()
        print(f"\n=== {path}")
        for n, l in enumerate(find_lists(c)):
            kind = f"ordered '{l.bullet}'" if l.ordered else f"bullet '{l.bullet}'"
            print(f"  [{n}] lines {l.start+1}-{l.end+1}  {kind}  "
                  f"{len(l.items)} items  {'loose' if l.loose else 'tight'}")
            for it in l.items:
                cb = f"[{it.checkbox}] " if it.checkbox else ""
                print(f"        {'  '*it.depth}{it.marker:>4s} {cb}{it.text!r}")
