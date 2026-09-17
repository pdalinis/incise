#!/usr/bin/env python3
"""Markdown heading/section parsing shared by the ops and the grader.

The third sibling of `mdtable.py` and `mdlist.py`, same contract: small, strict,
and only obliged to handle the corpus fixtures. A wrong section boundary is
worse here than a wrong list boundary, because a section's span routinely covers
most of a document -- `## Install` in `corpus/sections/deep-nesting.md` owns 32
lines and six subsections. Getting `end` wrong by one heading means an op
silently eats or orphans a subtree.

Sections differ from tables and lists in four ways that matter, and each one is
a place the earlier two families give no guidance at all:

  * **A heading has a level, and the level is content.** `##` vs `###` is not
    formatting to be preserved incidentally; it is what makes the address a
    path. Inserting a section therefore requires *choosing* a level, which no
    table or list op ever had to do.
  * **Headings have three syntaxes, and a rename must preserve the one it
    found.** Setext (`Title` over `=====`), plain ATX (`### Title`), and closed
    ATX (`### Title ###`) all address identically and must all round-trip
    (`corpus/sections/setext-and-atx.md`).
  * **The body is arbitrary markdown**, not one line and not one row. It can
    contain fences, lists, tables and blank lines, so "the section's text" is a
    span of the document rather than a value.
  * **The document is a forest, not a tree.** `setext-and-atx.md` has two H1s
    and `deep-nesting.md` skips no levels but nothing guarantees that; a parent
    is the nearest *preceding* heading of lower level, or nothing.

Three classes of heading-shaped line are deliberately NOT sections, and the
distinction is the whole difficulty of the file:

  * Inside a fenced code block (`corpus/hazards/code-fences.md` -- including the
    four-backtick fence wrapping a three-backtick one, where naive matching
    terminates early and reads the rest of the file as prose).
  * Indented four or more spaces, which is an indented code block. This falls
    out of the `{0,3}` in `ATX_RE` rather than needing a code-block model.
  * Inside a blockquote (`corpus/hazards/nested-blocks.md`). `> ## Quoted
    heading` is a real heading of a quoted document, but editing it means
    maintaining the `> ` prefix on every emitted line, so it is not addressable
    as a section here.

None of those are silently dropped. `inert_headings` returns every one of them
with the reason it was rejected, and `resolve` consults it, because the corpus
names the failure to avoid explicitly: reporting "not found" for a heading that
is plainly there is worse than refusing.

**Unclosed fences run to end of document.** `code-fences.md` ends with one and
`PLAN.md` §5 records that either treatment is defensible provided it is chosen
deliberately. This is the choice: CommonMark's, so the trailing `## Trailing
heading inside an unclosed fence` is inert. `test_unclosed_fence` pins it.
"""

import re
from dataclasses import dataclass, field

# Up to three spaces of indent, one to six hashes, then whitespace or EOL.
# `#####Authentication` is not a heading and the trailing `$` is what rejects
# it: no amount of backtracking finds a shorter hash run followed by a space.
ATX_RE = re.compile(r"^( {0,3})(#{1,6})(?:([ \t]+)(.*))?$")

# A closing hash sequence is decoration. It must be preceded by whitespace and
# be nothing but hashes to the end, so `### foo #bar` keeps its `#bar`.
CLOSING_RE = re.compile(r"^(.*?)[ \t]+(#+)[ \t]*$")

# A setext underline: all `=` (H1) or all `-` (H2). Whether a `---` line is this
# or a thematic break depends entirely on what precedes it, which is why the
# check lives in `_is_setext` and not in the pattern.
SETEXT_RE = re.compile(r"^( {0,3})(=+|-+)[ \t]*$")

BLOCKQUOTE_RE = re.compile(r"^ {0,3}>")

# A link reference definition: `[label]: destination`. Used only to recognise a
# document's trailing footer block; see `_footer_start`.
LINKREF_RE = re.compile(r"^ {0,3}\[[^\]]+\]:[ \t]*\S")

# Imported rather than re-spelled. `ITEM_RE` is the authority on what a list
# item looks like -- a `-----` line under a list item is that item's own text,
# not a setext underline -- and `frontmatter_span` has to give the same answer
# to both parsers or a YAML document is two different shapes depending on who
# is asking. Both are leaf-level and `mdlist` imports nothing, so the
# dependency runs one way only.
#
# `fence_mask` arrives the same way, and did not always. It lived here, and
# `find_lists` kept a second copy inline as loop state, on the argument that
# sharing it would mean refactoring code 51 corpus lists depend on; a test held
# the two together. The two drifted anyway, on the one point that test admitted
# it could not see: whether a closing fence may carry trailing words. The same
# document then had two answers to "is this line code?" (FINDINGS F-fence).
# One scanner now, in the file that owns the other bottom-layer scanners.
from mdlist import ITEM_RE, fence_mask, frontmatter_span  # noqa: E402


@dataclass
class Section:
    start: int             # line index of the heading (setext: its text line)
    heading_end: int       # last line of the heading itself (setext: underline)
    own_end: int           # last non-blank line of this section's own body
    end: int               # last non-blank line of the subtree
    level: int             # 1-6
    text: str              # addressing form: stripped, decoration removed
    raw_text: str          # between the marker and any closing hashes, verbatim
    style: str             # "atx" | "atx_closed" | "setext"
    indent: str            # leading whitespace of the heading line, verbatim
    marker: str            # "##" / "=====" / "-----", verbatim
    space: str             # whitespace between the hashes and the text
    closing: str           # the closing hash run, or ""
    eol: str = ""          # "\r" if the heading line is CRLF, else ""
    parent: int = -1       # index into the section list, or -1
    path: tuple = ()       # ancestor texts, ending with this section's own
    gap_after: int = 0     # blank lines between `end` and whatever follows

    @property
    def has_body(self):
        return self.own_end > self.heading_end

    @property
    def slug(self):
        return " > ".join(self.path)


    def rebuild(self, text=None):
        """The heading line(s) as they should be written back.

        A rename goes through here rather than through string surgery at the
        call site, because three things have to survive that are easy to lose:
        the original syntax (setext stays setext), the closing hash run, and
        `eol`. That last one is not hypothetical -- `corpus/hazards/crlf.md`
        stores `\\r` at the end of every line, and a heading rebuilt from
        `raw_text` alone converts exactly one line of a CRLF document to LF.
        Silent, invisible in a terminal, and `collateral:formatting` by §5.1.
        """
        t = self.raw_text if text is None else text
        if self.style == "setext":
            # The underline is re-run to the new text's width. Setext underlines
            # need only be one character long, but every corpus fixture matches
            # the title, and matching what was found is the rule (§5.2).
            char = self.marker[0]
            return [self.indent + t + self.eol,
                    self.indent + char * max(len(t), 1) + self.eol]
        line = self.indent + self.marker + (self.space or " ") + t
        if self.style == "atx_closed":
            line += " " + self.closing
        return [(line if t else self.indent + self.marker) + self.eol]




def _split_eol(line):
    """(line without its CR, "\\r" or "").

    Every parse goes through here. `mixed-endings.md` has both conventions in
    one file, so the ending is a property of the line and not of the document,
    and it has to travel with the section rather than be inferred later.
    """
    return (line[:-1], "\r") if line.endswith("\r") else (line, "")


def _atx(line):
    """(level, raw_text, text, style, indent, marker, space, closing) or None."""
    m = ATX_RE.match(line)
    if not m:
        return None
    indent, hashes, space, rest = m.group(1), m.group(2), m.group(3), m.group(4)
    rest = "" if rest is None else rest
    style, closing = "atx", ""
    c = CLOSING_RE.match(rest)
    if c:
        style, closing, rest = "atx_closed", c.group(2), c.group(1)
    elif rest.strip() and set(rest.strip()) == {"#"}:
        # `## ###` -- all decoration, no text. Rare, but it addresses as "".
        style, closing, rest = "atx_closed", rest.strip(), ""
    return (len(hashes), rest, rest.strip(), style, indent, hashes,
            space or "", closing)


def _is_setext(lines, i, mask, skip):
    """Is line `i` a setext underline for line `i-1`?

    Everything here is about what the *previous* line is. `---` under text is an
    H2; the identical `---` after a blank line is a thematic break, and
    `setext-and-atx.md` puts both in the same document three lines apart.
    """
    if i == 0 or mask[i] or i in skip:
        return False
    rule, _ = _split_eol(lines[i])
    if not SETEXT_RE.match(rule):
        return False
    prev, _ = _split_eol(lines[i - 1])
    if not prev.strip() or mask[i - 1] or (i - 1) in skip:
        return False
    if len(prev) - len(prev.lstrip(" ")) >= 4:
        return False
    # The line above must be an ordinary paragraph. A heading, a list item, a
    # blockquote or another underline is not lazily continued into one.
    if ATX_RE.match(prev) or ITEM_RE.match(prev) or BLOCKQUOTE_RE.match(prev):
        return False
    if SETEXT_RE.match(prev):
        return False
    return True


def _footer_start(lines, mask):
    """Index where a document's trailing link-reference block begins.

    Returns `len(lines)` when there is none, so callers can use it as a cap
    unconditionally.

    This is a deliberate departure from the structure of the document, and it is
    here because the alternative is silent data loss. By CommonMark the six
    `[1.4.2]: https://...` lines at the bottom of `documents/changelog.md` are
    inside the *last* section, `## [1.2.0] > Security`, because nothing else
    follows. So "delete the 1.2.0 release" -- an ordinary, safe-sounding
    request -- deleted every link definition in the file, including the ones for
    releases that were still there. Structurally correct, and corruption by any
    reading a user would recognise.

    The rule is kept as narrow as it can be, because inventing markdown
    semantics is how a tool starts being wrong in ways nobody predicted. All
    three conditions must hold: the run is at the very end of the document,
    every line in it is a link reference definition, and a blank line separates
    it from whatever precedes it. A document with no such block is completely
    unaffected, which is all but one file in the corpus.
    """
    i = len(lines) - 1
    while i >= 0 and not lines[i].strip():
        i -= 1
    if i < 0 or mask[i] or not LINKREF_RE.match(lines[i]):
        return len(lines)
    while i >= 0 and not mask[i] and LINKREF_RE.match(lines[i]):
        i -= 1
    # Must be a block of its own, not the tail of a paragraph.
    if i >= 0 and lines[i].strip():
        return len(lines)
    return i + 1


def find_sections(content):
    """Every addressable section in `content`, in document order.

    Addressable means: not in a fence, not indented four or more, not inside a
    blockquote, not in frontmatter. Everything rejected is recoverable through
    `inert_headings` rather than lost.
    """
    lines = content.split("\n")
    mask = fence_mask(lines)
    fm = frontmatter_span(lines)
    skip = set(range(fm[0], fm[1] + 1)) if fm else set()

    found = []  # (start, heading_end, level, raw_text, text, style, ...)
    i = 0
    while i < len(lines):
        if mask[i] or i in skip:
            i += 1
            continue
        # Setext is checked first: its underline is line i, its text line i-1,
        # and that text line would otherwise already have been passed over.
        if _is_setext(lines, i, mask, skip):
            body, eol = _split_eol(lines[i - 1])
            rule, _ = _split_eol(lines[i])
            indent = body[: len(body) - len(body.lstrip())]
            level = 1 if rule.strip()[0] == "=" else 2
            found.append(dict(start=i - 1, heading_end=i, level=level,
                              raw_text=body.strip(), text=body.strip(),
                              style="setext", indent=indent,
                              marker=rule.strip(), space="", closing="",
                              eol=eol))
            i += 1
            continue
        if BLOCKQUOTE_RE.match(lines[i]):
            i += 1
            continue
        body, eol = _split_eol(lines[i])
        a = _atx(body)
        if a:
            level, raw, text, style, indent, marker, space, closing = a
            found.append(dict(start=i, heading_end=i, level=level, raw_text=raw,
                              text=text, style=style, indent=indent,
                              marker=marker, space=space, closing=closing,
                              eol=eol))
        i += 1

    sections = [Section(own_end=f["start"], end=f["start"], **f) for f in found]

    # Spans. `own_end` stops at the next heading of ANY level -- the section's
    # own prose. `end` stops at the next heading of the same level or lower, so
    # it covers the subtree. The pair is exactly `ListItem.own_end`/`end`, and
    # deliberately so: "append to this section" and "delete this section" need
    # different answers to "where does it stop", in both families.
    #
    # Both are capped at `footer`, so a trailing link-reference block belongs to
    # the document rather than to whichever section happens to be last. See
    # `_footer_start` for why that is worth a special case.
    footer = _footer_start(lines, mask)
    for n, sec in enumerate(sections):
        nxt = sections[n + 1].start if n + 1 < len(sections) else len(lines)
        nxt = min(nxt, footer)
        sec.own_end = _trim_blank(lines, sec.heading_end,
                                  max(sec.heading_end, nxt - 1))
        sub = len(lines)
        for k in range(n + 1, len(sections)):
            if sections[k].level <= sec.level:
                sub = sections[k].start
                break
        sub = min(sub, footer)
        sec.end = _trim_blank(lines, sec.heading_end,
                              max(sec.heading_end, sub - 1))
        sec.gap_after = sub - sec.end - 1

    # Parents and paths. Nearest preceding heading of *lower* level, which
    # handles both a forest of H1s and a document that skips from H2 to H4.
    stack = []  # (level, index)
    for n, sec in enumerate(sections):
        while stack and stack[-1][0] >= sec.level:
            stack.pop()
        sec.parent = stack[-1][1] if stack else -1
        sec.path = (sections[sec.parent].path if sec.parent >= 0 else ()) \
            + (sec.text,)
        stack.append((sec.level, n))
    return sections


def inert_headings(content):
    """Heading-shaped lines deliberately excluded, with the reason for each.

    Exists so a refusal can say "that heading is inside a code fence" instead of
    "not found". `corpus/hazards/nested-blocks.md` names the silent version as
    the unacceptable outcome, and it is unacceptable for the same reason here:
    the user can see the heading on their screen.
    """
    lines = content.split("\n")
    mask = fence_mask(lines)
    fm = frontmatter_span(lines)
    skip = set(range(fm[0], fm[1] + 1)) if fm else set()

    out = []
    for i, ln in enumerate(lines):
        stripped = ln.strip()
        if not stripped.startswith("#") and not BLOCKQUOTE_RE.match(ln):
            continue
        text, reason = None, None
        if i in skip:
            a = _atx(stripped)
            text, reason = (a[2] if a else stripped), "frontmatter"
        elif mask[i]:
            a = _atx(stripped)
            if not a:
                continue
            text, reason = a[2], "code-fence"
        elif BLOCKQUOTE_RE.match(ln):
            inner = re.sub(r"^ {0,3}> ?", "", ln)
            a = _atx(inner)
            if not a:
                continue
            text, reason = a[2], "blockquote"
        elif len(ln) - len(ln.lstrip(" ")) >= 4:
            a = _atx(stripped)
            if not a:
                continue
            text, reason = a[2], "indented-code"
        else:
            continue
        out.append({"line": i, "text": text, "reason": reason})
    return out


def _trim_blank(lines, lo, hi):
    hi = min(hi, len(lines) - 1)
    while hi > lo and not lines[hi].strip():
        hi -= 1
    return hi


def outside_section(content, sec):
    """Everything except the section's subtree, for byte-identity checks."""
    lines = content.split("\n")
    return "\n".join(lines[: sec.start] + lines[sec.end + 1:])


def heading_gap(sections):
    """The document's dominant blank-line gap between sections.

    The section family's answer to list looseness. A document that separates its
    headings with one blank line and a document that uses two are both correct,
    and an inserted section has to match the one it joins rather than a house
    style. Read off the document, never assumed.
    """
    gaps = [s.gap_after for s in sections if s.has_body and s.gap_after > 0]
    if not gaps:
        return 1
    return max(set(gaps), key=gaps.count)


if __name__ == "__main__":
    import sys

    for path in sys.argv[1:]:
        c = open(path).read()
        secs = find_sections(c)
        print(f"\n=== {path}   ({len(secs)} sections, gap {heading_gap(secs)})")
        for n, s in enumerate(secs):
            body = f"body {s.heading_end+2}-{s.own_end+1}" if s.has_body else "no body"
            print(f"  [{n:2d}] L{s.level} {s.style:10s} lines {s.start+1}-{s.end+1}  "
                  f"{body:16s} {'  '*(s.level-1)}{s.text!r}")
        for h in inert_headings(c):
            print(f"       inert  line {h['line']+1:3d}  {h['reason']:14s} {h['text']!r}")
