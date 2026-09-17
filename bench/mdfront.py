#!/usr/bin/env python3
"""Frontmatter parsing, shared by the ops and the grader.

The fourth sibling of `mdtable.py`, `mdlist.py` and `mdsection.py`, and the same
shape: small, strict, and only obliged to handle the corpus fixtures. It sits
beside `mdlist.py` rather than above it because `frontmatter_span` already lives
there -- `find_lists` and `find_sections` both need it, since a YAML sequence
looks like a bullet list and a YAML comment looks like an H1 -- and asking two
modules where the frontmatter is, is how they come to disagree.

**This is not a YAML parser and must never become one.**
`corpus/frontmatter/rich.md:37-43` is the whole specification:

    `frontmatter-set build.jobs 8` must change exactly that value. Key order,
    the leading comment, the inline comment on `build.target`, the block scalar
    styles, and the quoting of `quoted_key` must all be byte-identical
    afterward. Most YAML libraries destroy at least three of those on a
    load/dump round trip.

A parse-and-serialize design fails that by construction, so nothing here loads a
value into a Python object and writes it back. Every entry records the byte
offsets of its own pieces -- the text before the key, the key exactly as
written, the gap after the colon, the value, the padding, the trailing comment
-- and an edit rewrites one of those pieces and leaves the rest of the line
alone. Lines no edit names are never touched at all, which is why comments,
blank lines and block scalar styles survive without any code that knows they
exist.

What is deliberately *not* modelled: anchors, aliases, tags, flow mappings
(`{a: 1}`), flow sequences (`[1, 2]`), multi-document streams, and merge keys.
None appears in the corpus. They parse as opaque scalar text, which is the safe
failure: an op that cannot address inside them refuses, and one that rewrites a
sibling leaves them byte-identical.

**Addressing.** Dotted keys, plus bracket indices into a sequence --
`authors[0].role`, which `corpus/frontmatter/rich.md:50` names as one of its own
cases. `REQUIREMENTS.md:405` promises only the dotted form; the wider contract
is a decision recorded in FINDINGS rather than one this module took quietly.
"""

import re
from dataclasses import dataclass

from mdlist import frontmatter_span

# A sequence entry: indent, `-`, then either a space and content, or nothing.
# The empty branch is spelled out so `-` alone is an item rather than a scalar
# that happens to start with a dash.
SEQ_RE = re.compile(r"^([ ]*)(-)(?:([ \t]+)(.*)|()$)")

# A quoted key, both YAML spellings. Kept as one pattern so the key's own quotes
# are part of `key_text` and survive an edit to its value -- `quoted_key` in
# `rich.md` is quoted for a reason and un-quoting it is one of the three things
# that file exists to catch.
QUOTED_KEY_RE = re.compile(r"""^("(?:[^"\\]|\\.)*"|'(?:[^']|'')*')[ \t]*:""")

# A block scalar header: `|`, `>`, with optional chomping and explicit indent.
BLOCK_RE = re.compile(r"^[|>][+-]?\d*$|^[|>]\d*[+-]?$")

# A bracket index in an address: `authors[0]`.
INDEX_RE = re.compile(r"^(.*?)\[(\d+)\]$")


@dataclass
class Entry:
    """One addressable thing in the block, and every byte of the line it owns.

    `line` is where the key is written and `end` is the last line of what it
    owns -- the same line for a scalar, the last child for a map, the last
    content line for a block scalar. Deleting an entry is `lines[line:end+1]`,
    and that is the only definition of "this key's lines" anywhere in the
    family.
    """

    path: tuple           # ("build", "jobs") or ("authors", 0, "role")
    line: int             # line index of the key (or of the `-` for an item)
    end: int              # inclusive last line owned by this entry
    prefix: str           # everything before the key, verbatim: indent, or "  - "
    key_text: str         # the key as written, quotes included; "" for an item
    gap: str              # between the colon and the value
    value: str            # the value text on the key line, verbatim
    pad: str              # between the value and the comment
    comment: str          # "# ...", verbatim, or ""
    kind: str             # scalar | null | map | seq | block | item
    eol: str = ""         # "\r" if this line is CRLF, else ""

    @property
    def indent(self):
        """The column the key starts in -- what a sibling must align to."""
        return len(self.prefix)

    def rebuilt(self, value=None):
        """This entry's key line, with `value` swapped in if one is given.

        The gap is decided by the value, not kept blindly: `empty_value:`
        becomes `empty_value: 4`, and setting a key to null gives back
        `title:` rather than `title: ` with a trailing space that was never in
        the file. `target: release        # comment` keeps both its gap and its
        padding, which is what holds the inline comment in the column it was
        written in.

        The `\\r` goes back on last. Lines arrive from a split on `\\n`, so a
        CRLF line still carries one; a line rebuilt without it is a silent
        conversion of that line to LF, which is `_table_eol`'s defect one family
        over.
        """
        v = self.value if value is None else value
        if self.kind == "item":
            # An item has no key and no colon; the dash is already in `prefix`.
            # A bare `-` carries no gap, so one is supplied rather than writing
            # `-value`, which is a scalar beginning with a dash and not an item.
            pre = self.prefix
            if v and not pre.endswith((" ", "\t")):
                pre += " "
            elif not v and not self.pad and not self.comment:
                # `- ` with nothing after it is a null item written with a
                # trailing space the file never had; `-` alone is the same item.
                pre = pre.rstrip(" \t")
            return f"{pre}{v}{self.pad}{self.comment}{self.eol}"
        gap = (self.gap or " ") if v else ""
        return (f"{self.prefix}{self.key_text}:{gap}{v}{self.pad}{self.comment}"
                f"{self.eol}")


@dataclass
class FrontMatter:
    present: bool
    fmt: str              # "yaml" | "toml" | None
    start: int            # opening delimiter line, or -1
    end: int              # closing delimiter line, or -1
    delim: str            # "---" / "+++" / "", verbatim
    close: str            # the closing delimiter as written -- may be `...`
    entries: list
    eol: str = ""         # the block's own line ending, for lines inserted into it

    def by_path(self):
        return {e.path: e for e in self.entries}

    def children_of(self, path):
        n = len(path)
        return [e for e in self.entries
                if len(e.path) == n + 1 and e.path[:n] == path]

    def top(self):
        return [e for e in self.entries if len(e.path) == 1]


def _split_comment(rest):
    """`rest` after the colon -> (gap, value, pad, comment).

    A `#` is a comment only at the start or after whitespace, and only outside
    quotes. `quoted_key: "value: with a colon"` has neither, but a naive
    `split("#")` would cut `folded: > # ...` styles and any value containing a
    URL fragment, and the damage would be silent -- the comment would be
    re-emitted as part of the value.
    """
    i, q = 0, None
    cut = None
    while i < len(rest):
        ch = rest[i]
        if q:
            if ch == "\\" and q == '"':
                i += 2
                continue
            if ch == q:
                q = None
        elif ch in "\"'":
            q = ch
        elif ch == "#" and (i == 0 or rest[i - 1] in " \t"):
            cut = i
            break
        i += 1

    head, comment = (rest, "") if cut is None else (rest[:cut], rest[cut:])
    stripped = head.lstrip(" \t")
    gap = head[: len(head) - len(stripped)]
    value = stripped.rstrip(" \t")
    pad = stripped[len(value):]
    return gap, value, pad, comment


def _split_key(text):
    """Post-prefix text -> (key_text, rest) or None if this is not a key line.

    A bare key ends at the first colon that is followed by a space or the end of
    the line. That is YAML's own rule, and it is what keeps `quoted_key: "value:
    with a colon"` a single key rather than two.
    """
    m = QUOTED_KEY_RE.match(text)
    if m:
        return m.group(1), text[text.index(":", len(m.group(1))) + 1:]
    if not text or text[0] == "#":
        return None
    i = text.find(":")
    while i != -1:
        if i + 1 == len(text) or text[i + 1] in " \t":
            key = text[:i]
            # A key cannot span a `#`; if one is in the way this is a comment
            # line with a colon in it, not a mapping.
            return (None if "#" in key else (key, text[i + 1:]))
        i = text.find(":", i + 1)
    return None


def _block_end(lines, hi, i, indent):
    """Last line of the block owned by a key at `indent`, starting after `i`.

    Blank lines inside are absorbed; blank lines trailing the block are not, so
    a delete never eats the separator before the next key.
    """
    j, last = i + 1, i
    while j <= hi:
        raw = lines[j]
        if not raw.strip():
            j += 1
            continue
        if len(raw) - len(raw.lstrip(" ")) <= indent:
            break
        last = j
        j += 1
    return last


def _seq_at(lines, hi, i, indent):
    """Last line of a sequence written at its *own key's* indent, or `i`.

    `tags:\\n- a\\n- b` is valid YAML and is what most static site generators
    emit, but the items are not indented past the key, so `_block_end` stops at
    the first one and the key reads as null. Left that way the items parse as a
    second, top-level sequence -- and `frontmatter-delete tags` then removes the
    `tags:` line and leaves them behind, which is the family's worst available
    failure: a success that produces a document nothing can read.

    A key at this indent followed by a dash at the same indent can only be that
    key's sequence; a mapping cannot have a bare `-` sibling. Deeper lines
    belong to whichever item is open.
    """
    j, last = i + 1, i
    while j <= hi:
        raw = lines[j]
        if not raw.strip():
            j += 1
            continue
        ind = len(raw) - len(raw.lstrip(" "))
        if ind < indent or (ind == indent and not SEQ_RE.match(raw)):
            break
        last = j
        j += 1
    return last


def _parse(lines, lo, hi, indent, prefix_path, out):
    """Entries at `indent`, between `lo` and `hi` inclusive, into `out`."""
    i, seq_n = lo, 0
    while i <= hi:
        raw = lines[i]
        if not raw.strip() or raw.lstrip(" ").startswith("#"):
            i += 1
            continue
        ind = len(raw) - len(raw.lstrip(" "))
        if ind < indent:
            break
        if ind > indent:
            # Deeper than anything at this level: owned by a key already taken,
            # or malformed. Either way not ours to describe.
            i += 1
            continue

        m = SEQ_RE.match(raw)
        if m:
            i = _parse_item(lines, hi, i, m, prefix_path, seq_n, out)
            seq_n += 1
            continue

        split = _split_key(raw[ind:])
        if split is None:
            i += 1
            continue
        key_text, rest = split
        i = _parse_key(lines, hi, i, raw[:ind], key_text, rest,
                       prefix_path + (_unquote(key_text),), out)
    return i


def _parse_key(lines, hi, i, prefix, key_text, rest, path, out):
    """One `key:` line and whatever it owns. Returns the next line to read."""
    gap, value, pad, comment = _split_comment(rest)
    end = _block_end(lines, hi, i, len(prefix))
    if end == i and value == "":
        end = _seq_at(lines, hi, i, len(prefix))
    if BLOCK_RE.match(value):
        kind = "block"
    elif end > i:
        first = next((l for l in lines[i + 1:end + 1] if l.strip()), "")
        kind = "seq" if SEQ_RE.match(first) else "map"
    else:
        kind = "null" if value == "" else "scalar"

    out.append(Entry(path, i, end, prefix, key_text, gap, value, pad, comment,
                     kind))
    if kind in ("map", "seq"):
        child_indent = min(len(l) - len(l.lstrip(" "))
                           for l in lines[i + 1:end + 1] if l.strip())
        _parse(lines, i + 1, end, child_indent, path, out)
    return end + 1


def _parse_item(lines, hi, i, m, prefix_path, n, out):
    """One `- ...` sequence item. Returns the next line to read.

    A map item's first key is physically on the dash line, so the key's prefix
    is `indent + "- "` and its siblings align to that column. Recording the
    prefix verbatim is what lets `frontmatter-set authors[0].name` rewrite that
    line without having to know it is the first key of anything.
    """
    ind, dash, sp, content = m.group(1), m.group(2), m.group(3) or "", m.group(4) or ""
    path = prefix_path + (n,)
    end = _block_end(lines, hi, i, len(ind))
    split = _split_key(content) if content else None

    # A scalar item's trailing comment is split off, so setting its value keeps
    # it; a *map* item's is left in `content` on purpose, because the key on
    # that same line owns it and splitting here would give it two owners and
    # write it twice.
    if split is None:
        _, value, pad, comment = _split_comment(content)
    else:
        value, pad, comment = content, "", ""
    out.append(Entry(path, i, end, ind + dash + sp, "", "", value, pad, comment,
                     "item"))

    if split is not None:
        key_text, rest = split
        _parse_key(lines, end, i, ind + dash + sp, key_text, rest,
                   path + (_unquote(key_text),), out)
        # Siblings of that first key sit one line down, at its own column.
        _parse(lines, i + 1, end, len(ind + dash + sp), path, out)
    return end + 1


def _unquote(key_text):
    """The key's identity for addressing, with YAML's two quotings removed."""
    if len(key_text) >= 2 and key_text[0] == key_text[-1] == '"':
        return key_text[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    if len(key_text) >= 2 and key_text[0] == key_text[-1] == "'":
        return key_text[1:-1].replace("''", "'")
    return key_text


def find_frontmatter(content):
    """The block, its format, and every addressable entry in it.

    The span comes from `mdlist.frontmatter_span` rather than from a second
    scanner here, because that one is what the list and section parsers skip
    over: two answers to "where is the frontmatter" is how an op comes to edit
    lines the other family thinks are body. It accepts `+++` as a span, which is
    correct for skipping and wrong for editing, so the *format* is read back off
    the delimiter here and the ops refuse on it.

    Parsing runs over a copy with `\\r` stripped, so every pattern here is
    written once, against the line ending the file does not have. Each entry is
    then told what its own line ended with, which is what `rebuilt` puts back.
    """
    raw = content.split("\n")
    lines = [ln[:-1] if ln.endswith("\r") else ln for ln in raw]
    span = frontmatter_span(lines)
    if span is None:
        return FrontMatter(False, None, -1, -1, "", "", [])
    start, end = span
    delim = lines[start].strip()
    fmt = "yaml" if delim == "---" else "toml"
    entries = []
    if fmt == "yaml" and end > start + 1:
        _parse(lines, start + 1, end - 1, 0, (), entries)
    for e in entries:
        e.eol = "\r" if raw[e.line].endswith("\r") else ""
    return FrontMatter(True, fmt, start, end, delim, lines[end].strip(),
                       entries, "\r" if raw[start].endswith("\r") else "")


def parse_path(text):
    """`"authors[0].role"` -> `("authors", 0, "role")`, or None if unreadable.

    Returns None rather than raising: the refusal belongs in the ops layer,
    where it can name the paths that do exist. An empty segment -- `a..b`,
    `.a`, `a.` -- is unreadable rather than a key whose name is the empty
    string, because no such key can be written in YAML without quotes.
    """
    if not text:
        return None
    out = []
    for seg in text.split("."):
        # `a[0][1]` peels right to left, so the indices come off reversed and
        # go back on in document order once the name is known.
        idx = []
        m = INDEX_RE.match(seg)
        while m:
            seg = m.group(1)
            idx.append(int(m.group(2)))
            m = INDEX_RE.match(seg)
        if not seg and not idx:
            return None
        if seg:
            out.append(seg)
        out.extend(reversed(idx))
    return tuple(out)


def format_path(path):
    """The inverse of `parse_path`, for refusal messages and summaries."""
    out = ""
    for seg in path:
        if isinstance(seg, int):
            out += f"[{seg}]"
        else:
            out += (f".{seg}" if out else seg)
    return out
