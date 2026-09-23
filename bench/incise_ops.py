#!/usr/bin/env python3
"""Reference implementation of incise's Tier 1 table ops, in Python.

Two jobs:

1. It is the executor behind Arm B (`armb.py`) -- the model emits a incise tool
   call and this applies it, so Arm B measures whether the model can *address*
   an edit correctly, independent of whether incise implements it correctly.
2. It is the differential-testing oracle for the Rust implementation. These
   semantics are the spec: REQUIREMENTS.md section 5.2 re-padding, and the two
   invariants from FINDINGS.md F2 and F4.

Deliberately simple and strict. Every failure returns a message written for a
small model to recover from (REQUIREMENTS.md section 5.3), because those
messages are themselves part of what Arm B measures.
"""

import difflib
import heapq
import json

import mdfront
from mdlist import ITEM_RE, find_lists
from mdsection import ATX_RE, find_sections, heading_gap, inert_headings
from mdtable import find_tables, split_row

MARKER_NONE, MARKER_LEFT, MARKER_RIGHT, MARKER_CENTER = 0, 1, 2, 3


def _close_matches(word, possibilities, n, cutoff):
    """`difflib.get_close_matches`, transcribed, with `autojunk=False`.

    Every "Near matches:" line in this file comes from here, and §5.3 makes
    those lines part of the contract -- so the reason for not calling the
    stdlib function has to be better than a preference.

    `get_close_matches` takes no `autojunk` argument and therefore cannot opt
    out of the heuristic the way `_line_counts` does. It calls `set_seq2(word)`,
    which makes the **caller's value** the indexed side, and it diffs by
    character -- so the 200-element threshold counts *characters of the value a
    model sent*, not candidates. Send a 200-character cell value and difflib
    drops every character occurring more than `n // 100 + 1` times, which for a
    sentence means the spaces and the vowels: the answer stops being a string
    similarity at all. Measured on `bench/synthetic/long-cells.md`, a value one
    word short of a real cell scored below the 0.4 cutoff against the cell it
    was derived from, and the refusal read `Near matches: none` while a 98%
    match sat in the column.

    This is F-autojunk one layer up, and the same argument settles it: the
    heuristic is a speed guard that assumes popular elements are noise, and for
    our data they are the signal. Turning it off is a deliberate divergence
    from stdlib, so it is bounded to exactly that -- `SequenceMatcher` still
    does the matching, the ratio filters are still upper bounds applied in the
    same order, and `nlargest` still breaks ties on `(score, candidate)`. The
    body below is the stdlib body with one keyword added and the two argument
    validations dropped, because every caller here passes literals.

    `bench/test_incise_ops.py` pins it to stdlib on every input where autojunk
    cannot engage, which is the only place the two are allowed to agree by
    assumption rather than by test. FINDINGS F-nearmatch.
    """
    s = difflib.SequenceMatcher(autojunk=False)
    s.set_seq2(word)
    result = []
    for x in possibilities:
        s.set_seq1(x)
        if (s.real_quick_ratio() >= cutoff and s.quick_ratio() >= cutoff
                and s.ratio() >= cutoff):
            result.append((s.ratio(), x))
    return [x for _score, x in heapq.nlargest(n, result)]


class OpError(Exception):
    """A failure whose message is intended to be handed straight back to a model."""


# --------------------------------------------------------------------------
# structure
# --------------------------------------------------------------------------

def _headings(lines):
    """(line_index, level, text) for every addressable heading.

    Was a private ATX-only scanner. It now delegates to `mdsection`, which was
    written for the section family and is strictly better in two ways this
    function was silently wrong about:

      * **Frontmatter.** `corpus/frontmatter/rich.md` opens with the YAML
        comment `# Build configuration for the example project`. The old
        scanner read it as an H1, so `render_list_summary` told the model that
        two of that file's lists lived under a heading that does not exist.
      * **Setext.** The three setext headings in
        `corpus/sections/setext-and-atx.md` were invisible, so anything under
        them was reported at the wrong path -- or at no path at all.

    Those are the *only* two files in the corpus where the two scanners
    disagree, and neither backs a task or a golden, so no measured result moves.
    Verified by `test_heading_scanners_agree` rather than asserted here.
    """
    return [(s.start, s.level, s.text) for s in find_sections("\n".join(lines))]


def heading_path(lines, table):
    """Heading path enclosing a table, as a list of headings outermost-first."""
    stack = []
    for idx, level, text in _headings(lines):
        if idx > table.start:
            break
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, text))
    return [t for _, t in stack]


def caption(lines, table):
    """The label introducing a table, or "" if it has none.

    Needed because heading path plus columns does not disambiguate
    corpus/tables/multiple-per-section.md, where three tables under one heading
    share identical columns and differ only by the line above them.

    A caption must be the nearest non-blank line above the table *and* end in a
    colon. The colon is not decoration -- without it the rule returns the last
    line of whatever paragraph happens to precede the table, which on
    corpus/tables/ragged.md yields the mid-sentence fragment "treated as ragged
    and left alone." A wrong label is worse than no label: it costs prompt
    tokens and actively misdescribes the table. Captions are only a
    disambiguation hint anyway -- addressing is by heading and ordinal -- so the
    conservative rule loses nothing.
    """
    for i in range(table.start - 1, -1, -1):
        s = lines[i].strip()
        if not s:
            continue
        if s.startswith("#") or s.startswith("|") or not s.endswith(":"):
            return ""
        return s[:-1].strip()
    return ""


def list_tables(content, path):
    """The compact structural summary a model sees instead of the document."""
    lines = content.split("\n")
    out = []
    for t in find_tables(content):
        out.append({
            "ordinal": None,  # filled below, per heading
            "heading": " > ".join(heading_path(lines, t)) or "(document root)",
            "caption": caption(lines, t),
            "columns": list(t.cells(t.header)),
            "rows": len(t.body),
        })
    # Ordinal is per heading path, matching how a model would count them.
    seen = {}
    for e in out:
        e["ordinal"] = seen.get(e["heading"], 0)
        seen[e["heading"]] = e["ordinal"] + 1
    return out


def render_table_list(content, path):
    """Human/model-readable form of list_tables -- the Arm B prompt context."""
    entries = list_tables(content, path)
    lines = [f"Tables in `{path}`:"]
    for e in entries:
        cap = f'  labelled "{e["caption"]}"' if e["caption"] else ""
        lines.append(
            f'  heading "{e["heading"]}"  ordinal {e["ordinal"]}{cap}\n'
            f'    columns: {" | ".join(e["columns"])}   ({e["rows"]} rows)'
        )
    return "\n".join(lines)


def table_get(content, address, filter=None):
    """Rows of one named table, optionally filtered. A read, not an edit.

    Not an `apply_op` entry, and deliberately so (REQUIREMENTS.md 6.1). Every op
    in `OPS` takes a document and returns a document or a refusal; this returns
    text *about* a document, which does not fit that contract. Adding it anyway
    would also change the "unknown operation" refusal, which is a sentence the
    benchmark measured.

    `filter` is not `where`. On the write ops `where` must identify exactly one
    row or refuse, because B2 measured the model inventing selector values and
    silently editing the wrong row. On a read, zero or many matches is the
    normal answer and refusing would be absurd -- so the leniency gets its own
    word rather than overloading a strict one, which is the mistake S15 found in
    `path` and fixed by renaming.
    """
    table = _locate_table(content, address)
    _check_rectangular(table, read=True)
    cols = list(table.cells(table.header))
    supplied = _check_filter(filter) or {}
    supplied = {k: _check_cell(v, k, "filter") for k, v in supplied.items()}
    for c in supplied:
        if c not in cols:
            near = _close_matches(c, cols, n=2, cutoff=0.4)
            raise OpError(
                f'no column "{c}".\n  Near matches: {", ".join(near) if near else "none"}'
                f'\n  Columns: {" | ".join(cols)}'
            )
        # The one call site with a performable remedy. FINDINGS, F-remedy.
        _check_unambiguous(
            cols, c,
            "Omit `filter` to read every row, and pick the one you want "
            "from the result.",
        )
    rows = table.rows()
    kept = [r for r in rows
            if all(str(dict(zip(cols, r)).get(k, "")) == str(v)
                   for k, v in supplied.items())]
    lines = content.split("\n")
    return {
        "heading": " > ".join(heading_path(lines, table)) or "(document root)",
        "columns": cols,
        # Positional, not keyed by column name. A table may legally repeat a
        # header, and `dict(zip(cols, row))` would then report the last such
        # cell's value under every one of its positions -- a false statement
        # about the document, in the op whose whole job is to report the
        # document. `_check_unambiguous` refuses a *filter* on a repeated name;
        # it does not refuse the table, so the rows still have to be right.
        "rows": kept,
        "matched": len(kept),
        "total": len(rows),
    }


def render_table_get(content, address, filter=None):
    r"""Model-readable form of table_get.

    Rendered with single-space padding rather than aligned. Alignment is a
    display-width question this tool cannot answer (REQUIREMENTS.md 5.2, and the
    reason `table-realign` refuses some tables), and a *result* has no author's
    formatting to preserve -- so the honest option is the one that never claims
    an alignment it cannot verify.

    Cells are emitted exactly as stored, escapes intact, because `split_row`
    leaves them intact: a cell holding `a \| b` round-trips as `a \| b` and the
    rendered table has the column count it claims.
    """
    got = table_get(content, address, filter)
    head = (f'Table "{got["heading"]}" -- {got["matched"]} of {got["total"]} '
            f'row{"" if got["total"] == 1 else "s"}')
    if not got["rows"]:
        # A read that matched nothing still has to be actionable (5.3): the
        # columns are the thing the caller got wrong, so name them.
        return (f'{head}\n  No row matches.\n'
                f'  Columns: {" | ".join(got["columns"])}')
    out = [head,
           "| " + " | ".join(got["columns"]) + " |",
           "| " + " | ".join("---" for _ in got["columns"]) + " |"]
    for r in got["rows"]:
        out.append("| " + " | ".join(r) + " |")
    return "\n".join(out)


def _check_unambiguous(cols, name, remedy=None):
    r"""Refuse a column name this table's header uses more than once.

    GFM permits two columns with the same name, and nothing can then say which
    one `where`, `column`, `values` or `filter` meant. Three places in this
    project answered that unanswerable question three different ways:
    `dict(zip(cols, row))` keeps the *last*, `cols.index(name)` finds the
    *first*, and the Rust port's `cell_of` also finds the first -- so the oracle
    matched a row against the last column and then wrote into the first, and the
    port matched against the first. Both reported success (FINDINGS F-dupcol).

    Refused, for the reason `_check_rectangular` gives: this tool does not guess
    which cell the caller meant. Scoped to *name* resolution, so the ops that
    never map a name to a cell -- `table-realign`, and an ordered `values` --
    still work on such a table.

    `remedy` replaces the last line, and the default is the shipped sentence.
    F-remedy measured that sentence at 0/10 recovery: it names a document edit
    no tool in the set can make, and every one of the ten trials read it,
    believed it and reported the question unanswerable. But there is no single
    performable remedy here, because what the caller can do depends on which
    argument it sent -- omitting `filter` answers the question, and nothing
    addresses a repeated column for `column`, where renaming really is the only
    way out. So the caller passes the remedy it can honour, and the default
    stays byte-identical to what was measured. Only the `filter` site overrides
    it today; the other three are reached 0 times in 2071 recorded trials, and
    rewriting a refusal nothing draws is an unmeasured 5.3 change.
    """
    n = sum(1 for c in cols if c == name)
    if n > 1:
        raise OpError(
            f'the column "{name}" appears {n} times in this table\'s header, so '
            "it does not identify one cell.\n"
            f'  Columns: {" | ".join(cols)}\n'
            "  " + (remedy or "Rename one of them in the document, then retry.")
        )


def _check_filter(value):
    """`filter` is an object mapping column name to the value to match.

    Same shapes and the same refusal as `where` (`_check_where`), because the
    model's mistakes do not know which op it is calling. The difference between
    the two is what happens when the object is *valid* and matches nothing.
    """
    if value is None or isinstance(value, dict):
        return value
    raise OpError(
        f"`filter` must be an object mapping column names to values, but "
        f"arrived as {_type_name(value)}.\n"
        f"  Got: {value!r}\n"
        '  Send {"Column": "value"}, or omit it to get every row.'
    )


# --------------------------------------------------------------------------
# addressing
# --------------------------------------------------------------------------

def resolve_table(content, address):
    """The table an address names, once it is safe to rewrite.

    Split from `_locate_table` so the rectangularity guard applies to every op
    without being repeated at each of the four places a table is found.
    """
    table = _locate_table(content, address)
    _check_rectangular(table)
    return table


def _check_rectangular(table, read=False):
    r"""Refuse a table whose rows disagree with its header on cell count.

    `corpus/tables/cell-edge-cases.md` states the requirement in the document
    itself: "GFM pads short rows and truncates long ones. incise must decide
    explicitly: normalize to the header's column count, or fail loudly. It must
    not silently drop the extra cell." This is the loud failure.

    Without it, `table-update-cell` on a short row raised `IndexError` out of the
    backstop in `apply_op` -- an exception repr where section 5.3 wants a repair --
    and on a long row it wrote into a cell the header does not name and re-emitted
    the row at its own width, so the table's column count changed. Both reported
    success.

    Normalizing instead was rejected for the reason the fixture gives: padding a
    short row invents a cell, truncating a long one destroys bytes GFM would have
    hidden but not deleted. Neither is a formatting change, and this tool's only
    reformatting operation is one the caller asks for by name.

    `read=True` is `table_get`, which refuses the same tables for a different
    reason: it names cells by column, and a row that disagrees with the header
    has no unambiguous mapping. Only the third line changes, because "will not
    rewrite" is not true of a read and a message that misdescribes what the tool
    was doing is the sort of thing section 5.3 exists to prevent. Refusing is
    also the more useful answer -- every *write* to this table will refuse too,
    so saying so now, with the row named, is the shortest path to a document
    that works.
    """
    counts = [len(split_row(ln)) for ln in table.lines]
    want = counts[0]
    for i, n in enumerate(counts):
        if n == want:
            continue
        where = "the delimiter row" if i == 1 else f"row {i - 1}"
        cannot = ("incise will not report cells it cannot map to columns"
                  if read else
                  "incise will not rewrite a table it cannot read")
        raise OpError(
            f"this table is not rectangular: the header has {want} columns but "
            f"{where} has {n}.\n"
            f"  {where.capitalize()}: {table.lines[i].strip()}\n"
            f"  {cannot} unambiguously.\n"
            "  A literal pipe inside a cell must be written `\\|`; otherwise add "
            "or remove a cell by hand, then retry."
        )


def _locate_table(content, address):
    """Find the one table an address names, or raise with the candidates.

    `address` is either an object -- {"heading": ..., "ordinal": N} -- or a bare
    heading string, which is shorthand for {"heading": ...}. The string form
    exists for the same reason the ordered row form does (REQUIREMENTS.md 6.2):
    a nested object the model has to assemble is friction, and the measured
    failure here was the model omitting the address altogether.
    """
    if isinstance(address, str):
        address = {"heading": address}
    address = _check_address(address, "table")
    lines = content.split("\n")
    tables = find_tables(content)
    entries = list_tables(content, "")
    want_h = _check_heading((address or {}).get("heading"), "table")
    want_o = _check_ordinal((address or {}).get("ordinal"), "table")

    if want_h is None:
        if len(tables) == 1:
            return tables[0]
        raise OpError(
            "table address required: this file has "
            f"{len(tables)} tables.\n  Candidates: "
            + "; ".join(f'"{e["heading"]}" ordinal {e["ordinal"]}' for e in entries)
        )

    norm = want_h.strip().lower()
    matched = [
        (t, e) for t, e in zip(tables, entries)
        if e["heading"].lower() == norm or e["heading"].lower().split(" > ")[-1] == norm
    ]
    if not matched:
        near = _close_matches(want_h, [e["heading"] for e in entries], n=3, cutoff=0.4)
        raise OpError(
            f'no table under heading "{want_h}".\n'
            f'  Near matches: {", ".join(near) if near else "none"}\n'
            f'  Headings with tables: {", ".join(sorted({e["heading"] for e in entries}))}'
        )
    if want_o is None:
        if len(matched) == 1:
            return matched[0][0]
        raise OpError(
            f'ambiguous: {len(matched)} tables under "{want_h}". Pass an ordinal.\n'
            "  Candidates: "
            + "; ".join(
                f'ordinal {e["ordinal"]}'
                + (f' ("{e["caption"]}")' if e["caption"] else "")
                + f' columns {" | ".join(e["columns"])}'
                for _, e in matched
            )
        )
    for t, e in matched:
        if e["ordinal"] == want_o:
            return t
    raise OpError(
        f'no table with ordinal {want_o} under "{want_h}".\n'
        f'  Valid ordinals: {", ".join(str(e["ordinal"]) for _, e in matched)}'
    )


def resolve_row(table, where):
    """Index into table.body for the single row matching `where`, or raise."""
    where = _check_where(where)
    if not where:
        raise OpError("a `where` selector is required to identify the row.")
    cols = list(table.cells(table.header))
    where = {k: _check_cell(v, k, "where") for k, v in where.items()}
    for c in where:
        if c not in cols:
            near = _close_matches(c, cols, n=2, cutoff=0.4)
            raise OpError(
                f'no column "{c}".\n  Near matches: {", ".join(near) if near else "none"}'
                f'\n  Columns: {" | ".join(cols)}'
            )
        _check_unambiguous(cols, c)
    hits = []
    for i, row in enumerate(table.rows()):
        rec = dict(zip(cols, row))
        if all(str(rec.get(k, "")) == str(v) for k, v in where.items()):
            hits.append(i)
    if not hits:
        raise OpError(_no_row_message(table, cols, where))
    if len(hits) > 1:
        raise OpError(
            f"{len(hits)} rows match {where}; the selector must identify exactly one."
        )
    return hits[0]


def _no_row_message(table, cols, where):
    """Explain a failed row selector well enough for a model to fix it in one turn.

    Arm B (FINDINGS.md B2) measured the failure this exists for: the model
    cannot see the document, so it *invents* extra selector columns --
    `{Component: "gadget", Owner: "unknown", Status: "active"}` against a row
    that is actually retired/rowan. Refusing is right; the document is untouched
    and the model gets a turn to retry.

    But the naive message reported only `next(iter(where))`, which picked the
    one key that DID match and said 'no row where Component="gadget" / near
    matches: gadget'. That is worse than useless -- it points at the correct
    part of the selector. So when some keys match and others do not, name the
    conflict precisely and say what to send instead.
    """
    rows = table.rows()
    sel = ", ".join(f'{k}="{v}"' for k, v in where.items())
    recs = [dict(zip(cols, r)) for r in rows]

    def matched(rec):
        return [k for k, v in where.items() if str(rec.get(k, "")) == str(v)]

    # Which row did the model most likely mean? Not "the first row matching any
    # key" -- that picks whichever row happens to share a low-information value.
    # On the measured delete-row failure, `Status="active"` matched `widget`
    # before `Component="gadget"` matched the intended row, and the message then
    # advised sending `{"Status": "active"}`, which matches two rows.
    #
    # Score a match by how identifying it is: 1/(rows sharing that value). A
    # value unique to one row scores 1.0; one shared by two scores 0.5. So
    # "gadget" beats "active" and the message names the row the model meant.
    def selectivity(rec, k):
        v = str(where[k])
        n = sum(1 for r in recs if str(r.get(k, "")) == v)
        return 1.0 / n if n else 0.0

    scored = [
        (sum(selectivity(rec, k) for k in matched(rec)), i, rec)
        for i, rec in enumerate(recs) if matched(rec)
    ]

    if scored and len(where) > 1:
        _, i, rec = max(scored, key=lambda t: t[0])
        good = matched(rec)
        bad = [(k, v) for k, v in where.items() if k not in good]
        conflicts = ", ".join(
            f'you said {k}="{v}" but it is "{rec.get(k, "")}"' for k, v in bad
        )
        subset = {k: str(where[k]) for k in good}
        unique = sum(
            1 for r in recs if all(str(r.get(k, "")) == v for k, v in subset.items())
        ) == 1
        fix = (
            f"  `where` only needs enough columns to identify one row. "
            f"Send {json.dumps(subset)}."
            if unique else
            "  `where` must match one row exactly. Drop the columns you are not "
            "sure of, and keep enough to be unique."
        )
        return (
            f"no row matches all of {{{sel}}}.\n"
            f'  Row {i + 1} matches on {", ".join(good)}, but {conflicts}.\n' + fix
        )

    col, val = next(iter(where.items()))
    vals = [rec.get(col, "") for rec in recs]
    near = _close_matches(str(val), vals, n=3, cutoff=0.4)
    return (
        f'no row where {col}="{val}".\n'
        f'  Near matches: {", ".join(near) if near else "none"}\n'
        f'  Values in {col}: {", ".join(vals) if vals else "(table is empty)"}'
    )


# --------------------------------------------------------------------------
# rendering -- REQUIREMENTS.md section 5.2
# --------------------------------------------------------------------------

def _marker(delim_cell):
    c = delim_cell.strip()
    if c.startswith(":") and c.endswith(":"):
        return MARKER_CENTER
    if c.startswith(":"):
        return MARKER_LEFT
    if c.endswith(":"):
        return MARKER_RIGHT
    return MARKER_NONE


def _delim_cell(marker, width):
    """Rebuild one delimiter cell at `width` chars between pipes, markers intact."""
    inner = max(width - 2, 3)
    if marker == MARKER_CENTER:
        body = ":" + "-" * max(inner - 2, 1) + ":"
    elif marker == MARKER_LEFT:
        body = ":" + "-" * max(inner - 1, 1)
    elif marker == MARKER_RIGHT:
        body = "-" * max(inner - 1, 1) + ":"
    else:
        body = "-" * inner
    return " " + body + " "


def _render_aligned(header, markers, body, existing):
    """Re-pad every line to uniform column width. The whole point of the tool.

    `existing` is the table's current column widths. Columns are **widened when
    content requires it and never shrunk**, which is not a detail:

    - corpus/tables/aligned.md pads Owner to 9 where its content needs 7. A
      renderer that normalized to minimum width would rewrite all three existing
      rows just to append a short one -- breaking the byte-preservation
      invariant (REQUIREMENTS.md 5.2) on the most common operation there is.
    - Shrinking on delete would likewise rewrite an entire table to remove one
      row.

    So a short add touches only the added line, a delete touches only the
    removed line, and a re-pad happens exactly when some value genuinely
    outgrows its column.
    """
    ncols = len(header)
    widths = []
    for i in range(ncols):
        need = max([len(header[i])] + [len(r[i]) for r in body]) + 2
        widths.append(max(need, existing[i] if i < len(existing) else 0, 5))

    def row(cells):
        return "|" + "|".join(f" {c.ljust(widths[i] - 2)} " for i, c in enumerate(cells)) + "|"

    out = [row(header)]
    out.append("|" + "|".join(_delim_cell(markers[i], widths[i]) for i in range(ncols)) + "|")
    out.extend(row(r) for r in body)
    return out


def _render_row_loose(cells):
    """Single-space padding, for inserting into a ragged table (5.2)."""
    return "| " + " | ".join(cells) + " |"


def _table_eol(table):
    """The line ending the table's own lines use, or raise if they disagree.

    Lines arrive from a split on '\\n', so a CRLF line still carries its '\\r'.
    Rebuilt lines are constructed fresh and would silently drop it, converting a
    CRLF table to LF -- caught by corpus/hazards/crlf.md.

    REQUIREMENTS.md 12.3 asks what to do when a file has no single convention.
    Scoped to one table the answer is narrower and can be decided here: match
    the table's own lines when they agree, and refuse when they do not, rather
    than silently picking a winner. Whole-file convention is not consulted --
    5.2 says an edit touches the target range only.
    """
    eols = {"\r" if ln.endswith("\r") else "" for ln in table.lines}
    if len(eols) == 1:
        return eols.pop()
    raise OpError(
        "this table mixes CRLF and LF line endings, so there is no convention "
        "to match.\n  Normalize the table's line endings first, then retry."
    )


def _table_indent(table):
    """The leading whitespace shared by the table's lines, or raise if they differ.

    A table inside a list item is indented (`corpus/hazards/nested-blocks.md`).
    Rebuilt lines are constructed from cell values and carry no indentation, so
    without this a table nested in a list is silently de-indented and falls out
    of its list item -- structural corruption of the kind REQUIREMENTS.md 12.4
    calls the worst possible outcome. Caught by the add-then-delete round-trip
    in `test_incise_ops.py`, not by inspection.
    """
    indents = {ln[: len(ln) - len(ln.lstrip())] for ln in table.lines}
    if len(indents) == 1:
        return indents.pop()
    raise OpError(
        "this table's lines are indented inconsistently, so there is no "
        "indentation to match.\n  Normalize the table's indentation first, then retry."
    )


def _has_tabs(table):
    """True if any of the table's lines contains a tab.

    `corpus/hazards/whitespace.md` pads its cells with tabs. Those cells have
    equal *character* counts, so `is_aligned()` reports aligned and the re-pad
    path rewrites the tabs to spaces -- a silent whitespace rewrite of lines
    nobody asked to touch.

    Character-count alignment is the only kind that can be maintained
    arithmetically; tab alignment depends on a tab stop this tool does not know.
    So a tab-containing table is treated as ragged: existing lines are preserved
    byte-for-byte and only the new row is rendered. This follows the rule
    already in 5.2 -- alignment is computed from the table as found, and a table
    whose alignment cannot be verified counts as ragged.
    """
    return any("\t" in ln for ln in table.lines)


def _rebuild(content, table, header, body, was_aligned, realign=False):
    """Splice the table's lines back into the document, touching nothing else.

    Invariant (FINDINGS.md F4): only lines table.start..table.end are replaced,
    so the blank line after the table is structurally untouchable.

    `realign` is the one caller that is allowed to reformat lines nobody named:
    `table_realign`, the sanctioned repair for the ratchet in REQUIREMENTS.md
    5.2. It differs from the ordinary aligned path in exactly two ways, both
    deliberate. It renders aligned even when the table was found ragged -- that
    is the whole operation -- and it passes no `existing` widths, so columns
    come from content alone rather than inheriting a floor from whatever
    padding the damaged table happened to carry.
    """
    lines = content.split("\n")
    eol = _table_eol(table)
    indent = _table_indent(table)
    markers = [_marker(c) for c in split_row(table.delimiter)]

    def bare(ln):
        return ln.rstrip("\r")[len(indent):]

    if realign:
        new_lines = _render_aligned(header, markers, body, [])
    elif was_aligned and not _has_tabs(table):
        new_lines = _render_aligned(header, markers, body, list(table.widths()[0]))
    else:
        existing = {tuple(table.cells(ln)): bare(ln) for ln in table.lines}
        new_lines = [existing.get(tuple(header), _render_row_loose(header)),
                     bare(table.delimiter)]
        new_lines += [existing.get(tuple(r), _render_row_loose(r)) for r in body]
    new_lines = [indent + ln + eol for ln in new_lines]
    return "\n".join(lines[: table.start] + new_lines + lines[table.end + 1:])


# --------------------------------------------------------------------------
# operations
# --------------------------------------------------------------------------

def _values_to_row(cols, values):
    """Normalize either row shape into a cell list in column order.

    Two shapes are accepted (REQUIREMENTS.md 6.2), because Arm B measured the
    named-only shape scoring 3/10 on an instruction that supplied values
    positionally -- "add a row with the values i, j, k and l" -- against 9/10
    for editing the document directly. The object shape imposed a
    positional->named translation the model gets wrong.

    The ordered form is strict about length. A short array is the one case where
    guessing would be catastrophic: silently left-padding or right-padding puts
    every value in the wrong column, and the result is a well-formed table that
    is entirely wrong. Refuse and say the count.
    """
    if isinstance(values, (list, tuple)):
        if len(values) != len(cols):
            raise OpError(
                f"`values` is an array of {len(values)}, but the table has "
                f'{len(cols)} columns: {" | ".join(cols)}.\n'
                "  Ordered rows must supply every column, in order. Use the "
                "named form to fill only some."
            )
        return [_check_cell(v, cols[i], "values") for i, v in enumerate(values)]

    if not isinstance(values, dict):
        raise OpError(
            f"`values` must be an object keyed by column name, or an ordered "
            f'array of {len(cols)} values.\n  Columns: {" | ".join(cols)}'
        )

    unknown = [k for k in values if k not in cols]
    if unknown:
        near = _close_matches(unknown[0], cols, n=2, cutoff=0.4)
        raise OpError(
            f'no column "{unknown[0]}".\n'
            f'  Near matches: {", ".join(near) if near else "none"}\n'
            f'  Columns: {" | ".join(cols)}'
        )
    for k in values:
        _check_unambiguous(cols, k)
    # An absent column is an empty cell -- that is the named form's whole
    # point. A column present with an unusable value is a different thing, and
    # `_check_cell` refuses it rather than writing a Python repr into the row.
    return [_check_cell(values[c], c, "values") if c in values else ""
            for c in cols]


def table_add_row(content, address, values, position="end", row=None):
    """Add a row. `values` takes either shape; `row` is a legacy alias.

    The shipping schema exposes **one** argument (REQUIREMENTS.md 6.2) -- the
    two-parameter variant was measured and rejected. `row` is still accepted
    here so scheme_d's recorded trials stay regradable without re-spending GPU
    time. Do not add it to the tool schema.
    """
    table = resolve_table(content, address)
    cols = list(table.cells(table.header))
    if values is not None and row is not None:
        # Accept iff both readings produce the identical row. Measured: given
        # two ways to express a row, the model sometimes fills in both (3/60 in
        # scheme_d), and usually they agree exactly -- refusing then would cost
        # a turn to arrive at the same bytes.
        #
        # This is NOT the relaxation rejected for `where` in REQUIREMENTS.md
        # 6.2. That one would have *discarded* a constraint the model asserted,
        # changing which row is affected. Here nothing is discarded and there is
        # no ambiguity to resolve: if the two disagree by even one cell we still
        # refuse, because then one of them is wrong and guessing which is the
        # error worth preventing.
        if _values_to_row(cols, values) != _values_to_row(cols, row):
            raise OpError(
                "`values` and `row` describe different rows:\n"
                f'  values -> {_values_to_row(cols, values)}\n'
                f"  row    -> {_values_to_row(cols, row)}\n"
                "  Supply exactly one of them."
            )
        row = None
    supplied = values if values is not None else row
    if not supplied:
        # Names `values` and nothing else, in the schema's own words. This
        # sentence used to offer `row` as an ordered array, which the shipping
        # schema does not declare and the crate refuses on purpose
        # (`ops/dispatch.rs`, §6.2) -- so it recommended a repair that could not
        # work. There is no measured cost and no population to measure one on:
        # of 480 recorded table calls, zero ever drew this refusal, and all 41
        # `row`-as-array calls came from `scheme_d`, the one scheme that
        # declares it. (F-framing appeared to price it at 13/38; that was a
        # harness artifact and is withdrawn -- see FINDINGS, "the stratum is an
        # artifact".) It is fixed because a refusal must describe the schema in
        # force, which is §5.3, not because a number said so. The oracle still
        # *accepts* `row` above, because scheme_d's recorded trials have to stay
        # regradable; accepting more than you advertise is safe, and the bug was
        # advertising more than the product accepts.
        raise OpError(
            f'a row is required: `values`, either an object keyed by column '
            f'name or an array of values in column order.'
            f'\n  Columns: {" | ".join(cols)}'
        )
    new = _values_to_row(cols, supplied)
    body = table.rows()
    position = _check_position(position)
    if position == "start":
        body = [tuple(new)] + body
    elif isinstance(position, int):
        body = body[:position] + [tuple(new)] + body[position:]
    else:
        body = body + [tuple(new)]
    return _rebuild(content, table, cols, [list(r) for r in body], table.is_aligned())


def table_update_cell(content, address, where, column, value):
    table = resolve_table(content, address)
    cols = list(table.cells(table.header))
    column = _check_column(column)
    if column not in cols:
        near = _close_matches(column, cols, n=2, cutoff=0.4)
        raise OpError(
            f'no column "{column}".\n'
            f'  Near matches: {", ".join(near) if near else "none"}\n'
            f'  Columns: {" | ".join(cols)}'
        )
    _check_unambiguous(cols, column)

    idx = resolve_row(table, where)
    # After the row resolves, not before: every recorded trial sent a usable
    # value, so this placement is the one that cannot move a graded call.
    value = _check_value(value, column)
    body = [list(r) for r in table.rows()]
    body[idx][cols.index(column)] = value
    return _rebuild(content, table, cols, body, table.is_aligned())


def table_delete_row(content, address, where):
    table = resolve_table(content, address)
    cols = list(table.cells(table.header))
    idx = resolve_row(table, where)
    body = [list(r) for r in table.rows()]
    del body[idx]
    return _rebuild(content, table, cols, body, table.is_aligned())


def table_realign(content, address):
    """Re-pad one named table to uniform column width.

    The only reformatting operation in the tool (REQUIREMENTS.md 6.2) and the
    repair path for the ratchet in 5.2: alignment is detected from the table as
    found, so one misalignment introduced by anything else flips that table to
    ragged permanently, and every later incise edit then preserves the
    raggedness faithfully because that is the rule. Nothing else can undo it.

    It is safe only because it is *requested*. incise cannot tell a ragged table
    the author wrote from one that was damaged, so it never infers this, never
    applies it to a whole document, and takes an address like any other op.

    Already aligned is a no-op, and `describe_change` reports it as one --
    "Applied, but the document is unchanged." That is not just an optimization.
    Re-rendering an aligned table would *shrink* it to minimum width, and
    `corpus/tables/aligned.md` pads Owner to 9 where its content needs 7. That
    padding is an author's choice, and 5.2 protects it everywhere else; realign
    is a repair, not a normalizer, so it must not take it away either.

    A tab-padded table is not "already aligned" for this purpose. Its cells have
    equal character counts, so `is_aligned()` says yes, but 5.2 counts a table
    whose alignment cannot be verified as ragged -- which is exactly the state
    this op exists to repair, so it goes down the realign path.

    Non-ASCII tables are refused outright; see `_check_realignable`.    """
    table = resolve_table(content, address)
    if table.is_aligned() and not _has_tabs(table):
        return content
    _check_realignable(table)
    cols = list(table.cells(table.header))
    body = [list(r) for r in table.rows()]
    return _rebuild(content, table, cols, body, True, realign=True)


def _check_realignable(table):
    """Refuse to re-pad a table whose width incise cannot measure.

    Column width here is counted in **characters**, which is the only measure
    that can be maintained arithmetically without a full Unicode width table
    (see `Table.widths`). A terminal lays text out in **display columns**, and
    for CJK, Hangul, kana, fullwidth forms and emoji the two disagree by a
    factor of two.

    `corpus/tables/cell-edge-cases.md` is the case. Its cells are padded to
    display width, so by character count it reads ragged -- and realigning it
    re-pads to character count, producing a table that is aligned by incise's
    measure and visibly *worse* on screen than what it replaced. Realign exists
    to make a table look aligned; an output that looks less aligned than the
    input is a failure of the operation on its own terms, not a trade-off.

    So it is refused, and only here. Add, update and delete never reach the
    aligned renderer on such a table -- it reads ragged, so they take the loose
    path and preserve every existing line byte-for-byte (5.2). Only the reformat
    is withheld, which is the reversible choice: a refusal can be relaxed later,
    a mangled table has already been written.
    """
    bad = next((ch for ln in table.lines for ch in ln if _not_one_column(ch)), None)
    if bad is None:
        return
    cell = next(c for ln in table.lines for c in table.cells(ln)
                if any(_not_one_column(ch) for ch in c))
    raise OpError(
        f'this table contains "{bad}", which does not occupy one display '
        "column, and incise counts column width in characters.\n"
        "  Re-padding it would produce a table that is aligned by that count "
        "and ragged on screen, which is the opposite of what realign is for.\n"
        f'  First such cell: "{cell}"\n'
        "  Realign is refused. Add, update and delete still work on this table "
        "and leave its existing lines byte-for-byte intact."
    )


# East Asian Wide and Fullwidth, plus emoji: the characters a terminal prints
# two columns wide. Zero-width combining marks and variation selectors are in
# here for the same reason, from the other direction.
#
# Deliberately a coarse over-approximation of `wcwidth`, and correct to be one.
# The consequence of over-including is a refused realign on a table that would
# have come out fine, with a message saying so; the consequence of missing a
# character is a silently mis-padded table, which is the outcome the whole guard
# exists to prevent. So the ranges are drawn wide and the list stays short
# enough to transcribe into the crate without a data dependency.
#
# It must stay narrow enough to be useful, though: an em dash is one column, and
# `corpus/documents/project-readme.md` -- whose "Feature status" table is the
# most realistic ratchet-repair case in the corpus -- has one in every row. An
# earlier version of this test was "any non-ASCII", which refused it.
_WIDE_RANGES = (
    (0x0300, 0x036F),      # combining diacritical marks (zero width)
    (0x1100, 0x115F),      # Hangul Jamo, initial consonants
    (0x200B, 0x200F),      # zero-width space .. RTL mark
    (0x2028, 0x202E),      # line/paragraph separators, bidi overrides
    (0x2060, 0x206F),      # word joiner, invisible operators
    (0x2E80, 0x303E),      # CJK radicals, Kangxi, CJK symbols and punctuation
    (0x3041, 0x33FF),      # kana, Bopomofo, Hangul compat, CJK compat
    (0x3400, 0x4DBF),      # CJK ext A
    (0x4E00, 0x9FFF),      # CJK unified ideographs
    (0xA000, 0xA4CF),      # Yi
    (0xAC00, 0xD7A3),      # Hangul syllables
    (0xF900, 0xFAFF),      # CJK compatibility ideographs
    (0xFE00, 0xFE0F),      # variation selectors (zero width)
    (0xFE10, 0xFE19),      # vertical forms
    (0xFE20, 0xFE2F),      # combining half marks (zero width)
    (0xFE30, 0xFE6F),      # CJK compatibility forms, small form variants
    (0xFF00, 0xFF60),      # fullwidth forms
    (0xFFE0, 0xFFE6),      # fullwidth signs
    (0x1F300, 0x1F9FF),    # emoji, pictographs, supplemental symbols
    (0x20000, 0x3FFFD),    # CJK ext B and beyond
)


def _not_one_column(ch):
    """True if `ch` is not reliably one display column wide."""
    n = ord(ch)
    return any(lo <= n <= hi for lo, hi in _WIDE_RANGES)


def _unstring(value, expect, field, plain_ok=False):
    """Recover a structured argument the model serialized into a string.

    Measured: the model sometimes sends `"{\\"Component\\": \\"gadget\\"}"` where
    an object belongs, or `"i, j, k, l"` where an array belongs. The first is
    unambiguous -- it parses as JSON to exactly the intended value, so parsing
    it recovers the call with nothing guessed. The second is not JSON, and
    splitting it on commas would be guessing at cell boundaries, which is the
    class of error REQUIREMENTS.md 6.2 exists to refuse. So: parse what parses,
    refuse the rest with a message that names the shape wanted.

    `plain_ok` is for `table`, where a bare string is a legitimate shape (the
    heading shorthand) rather than a mistake -- parse it if it happens to be
    JSON, otherwise hand it back untouched.

    Without this the failure surfaced as `no column "{"` -- an error about the
    consequence rather than the cause, which is the opposite of section 5.3.
    """
    if not isinstance(value, str):
        return value
    try:
        parsed = json.loads(value)
    except ValueError:
        parsed = None
    if isinstance(parsed, expect):
        return parsed
    if plain_ok:
        return value
    names = expect if isinstance(expect, tuple) else (expect,)
    want = " or ".join("an object" if t is dict else "an array" for t in names)
    raise OpError(
        f"`{field}` arrived as a string, but must be {want}.\n"
        f"  Got: {value!r}\n"
        f"  Send {want} directly, not a string containing one."
    )


def _clean_keys(obj):
    """Strip stray literal quotes from object keys.

    Measured once: `{"\\"heading\\"": "..."}`. The key is unambiguous once the
    quotes come off, and dropping the field instead would produce a confusing
    "address required" error for a call that supplied the address.
    """
    if not isinstance(obj, dict):
        return obj
    return {(k[1:-1] if len(k) > 1 and k[0] == k[-1] == '"' else k): v
            for k, v in obj.items()}


# --------------------------------------------------------------------------
# argument validation
# --------------------------------------------------------------------------
# REQUIREMENTS.md 11: "every argument is validated at runtime, because the
# schema's `required` and type constraints do not bind the model's output."
# These functions are that requirement.
#
# They were written after a survey of the executor's behaviour on ill-typed
# arguments (FINDINGS.md F-args) found three classes of defect, none of which
# any of the 4009 recorded trials ever reached -- which is why the numbers in
# FINDINGS are unaffected, and why the defects survived this long:
#
#   * crashes -- `table` as a number raised AttributeError straight out of
#     `apply_op`, which catches four exception types and not that one;
#   * leaks -- a missing `column` surfaced as "TypeError: 'NoneType' object is
#     not iterable", and a `where` given as a list of otherwise-VALID column
#     names reached `.items()` and raised AttributeError -- the opposite of a
#     message written for recovery (5.3);
#   * silent defaults -- `position: "0"` appended at the END of the table and
#     reported success, and a nested object in `values` was written into the
#     cell as a Python repr. Both are silent corruption, the exact failure this
#     project exists to remove.
#
# The rule they follow is the one `_unstring` already established: **parse what
# parses, refuse the rest.** Coercions that cannot be wrong are performed --
# `"0"` is an integer, `"End"` is `end` -- and anything requiring a guess is
# refused with the reason. A default is not a guess only when the argument is
# absent; `position` absent means `end`, but `position` present and unreadable
# means stop.


def _type_name(v):
    """The JSON name for a Python type, since the model speaks JSON."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "a boolean"
    if isinstance(v, (int, float)):
        return "a number"
    if isinstance(v, str):
        return "a string"
    if isinstance(v, (list, tuple)):
        return "an array"
    if isinstance(v, dict):
        return "an object"
    return type(v).__name__


def _check_address(value, field):
    """An address is an object, a bare heading string, or absent."""
    if value is None or isinstance(value, (str, dict)):
        return value
    raise OpError(
        f"`{field}` must be an object or a heading string, but arrived as "
        f"{_type_name(value)}.\n"
        f"  Got: {value!r}\n"
        f'  Send {{"heading": "..."}}, or the heading on its own.'
    )


def _check_heading(value, field):
    return _check_heading_named(value, f"{field}.heading")


def _check_heading_named(value, label):
    """The same check, told the whole key to quote.

    The section family reaches its address through either `section.path` or
    `section.heading` and picks between them by truthiness, so it is the one
    caller that cannot let the label be derived from the family name: a refusal
    naming `section.heading` when the caller sent `section.path` describes a key
    that is not in the call.
    """
    if value is None or isinstance(value, str):
        return value
    raise OpError(
        f"`{label}` must be a string, but arrived as "
        f"{_type_name(value)}.\n"
        f"  Got: {value!r}\n"
        "  Send the heading text, or the heading path joined with \" > \"."
    )


def _check_ordinal(value, field):
    """`0` and `"0"` are the same number; `0.5` and `true` are not ordinals.

    A string that is exactly an integer is parsed rather than refused, for the
    reason `_unstring` parses a serialized object: nothing is guessed, and the
    alternative message ("no table with ordinal 0" when ordinal 0 exists) is an
    error about the consequence rather than the cause.
    """
    if value is None or (isinstance(value, int) and not isinstance(value, bool)):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            pass
    raise OpError(
        f"`{field}.ordinal` must be a whole number, but arrived as "
        f"{_type_name(value)}.\n"
        f"  Got: {value!r}\n"
        # `{field}s` rather than a literal "tables": the table family was the
        # only caller when this was written, and the list family's resolver
        # would otherwise explain a `list.ordinal` error in terms of tables.
        # Byte-identical for `field="table"`, which is every measured call.
        f"  Ordinals count {field}s under the same heading, starting at 0."
    )


def _check_position(value):
    """`start`, `end`, or an index. Absent means `end`; unreadable means stop.

    The measured failure this prevents: every unrecognized value -- `"middle"`,
    `1.5`, `[1]`, and `"0"` -- was silently appended at the end and reported as
    success. `"0"` is the worst of them, because a model that sends the index as
    a string gets the opposite of what it asked for and is told it worked.
    """
    return _check_position_in(value, "table")


# What each family's `position` may hold, and what to send instead. The two
# place a new thing differently, so one check cannot use one sentence: a table
# row has a position in a grid and an index means something there; a list item
# is placed by the item it follows, and `after` is how that is said. Sharing the
# *parsing* is the point of REQUIREMENTS 6.4's "one habit" -- `"Start"` must
# mean start in both families, which it did not. Sharing the *prose* would mean
# telling a model about rows in a list.
_POS_ACCEPTS = {
    "table": "\"start\", \"end\", or a row index",
    "list": "\"start\" or \"end\"",
}
_POS_REPAIR = {
    "table": "\n  Use \"start\" for the first row, \"end\" for the last, or a "
             "0-based index to insert before an existing row.",
    "list": "\n  Send \"start\" for the first item, \"end\" for the last, or "
            "`after` with the text of the item to put the new one below.",
}


def _check_position_in(value, family):
    """The same check, for a family that may have no indices.

    `list_add_item` compared `position` against the literal `"start"` and
    appended on everything else, so `"Start"` and `0` both meant *start* on a
    table and *end* on a list -- silently, reported as success. That is the same
    shape of defect B6 measured for `values` and F-pipes for cells: the wrong
    thing done, and called done. Sharing the parser closes it.

    An index parses and is then refused for a list rather than coerced, because
    a list has no row numbers to count and guessing which of "top-level items"
    or "every item" was meant is exactly the invention 6.4 forbids.
    """
    accepts, repair = _POS_ACCEPTS[family], _POS_REPAIR[family]

    def _index(parsed, sent):
        # `sent` rather than `parsed`: the `Got:` line quotes what the caller
        # wrote, so `"0"` is reported as the string it was. That is section
        # 5.3's convention and `difftest` caught the two implementations
        # disagreeing about it.
        if family == "list":
            raise OpError(
                f"`position` must be {accepts}, but arrived as an index.\n"
                f"  Got: {sent!r}\n"
                "  A list item is placed by the item it follows, not by "
                f"number.{repair}"
            )
        return parsed

    if value is None:
        return "end"
    if isinstance(value, bool):
        # `isinstance(True, int)` is True in Python, so a boolean would slip
        # through the index branch below and insert at index 1. Named first.
        raise OpError(
            f"`position` must be {accepts}, but arrived "
            f"as a boolean.\n  Got: {value!r}"
        )
    if isinstance(value, int):
        return _index(value, value)
    if isinstance(value, str):
        low = value.strip().lower()
        if low in ("start", "end"):
            return low
        try:
            parsed = int(low)
        except ValueError:
            pass
        else:
            return _index(parsed, value)
    raise OpError(
        f"`position` must be {accepts}, but arrived as "
        f"{_type_name(value)}.\n"
        f"  Got: {value!r}"
        f"{repair}"
    )


def _check_cell(value, column, field):
    """A cell holds one value. Nested structures are refused, not stringified.

    Measured: `{"Component": {"a": 1}}` wrote `{'a': 1}` into the table -- a
    Python repr, in the document, reported as success. The same coercion in a
    `where` selector was merely useless rather than destructive, producing
    `no row where Component="{'a': 1}"`, but it explains the consequence
    instead of the cause, which is the thing section 5.3 is about.
    """
    if isinstance(value, (dict, list, tuple)):
        raise OpError(
            f'the value for "{column}" in `{field}` must be text, but arrived '
            f"as {_type_name(value)}.\n"
            f"  Got: {value!r}\n"
            "  A table cell holds a single value; flatten it first."
        )
    if value is None:
        raise OpError(
            f'the value for "{column}" in `{field}` is null.\n'
            '  Send "" for an empty cell, or omit the column entirely.'
        )
    if isinstance(value, bool):
        raise OpError(
            f'the value for "{column}" in `{field}` arrived as a boolean.\n'
            f"  Got: {value!r}\n"
            '  Send the text you want in the cell, e.g. "true" or "yes".'
        )
    text = str(value)
    # A cell is one line between two pipes. Text that breaks either of those two
    # facts does not produce a bad cell, it produces a different table, and both
    # were measured writing silent corruption and reporting success:
    #
    #   {"A": "x | y"}         ->  | x | y | z |     a three-column row in a
    #                                                two-column table
    #   {"A": "has\nnewline"}  ->  | has                 the table ends at the
    #                              newline | z |         break; the rest is a
    #                                                    new table with no header
    #
    # Neither can be repaired by quoting, because a cell holds *source markdown*
    # here -- `**bold**` in a cell is bold, and `\|` is the escape the corpus
    # fixture already uses. So the fix is to say which escape to write, not to
    # guess one: escaping on the model's behalf would make the stored text
    # differ from the text it sent, and `where` matches the stored text.
    if "\n" in text or "\r" in text:
        raise OpError(
            f'the value for "{column}" in `{field}` contains a line break, and '
            f"a table cell is a single line.\n"
            f"  Got: {text!r}\n"
            "  Use `<br>` where the break should go, or send one line."
        )
    if _bare_pipe(text):
        raise OpError(
            f'the value for "{column}" in `{field}` contains a `|`, which would '
            f"start a new column.\n"
            f"  Got: {text!r}\n"
            "  Write `\\|` for a literal pipe."
        )
    return text


def _bare_pipe(text):
    r"""True if `text` contains a `|` that is not escaped.

    Same scan as `mdtable.split_row`, and for the same reason: `\|` is content
    and `\\|` is a literal backslash followed by a separator, and only consuming
    the escape pair tells them apart.
    """
    i = 0
    while i < len(text):
        if text[i] == "\\":
            i += 2
        elif text[i] == "|":
            return True
        else:
            i += 1
    return False


def _check_where(value):
    """`where` is an object mapping column name to the value to match.

    A list of column names reached `.items()` and raised AttributeError; a
    number reached `for c in where` and raised TypeError. Both are the model
    sending the right idea in the wrong shape, which is a refusal.
    """
    if value is None or isinstance(value, dict):
        return value
    raise OpError(
        f"`where` must be an object mapping column names to values, but "
        f"arrived as {_type_name(value)}.\n"
        f"  Got: {value!r}\n"
        '  Send {"Column": "value"} naming enough columns to identify one row.'
    )


# `a.get("value")` cannot tell an absent field from an explicit null, and the
# two want different messages: one says the field is required, the other says
# how to write an empty cell. A sentinel is the only way to keep them apart.
_MISSING = object()


def _check_value(value, column):
    """The text a cell becomes.

    Measured, and the worst of the F-args defects because it is the op's entire
    purpose: `table-update-cell` with no `value` wrote the literal string
    "None" into the cell and reported success. A nested object wrote
    `{'a': 1}`, a boolean wrote `True`. `str(value)` accepts anything, which is
    how a required field came to have a silent default.
    """
    if value is _MISSING:
        raise OpError(
            "`value` is required: it is the text the cell becomes.\n"
            '  Send "" to empty the cell.'
        )
    return _check_cell(value, column, "value")


def _check_column(value):
    if isinstance(value, str) and value.strip():
        return value
    if value is None:
        raise OpError(
            "`column` is required: it names the column whose cell changes.\n"
            "  Send the column's header text."
        )
    raise OpError(
        f"`column` must be a string, but arrived as {_type_name(value)}.\n"
        f"  Got: {value!r}\n"
        "  Send the column's header text."
    )


def _address(a):
    return _check_address(
        _clean_keys(_unstring(a.get("table"), dict, "table", plain_ok=True)),
        "table")


def _list_address(a):
    # The type check applies to every family, and so now do the per-field
    # `heading`/`ordinal` checks: `resolve_table`, `resolve_list` and
    # `resolve_section` all run them. The section resolver was the last holdout
    # and the reason REQUIREMENTS 6.4's "one habit" was not true.
    return _check_address(
        _clean_keys(_unstring(a.get("list"), dict, "list", plain_ok=True)), "list")


def _section_address(a):
    return _check_address(
        _clean_keys(_unstring(a.get("section"), dict, "section", plain_ok=True)),
        "section")


def _where(a):
    return _check_where(_clean_keys(_unstring(a.get("where"), dict, "where")))


def _values(a, field="values"):
    value = _clean_keys(_unstring(a.get(field), (dict, list), field))
    # MiniCPM5 serializes a named row as `[{...}]`. It cannot be an ordered
    # row -- ordered cells are scalars and add-row is singular -- so unwrap it
    # before the existing named-row validation. Keep the compatibility rule on
    # `values`; `row` exists only so the rejected scheme_d trials stay
    # regradable and is not part of the shipping contract.
    if (field == "values" and isinstance(value, list) and len(value) == 1
            and isinstance(value[0], dict)):
        # The outer `_clean_keys` could not see through the list.
        return _clean_keys(value[0])
    return value


# ==========================================================================
# lists -- the second op family (REQUIREMENTS.md 6.4)
# ==========================================================================
# Structurally the same bet as the table family: the model supplies *content*
# and incise does the bookkeeping. What counts as bookkeeping is different, and
# the corpus fixtures name it -- marker character, marker delimiter, indent
# width, loose/tight blank lines, and ordered-list numbering. Every one of those
# is a per-list convention that must be read off the list as found, never
# normalized to a house style.
#
# Ordered numbering is the direct analogue of table re-padding (5.2), and it has
# the same shape: sometimes the surrounding items must ALL be rewritten
# (inserting into 1,2,3,4) and sometimes rewriting even one of them is the bug
# (inserting into 1,1,1, or into an already non-sequential list). A rule that
# always renumbers and a rule that never renumbers are both wrong.


class _Span:
    """Minimal stand-in so `heading_path` can be shared with the table family."""

    def __init__(self, start, end):
        self.start, self.end = start, end


def list_lists(content, path=""):
    """The compact structural summary a model sees instead of the document.

    Deliberately withholds item text, exactly as `list_tables` withholds cell
    values: Arm B's premise is that the model addresses an edit it cannot see,
    and the instruction is what supplies the text to match. What it must include
    is everything needed to *choose* a list -- heading, ordinal, and enough
    shape to tell two lists under one heading apart.
    """
    lines = content.split("\n")
    out = []
    for l in find_lists(content):
        probe = _Span(l.start, l.end)
        out.append({
            "ordinal": None,
            "heading": " > ".join(heading_path(lines, probe)) or "(document root)",
            "kind": "ordered" if l.ordered else "bullet",
            # The FIRST item's marker verbatim, not a synthesized "1.". A list
            # numbered 5, 6, 7 is legal and the summary is the model's only view
            # of the file, so a tidied-up marker here is a false statement about
            # the document even where no current task turns on it.
            "marker": (l.items[0].marker if l.items else l.bullet),
            "items": len(l.items),
            "levels": max((it.depth for it in l.items), default=0) + 1,
            "loose": l.loose,
            "tasks": sum(1 for it in l.items if it.checkbox is not None),
        })
    seen = {}
    for e in out:
        e["ordinal"] = seen.get(e["heading"], 0)
        seen[e["heading"]] = e["ordinal"] + 1
    return out


def render_list_summary(content, path):
    entries = list_lists(content, path)
    out = [f"Lists in `{path}`:"]
    for e in entries:
        bits = [f'{e["kind"]} list, marker "{e["marker"]}"',
                f'{e["items"]} items',
                "loose (blank line between items)" if e["loose"] else "tight"]
        if e["levels"] > 1:
            bits.insert(1, f'{e["levels"]} levels of nesting')
        if e["tasks"]:
            bits.append(f'{e["tasks"]} task checkboxes')
        out.append(f'  heading "{e["heading"]}"  ordinal {e["ordinal"]}\n'
                   f'    {", ".join(bits)}')
    return "\n".join(out)


def resolve_list(content, address):
    """Find the one list an address names, or raise with the candidates.

    Same contract as `resolve_table`, including the bare-string shorthand, so
    the two families do not teach the model two different addressing habits.
    """
    if isinstance(address, str):
        address = {"heading": address}
    lists = find_lists(content)
    entries = list_lists(content)
    # Both up front, exactly as `_locate_table` does them, so a malformed
    # `ordinal` is refused even when the heading it accompanies does not exist.
    # These were missing until the Rust port: `resolve_list` read both fields
    # raw, so `{"list": {"heading": 7}}` reached `.strip()` and came back as
    # `AttributeError: 'int' object has no attribute 'strip'` from `apply_op`'s
    # backstop -- a stack-trace fragment where 5.3 requires a repair -- and
    # `{"ordinal": "0"}` failed to coerce where the table family coerces.
    want_h = _check_heading((address or {}).get("heading"), "list")
    want_o = _check_ordinal((address or {}).get("ordinal"), "list")

    if want_h is None:
        if len(lists) == 1:
            return lists[0]
        raise OpError(
            f"list address required: this file has {len(lists)} lists.\n"
            "  Candidates: "
            + "; ".join(f'"{e["heading"]}" ordinal {e["ordinal"]}' for e in entries))

    norm = want_h.strip().lower()
    matched = [(l, e) for l, e in zip(lists, entries)
               if e["heading"].lower() == norm
               or e["heading"].lower().split(" > ")[-1] == norm]
    if not matched:
        near = _close_matches(want_h, [e["heading"] for e in entries],
                                         n=3, cutoff=0.4)
        raise OpError(
            f'no list under heading "{want_h}".\n'
            f'  Near matches: {", ".join(near) if near else "none"}\n'
            f'  Headings with lists: {", ".join(sorted({e["heading"] for e in entries}))}')
    if want_o is None:
        if len(matched) == 1:
            return matched[0][0]
        raise OpError(
            f'ambiguous: {len(matched)} lists under "{want_h}". Pass an ordinal.\n'
            "  Candidates: "
            + "; ".join(f'ordinal {e["ordinal"]} ({e["kind"]}, marker "{e["marker"]}", '
                        f'{e["items"]} items)' for _, e in matched))
    for l, e in matched:
        if e["ordinal"] == want_o:
            return l
    raise OpError(
        f'no list with ordinal {want_o} under "{want_h}".\n'
        f'  Valid ordinals: {", ".join(str(e["ordinal"]) for _, e in matched)}')


def list_get(content, address):
    """Return copyable item text and nesting for one resolved list."""
    resolved = resolve_list(content, address)
    lists = find_lists(content)
    index = next((i for i, candidate in enumerate(lists)
                  if candidate.start == resolved.start), None)
    if index is None:
        raise OpError("internal: resolved list has no summary entry.")
    entry = list_lists(content)[index]
    return {
        "heading": entry["heading"],
        "ordinal": entry["ordinal"],
        "items": [
            {
                "text": item.text,
                "depth": item.depth,
                # The Python parser uses -1 for a root item; the Rust parser
                # uses None. The read contract exposes JSON null in either
                # implementation.
                "parent": (None if item.parent in (None, -1) else item.parent),
                "checked": (item.checkbox.lower() == "x"
                            if item.checkbox is not None else None),
            }
            for item in resolved.items
        ],
    }


def render_list_items(got):
    out = [f'List {json.dumps(got["heading"])} '
           f'ordinal {got["ordinal"]} -- {len(got["items"])} items']
    for index, item in enumerate(got["items"]):
        out.append(
            f'  [{index}] text={json.dumps(item["text"])} '
            f'depth={item["depth"]} '
            f'parent={json.dumps(item["parent"])} '
            f'checked={json.dumps(item["checked"])}')
    return "\n".join(out)


def render_list_get(content, address):
    return render_list_items(list_get(content, address))


def resolve_item(lst, text, field="item"):
    """Index of the one item `text` names, or raise.

    Three passes, narrowest first: exact, case-insensitive exact, then unique
    substring. This is looser than the table family's `where`, and the looseness
    is deliberate rather than inherited -- a list item is prose, not a cell
    value, so a request that says "the child pending task" is naming a real
    thing that a strict comparison would reject over a word of surrounding
    phrasing.

    What does NOT change is the rule underneath: the selector must identify
    exactly one item. A substring matching two items refuses, and names both.
    """
    if not text or not str(text).strip():
        raise OpError(
            f"`{field}` is required: the text of the list item to act on.\n"
            f"  The list has {len(lst.items)} items.")
    want = str(text).strip()
    texts = [it.text for it in lst.items]

    for pred in (lambda t: t == want,
                 lambda t: t.lower() == want.lower(),
                 lambda t: want.lower() in t.lower()):
        hits = [i for i, t in enumerate(texts) if pred(t)]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            raise OpError(
                f'"{want}" matches {len(hits)} items; it must identify exactly one.\n'
                "  Matches: " + "; ".join(f'"{texts[i]}"' for i in hits))
    near = _close_matches(want, texts, n=3, cutoff=0.4)
    raise OpError(
        f'no list item matching "{want}".\n'
        f'  Near matches: {", ".join(near) if near else "none"}\n'
        f'  Items: {"; ".join(texts)}')


def _list_eol(lst):
    eols = {"\r" if ln.endswith("\r") else "" for ln in lst.lines}
    if len(eols) == 1:
        return eols.pop()
    raise OpError(
        "this list mixes CRLF and LF line endings, so there is no convention to "
        "match.\n  Normalize the list's line endings first, then retry.")


def _marker_gap(lines, item):
    """The whitespace between marker and content, copied rather than assumed."""
    m = ITEM_RE.match(lines[item.start])
    return (m.group(3) or " ") if m else " "


def _sibling_numbers(lst, group):
    return [lst.items[i].number for i in group]


def _numbering_style(nums):
    """How an ordered sibling group is numbered: sequential, all-ones, or neither.

    The three cases are not stylistic preferences, they are three different
    correct answers, and `corpus/lists/ordered-numbering.md` was built to make
    that concrete:

      sequential   1,2,3,4  -- inserting requires renumbering everything after
      constant     1,1,1    -- legal CommonMark; renumbering would be the bug
      irregular    1,3,7    -- already inconsistent; renumbering is a behaviour
                              change the caller did not ask for

    A sibling group can MIX ordered and unordered items: a marker change ends a
    top-level list, but nothing stops `- y` and `1. x` sitting at the same depth
    under one parent, and `mdlist` gives the bullet a `number` of `None`. Such a
    group is irregular by the same argument as 1,3,7 -- it is already something
    no renumbering scheme describes, so leaving it alone is the only answer that
    does not invent a change. Before this test existed, `None + 0` raised inside
    the `all(...)` below and `apply_op`'s backstop reported the TypeError to the
    model (FINDINGS F-mixnum). No corpus file contains such a group.
    """
    if any(n is None for n in nums):
        return "irregular"
    if len(nums) >= 2 and len(set(nums)) == 1:
        return "constant"
    if all(n == nums[0] + k for k, n in enumerate(nums)):
        return "sequential"
    return "irregular"


def _group_start(nums, fallback):
    """The number a renumbering run counts from: the group's first real one.

    `nums[0]` is `None` when the group's first item is a bullet, and that value
    reaches `_renumber` as `start` even on the irregular path where it is never
    read. Falling back to the anchor's own number keeps it a number either way.
    """
    return next((n for n in nums if n is not None), fallback)


def _renumber(lines, lst_idx, depth, parent_text, style, start):
    """Rewrite the marker numbers of one sibling group, touching nothing else."""
    if style == "irregular":
        return lines
    rebuilt = find_lists("\n".join(lines))[lst_idx]
    group = [it for it in rebuilt.items
             if it.depth == depth
             and (rebuilt.items[it.parent].text if it.parent >= 0 else "") == parent_text]
    for k, it in enumerate(group):
        want = start if style == "constant" else start + k
        if it.number == want:
            continue
        m = ITEM_RE.match(lines[it.start])
        lines[it.start] = (m.group(1) + f"{want}{it.delim}"
                           + lines[it.start][m.end(2):])
    return lines


def _list_context(lst, idx):
    """(depth, parent_text, sibling indices) for the group an item belongs to."""
    it = lst.items[idx]
    parent_text = lst.items[it.parent].text if it.parent >= 0 else ""
    group = [i for i, o in enumerate(lst.items)
             if o.depth == it.depth and o.parent == it.parent]
    return it.depth, parent_text, group


def list_add_item(content, address, text, position="end", after=None, checked=None):
    """Insert an item, matching every convention of the list it joins.

    The new item takes its indent, marker character, marker delimiter and
    marker spacing from the sibling it is placed next to. That is why there is
    no `depth` or `indent` argument: "add a nested item under beta" is
    expressed as `after: "beta-two"`, and an impossible depth is unsayable.
    """
    lst = resolve_list(content, address)
    if text is None or not str(text).strip():
        raise OpError("`text` is required: the content of the new list item.")
    text = str(text).strip()
    if not lst.items:
        raise OpError("this list has no items to match conventions against.")
    lines = content.split("\n")
    eol = _list_eol(lst)

    # Shared with the table family so that one word means one thing: `"Start"`
    # and `0` used to be *start* on a table and *end* on a list, silently, and
    # reported as success. Evaluated before the `after` branch, as the old
    # literal comparison was, so an ill-typed `position` is refused rather than
    # ignored when `after` decides the placement -- F-args' rule, not a new one.
    starts = _check_position_in(position, "list") == "start"
    if after is not None and str(after).strip():
        anchor = resolve_item(lst, after, field="after")
        insert_at = lst.items[anchor].end + 1
    elif starts:
        anchor = 0
        insert_at = lst.items[0].start
    else:
        tops = [i for i, it in enumerate(lst.items) if it.depth == 0]
        anchor = tops[-1]
        insert_at = lst.items[anchor].end + 1

    depth, parent_text, group = _list_context(lst, anchor)
    a = lst.items[anchor]
    gap = _marker_gap(lines, a)

    # Checkbox: supplied explicitly, or inferred when every sibling is a task
    # item. Inference here is the same class of rule as copying the marker --
    # adding a plain item to an all-task list produces a list that renders
    # inconsistently -- but it IS an inference, and it is flagged as an open
    # question in REQUIREMENTS.md rather than treated as settled.
    box = ""
    if checked is not None:
        box = "[x] " if checked in (True, "true", "True", "yes", 1) else "[ ] "
    elif group and all(lst.items[i].checkbox is not None for i in group):
        box = "[ ] "

    style, start = None, None
    if a.ordered:
        nums = _sibling_numbers(lst, group)
        style = _numbering_style(nums)
        start = _group_start(nums, a.number)
        if style == "constant":
            number = start
        elif style == "sequential":
            number = start  # placeholder; the group is renumbered below
        else:
            # Irregular: leave the neighbours alone and follow the predecessor.
            # Only *numbered* predecessors count -- a bullet sibling has no
            # number to follow (FINDINGS F-mixnum).
            before = [lst.items[i].number for i in group
                      if lst.items[i].start < insert_at
                      and lst.items[i].number is not None]
            number = (before[-1] + 1) if before else start
        marker = f"{number}{a.delim}"
    else:
        marker = a.marker

    new_line = a.indent + marker + gap + box + text + eol
    block = [new_line]
    if lst.loose:
        blank = eol
        block = ([blank] + block) if insert_at > lst.items[anchor].start else (block + [blank])
    lines = lines[:insert_at] + block + lines[insert_at:]

    if a.ordered and style in ("sequential", "constant"):
        lines = _renumber(lines, _list_index(content, lst), depth,
                          parent_text, style, start)
    return "\n".join(lines)


def list_remove_item(content, address, item):
    """Remove an item and everything nested under it."""
    lst = resolve_list(content, address)
    idx = resolve_item(lst, item)
    it = lst.items[idx]
    depth, parent_text, group = _list_context(lst, idx)
    lines = content.split("\n")

    lo, hi = it.start, it.end
    if lst.loose:
        # Take one separating blank line with the item, or the list grows a
        # trailing blank and the following block appears to move.
        if hi + 1 <= lst.end and not lines[hi + 1].strip():
            hi += 1
        elif lo - 1 >= lst.start and not lines[lo - 1].strip():
            lo -= 1
    lines = lines[:lo] + lines[hi + 1:]

    if it.ordered:
        nums = _sibling_numbers(lst, group)
        style = _numbering_style(nums)
        if style in ("sequential", "constant") and len(group) > 1:
            lines = _renumber(lines, _list_index(content, lst), depth,
                              parent_text, style,
                              _group_start(nums, it.number))
    return "\n".join(lines)


def list_set_checked(content, address, item, checked=True):
    """Tick or untick one task item, leaving the rest of the line untouched."""
    lst = resolve_list(content, address)
    idx = resolve_item(lst, item)
    it = lst.items[idx]
    if it.checkbox is None:
        tasks = [o.text for o in lst.items if o.checkbox is not None]
        raise OpError(
            f'"{it.text}" is not a task item -- it has no [ ] checkbox.\n'
            f'  Task items in this list: {"; ".join(tasks) if tasks else "none"}')
    want = checked in (True, "true", "True", "yes", 1)
    if want == (it.checkbox in ("x", "X")):
        raise OpError(
            f'"{it.text}" is already {"checked" if want else "unchecked"}; '
            "nothing to do.")
    # Preserve the author's capitalization when ticking a box that was capital
    # X elsewhere in the list is NOT attempted -- `corpus/lists/tasks.md`
    # requires [X] to round-trip untouched, which it does because this only
    # rewrites the one line it was asked to.
    lines = content.split("\n")
    ln = lines[it.start]
    m = ITEM_RE.match(ln)
    head = m.end(2) + len(m.group(3) or "")
    lines[it.start] = ln[:head] + ("[x]" if want else "[ ]") + ln[head + 3:]
    return "\n".join(lines)


def _list_index(content, lst):
    """Position of `lst` among the document's lists -- stable across edits."""
    for n, other in enumerate(find_lists(content)):
        if other.start == lst.start:
            return n
    raise OpError("internal: list could not be relocated after the edit.")


# --------------------------------------------------------------------------
# sections
# --------------------------------------------------------------------------
#
# The third op family, and the first whose address is a *path* rather than a
# name plus an ordinal. Three things here have no table or list precedent, and
# they are the reason this family was measured rather than assumed:
#
#   1. **Level is derived, never supplied.** `section-insert` takes an anchor
#      and a position, and computes the new heading's level from the anchor.
#      This is the list family's `after`-copies-the-sibling's-marker rule (L4)
#      carried across: a number the model cannot see is a number it will invent,
#      and there is no way to express an impossible one if it is never asked for.
#   2. **Ordinals are the fallback, not the interface.** A path disambiguates
#      three `macOS` headings in `deep-nesting.md`; only genuinely identical
#      siblings (`duplicate-siblings.md`) need an ordinal, and only those
#      refusals mention one.
#   3. **A refusal must distinguish "absent" from "not addressable."** A heading
#      inside a code fence or a blockquote is on the user's screen. Saying "not
#      found" about it is the outcome `nested-blocks.md` names as unacceptable.


def section_outline(content, path=""):
    """The structural summary a model sees instead of the document.

    Unlike `list_tables` and `list_lists`, this does NOT withhold the content
    being addressed -- the heading text *is* the address, so hiding it would
    leave nothing to address with. What it withholds is every section's body,
    which is the part an edit supplies.
    """
    secs = find_sections(content)
    counts = {}
    for s in secs:
        counts[s.slug] = counts.get(s.slug, 0) + 1
    seen, out = {}, []
    for s in secs:
        ordinal = seen.get(s.slug, 0)
        seen[s.slug] = ordinal + 1
        out.append({
            "level": s.level,
            "path": s.slug,
            "text": s.text,
            "style": s.style,
            "ordinal": ordinal,
            # Whether the path is enough on its own. Anything false here is a
            # section the model must pass an ordinal for, and the outline is
            # where it finds that out -- not the error message.
            "unique": counts[s.slug] == 1,
            "has_body": s.has_body,
            "subsections": sum(1 for o in secs if o.parent == secs.index(s)),
        })
    return out


def render_section_outline(content, path):
    entries = section_outline(content, path)
    # The example is taken from this document rather than being a fixed string.
    # A model shown `e.g. "Install > macOS"` while editing a changelog has to
    # infer that the separator generalizes; a model shown a path it can see in
    # the outline below does not. Nothing is leaked -- every path here is
    # already printed.
    deep = next((e["path"] for e in entries if " > " in e["path"]), None)
    hint = f'e.g. "{deep}"' if deep else "one heading per line, indented by level"
    out = [f"Sections in `{path}` (address by heading path, {hint}):"]
    for e in entries:
        bits = []
        bits.append("body" if e["has_body"] else "no body of its own")
        if e["subsections"]:
            bits.append(f'{e["subsections"]} subsection'
                        + ("s" if e["subsections"] > 1 else ""))
        if not e["unique"]:
            bits.append(f'DUPLICATE PATH -- needs ordinal {e["ordinal"]}')
        out.append(f'{"  " * e["level"]}{e["text"]}   ({", ".join(bits)})')
    return "\n".join(out)


# --------------------------------------------------------------------------
# what changed
# --------------------------------------------------------------------------
#
# The success half of "error messages are the product" (REQUIREMENTS §5.3).
#
# S13 measured what a tool result costs when it gets this wrong. The benchmark
# harness answered every successful call with the document's new heading
# outline, and across the twelve single-call section tasks a model that made a
# further call *after one that had already worked* was 32x more likely to
# destroy the document (4/11 vs 4/349, Fisher p = 3.2e-5). An outline that
# already reflects the edit cannot tell the model it made the edit: the model
# reads a document that looks like the one it wanted, cannot find evidence its
# own call produced it, and escalates to `delete` or `rename` or
# `replace-body overwrite:true`.
#
# So the response says what *changed*, and it is derived from the two documents
# rather than from the arguments. Echoing the call back would be cheaper and
# would be worthless for exactly the case that matters -- a model second-
# guessing whether its call landed learns nothing from being told what it
# asked for. Every line below is a difference between the before and after
# bytes, which is the one thing the model cannot see and cannot infer.

def _own_body_lines(content, sec):
    return content.split("\n")[sec.heading_end + 1: sec.own_end + 1]


def _describe_entries(content):
    """(text, level, own-body) per heading, in document order."""
    return [(s.text, s.level, "\n".join(_own_body_lines(content, s)).strip())
            for s in find_sections(content)]


def _plural(n, noun):
    return f"{n} {noun}" + ("" if n == 1 else "s")


def _run_notes(verb, run):
    """Describe a block of added or removed headings.

    A subtree collapses. `delete` on a section with three subsections removes
    four headings, and four sentences about it buries the one fact worth
    reading -- that three sections went with the one that was named. The
    collapsed form states the count instead, which is the same information in
    the shape a model can act on. Two headings stay itemized: that is the
    `children` payload landing, and there the model wants to see both.
    """
    if len(run) > 2 and all(e[1] > run[0][1] for e in run[1:]):
        return [f'{verb} the section "{run[0][0]}" (level {run[0][1]}) '
                f"and {_plural(len(run) - 1, 'section')} nested under it"]
    return [f'{verb} the section "{e[0]}" (level {e[1]})' for e in run]


def describe_change(before, after, path=""):
    """A one-paragraph account of what an op did to a document.

    Derived from the documents, so it is correct for an op this function has
    never heard of, and it cannot claim a change that did not happen -- the
    failure mode of describing the *call* instead.
    """
    if before == after:
        return "Applied, but the document is unchanged."

    import difflib
    b, a = _describe_entries(before), _describe_entries(after)
    # autojunk off -- see `_line_counts`. Unreachable here today (it needs 200
    # headings and the largest document has 94), set for the same reason and so
    # the two matchers in this function cannot drift apart.
    sm = difflib.SequenceMatcher(a=[e[0] for e in b], b=[e[0] for e in a],
                                 autojunk=False)
    notes, levels = [], []          # `levels` collects a run of level shifts
    tally_wanted = False            # do the notes account for the byte change?

    def flush_levels():
        # `set-level` with `subtree` moves a heading and every descendant, and
        # naming all six of them is a wall of text that buries the one the
        # model asked about. The first is the one it named.
        if not levels:
            return
        (text, old, new), rest = levels[0], levels[1:]
        verb = "promoted" if new < old else "demoted"
        who = f'"{text}"'
        if rest:
            who += f" and {_plural(len(rest), 'descendant')}"
        notes.append(f"{verb} {who} from level {old} to level {new}")
        levels.clear()

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for i, j in zip(range(i1, i2), range(j1, j2)):
                if b[i][1] != a[j][1]:
                    levels.append((a[j][0], b[i][1], a[j][1]))
                    continue
                flush_levels()
                if b[i][2] != a[j][2]:
                    notes.append(f'changed the body of "{a[j][0]}" '
                                 f"({_lines_delta(b[i][2], a[j][2])})")
        elif tag == "replace" and i2 - i1 == 1 and j2 - j1 == 1:
            # One heading swapped for one heading in the same place: a rename.
            # Saying "removed X, added Y" here would be true and would read as
            # data loss, which is the opposite of what happened.
            flush_levels()
            notes.append(f'renamed "{b[i1][0]}" to "{a[j1][0]}"')
        else:
            flush_levels()
            tally_wanted = True
            notes += _run_notes("removed", b[i1:i2])
            notes += _run_notes("added", a[j1:j2])
    flush_levels()

    # Nothing above catches an edit to the text before the first heading, and a
    # response that goes quiet on a real change is worse than one that is
    # vague. The line count is the backstop, and it prints whenever the notes
    # do not already account for the bytes: a rename or a level shift rewrites
    # one heading line and reporting that as "+1 line, -1 line" reads as churn
    # nobody asked for, while "added the section X" says nothing about its size.
    if not notes:
        notes.append("changed text outside any heading")
        tally_wanted = True
    tally = []
    if tally_wanted:
        added, removed = _line_counts(before, after)
        if added:
            tally.append(f"+{_plural(added, 'line')}")
        if removed:
            tally.append(f"-{_plural(removed, 'line')}")

    head = "Applied: " + "; ".join(notes) + "."
    return head + (f" ({', '.join(tally)}.)" if tally else "")


def _lines_delta(old, new):
    added, removed = _line_counts(old, new)
    bits = []
    if added:
        bits.append(f"+{added}")
    if removed:
        bits.append(f"-{removed}")
    return ", ".join(bits) + " lines" if bits else "same line count"


def _line_counts(before, after):
    # `autojunk=False`, and this is the one place in the file where difflib's
    # default is actively wrong for us. The heuristic engages at 200 elements
    # and drops any line occurring more than `n // 100 + 1` times -- which on a
    # long document means the blank line, the table delimiter, the repeated
    # bullet: exactly the lines that give a diff its anchors. Deleting an
    # 18-line section from a 232-line changelog was reported as
    # `(+71 lines, -89 lines)`. The tally exists so a model can tell whether its
    # call landed, and a confidently wrong number is worse than no number.
    #
    # It is safe as well as better: of 76352 differential cases, seven change,
    # all seven on `bench/synthetic/repeated-lines.md`, and every one moves to
    # the true minimal edit. No corpus document and no refusal message moves, so
    # nothing S14 measured is affected. FINDINGS F-autojunk.
    import difflib
    a, b = before.split("\n"), after.split("\n")
    added = removed = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b,
                                                       autojunk=False).get_opcodes():
        if tag in ("replace", "delete"):
            removed += i2 - i1
        if tag in ("replace", "insert"):
            added += j2 - j1
    return added, removed


def resolve_section(content, address):
    """Find the one section an address names, or raise with the candidates.

    Matching runs narrowest-first, and a pass that finds several stops rather
    than falling through to a looser one: an exact full path that hits three
    sections is ambiguous, and trying a suffix match next would only widen it.

      full path exact -> full path case-folded -> path suffix -> suffix folded

    The suffix pass is what makes `"macOS"` legal shorthand for
    `"Install > macOS"` in a file that has only one, and what makes it refuse
    with all three in `deep-nesting.md`, which has three.
    """
    if isinstance(address, str):
        address = {"path": address}
    address = address or {}
    secs = find_sections(content)
    entries = section_outline(content)
    # The label travels with the value because the refusal has to quote the key
    # the caller actually sent, not the one this family happens to prefer.
    if address.get("path"):
        want, want_label = address.get("path"), "section.path"
    else:
        want, want_label = address.get("heading"), "section.heading"
    want_o = address.get("ordinal")

    # Both up front, as `resolve_table` does, so a malformed `ordinal` is
    # refused even when the heading it accompanies does not exist -- and ahead
    # of the no-headings refusal, because a call that could never be well formed
    # is answered before the document is consulted.
    #
    # This is what made the section family the odd one out. `_check_heading` was
    # never called here, so `{"path": 1}` was stringified to `"1"` and hunted
    # for; `_check_ordinal` was never called, so `{"ordinal": "0"}` addressed a
    # table and a list and refused a section. REQUIREMENTS 6.4 asks the three
    # families to teach one habit, and this was the line where they stopped.
    want = _check_heading_named(want, want_label)
    want_o = _check_ordinal(want_o, "section")

    if not secs:
        raise OpError("this file has no headings, so no section can be addressed.")
    if want is None or not want.strip():
        raise OpError(
            "`section` is required: the heading path of the section to act on.\n"
            f"  This file has {len(secs)} sections. Candidates: "
            + "; ".join(f'"{e["path"]}"' for e in entries[:8])
            + ("; ..." if len(entries) > 8 else ""))

    segs = tuple(p.strip() for p in want.split(">") if p.strip())
    lower = tuple(p.lower() for p in segs)

    def suffix(p, q):
        return len(p) >= len(q) and p[len(p) - len(q):] == q

    for pred in (lambda s: s.path == segs,
                 lambda s: tuple(t.lower() for t in s.path) == lower,
                 lambda s: suffix(s.path, segs),
                 lambda s: suffix(tuple(t.lower() for t in s.path), lower)):
        hits = [i for i, s in enumerate(secs) if pred(s)]
        if not hits:
            continue
        # If their full paths differ, the fix is a longer path and the message
        # shows exactly which ones -- an ordinal would work too but teaches the
        # wrong habit. Identical paths are the only case where an ordinal is
        # the answer, and `duplicate-siblings.md` requires it. This split is
        # computed before the ordinal branch because a *missed* ordinal has to
        # make it too: `{"heading": "Errors", "ordinal": 9}` against a file with
        # twenty-one distinct sections named "Errors" is an ambiguity, not an
        # out-of-range ordinal, and listing twenty-one zeroes as the valid
        # ordinals is advice that cannot be taken.
        paths = [secs[i].slug for i in hits]
        distinct = len(set(paths)) == len(paths)
        if want_o is not None:
            for i in hits:
                if entries[i]["ordinal"] == want_o:
                    return secs[i]
            if distinct and len(hits) > 1:
                raise OpError(
                    f'no section "{want}" with ordinal {want_o}.\n'
                    f"  These {len(hits)} sections have different paths, so an "
                    "ordinal does not tell them apart. Use a longer path.\n"
                    "  Candidates: "
                    + "; ".join(f'"{p}"' for p in paths))
            if len(hits) == 1:
                # The whole recorded population, and the branch below was
                # written for none of it. `bench/ordinal_sizing.py`: 140 of 140
                # ordinal refusals in `bench/results/` come from here, the path
                # matched one section in every one of them, and the message
                # below -- which explains how to tell tied sections apart --
                # was answering a caller who had no tie.
                #
                # Worse than useless. Taking its advice, on the 111 that were
                # first calls, gives `correct` 37 times and **destroys the
                # document 52 times**, all on `rename-closed-atx`, where the
                # model addresses the parent and means a child: dropping the
                # ordinal renames the parent and reports success. That is the
                # destructive retry S11 and S12 traced to `Valid ordinals: 0`,
                # surviving the rewrite that was supposed to answer them,
                # and 5.3's own rule against it -- *a wrong suggestion is worse
                # than none: it is authoritative and the model will follow it.*
                #
                # So say the thing that is true and load-bearing, in the order
                # S11's own reasoning gives. S11 kept this refusal because *the
                # ordinal is the only evidence the path is wrong*; a caller who
                # sends one has asserted there are several of these, and there
                # is one, so the caller's own call is the evidence. "You
                # probably meant this one, drop the ordinal" throws that away,
                # which is why the path reading leads and the sections nested
                # under the match are quoted: that list contains the address
                # the task wanted in 52 of the 52 calls whose old advice
                # destroyed the document. Nothing here scores or ranks the two
                # readings -- the resolver cannot tell them apart, and guessing
                # would be the invention 6.4 forbids.
                #
                # Which is why both lines are conditionals and neither is an
                # imperative. `Send ordinal 0, or drop it.` told the caller what
                # to do; these tell it what each reading would mean, and the
                # caller is the only party that knows which it meant. The
                # adversarial number says why that matters: take the first path
                # quoted here without reading it and the sizing run scores 62 of
                # 111 destructive, worse than the old 52, because any wrong
                # address renames the wrong heading. The claim this branch makes
                # is only that the right address is now *in* the sentence -- 91
                # of 111, against 37 -- not that a model picks it. Which one a
                # model picks is unmeasured, and `armc.replay --select refusal`
                # with two `--binary`s is the instrument that would settle it.
                inner = [s.slug for s in secs
                         if len(s.path) > len(secs[hits[0]].path)
                         and s.path[:len(secs[hits[0]].path)] == secs[hits[0]].path]
                # `want_label`, not the word "path", and the replay is why. The
                # first draft of this message said "send the longer path", and
                # two of its 27 after-trials answered by putting the section
                # address into the tool's `path` argument -- the FILE --
                # `"path": "corpus/sections/setext-and-atx.md/Setext H1
                # Title/Setext H2/Closed ATX level 3"` -- and one of those two
                # had recovered correctly under the old message. That is S15's
                # collision, measured again: `path` names the file on every
                # tool and the address inside `section`. Worse, the schema S15
                # adopted addresses sections by `section.heading`, so in the
                # shipping scheme "send the longer path" names the file
                # argument and nothing else. The convention six lines above
                # already said this -- *the refusal has to quote the key the
                # caller actually sent* -- and the first draft did not follow
                # it.
                raise OpError(
                    f'no section "{want}" with ordinal {want_o}.\n'
                    f"  Only one section matches `{want_label}`. Sending an "
                    "ordinal says you expected several, so it may not be the "
                    "section you meant.\n"
                    + (f"  If you meant a section inside it, send one of these "
                       f"as `{want_label}`: "
                       + "; ".join(f'"{p}"' for p in inner[:8])
                       + ("; ..." if len(inner) > 8 else "") + "\n"
                       "  If you did mean this one, send it again without an "
                       "ordinal."
                       if inner else
                       "  Nothing is nested under it, so a longer address will "
                       f"not help -- check `{want_label}`, or send it again "
                       "without an ordinal."))
            valid = [str(n) for n in sorted({entries[i]["ordinal"] for i in hits})]
            raise OpError(
                f'no section "{want}" with ordinal {want_o}.\n'
                "  Ordinals count sections that share a heading path, "
                "starting at 0.\n"
                "  This one has "
                + (f"just ordinal {valid[0]}" if len(valid) == 1
                   else "ordinals " + ", ".join(valid))
                + ". Send ordinal " + " or ".join(valid) + ", or drop it.")
        if len(hits) == 1:
            return secs[hits[0]]
        if distinct:
            raise OpError(
                f'ambiguous: "{want}" matches {len(hits)} sections. '
                "Use a longer path.\n  Candidates: "
                + "; ".join(f'"{p}"' for p in paths))
        raise OpError(
            f'ambiguous: {len(hits)} sections share the path "{paths[0]}" and '
            "nothing distinguishes them but position. Pass an ordinal.\n"
            "  Candidates: "
            + "; ".join(f'ordinal {entries[i]["ordinal"]} (line {secs[i].start + 1}, '
                        f'{"body" if secs[i].has_body else "no body"})' for i in hits))

    _no_section(content, want, entries)


def _no_section(content, want, entries):
    """Raise the not-found error, having first checked it is really not there."""
    leaf = str(want).split(">")[-1].strip()
    for h in inert_headings(content):
        if h["text"].lower() == leaf.lower():
            where = {"code-fence": "inside a fenced code block",
                     "blockquote": "inside a blockquote",
                     "indented-code": "in an indented code block",
                     "frontmatter": "in the frontmatter"}[h["reason"]]
            raise OpError(
                f'"{leaf}" is on line {h["line"] + 1}, but it is {where}, so it '
                "is not an addressable section.\n"
                "  Nothing there can be edited by heading path; edit the "
                "enclosing section's body instead.")
    near = _close_matches(leaf, [e["text"] for e in entries],
                                     n=3, cutoff=0.4)
    raise OpError(
        f'no section at path "{want}".\n'
        f'  Near matches: {", ".join(near) if near else "none"}\n'
        f'  Paths: ' + "; ".join(f'"{e["path"]}"' for e in entries[:10])
        + ("; ..." if len(entries) > 10 else ""))


def _section_eol(content, sec):
    lines = content.split("\n")[sec.start:sec.end + 1]
    eols = {"\r" if ln.endswith("\r") else "" for ln in lines}
    if len(eols) == 1:
        return eols.pop()
    raise OpError(
        "this section mixes CRLF and LF line endings, so there is no convention "
        "to match.\n  Normalize the section's line endings first, then retry.")


def _block(text, eol, field="text"):
    """A model-supplied markdown block as a list of lines, with `eol` applied.

    Blank lines are dropped from *both* ends rather than preserved. The spacing
    between a block and what surrounds it is the *document's* convention (§6.3),
    not the payload's, and a model that wraps its text in newlines is not making
    a statement about that.

    The leading half of that was added after the section fix arm: four trials in
    130 sent `"\\nSuperseded."` or `"\\n\\nNone of the above is parsed as
    markdown."` -- correct prose, correct section, with the separator the op
    already inserts supplied a second time by hand. Keeping the payload's blank
    line put two where the document uses one, which graded
    `collateral:formatting`: a document damaged in a way no user asked for,
    because the executor took a guess about whitespace as an instruction.
    """
    if text is None or not str(text).strip():
        raise OpError(f"`{field}` is required and must not be empty.")
    body = [ln.rstrip("\r") for ln in str(text).replace("\r\n", "\n").split("\n")]
    while body and not body[-1].strip():
        body.pop()
    while body and not body[0].strip():
        body.pop(0)
    return [ln + eol for ln in body]


def section_append(content, address, text, heading=None):
    """Append a block to the end of a section's OWN body.

    "Own" is the whole decision. `## [1.4.2]` in `changelog.md` has no prose of
    its own and two subsections; appending to it means putting a paragraph
    between the heading and `### Fixed`, not after `### Changed`. That is what
    the address names, and `own_end` is the field that says where it stops.

    The outline reports `has_body` and a subsection count for exactly this
    reason: a model that meant `### Fixed` can see that it should have said so.

    `heading` is not a parameter this op uses -- it is here to refuse. FINDINGS
    S3: asked to add a subsection, the model called `append` and passed it a
    heading and a `position` five times in ten, and got a paragraph of prose
    where a section should have been. Accepting the call and ignoring the two
    arguments that say what it meant turns a recoverable mistake into a silent
    one.
    """
    sec = resolve_section(content, address)
    _reject_heading(
        sec, heading,
        "`append` cannot create a section",
        "  To add a subsection use action=insert with position=last-child "
        "(or first-child) and the parent as `section`.\n"
        "  To add prose to this section, drop the heading and pass `text`.")
    eol = _section_eol(content, sec)
    lines = content.split("\n")
    block = _block(text, eol)
    at = sec.own_end + 1
    # One blank line separates block-level constructs. This is markdown's rule,
    # not a document convention, so unlike the gap between sections it is not
    # read off the file.
    return "\n".join(lines[:at] + [eol] + block + lines[at:])


def _reject_heading(sec, heading, what, remedy):
    """Refuse a `heading` argument on an op that has no heading to give it to.

    With one exception, and the exception is the whole reason this is a shared
    function rather than two inline `if`s. Re-grading the section arm under the
    first version of these guards turned six previously-correct trials into
    `op_error`, all of the same shape:

        {"action": "replace-body", "section": {"path": "Changelog > [1.4.2]..."},
         "new_heading": "[1.4.2] - 2026-08-14", "text": "..."}

    The model echoed the section it was already addressing back into the heading
    field. That asks for nothing -- rename X to X -- and the old executor, which
    ignored the argument entirely, produced exactly the right document. Refusing
    it is a guard that costs correct calls to catch nothing, so an echo of the
    addressed section's own name (leaf or full path) passes through.

    Anything else is a real second intent riding on an op that cannot serve it,
    and that is what S2 and S3 were made of.
    """
    if heading is None:
        return
    asked = str(heading).strip()
    if not asked or asked in (sec.text, sec.slug):
        return
    raise OpError(f"{what}, and you passed a heading ({asked!r}).\n{remedy}")


def _has_own_body(content, sec):
    lines = content.split("\n")
    return any(ln.strip()
               for ln in lines[sec.heading_end + 1: sec.own_end + 1])


def section_replace_body(content, address, text, overwrite=False,
                         heading=None):
    """Replace a section's own body, leaving its heading and subsections alone.

    Refuses to discard a non-empty body unless `overwrite` says so. This is the
    one op in the family that destroys content as its normal function, and
    FINDINGS S2 measured what that costs: asked to *add* a line to a section,
    the model called `replace-body` in five trials of ten and deleted the line
    that was already there. Addressing was correct in every one -- right file,
    right section, right ordinal -- so nothing about *where* was in doubt. The
    model was wrong about the verb, and the executor cannot tell a deliberate
    overwrite from a mistaken one by looking at the arguments.

    So it asks. An unacknowledged overwrite of existing prose becomes an
    `op_error`, which B3 measured as recoverable in a single turn, and the
    price of the guard is one round trip on the rarer intent. A section whose
    body is empty is not protected, because there is nothing to lose.
    """
    sec = resolve_section(content, address)
    _reject_heading(
        sec, heading,
        "`replace-body` cannot create or rename a section",
        "  Use action=rename to change a heading, or action=insert to add "
        "a section.")
    if not overwrite and _has_own_body(content, sec):
        raise OpError(
            f'"{sec.slug}" already has a body, and `replace-body` discards it.\n'
            "  If you meant to add to it, use action=append.\n"
            "  If you really meant to replace it, pass overwrite=true.")
    eol = _section_eol(content, sec)
    lines = content.split("\n")
    block = _block(text, eol)
    return "\n".join(lines[:sec.heading_end + 1] + [eol] + block
                     + lines[sec.own_end + 1:])


def section_delete(content, address):
    """Delete a section and its entire subtree.

    Deleting `## Install` from `deep-nesting.md` removes 32 lines and six
    subsections. That is correct and it is also the most destructive op in the
    vocabulary, so the outline's subsection count is the model's warning and
    this docstring is the reader's: `end`, not `own_end`.
    """
    sec = resolve_section(content, address)
    lines = content.split("\n")
    # Take the trailing gap with it, so the document's section spacing is
    # unchanged rather than doubled where the section used to be.
    stop = sec.end + 1 + sec.gap_after
    if stop >= len(lines):
        # Last section in the file: there is no following gap to absorb, so take
        # the *leading* blank lines instead. Otherwise the document keeps the
        # separator for a section that no longer exists.
        start = sec.start
        while start > 0 and not lines[start - 1].strip():
            start -= 1
        return "\n".join(lines[:start] + lines[sec.end + 1:])
    return "\n".join(lines[:sec.start] + lines[stop:])


def section_delete_confirmed(content, address, confirm_subtree=False):
    """Agent-facing deletion guard; leaf deletion remains one call."""
    target = resolve_section(content, address)
    descendants = [f'"{section.slug}"' for section in find_sections(content)
                   if section.start > target.start and section.start <= target.end]
    if descendants and not confirm_subtree:
        plural = "" if len(descendants) == 1 else "s"
        raise OpError(
            f'deleting "{target.slug}" would also delete {len(descendants)} '
            f'descendant section{plural}: {"; ".join(descendants)}.\n'
            "  If you intend to delete the whole subtree, pass subtree=true.")
    return section_delete(content, address)


def section_rename(content, address, heading):
    """Change a heading's text, preserving the syntax it was written in.

    Setext stays setext, a closed ATX heading keeps its trailing hashes, an
    unusual run of spaces after the marker survives, and a CRLF file stays CRLF.
    `Section.rebuild` owns all four; see its docstring for why the last one is
    not hypothetical.
    """
    sec = resolve_section(content, address)
    if heading is None or not str(heading).strip():
        raise OpError("`heading` is required: the new text for the heading.")
    new = str(heading).strip()
    # A model handed "## Fixed" for a rename is quoting the line, not naming the
    # text. Stripping the marker is tolerance, not normalization: the level is
    # not the model's to set here, and `section-set-level` is the op that does.
    m = ATX_RE.match(new)
    if m and m.group(4) is not None:
        new = m.group(4).strip().rstrip("#").strip()
    if not new:
        raise OpError("`heading` cannot be only a heading marker.")
    lines = content.split("\n")
    return "\n".join(lines[:sec.start] + sec.rebuild(new)
                     + lines[sec.heading_end + 1:])


POSITIONS = ("before", "after", "first-child", "last-child")


def _reject_heading_in_body(body, field="body"):
    """Refuse a `body` payload that contains a heading.

    S6: `insert`'s preamble promises the model never has to count levels, and
    for `heading` that is true and measured (18-20/20 on rename and set-level).
    `body` takes markdown *source*, so the promise stops at its boundary in the
    one place the model most needs it: a new changelog release needs an `Added`
    subsection, and the only way to say so in one call was to write `### Added`
    by hand and get the 3 right. Across 30 `insert-release-at-top` trials the
    model wrote that heading at level 1, 2 and 4 -- never at 3.

    Refusing converts the class from `wrong` to `op_error`: the difference
    between a changelog with a malformed release and a calling agent that knows
    it needs a second call. The level is never named in the message, for the
    same reason it is never named in the schema.
    """
    if body is None or not str(body).strip():
        return
    text = str(body).replace("\r\n", "\n")
    # Parsed, not pattern-matched on the first line. `find_sections` is the same
    # parser the document itself goes through, so a `# comment` inside a fenced
    # bash block is not a heading here either -- and a heading that arrives on
    # the *third* line, after a stray table row, is. One trial sent exactly
    # that; a first-line check would have written it.
    found = find_sections(text)
    if not found:
        return
    first = found[0]
    name = first.text
    raise OpError(
        f"`{field}` contains a heading ({name!r}), and it is inserted as "
        "literal text -- the level would not be worked out for you.\n"
        "  Make the section first, then add the subsection with a second "
        "call: action=insert, position=last-child, `section` = the section you "
        "just created.\n"
        f"  If {name!r} is meant to be prose, drop the `#` marks.")


def _child_blocks(children, level, eol, field="children"):
    """Render `[{heading, body, children?}]` as lines at `level`, recursively.

    The structured alternative to S6's raw-markdown `body`: the caller names
    the shape, the executor names the levels. `level` is the child's own level,
    already derived from the parent, so nothing here can produce a heading the
    document could not contain.
    """
    if children is None:
        return []
    if isinstance(children, dict):
        children = [children]
    if not isinstance(children, list):
        raise OpError(
            f"`{field}` must be a list of subsections, each with a `heading` "
            f"and an optional `body`. Got {type(children).__name__}.")
    if level > 6:
        raise OpError(
            "a subsection here would be level 7 and markdown stops at 6.\n"
            f"  Drop `{field}` and insert those sections as siblings instead.")
    out = []
    for i, ch in enumerate(children):
        if isinstance(ch, str):
            ch = {"heading": ch}
        if not isinstance(ch, dict):
            raise OpError(
                f"`{field}`[{i}] must be an object with a `heading`. Got "
                f"{type(ch).__name__}.")
        head = _item(ch, "heading", "title", "new_heading")
        if head is None or not str(head).strip():
            raise OpError(f"`{field}`[{i}] is missing `heading`.")
        head = str(head).strip()
        m = ATX_RE.match(head)
        if m and m.group(4) is not None:
            head = m.group(4).strip().rstrip("#").strip()
        if not head:
            raise OpError(f"`{field}`[{i}] `heading` cannot be only `#` marks.")
        if out:
            out.append(eol)
        out.append("#" * level + " " + head + eol)
        body = _item(ch, "body", "text")
        if body is not None and str(body).strip():
            _reject_heading_in_body(body, f"{field}[{i}].body")
            out += [eol] + _block(body, eol, f"{field}[{i}].body")
        kids = ch.get("children") or ch.get("sections")
        if kids:
            out += [eol] + _child_blocks(kids, level + 1, eol, f"{field}[{i}].children")
    return out


def section_insert(content, anchor, position, heading, body=None, children=None):
    """Insert a new section relative to an existing one.

    The level is DERIVED, never passed. `before`/`after` make a sibling of the
    anchor; `first-child`/`last-child` make a child one level deeper. This is
    the list family's L4 result carried across: the model cannot see the
    document, so a level argument is a number it would have to invent, and
    deriving it makes an impossible level unexpressible rather than merely
    invalid.

    `after` means after the anchor's whole subtree. Inserting `## [1.5.0]`
    after `## [1.4.2]` must land past that release's `### Fixed` and
    `### Changed`, not between the heading and its first subsection -- which is
    the single most common changelog edit there is.
    """
    sec = resolve_section(content, anchor)
    if position not in POSITIONS:
        raise OpError(
            f'unknown position "{position}". Valid: {", ".join(POSITIONS)}.\n'
            "  before/after make a sibling of the anchor; first-child and "
            "last-child make a subsection of it.")
    if heading is None or not str(heading).strip():
        raise OpError("`heading` is required: the new section's heading text.")
    new_text = str(heading).strip()
    m = ATX_RE.match(new_text)
    if m and m.group(4) is not None:
        new_text = m.group(4).strip().rstrip("#").strip()
    if not new_text:
        raise OpError("`heading` cannot be only a heading marker.")

    eol = _section_eol(content, sec)
    lines = content.split("\n")
    secs = find_sections(content)
    idx = next(i for i, s in enumerate(secs) if s.start == sec.start)
    level = sec.level if position in ("before", "after") else sec.level + 1
    if level > 6:
        raise OpError(
            f'"{sec.slug}" is already at level {sec.level}; a subsection of it '
            "would be level 7 and markdown stops at 6.\n"
            "  Insert it as a sibling with position=after instead.")

    if position == "before":
        at = sec.start
    elif position == "after":
        at = sec.end + 1
    elif position == "first-child":
        at = sec.own_end + 1
    else:  # last-child
        at = sec.end + 1

    gap = [eol] * max(1, heading_gap(secs))
    block = ["#" * level + " " + new_text + eol]
    if body is not None and str(body).strip():
        _reject_heading_in_body(body)
        block += [eol] + _block(body, eol, "body")
    if children:
        block += [eol] + _child_blocks(children, level + 1, eol)

    if position == "before":
        out, head_at = lines[:at] + block + gap + lines[at:], at
    else:
        # `at` is one past the anchor's last non-blank line, so whatever blank
        # lines already separated it from the next section are still ahead of it.
        tail = at
        while tail < len(lines) and not lines[tail].strip():
            tail += 1
        if tail < len(lines):
            # Step over that existing separator instead of replacing it, and put
            # the new gap on the far side of the block. Two reasons, and they
            # agree. Those blank lines are the document's own bytes --
            # `whitespace.md` separates two of its sections with two of them,
            # `mixed-endings.md` with a CRLF one -- and §5.2 says match what was
            # found. And `section-delete` takes a section's *trailing* gap, so a
            # leading gap here would not compose: insert-then-delete would leave
            # a blank line behind and slowly loosen the document.
            out, head_at = lines[:tail] + block + gap + lines[tail:], tail
        else:
            # End of document: nothing follows to separate from, so the gap goes
            # before the block, and the blank lines `tail` just skipped stay
            # exactly as they were. `split("\n")` represents a file's final
            # newline as a last empty element; dropping it deletes a byte that is
            # invisible in a terminal and `collateral:formatting` by §5.1.
            # `whitespace.md` ends without one and has to keep not having one.
            out, head_at = lines[:at] + gap + block + lines[at:], at + len(gap)

    result = "\n".join(out)
    _verify_heading(result, head_at, new_text, sec)
    return result


def _verify_heading(result, line, text, anchor):
    """Refuse if the heading just written is not a heading in the output.

    The only place in this family where an op can succeed and still be wrong in
    a way the model cannot see. `corpus/hazards/code-fences.md` ends inside an
    unclosed fence, so by CommonMark everything after it -- including the
    anchor's own last line, and therefore the insertion point -- is code.
    Writing `## Foo` there changes the file, reports success, and creates no
    section. That is the difference §12 draws between `wrong` and `op_error`,
    and `op_error` is the loud one: better to refuse than to be believed.

    Checked by re-parsing rather than by testing the insertion point against
    `fence_mask`, because the property that matters is the one the next op will
    see, and only a parse establishes it.
    """
    if any(s.start == line for s in find_sections(result)):
        return
    where = "is not parsed as a heading there"
    for h in inert_headings(result):
        if h["line"] == line:
            where = {
                "code-fence": "would land inside a fenced code block that is "
                              "never closed, so it would be code, not a heading",
                "blockquote": "would land inside a blockquote",
                "indented-code": "would land inside an indented code block",
                "frontmatter": "would land inside the frontmatter",
            }[h["reason"]]
            break
    raise OpError(
        f'refusing to insert "{text}": at line {line + 1} it {where}.\n'
        f'  "{anchor.slug}" runs to the end of an unterminated block, so there '
        "is no point after it where a new section would be addressable.\n"
        "  Close the block first, or edit the section's body instead.")


def section_set_level(content, address, level, subtree=True):
    """Promote or demote a heading, optionally carrying its subsections.

    Two refusals with no analogue in the earlier families:

      * A setext heading can only express levels 1 and 2. Demoting one to level
        3 means rewriting it as ATX, which is a syntax change nobody asked for,
        so it refuses and says so.
      * `subtree=False` reparents children rather than moving them. That is a
        legitimate thing to want and a terrible thing to do by accident, so it
        is not the default.
    """
    sec = resolve_section(content, address)
    try:
        want = int(level)
    except (TypeError, ValueError):
        raise OpError(f"`level` must be a number from 1 to 6, not {level!r}.")
    if not 1 <= want <= 6:
        raise OpError(f"`level` must be between 1 and 6; got {want}.")
    if want == sec.level:
        raise OpError(
            f'"{sec.slug}" is already at level {sec.level}; nothing to do.')

    secs = find_sections(content)
    idx = next(i for i, s in enumerate(secs) if s.start == sec.start)
    delta = want - sec.level
    moving = [idx]
    if subtree:
        for k in range(idx + 1, len(secs)):
            if secs[k].level <= sec.level:
                break
            moving.append(k)

    for k in moving:
        new_level = secs[k].level + delta
        if not 1 <= new_level <= 6:
            raise OpError(
                f'moving "{sec.slug}" to level {want} would put its subsection '
                f'"{secs[k].slug}" at level {new_level}, which markdown cannot '
                "express.\n  Choose a level that keeps the whole subtree within "
                "1-6, or pass subtree=false to move only the heading.")
        if secs[k].style == "setext" and new_level > 2:
            raise OpError(
                f'"{secs[k].slug}" is written in setext form (underlined), which '
                f"can only express levels 1 and 2. Moving it to level "
                f"{new_level} would require rewriting it as `{'#' * new_level}`, "
                "a change to the document's style that was not asked for.\n"
                "  Convert that heading to ATX first if that is what you want.")

    lines = content.split("\n")
    for k in moving:
        s = secs[k]
        new_level = s.level + delta
        if s.style == "setext":
            # Still setext: only the underline character changes.
            char = "=" if new_level == 1 else "-"
            lines[s.heading_end] = s.indent + char * len(s.marker) + s.eol
        else:
            line = (s.indent + "#" * new_level + (s.space or " ") + s.raw_text)
            if s.style == "atx_closed":
                line += " " + s.closing
            lines[s.start] = line + s.eol
    return "\n".join(lines)


# --------------------------------------------------------------------------
# frontmatter
# --------------------------------------------------------------------------
# The fourth op family, and the first whose specification is a corpus file
# rather than a section of REQUIREMENTS: `corpus/frontmatter/rich.md:37-43`
# names key order, a leading comment, an inline comment on a sibling, two block
# scalar styles and one quoted key, and requires every one of them byte-
# identical after `frontmatter-set build.jobs 8`. `mdfront.py` is what makes
# that reachable -- an edit rewrites one line's value and no other line is
# touched at all.
#
# Two ops, not three: `frontmatter-set` creates a key as readily as it changes
# one, so a separate `-add` would be a second name for one behaviour and a
# second way for a model to pick wrong. `frontmatter_get` is a read and stays
# out of `OPS` for the reason `table_get` does -- it returns text *about* a
# document rather than a document.


def _front(content, verb="edits"):
    """The block, with TOML refused.

    `verb` arrives already conjugated. A caller that passes a stem and lets this
    add the `s` writes `incise delete froms YAML`, and a refusal is the product
    (section 5.3) -- it is read by a model that has to decide what to do next,
    and a sentence that has visibly been assembled by string arithmetic is one
    more reason not to believe the rest of it.

    `mdlist.frontmatter_span` accepts `+++` on purpose: the list and section
    parsers only need to know which lines to skip, and skipping a TOML block is
    as correct as skipping a YAML one. An op cannot be that relaxed.
    `corpus/hazards/toml-frontmatter.md` states the requirement and the failure
    it guards against -- "a YAML parser accepting some of this by accident and
    writing back a mangled block" -- so the format is checked here, once, before
    any op can reach the entries.
    """
    fm = mdfront.find_frontmatter(content)
    if fm.present and fm.fmt != "yaml":
        raise OpError(
            f"this file's frontmatter is TOML (`{fm.delim}`), and incise "
            f"{verb} YAML (`---`) frontmatter only.\n"
            "  Tables, lists and sections in this file are unaffected; only "
            "frontmatter ops stop here."
        )
    return fm


def _check_key(value):
    """A frontmatter key is a dotted path, as a string."""
    if isinstance(value, str):
        path = mdfront.parse_path(value)
        if path is not None:
            return path
        raise OpError(
            f"`key` is not a readable frontmatter path.\n"
            f"  Got: {value!r}\n"
            '  Send a dotted path, e.g. "build.jobs", or an indexed one, '
            'e.g. "authors[0].role".'
        )
    if value is None:
        raise OpError(
            "`key` is required: it says which frontmatter key to change.\n"
            '  Send a dotted path, e.g. "build.jobs".'
        )
    raise OpError(
        f"`key` must be a string, but arrived as {_type_name(value)}.\n"
        f"  Got: {value!r}\n"
        '  Send a dotted path, e.g. "build.jobs".'
    )


def _check_front_value(value):
    """A frontmatter value is one scalar. A structure is refused, not written.

    `_check_cell`'s reasoning, one family over: a nested object stringified into
    a cell was silent corruption, and a nested object written into a YAML value
    would be the same thing with a Python repr in it. Writing a real nested
    block is a different edit and needs a different op, which is why this names
    the key rather than suggesting a spelling.
    """
    if value is _MISSING:
        raise OpError(
            "`value` is required: it says what to set the key to.\n"
            '  Send null to set the key to an empty (YAML null) value.'
        )
    if isinstance(value, (dict, list, tuple)):
        raise OpError(
            f"`value` must be a single value, but arrived as "
            f"{_type_name(value)}.\n"
            f"  Got: {value!r}\n"
            "  A frontmatter key holds one scalar; set its leaf keys "
            "individually."
        )
    return value


def _yaml_scalar(value):
    """A value as the bytes that go after the colon.

    **Quoting is decided by the text, not by the JSON type it arrived as.**
    `8` and `"8"` produce the same byte, and that is deliberate: a tool schema
    cannot express YAML's scalar types, every arm's calls arrive as JSON, and
    quoting a value because the transport happened to carry it as a string
    would measure JSON rather than the model. §6.5's own example is
    `frontmatter-set build.jobs 8` writing `8`.

    Quotes go on only where the text would not survive being read back plain:
    an empty value, leading or trailing space, a leading indicator character,
    an embedded `: ` or ` #`. Those are the cases where writing it bare changes
    the document's structure rather than its value.
    """
    if value is None:
        return ""
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, float):
        return repr(value)
    s = str(value)
    if (s == "" or s != s.strip() or s[0] in "-?:,[]{}#&*!|>'\"%@`"
            or ": " in s or " #" in s or "\n" in s or "\t" in s):
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return s


def _yaml_key(name):
    """A new key's own bytes. Existing keys are never re-spelled."""
    s = str(name)
    if (s == "" or s != s.strip() or ":" in s or "#" in s
            or s[0] in "-?,[]{}&*!|>'\"%@`"):
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return s


def _no_front_key(fm, missing, wanted):
    """"No such key", with the paths that do exist.

    `missing` is the deepest segment that could not be resolved and `wanted` is
    what the caller asked for; when they differ the message says so, because
    "no key `build.cache.size`" on a file that has `build` sends a model
    hunting for a typo in the wrong segment.
    """
    have = [mdfront.format_path(e.path) for e in fm.entries]
    want = mdfront.format_path(missing)
    near = _close_matches(want, have, 3, 0.6)
    lines = [f"no frontmatter key `{want}`."]
    if missing != wanted:
        lines.append(f"  `{mdfront.format_path(wanted)}` needs it to exist "
                     "first.")
    # A key whose own name contains a dot is unreachable: `a.b` is read as two
    # segments before anything looks at the document, so no spelling of `key`
    # addresses it. Saying so is the difference between a model trying another
    # spelling and a model trying the same one four times.
    literal = ".".join(str(s) for s in wanted)
    if any(len(e.path) == 1 and e.path[0] == literal for e in fm.entries):
        lines.append(f"  This file has a single key *named* `{literal}`. A dot "
                     "always separates path segments, so that key cannot be "
                     "addressed.")
    if near:
        lines.append(f"  Near matches: {', '.join(near)}")
    if have:
        shown = have[:12]
        more = "" if len(have) == len(shown) else f", ... ({len(have) - 12} more)"
        lines.append(f"  Keys: {', '.join(shown)}{more}")
    else:
        lines.append("  The frontmatter block has no keys.")
    raise OpError("\n".join(lines))


def _front_children(fm, path):
    """Every entry written under `path`, at any depth."""
    n = len(path)
    return [e for e in fm.entries if len(e.path) > n and e.path[:n] == path]


def _holds(entry):
    """What a container entry holds, for a refusal that names the cost."""
    if entry.kind == "map":
        return "a map"
    if entry.kind == "seq":
        return "a sequence"
    if entry.kind == "block":
        return "a block scalar"
    return "a map on its `-` line"


def _front_value_type(entry, fm):
    if entry.kind == "map":
        return "object"
    if entry.kind == "seq":
        return "array"
    if entry.kind == "block":
        return "string"
    if entry.kind == "null":
        return "null"
    if entry.kind == "item" and _front_children(fm, entry.path):
        return "object"
    value = entry.value.strip()
    if ((value.startswith('"') and value.endswith('"'))
            or (value.startswith("'") and value.endswith("'"))):
        return "string"
    if value in ("true", "false", "True", "False", "TRUE", "FALSE"):
        return "boolean"
    if not value or value in ("null", "Null", "NULL", "~"):
        return "null"
    try:
        int(value)
        return "integer"
    except ValueError:
        try:
            float(value)
            return "number"
        except ValueError:
            return "string"


def frontmatter_get(content, key=None):
    """The block as structure: present, format, and every path with its value.

    Off `OPS` by requirement (§6.1): it returns text about a document rather
    than a document. `absent` and `empty` are distinct states here and not two
    spellings of falsy, because `corpus/frontmatter/absent.md:17` and
    `empty.md:6` both require a caller to be able to tell them apart.
    """
    fm = _front(content, verb="reads")
    entries = fm.entries
    if key is not None:
        path = _check_key(key)
        by = fm.by_path()
        if path not in by:
            _no_front_key(fm, path, path)
        entries = [e for e in entries
                   if e.path[:len(path)] == path]
    return {
        "state": "absent" if not fm.present else
                 ("empty" if not fm.entries else "present"),
        "format": fm.fmt,
        "keys": [{"path": mdfront.format_path(e.path),
                  "kind": e.kind,
                  "type": _front_value_type(e, fm),
                  "value": e.value,
                  "lines": e.end - e.line + 1}
                 for e in entries],
    }


def _front_text(content, fm):
    """The block's own lines, or None if there is no block."""
    if not fm.present:
        return None
    return "\n".join(content.split("\n")[fm.start:fm.end + 1])


def _strip_front(content):
    """Everything but the frontmatter block, for "did anything else move?".

    Leading blank lines come off both sides, because the blank line between a
    block and the document belongs to the block: creating one on
    `corpus/frontmatter/absent.md` inserts that separator, and reporting it as
    a second, vaguer change to the body would describe one edit twice.
    """
    fm = mdfront.find_frontmatter(content)
    rest = content if not fm.present else \
        "\n".join(content.split("\n")[fm.end + 1:])
    return rest.lstrip("\n")


def _front_notes(before, after):
    """(notes, whether a line tally is wanted) for a change to the block."""
    fb = mdfront.find_frontmatter(before)
    fa = mdfront.find_frontmatter(after)
    if _front_text(before, fb) == _front_text(after, fa):
        return [], False
    if not fb.present:
        return [f"added a frontmatter block with "
                f"{_plural(len(fa.top()), 'key')}"], True
    if not fa.present:
        return ["removed the frontmatter block"], True

    b, a = fb.by_path(), fa.by_path()
    notes, tally = [], False
    for path, e in a.items():
        if path in b and b[path].value != e.value and e.kind != "item":
            notes.append(f'set `{mdfront.format_path(path)}` to '
                         f"{e.value or 'an empty value'}")
    # A subtree collapses to its root, for `_run_notes`' reason: deleting
    # `tags` removes four entries and four sentences bury the one fact.
    for verb, src, other in (("added", a, b), ("removed", b, a)):
        roots = [p for p in src if p not in other
                 and not any(p[:n] in src and p[:n] not in other
                             for n in range(1, len(p)))]
        for p in roots:
            tally = True
            under = sum(1 for q in src if len(q) > len(p) and q[:len(p)] == p)
            extra = f" and {_plural(under, 'key')} under it" if under else ""
            notes.append(f"{verb} the frontmatter key "
                         f"`{mdfront.format_path(p)}`{extra}")
    if not notes:
        notes.append("changed the frontmatter block")
        tally = True
    return notes, tally


def describe_frontmatter_change(before, after):
    """`describe_change`, for the block it would only ever call "outside".

    Deliberately *not* folded into `describe_change`, and the reason has been
    replaced once. It used to be that the Rust had no frontmatter parser, so
    teaching this oracle a sentence the port could not say would turn a
    differential test into a record of a divergence. F-frontport retired that:
    `crates/incise-core/src/ops/frontmatter.rs` has this function, and
    `incise-cli/src/main.rs` dispatches on the op name exactly as `armb.py`
    does.

    What keeps them apart now is a count. F-describe folded them on a candidate
    basis and enumerated it: over 1888 distinct recorded edit calls and 54
    fixtures, 36 pairs are described differently, all of them `frontmatter-set`,
    all of them true, and all of them *vaguer* -- the closing clause goes from
    "changed text outside the frontmatter block" to "changed text outside any
    heading". The fold's measured effect is to lose the one word that names the
    region the model just edited.

    The hazard is the second reason, and it is unreached rather than absent.
    `describe_change` is derived from the two documents and not the op, so
    prepending text to a file that opens with `---` moves the delimiter off line
    0, `find_frontmatter` stops finding a block, and a folded description reports
    it as *removed*. No published op writes above every heading -- the block sits
    above them all -- so nothing reaches it today, and nothing asserts that
    stays true.

    What it buys is S14's finding: `describe_change` alone reports every
    frontmatter edit as "changed text outside any heading", which is true --
    the block is outside every heading -- and useless. A model that asked to
    change `build.jobs` and typed `build.jobz` is told here that it *added* a
    key, which is the one sentence that catches the typo. `render_frontmatter`
    cannot do it: it omits scalar values on purpose, so it cannot testify that
    a value changed.

    Like the rest of `describe_change` it is derived from the two documents, so
    it stays correct for an op it has never heard of.
    """
    if before == after:
        return "Applied, but the document is unchanged."
    notes, tally_wanted = _front_notes(before, after)
    # The block's notes come first, and the body fallback fires only for a
    # change they cannot account for -- otherwise one `frontmatter-set` is
    # described twice, once correctly and once vaguely.
    if not notes or _strip_front(before) != _strip_front(after):
        notes.append("changed text outside the frontmatter block")
        tally_wanted = True
    tally = []
    if tally_wanted:
        added, removed = _line_counts(before, after)
        if added:
            tally.append(f"+{_plural(added, 'line')}")
        if removed:
            tally.append(f"-{_plural(removed, 'line')}")
    head = "Applied: " + "; ".join(notes) + "."
    return head + (f" ({', '.join(tally)}.)" if tally else "")


def render_frontmatter(content, path):
    """The compact structural summary a model sees instead of the block.

    `list_tables`'s contract, one family over: every path needed to *choose* a
    key, and no scalar values. Arm B's premise is that the model addresses an
    edit it cannot see, and the instruction is what supplies the new value. The
    *kinds* stay, because they are what says `build` cannot be set to a scalar
    and `build.jobs` can.
    """
    fm = mdfront.find_frontmatter(content)
    if not fm.present:
        return f"Frontmatter in `{path}`: none. The file starts with content."
    if fm.fmt != "yaml":
        return (f"Frontmatter in `{path}`: TOML (`{fm.delim}`). incise edits "
                "YAML (`---`) frontmatter only.")
    if not fm.entries:
        return (f"Frontmatter in `{path}`: YAML, present but empty. The "
                "delimiters are there and the block has no keys.")
    out = [f"Frontmatter in `{path}`: YAML, {len(fm.top())} top-level keys"]
    for e in fm.entries:
        if e.kind == "item":
            continue
        if e.kind == "map":
            what = _plural(len(fm.children_of(e.path)), "key") + " below it"
        elif e.kind == "seq":
            what = _plural(len(fm.children_of(e.path)), "item")
        elif e.kind == "block":
            style = "literal" if e.value.startswith("|") else "folded"
            what = f"{style} block scalar, {e.end - e.line} lines"
        elif e.kind == "null":
            what = "empty (null)"
        else:
            what = "scalar"
        out.append(f"  {mdfront.format_path(e.path):<24s} {what}")
    return "\n".join(out)


def render_frontmatter_get(content, path, key=None):
    """Model-readable form of `frontmatter_get`: the same paths, with values.

    The counterpart to `render_frontmatter`, and the reason the project needs
    both. That one is the summary the *first* turn is handed, and it omits every
    scalar value on purpose: Arm B's premise is that the model addresses an edit
    it cannot see. This one is what comes back when the model asks, and its
    whole content is the values -- a read that showed what the summary already
    showed would be a tool that answers nothing, which is precisely the state
    `set-dana-role` measured (F-frontmatter: the summary lists
    `authors[0].name` and `authors[1].name` and no scheme offered any way to
    learn which one is Dana, so both arms guessed).

    Emitted as aligned `path` / `value` and deliberately **not** as YAML.
    `render_table_get`'s reason applies unchanged -- a result has no author's
    formatting to preserve, so the honest form is the one that claims nothing --
    and there is a second reason here: re-emitting a YAML block invites the
    model to send a YAML document back as a `value`, which is the failure
    §6.5 exists to avoid. The paths printed are the paths `key` accepts, so what
    the model reads is already spelled the way it must spell it back.

    Calls `frontmatter_get` rather than re-deriving the entry set, so the two
    cannot disagree about whether a key exists or in what order the refusals
    fire; the raw lines are consulted only for block scalars, whose value is
    not on the key's own line.
    """
    got = frontmatter_get(content, key)
    if got["state"] == "absent":
        return f"Frontmatter in `{path}`: none. The file starts with content."
    if got["state"] == "empty":
        return (f"Frontmatter in `{path}`: YAML, present but empty. The "
                "delimiters are there and the block has no keys.")

    fm = mdfront.find_frontmatter(content)
    lines = content.split("\n")
    wanted = {k["path"] for k in got["keys"]}
    head = f"Frontmatter in `{path}`: YAML"
    head += (f", under `{key}`" if key is not None
             else f", {len(fm.top())} top-level keys")
    out = [head]
    for e in fm.entries:
        p = mdfront.format_path(e.path)
        if p not in wanted:
            continue
        kids = fm.children_of(e.path)
        if e.kind == "map":
            what = _plural(len(kids), "key") + " below it"
        elif e.kind == "seq":
            what = _plural(len(kids), "item")
        elif e.kind == "item":
            # A sequence item that is itself a map (`authors[0]`) has no value
            # of its own -- `e.value` holds the first line of the mapping, which
            # would print `name: Peter` beside a path whose children print the
            # same two facts again. The children are the answer; this is a
            # signpost to them.
            if kids:
                what = _plural(len(kids), "key") + " below it"
            else:
                what = e.value
        elif e.kind == "null":
            what = "(empty)"
        elif e.kind == "block":
            style = "literal" if e.value.startswith("|") else "folded"
            body = lines[e.line + 1:e.end + 1]
            what = f"{style} block scalar, {_plural(len(body), 'line')}:"
            out.append(f"  {p:<24s} [string] {what}")
            # The body is the value, so it is shown. Indented past the column
            # the values sit in, and never re-wrapped: a folded scalar's line
            # breaks are the thing the author chose and the thing an edit has
            # to leave alone.
            out.extend("      " + ln.strip() for ln in body)
            continue
        else:
            what = e.value
        out.append(f"  {p:<24s} [{_front_value_type(e, fm)}] {what}")
    return "\n".join(out)


def _front_parent(fm, path):
    """(parent entry or None, insert-after line, indent) for a new key.

    The three shapes a new key can arrive in: top level, under an existing map,
    and under something that is not a map. The third is a refusal and not a
    silent append at the root, which is what "parse what parses, refuse the
    rest" means here.
    """
    parent = path[:-1]
    by = fm.by_path()
    if not parent:
        last = max((e.end for e in fm.entries), default=fm.start)
        return None, last, 0
    if parent not in by:
        # Walk out to the deepest ancestor that does exist, so the message
        # names the segment that actually broke rather than the whole path.
        missing = parent
        for n in range(len(parent) - 1, 0, -1):
            if parent[:n] in by:
                missing = parent[:n + 1]
                break
        _no_front_key(fm, missing, path)
    pe = by[parent]
    if pe.kind != "map":
        raise OpError(
            f"`{mdfront.format_path(parent)}` holds {_holds(pe)}, so "
            f"`{mdfront.format_path(path)}` cannot be added under it.\n"
            f"  Set `{mdfront.format_path(parent)}` itself, or add the key "
            "somewhere that holds a map."
        )
    kids = fm.children_of(parent)
    return pe, pe.end, kids[0].indent if kids else pe.indent + 2


def _front_eol(content, fm):
    """The line ending a line inserted into this block should carry.

    The block's own, when there is a block; otherwise the document's first
    line, which is the only convention a file with no frontmatter has to
    offer. `_table_eol`'s rule -- read the ending off the thing being edited --
    with the narrower scope that a created block has nothing of its own yet.
    """
    if fm.present:
        return fm.eol
    first = content.split("\n", 1)[0]
    return "\r" if first.endswith("\r") else ""


def _front_existence_flag(name, value):
    """One host-owned create/update precondition."""
    if value is _MISSING:
        return False
    if type(value) is bool:
        return value
    raise OpError(
        f"`{name}` must be a boolean, but arrived as {_type_name(value)}.\n"
        f"  Got: {value!r}"
    )


def frontmatter_set(content, key, value=_MISSING, must_absent=_MISSING,
                    must_exist=_MISSING):
    """Set one key, changing nothing else in the file.

    Three cases, in the order they are checked: the key exists and its value
    line is rewritten in place; the key is new and a line is inserted under its
    parent; the file has no block at all and one is created above the document.
    """
    fm = _front(content)
    path = _check_key(key)
    text = _yaml_scalar(_check_front_value(value))
    create_only = _front_existence_flag("must_absent", must_absent)
    update_only = _front_existence_flag("must_exist", must_exist)
    if create_only and update_only:
        raise OpError(
            "`must_absent` and `must_exist` cannot both be true.\n"
            "  Choose create-only (`must_absent`) or update-only "
            "(`must_exist`)."
        )
    eol = _front_eol(content, fm)

    exists = path in fm.by_path()
    if create_only and exists:
        shown = mdfront.format_path(path)
        raise OpError(
            f"`{shown}` already exists, but this edit requires an absent "
            "frontmatter key.\n"
            "  Use a new path for a create intent, or use update-only if "
            f"replacing `{shown}` is intended."
        )
    if update_only and not exists:
        shown = mdfront.format_path(path)
        raise OpError(
            f"`{shown}` does not exist, but this edit requires an existing "
            "frontmatter key.\n"
            "  Copy an exact path from `frontmatter_get`, or use create-only "
            "if adding a new key is intended."
        )

    if not fm.present:
        if len(path) > 1:
            raise OpError(
                f"this file has no frontmatter block, and `{key}` is nested, "
                "so there is nothing for it to attach to.\n"
                f"  Creating a block can set a top-level key -- "
                f"`{mdfront.format_path(path[:1])}` -- but not a path inside "
                "one."
            )
        if isinstance(path[0], int):
            raise OpError(
                f"this file has no frontmatter block, and `{key}` addresses a "
                "sequence item.\n"
                "  Creating a block can set a top-level key; a sequence has to "
                "exist before it can be indexed."
            )
        line = _yaml_key(path[0]) + (f": {text}" if text else ":")
        # A blank line goes between the new block and the document, unless the
        # document already opens with one. `corpus/frontmatter/absent.md:5`
        # names that blank line as part of what must be right.
        gap = "" if content.startswith(("\n", "\r\n")) else f"{eol}\n"
        return (f"{fm.delim or '---'}{eol}\n{line}{eol}\n---{eol}\n"
                f"{gap}{content}")

    by = fm.by_path()
    lines = content.split("\n")
    if path in by:
        e = by[path]
        # A sequence item holding one scalar is set like any other scalar --
        # `tags[1]` is `- two`, and rewriting it is the same line surgery with
        # the dash in the prefix instead of a key. An item holding a *map* is
        # not, and falls through to the refusal below with everything else that
        # has something written under it.
        settable = e.kind in ("scalar", "null") or (
            e.kind == "item" and not _front_children(fm, path))
        if not settable:
            raise OpError(
                f"`{mdfront.format_path(path)}` holds {_holds(e)}, so setting "
                "it to a single value would delete what is under it.\n"
                f"  Set one of its own keys instead, or delete "
                f"`{mdfront.format_path(path)}` first if replacing it is the "
                "intent."
            )
        lines[e.line] = e.rebuilt(text)
        return "\n".join(lines)

    if isinstance(path[-1], int):
        raise OpError(
            f"`{mdfront.format_path(path)}` addresses a sequence item that "
            "does not exist.\n"
            "  `frontmatter-set` changes a key's value; it does not extend a "
            "sequence."
        )
    _, after, indent = _front_parent(fm, path)
    new = " " * indent + _yaml_key(path[-1]) + (f": {text}" if text else ":")
    return "\n".join(lines[:after + 1] + [new + eol] + lines[after + 1:])


def frontmatter_delete(content, key):
    """Remove one key and everything written under it.

    The delimiters are never removed. Deleting the last key leaves `---\\n---`,
    which `corpus/frontmatter/empty.md:9-12` requires: taking the delimiters
    away is a structural change the caller did not ask for, and a file with an
    empty block is a state the family can already describe.
    """
    fm = _front(content, verb="deletes from")
    path = _check_key(key)
    if not fm.present:
        raise OpError(
            f"this file has no frontmatter block, so there is no `{key}` to "
            "delete.\n"
            "  The document starts with content; nothing needs removing."
        )
    by = fm.by_path()
    if path not in by:
        _no_front_key(fm, path, path)
    e = by[path]
    if e.key_text and e.prefix.rstrip(" ").endswith("-"):
        item = mdfront.format_path(path[:-1])
        raise OpError(
            f"`{mdfront.format_path(path)}` is written on the `-` line of "
            f"`{item}`, so deleting it alone would take the item marker with "
            "it.\n"
            f"  Delete `{item}` to remove the whole item, or set the key to "
            "null to empty it."
        )
    lines = content.split("\n")
    return "\n".join(lines[:e.line] + lines[e.end + 1:])



def _item(a, *fields):
    """The first of `fields` the caller supplied, as a string.

    Several names are accepted for the *selector* because the schemes under test
    spell it differently (`item` vs `match`), and the executor must be identical
    across schemes or the A/B measures the harness. It deliberately does NOT let
    `add-item` read `item`: that collision is the thing being measured (L3), and
    quietly absorbing it here would erase the result instead of recording it.
    """
    for f in fields or ("item",):
        v = a.get(f)
        if v is not None:
            return str(v)
    return None


OPS = {
    "table-add-row": lambda c, a: table_add_row(
        c, _address(a), _values(a), a.get("position", "end"), _values(a, "row")),
    "table-update-cell": lambda c, a: table_update_cell(
        c, _address(a), _where(a), a.get("column"), a.get("value", _MISSING)),
    "table-delete-row": lambda c, a: table_delete_row(
        c, _address(a), _where(a)),
    "table-realign": lambda c, a: table_realign(c, _address(a)),
    "list-add-item": lambda c, a: list_add_item(
        c, _list_address(a), _item(a, "text"), a.get("position", "end"),
        _item(a, "after"), a.get("checked")),
    "list-remove-item": lambda c, a: list_remove_item(
        c, _list_address(a), _item(a, "item", "match")),
    "list-set-checked": lambda c, a: list_set_checked(
        c, _list_address(a), _item(a, "item", "match"), a.get("checked", True)),
    "section-append": lambda c, a: section_append(
        c, _section_address(a), _item(a, "text", "body"),
        _item(a, "heading", "new_heading", "title")),
    "section-replace-body": lambda c, a: section_replace_body(
        c, _section_address(a), _item(a, "text", "body"),
        bool(a.get("overwrite")),
        _item(a, "heading", "new_heading", "title")),
    "section-insert": lambda c, a: section_insert(
        c, _section_address(a), a.get("position", "after"),
        _item(a, "heading", "title"), _item(a, "body", "text"),
        a.get("children") or a.get("subsections") or a.get("sections")),
    "section-delete": lambda c, a: section_delete_confirmed(
        c, _section_address(a), bool(a.get("subtree"))),
    "section-rename": lambda c, a: section_rename(
        c, _section_address(a), _item(a, "heading", "title", "text")),
    "section-set-level": lambda c, a: section_set_level(
        c, _section_address(a), a.get("level"), a.get("subtree", True)),
    # `key` and nothing else. `_item`'s alias list is deliberately not used
    # here: every call already carries `path`, meaning the *file*, and letting
    # it double as the frontmatter key is the exact failure S15 measured for the
    # section family. `a.get` rather than `_item` because `_item` stringifies,
    # which would swallow the type refusal `_check_key` exists to give.
    "frontmatter-set": lambda c, a: frontmatter_set(
        c, a.get("key"), a.get("value", _MISSING),
        a.get("must_absent", _MISSING), a.get("must_exist", _MISSING)),
    "frontmatter-delete": lambda c, a: frontmatter_delete(c, a.get("key")),
}



def apply_op(content, op_name, args):
    """Return (new_content, None) or (None, error_message)."""
    fn = OPS.get(op_name)
    if fn is None:
        return None, f'unknown operation "{op_name}". Valid: {", ".join(OPS)}'
    if args is not None and not isinstance(args, dict):
        # Reached when a model emits a bare string or array where the argument
        # object belongs. Without this it surfaced as "AttributeError: 'str'
        # object has no attribute 'get'".
        return None, (
            f"arguments for `{op_name}` must be an object, but arrived as "
            f"{_type_name(args)}.\n  Got: {args!r}"
        )
    try:
        return fn(content, args or {}), None
    except OpError as e:
        return None, str(e)
    except (KeyError, TypeError, ValueError, IndexError, AttributeError) as e:
        # A backstop, and one that should never fire: every message it can
        # produce is an exception repr rather than a repair (5.3), so reaching
        # it means an argument got through unvalidated. `AttributeError` was
        # missing from this tuple entirely, which turned `table: 7` into a
        # crash out of `apply_op` rather than any kind of refusal.
        return None, f"{type(e).__name__}: {e}"


if __name__ == "__main__":
    import sys
    for p in sys.argv[1:]:
        print(render_table_list(open(p).read(), p))
        print()
