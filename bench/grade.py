#!/usr/bin/env python3
"""Grade Arm A trials mechanically.

Patches are applied with hermes's OWN fuzzy matcher, imported directly from
~/.hermes/hermes-agent/tools/fuzzy_match.py (which depends only on re, typing
and difflib). Applying with exact matching instead would count as failures the
things hermes absorbs, which would rig the baseline against itself.

Outcome classes follow bench/PLAN.md section 5:

  correct               all mechanical checks pass
  destructive           an existing row or item disappeared that the task never
                        asked to remove -- silent data loss, the worst outcome
  collateral:formatting intended change made, but the table's or list's own
                        formatting was damaged
  collateral:content    intended change made, but content outside the target
                        table or list changed
  wrong                 intended change absent or incorrect
  misreported           the document is intact and the answer about it is false
  unfiltered            the answer is in there, along with rows nobody asked for
  no_match              the patch did not apply at all
  malformed             no tool call, bad JSON, or wrong tool

`misreported` is the read families' class and is deliberately not folded into
`wrong`. `wrong` is a failed edit: the document is not what the user asked for,
and the user can see that by looking at it. `misreported` is a *true-looking*
answer about a document that is untouched -- nothing on disk records that it
happened, and the output still has the shape of a table. `mutate.py`'s table-get
block states the same asymmetry from the other side ("worse than a refusal and
much harder to notice"). Collapsing the two would file the harder failure under
the easier one's remedy.

`unfiltered` is split off `misreported` for the opposite reason: nothing it
reports is false. It is the model reading the right table and doing the
narrowing in its head instead of in the argument, which is a correct strategy on
a five-row fixture and is the thing `table-get` exists to avoid on a five-hundred
row document -- Arm B's whole premise is that the model does not hold the file.
Scored apart because the two have different remedies and because pooling them
would make the `filter`-vs-`where` comparison unreadable: "asked about the wrong
table" and "did not narrow" are the two answers that question has.

`destructive` is checked before `wrong` because in the first pass every single
`wrong` trial turned out to be a lost row, and collapsing the two hid the fact.

The three op families are graded by different predicates and one shared
taxonomy, and they do not use the same standard of proof:

  tables    **no goldens.** `correct` means "passes every mechanical check";
            its conditions ("this row is present", "widths are uniform") are
            expressible as predicates.
  lists     **goldens scoped to the target list**, committed in
            `bench/tasks/lists.json`. A list's correctness *is* its formatting,
            so a predicate for it would be a golden written less legibly.
  sections  **whole-document goldens**, stored as a minimal changed window in
            `bench/tasks/sections.json`. A section edit can reach the whole
            file, so there is no smaller region to scope to.

That asymmetry is not an oversight; the reasons are in `make_list_tasks.py` and
`make_section_tasks.py`. Reports must state which standard they are quoting
rather than say "no goldens".

  python3 bench/grade.py
  python3 bench/grade.py --tasks bench/tasks/lists.json \\
      --trials bench/results/trials_lists.jsonl --out bench/results/graded_lists.jsonl
"""

import argparse
import json
import os
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bench"))
sys.path.insert(0, os.path.expanduser("~/.hermes/hermes-agent"))

from mdlist import CHECKBOX_RE, ITEM_RE, find_lists  # noqa: E402
from mdsection import find_sections  # noqa: E402
from mdtable import find_tables, outside_table  # noqa: E402
import mdfront  # noqa: E402

try:
    from tools.fuzzy_match import fuzzy_find_and_replace
    FUZZY = True
except ImportError:  # pragma: no cover
    FUZZY = False

    def fuzzy_find_and_replace(content, old_string, new_string, replace_all=False):
        """Exact-match fallback. Biases against the baseline -- flagged loudly."""
        n = content.count(old_string)
        if n == 0:
            return content, 0, None, "not found"
        if n > 1 and not replace_all:
            return content, 0, None, "not unique"
        return content.replace(old_string, new_string), n, "exact", None


def check_result(task, before, after, report=None):
    """Mechanical checks on an applied edit. Shared by Arm A and Arm B.

    Both arms must be judged by byte-identical criteria or the comparison
    between them is meaningless, so this is the single definition and neither
    arm gets its own. Dispatch is on the task's family: the two op families are
    graded by different predicates but the same outcome taxonomy, which is what
    makes their numbers comparable.

    `report` is the read families' third input and is `None` for every edit
    family. An edit's whole result is the document, so `before` and `after` say
    everything there is to say; a read leaves the document alone and puts its
    result somewhere neither argument can reach. Passing the structure rather
    than the rendered text is the point -- see `check_table_read_result`.
    """
    if task["family"].startswith("list-"):
        return check_list_result(task, before, after)
    if task["family"].startswith("section-"):
        return check_section_result(task, before, after)
    if task["family"].startswith("frontmatter-"):
        return check_frontmatter_result(task, before, after)
    if task["family"].startswith("table-get"):
        return check_table_read_result(task, before, after, report)
    return check_table_result(task, before, after)


def check_table_read_result(task, before, after, report):
    """Grade a read: the document must be untouched and the answer must be true.

    Scored against the structured result of `table_get` -- the same fields
    `TableRows` carries in the port (`ops/table.rs:154-162`) -- and never
    against `render_table_get`'s string. A grader that matched the rendered text
    would be a golden for the renderer: changing a separator or the `M of N`
    wording would fail every read task while every reported cell stayed correct,
    and a renderer bug that dropped a row would be indistinguishable from a
    model that never asked for it.

    Order of checks, worst first, mirroring the edit families:

      destructive          a line of the document is gone. A read task is never
                           satisfied by an edit, but losing a row is a different
                           severity from gaining one and the taxonomy already
                           draws that line.
      collateral:content   the document changed some other way. Everything a
                           read task can do to a file is outside its target,
                           because its target is the answer, not the file.
      op_error             every read the trial attempted was refused. Loud, and
                           costs a turn rather than a document.
      malformed            the trial never made a read call at all.
      misreported          a read succeeded and what it said is not true.
      unfiltered           a read succeeded, said nothing untrue, and did not
                           narrow: the rows the question wanted are in there
                           with others around them.

    `expect_*` are the whole contract: heading and columns catch a true report
    about the wrong table, `rows` catches the filter, and `total` catches a
    count that disagrees with the document even when every returned row is
    right. `matched` is checked against the rows themselves rather than against
    the task, because that one is an internal consistency claim -- an answer
    that says "2 of 9" above three rows is false no matter which table was
    asked for, and no task file should have to restate it.

    What this does *not* grade is the model's prose. There is no reference
    answer to check it against and grading it with another model is not a
    mechanical check, so the object scored is the question the model asked, not
    the sentence it wrote afterwards. `unfiltered` exists because that choice
    has a cost and the cost should be visible rather than charged to
    `misreported`.
    """
    if after != before:
        lost = [ln for ln in before.split("\n") if ln not in after.split("\n")]
        if lost:
            return "destructive", f"a read lost a line: {lost[0]!r}"
        return "collateral:content", "a read modified the document"

    if report is None:
        return "malformed", "no read call"
    if isinstance(report, str):
        return "op_error", report.replace("\n", " | ")

    if report["heading"] != task["expect_heading"]:
        return "misreported", (
            f'reported table {report["heading"]!r}, '
            f'the question was about {task["expect_heading"]!r}')
    if report["columns"] != task["expect_columns"]:
        return "misreported", (
            f'columns {report["columns"]}, expected {task["expect_columns"]}')
    if report["matched"] != len(report["rows"]):
        return "misreported", (
            f'claimed {report["matched"]} matches above '
            f'{len(report["rows"])} rows')
    if report["total"] != task["expect_total"]:
        return "misreported", (
            f'claimed {report["total"]} rows in the table, '
            f'it has {task["expect_total"]}')
    rows = [list(r) for r in report["rows"]]
    want = [list(r) for r in task["expect_rows"]]
    if rows != want:
        # Order matters, so the containment test is a subsequence and not a
        # subset: a read that returns the right rows shuffled has reordered the
        # document in its answer, which is a false statement about a table whose
        # row order is content.
        if _is_subsequence(want, rows):
            return "unfiltered", (
                f"reported {len(rows)} rows of the right table; the "
                f"{len(want)} the question asked for are among them")
        return "misreported", f"reported rows {rows}, expected {want}"
    return "correct", None


def _is_subsequence(want, rows):
    it = iter(rows)
    return all(any(r == w for r in it) for w in want)


def check_table_result(task, before, after):
    tables_before = find_tables(before)
    tables_after = find_tables(after)
    idx = task["target_table"]
    if len(tables_after) != len(tables_before):
        return "collateral:content", (
            f"table count changed {len(tables_before)}->{len(tables_after)}"
        )
    tb, ta = tables_before[idx], tables_after[idx]

    # --- data loss: an existing row vanished that nobody asked to remove ----
    rows_before = tb.rows()
    rows_after = ta.rows()
    asked_removed = {tuple(r) for r in task["require_absent"]}
    lost = [r for r in rows_before if r not in rows_after and r not in asked_removed]
    if lost:
        return "destructive", f"existing row lost: {lost[0]}"

    # --- intended change present? -------------------------------------------
    for want in task["require_present"]:
        if tuple(want) not in rows_after:
            return "wrong", f"missing row {want}; have {rows_after}"
    for unwanted in task["require_absent"]:
        if tuple(unwanted) in rows_after:
            return "wrong", f"row still present {unwanted}"
    delta = len(ta.body) - len(tb.body)
    if delta != task["expect_row_delta"]:
        return "wrong", f"row delta {delta}, expected {task['expect_row_delta']}"

    # --- content outside the target table --------------------------------
    if outside_table(before, tb) != outside_table(after, ta):
        return "collateral:content", "content outside the target table changed"

    # --- formatting of the target table ----------------------------------
    if task["require_delimiter_unchanged"] and ta.delimiter != tb.delimiter:
        return "collateral:formatting", (
            f"delimiter row changed: {tb.delimiter!r} -> {ta.delimiter!r}"
        )
    if task["preserve_existing_rows"]:
        removed = {tuple(r) for r in task["require_absent"]}
        kept_before = [ln for ln in tb.lines if tb.cells(ln) not in removed]
        missing = [ln for ln in kept_before if ln not in ta.lines]
        if missing:
            return "collateral:formatting", f"existing line rewritten: {missing[0]!r}"
    if task["require_aligned"] and not ta.is_aligned():
        return "collateral:formatting", f"table misaligned: widths {ta.widths()}"
    if not task["require_aligned"] and ta.is_aligned() and not tb.is_aligned():
        return "collateral:formatting", "ragged table was prettified"

    return "correct", None


# --------------------------------------------------------------------------
# lists
# --------------------------------------------------------------------------

def _block_items(block):
    """Item texts in a run of lines, by the same rules the ops use."""
    out = []
    for ln in block:
        m = ITEM_RE.match(ln)
        if not m:
            continue
        text = (m.group(4) or "")
        cb = CHECKBOX_RE.match(text)
        out.append(text[cb.end():].rstrip() if cb else text.rstrip())
    return out


def check_list_result(task, before, after):
    """Grade a list edit against a golden scoped to the target list.

    The list family is graded against goldens and the table family is not, and
    the reason is in `make_list_tasks.py`: a list's correctness *is* its
    formatting, so a predicate for "numbered the way this list is numbered" is
    a golden written less legibly. Using one does not collapse the taxonomy --
    the checks below run in order of severity and only the leftovers land on
    the golden comparison:

      content outside the list changed  -> collateral:content
      an item's text vanished entirely  -> destructive
      the requested line is absent      -> wrong
      a removed item is still there     -> wrong
      the item count is off             -> wrong
      anything else that differs        -> collateral:formatting

    So marker, indent, numbering and blank-line damage grade as formatting
    (loud in a diff, silent to a reader), and a missing or duplicated edit
    grades as wrong. `destructive` is checked on the text appearing *anywhere*
    in the block, not on it parsing as an item: an item whose marker was
    mangled is formatting damage, not data loss, and conflating them would
    inflate the headline number this benchmark exists to produce.
    """
    b, a = before.split("\n"), after.split("\n")
    lst = find_lists(before)[task["target_list"]]
    s, e = lst.start, lst.end
    shift = len(a) - len(b)

    if a[:s] != b[:s]:
        return "collateral:content", "content before the target list changed"
    if e + 1 + shift < 0 or a[e + 1 + shift:] != b[e + 1:]:
        return "collateral:content", "content after the target list changed"

    block = a[s: e + 1 + shift]
    texts_before = [it.text for it in lst.items]
    asked_gone = set(task["require_texts_absent"])
    lost = [t for t in texts_before
            if t not in asked_gone and not any(t in ln for ln in block)]
    if lost:
        return "destructive", f"existing item lost: {lost[0]!r}"

    for line in task["require_lines_present"]:
        if line not in block:
            return "wrong", f"missing line {line!r}; got {block}"
    texts_after = _block_items(block)
    for t in asked_gone:
        if t in texts_after:
            return "wrong", f"item still present {t!r}"
    delta = len(texts_after) - len(texts_before)
    if delta != task["expect_item_delta"]:
        return "wrong", (f"item delta {delta}, expected "
                         f"{task['expect_item_delta']}; got {block}")

    golden = task["golden"]
    if block != golden:
        for i in range(max(len(block), len(golden))):
            got = block[i] if i < len(block) else "(end of list)"
            want = golden[i] if i < len(golden) else "(end of list)"
            if got != want:
                return "collateral:formatting", (
                    f"line {s + i + 1}: {got!r}, expected {want!r}")
    return "correct", None


# --------------------------------------------------------------------------
# sections
# --------------------------------------------------------------------------

def _squash(lines):
    """The visible text of `lines`, with every whitespace difference removed.

    Used to separate `wrong` from `collateral:formatting` inside a section
    golden's changed window: what survives this is content, and §5's taxonomy
    only allows `collateral:formatting` when the content is intact.
    """
    return " ".join("".join(lines).split())


def _at(lines, i):
    return lines[i] if i < len(lines) else "(end of change)"


def check_section_result(task, before, after):
    """Grade a section edit against a whole-document golden.

    `make_section_tasks.py` explains the golden's shape: the common prefix and
    suffix are trimmed and stored as counts, so reassembling
    `before[:first_changed] + lines + before[len - unchanged_tail:]` gives the
    one correct output byte for byte. Nothing outside the window is merely
    unchecked here -- it is pinned, which is strictly stronger than the list
    family's scoped golden.

    The severity ladder deviates from `check_list_result` in one place, and the
    deviation is deliberate:

      an existing heading or body line vanished  -> destructive
      the requested change is absent or wrong    -> wrong
      text outside the window changed            -> collateral:content
      whitespace-only difference from the golden -> collateral:formatting

    `check_list_result` tests content-outside-the-list *first*, because a list
    op provably cannot reach outside the list, so a change there means the model
    edited some other construct entirely. That reasoning does not transfer. A
    section op legitimately rewrites arbitrary amounts of a file -- deleting
    `Install` from `deep-nesting.md` is thirty-two lines and six subsections --
    so a change outside the window is frequently *itself* the data loss.
    Grading it as `collateral:content` would file deletions in the milder
    bucket and understate the number this benchmark exists to produce.

    Section paths are compared as multisets, not sets. `duplicate-siblings.md`
    holds three sections whose path is identically `Notes`; against a set,
    losing one of them is invisible and the document's section count reads as
    -4 before any edit is made. Both bugs were live in the first section run:
    one trial that appended an extra blank line was reported as `wrong` with
    `section delta -4` when it was `collateral:formatting`, and a trial that
    deleted one of three identical siblings would not have been caught at all.
    """
    b, a = before.split("\n"), after.split("\n")
    g = task["golden"]
    pre, suf = g["first_changed"], g["unchanged_tail"]
    if a == b[:pre] + g["lines"] + b[len(b) - suf:]:
        return "correct", None

    # --- data loss ----------------------------------------------------------
    # Lines inside the window are the ones the edit was licensed to remove;
    # everything else that existed before must still be somewhere in the output.
    licensed = set(b[pre: len(b) - suf])
    survivors = set(a)
    exp = task["expect"]
    asked_gone = set(exp["paths_absent"])

    paths_before = [s.slug for s in find_sections(before)]
    paths_after = [s.slug for s in find_sections(after)]
    count_after = Counter(paths_after)
    for p, n in Counter(paths_before).items():
        if count_after[p] < n and p not in asked_gone:
            # A rename legitimately retires a path, and the task says which.
            # Anything else is a heading the user still expects to see.
            return "destructive", (f"section disappeared: {p!r}"
                                   f" ({n} before, {count_after[p]} after)")
    lost = [ln for ln in b
            if ln.strip() and ln not in licensed and ln not in survivors]
    if lost:
        return "destructive", f"existing line lost: {lost[0]!r}"

    # --- intended change present? -------------------------------------------
    for p in exp["paths_present"]:
        if p not in count_after:
            return "wrong", f"missing section {p!r}; have {sorted(count_after)}"
    for p in exp["paths_absent"]:
        if p in count_after:
            return "wrong", f"section still present {p!r}"
    delta = len(paths_after) - len(paths_before)
    if delta != exp["section_delta"]:
        return "wrong", (f"section delta {delta:+d}, expected "
                         f"{exp['section_delta']:+d}")

    # --- whitespace-only, anywhere in the document --------------------------
    # Checked before the window rungs, because the window is a statement about
    # *line numbers* and a line-structure difference invalidates it without
    # being content damage. The Arm A sections run produced ten trials of this
    # shape on `notes-second-ordinal`:
    #
    #     Second Notes section, same level, same parent, identical text.
    #     Superseded.
    #
    # -- the right sentence, in the right section, joined to the paragraph above
    # instead of separated by a blank line. The prefix rung below sees a changed
    # line before the window and calls it `collateral:content`, which asserts
    # content was altered. Nothing was: the document's visible text is exactly
    # the golden's. It is a paragraph break lost, which §5.1 still counts as
    # corruption -- `collateral:formatting` is not an acquittal -- but calling it
    # content damage would overstate 10% of the arm.
    golden_doc = b[:pre] + g["lines"] + b[len(b) - suf:]
    if a != golden_doc and _squash(a) == _squash(golden_doc):
        for i in range(max(len(a), len(golden_doc))):
            x, y = _at(a, i), _at(golden_doc, i)
            if x != y:
                return "collateral:formatting", (
                    f"whitespace only, line {i + 1}: {x!r}, expected {y!r}")

    # --- text outside the window --------------------------------------------
    shift = len(a) - len(b)
    if a[:pre] != b[:pre]:
        return "collateral:content", "text before the edited region changed"
    if suf and a[len(a) - suf:] != b[len(b) - suf:]:
        return "collateral:content", "text after the edited region changed"

    # --- inside the window: wrong payload, or damaged whitespace? -----------
    # §5's taxonomy reserves `collateral:formatting` for "intended change
    # correct, content intact". A difference that survives whitespace
    # normalization is not formatting: the model appended
    # `None of the above is parsed as markdown.\\n` -- a literal backslash-n,
    # from double-escaped JSON -- and filing that under formatting would report
    # visibly corrupted prose as a cosmetic miss.
    got = a[pre: len(a) - suf]
    want = g["lines"]
    if _squash(got) != _squash(want):
        for i in range(max(len(got), len(want))):
            x, y = _at(got, i), _at(want, i)
            if _squash([x]) != _squash([y]):
                return "wrong", f"line {pre + i + 1}: {x!r}, expected {y!r}"
        return "wrong", f"payload differs from the golden"
    for i in range(max(len(got), len(want))):
        x, y = _at(got, i), _at(want, i)
        if x != y:
            return "collateral:formatting", (
                f"line {pre + i + 1}: {x!r}, expected {y!r}")
    return "collateral:formatting", f"differs by {shift:+d} lines"


def _front_body(content):
    """Everything after the frontmatter block, with leading blanks dropped.

    Compared as *text*, never by line index. `create-on-absent` inserts four
    lines above every byte of the document, so an index-based comparison would
    report the whole file as changed when nothing in it did; and the blank line
    between a new block and the document is part of the block's own shape, which
    is why it is stripped from both sides rather than counted.
    """
    fm = mdfront.find_frontmatter(content)
    lines = content.split("\n")
    body = lines if not fm.present else lines[fm.end + 1:]
    return "\n".join(body).lstrip("\n")


def _front_keys(content):
    """Every addressable path in the block, and the value written on its line."""
    fm = mdfront.find_frontmatter(content)
    return {mdfront.format_path(e.path): e.value for e in fm.entries}


def _front_state(content):
    fm = mdfront.find_frontmatter(content)
    if not fm.present:
        return "absent"
    return "empty" if not fm.entries else "present"


def check_frontmatter_result(task, before, after):
    """Grade a frontmatter edit against a whole-document golden.

    The golden is `make_section_tasks.py`'s minimal changed window, for the
    reason `make_frontmatter_tasks.py` gives: this family's specification is a
    list of bytes that must not move, and only a whole-document golden can say
    that without restating the block and re-introducing the very serializer
    round trip it is guarding against.

    The **ladder** is the list family's, not the section family's, and the
    difference matters. `check_section_result` deliberately does not test
    outside-the-window first, because a section op legitimately rewrites
    arbitrary amounts of a file and a change out there is frequently itself the
    data loss. A frontmatter op has the narrow reach a list op has: it cannot
    touch a byte below the closing delimiter, ever. So a changed body means the
    trial edited some other construct entirely -- which is a fact about what
    happened worth reporting above whether the key also came out right, and a
    rung only Arm A can reach, since Arm B is handed no tool that can write
    there.

      a key or an unlicensed line that existed is gone -> destructive
      the document body changed                        -> collateral:content
      the requested key is absent, wrong or miscounted -> wrong
      whitespace-only difference from the golden       -> collateral:formatting
      every key right and the bytes still differ       -> collateral:content

    The last two are in that order in the code and this order on the page for
    the same reason: the whitespace rung is the narrower claim and is only
    reached once no line differs in anything but whitespace.

    The content rung is the one with no equivalent in any other family, and it is
    the reason this grader exists rather than reusing the section one. A YAML
    round trip that keeps every key and every value, and drops the leading
    comment, the inline comment on `build.target` and the quoting of
    `quoted_key`, passes every structural check there is. `rich.md:37-43` says
    that document is wrong, and the byte comparison is the only thing that
    agrees -- so what is left over after the keys check is graded as content
    damage and not as formatting. `collateral:formatting` above it stays
    reachable and stays honest, because `_squash` equality means the visible
    text really is identical.
    """
    b, a = before.split("\n"), after.split("\n")
    g = task["golden"]
    pre, suf = g["first_changed"], g["unchanged_tail"]
    if a == b[:pre] + g["lines"] + b[len(b) - suf:]:
        return "correct", None

    exp = task["expect"]
    keys_before, keys_after = _front_keys(before), _front_keys(after)
    asked_gone = set(exp["keys_absent"])

    # --- data loss ----------------------------------------------------------
    for k in keys_before:
        if k not in keys_after and k not in asked_gone:
            # A delete legitimately retires the paths under its target, and the
            # task names them; `delete-build` lists four and removes six, so
            # the check is "not asked for, and not under something asked for".
            if not any(k == p or k.startswith(p + ".") or k.startswith(p + "[")
                       for p in asked_gone):
                return "destructive", f"frontmatter key disappeared: {k!r}"

    # A comment line needs no rung of its own: it is a line, and this is the
    # section family's lost-line check, which protects every line the window
    # did not license the edit to touch.
    licensed = set(b[pre: len(b) - suf])
    survivors = set(a)
    lost = [ln for ln in b
            if ln.strip() and ln not in licensed and ln not in survivors]
    if lost:
        return "destructive", f"existing line lost: {lost[0]!r}"

    # --- the body, which a frontmatter op cannot reach ----------------------
    if _front_body(before) != _front_body(after):
        return "collateral:content", "the document below the frontmatter changed"

    # --- intended change present? -------------------------------------------
    state = _front_state(after)
    if state != exp["state"]:
        return "wrong", f"frontmatter is {state}, expected {exp['state']}"
    for k, v in exp["keys_present"].items():
        if k not in keys_after:
            return "wrong", f"missing key {k!r}; have {sorted(keys_after)}"
        if keys_after[k] != v:
            return "wrong", f"{k!r} holds {keys_after[k]!r}, expected {v!r}"
    for k in exp["keys_absent"]:
        if k in keys_after:
            return "wrong", f"key still present {k!r}"
    delta = len(keys_after) - len(keys_before)
    if delta != exp["key_delta"]:
        return "wrong", (f"key delta {delta:+d}, expected "
                         f"{exp['key_delta']:+d}")

    # --- the bytes, whitespace last -----------------------------------------
    # Compared line against line rather than document against document.
    # `check_section_result` squashes the whole window at once, and `_squash`
    # joins with "" -- so a trailing space at a line end merges two tokens
    # there and reads as a content difference. Inside a section's window that
    # is harmless; here the window is frequently one line and the rung below it
    # is content damage, so the comparison is done at the granularity the
    # answer is given at.
    golden_doc = b[:pre] + g["lines"] + b[len(b) - suf:]
    n = max(len(a), len(golden_doc))
    for i in range(n):
        x, y = _at(a, i), _at(golden_doc, i)
        if _squash([x]) != _squash([y]):
            # Every key is right and the visible text is not. This is the round
            # trip `rich.md` exists to catch -- a re-quoted scalar, a reflowed
            # block, a reordered map -- and it is content, not formatting.
            return "collateral:content", f"line {i + 1}: {x!r}, expected {y!r}"
    for i in range(n):
        x, y = _at(a, i), _at(golden_doc, i)
        if x != y:
            return "collateral:formatting", (
                f"whitespace only, line {i + 1}: {x!r}, expected {y!r}")
    return "collateral:content", f"differs by {len(a) - len(b):+d} lines"


def grade_one(task, trial):
    """Return (outcome, detail)."""
    if trial.get("error"):
        return "malformed", trial["error"]

    calls = trial.get("tool_calls") or []
    if not calls:
        return "malformed", "no tool call"
    fn = calls[0].get("function", {})
    if fn.get("name") != "patch":
        return "malformed", f"wrong tool: {fn.get('name')}"
    try:
        args = json.loads(fn.get("arguments") or "{}")
    except json.JSONDecodeError as e:
        return "malformed", f"unparseable arguments: {e}"
    if "old_string" not in args or "new_string" not in args:
        return "malformed", "missing old_string/new_string"

    before = open(os.path.join(ROOT, task["fixture"]), newline="").read()
    after, count, strategy, err = fuzzy_find_and_replace(
        before, args["old_string"], args["new_string"], bool(args.get("replace_all"))
    )
    if err or count == 0:
        return "no_match", err or "no match"

    outcome, detail = check_result(task, before, after)
    return outcome, (strategy or "exact") if outcome == "correct" else detail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default=os.path.join(ROOT, "bench/tasks/tables.json"))
    ap.add_argument("--trials", default=os.path.join(ROOT, "bench/results/trials.jsonl"))
    ap.add_argument("--out", default=os.path.join(ROOT, "bench/results/graded.jsonl"))
    args = ap.parse_args()

    tasks = {t["id"]: t for t in json.load(open(args.tasks))["tasks"]}
    path = args.trials
    if not os.path.exists(path):
        print(f"no trials at {path} -- run bench/runner.py first")
        return 1

    if not FUZZY:
        print("!! WARNING: hermes fuzzy_match not importable; using exact match.")
        print("!! This biases results AGAINST the baseline. Fix before reporting.\n")

    trials = [json.loads(l) for l in open(path) if l.strip()]
    by_cond = defaultdict(lambda: defaultdict(Counter))
    totals = defaultdict(Counter)
    cost = defaultdict(lambda: [0, 0, 0])  # trials, completion_tokens, seconds
    details = defaultdict(list)
    distinct = defaultdict(lambda: defaultdict(set))

    graded_path = args.out
    with open(graded_path, "w") as out:
        for tr in trials:
            task = tasks.get(tr["task_id"])
            if not task:
                continue
            outcome, detail = grade_one(task, tr)
            cond = tr["condition"]
            by_cond[cond][tr["task_id"]][outcome] += 1
            totals[cond][outcome] += 1
            c = cost[cond]
            c[0] += 1
            c[1] += tr.get("completion_tokens") or 0
            c[2] += tr.get("elapsed_s") or 0
            calls = tr.get("tool_calls") or []
            distinct[cond][tr["task_id"]].add(
                calls[0].get("function", {}).get("arguments") if calls else None)
            if outcome != "correct":
                details[(cond, tr["task_id"], outcome)].append(detail)
            out.write(json.dumps({**{k: tr[k] for k in ("task_id", "condition", "trial")},
                                  "outcome": outcome, "detail": detail}) + "\n")

    for cond in sorted(by_cond):
        n = sum(totals[cond].values())
        print(f"\n{'='*78}\nCONDITION: {cond}   ({n} trials)\n{'='*78}")
        print(f"{'task':28s} {'n':>3s}  outcomes")
        for tid in tasks:
            counts = by_cond[cond].get(tid)
            if not counts:
                continue
            tot = sum(counts.values())
            summary = "  ".join(f"{k}={v}" for k, v in counts.most_common())
            print(f"{tid:28s} {tot:3d}  {summary}")
        print(f"\n{'-'*78}\nTOTALS ({n} trials)")
        for k, v in totals[cond].most_common():
            print(f"  {k:24s} {v:4d}   {100*v/n:5.1f}%")
        corr = totals[cond]["correct"]
        dest = totals[cond]["destructive"]
        coll = totals[cond]["collateral:formatting"] + totals[cond]["collateral:content"]
        # `wrong` counts here: the document was modified, incorrectly, with no
        # error raised -- silent by any reasonable reading. It was excluded
        # originally, which cost nothing in Arm A (30.0% either way) but
        # understated Arm B's `scheme_b` as 0% when it was 11.7%. See
        # FINDINGS.md B6.
        wrong = totals[cond]["wrong"]
        print(f"\n  correct                  {100*corr/n:5.1f}%")
        print(f"  DATA LOSS                {100*dest/n:5.1f}%   (existing row destroyed)")
        print(f"  SILENT CORRUPTION        {100*(coll+dest+wrong)/n:5.1f}%"
              f"   (destructive {dest}, formatting {totals[cond]['collateral:formatting']}, "
              f"content {totals[cond]['collateral:content']}, wrong {wrong})")
        # Read families only -- see the note beside the same line in armb.grade
        # for why this is a line of its own rather than a term in the one above.
        if totals[cond]["misreported"]:
            print(f"  FALSE REPORT             {100*totals[cond]['misreported']/n:5.1f}%"
                  "   (document intact, answer untrue)")
        if totals[cond]["unfiltered"]:
            print(f"  unnarrowed read          {100*totals[cond]['unfiltered']/n:5.1f}%"
                  "   (right table, no filter applied)")
        t, tok, sec = cost[cond]
        print(f"  mean completion tokens   {tok/t:.0f}")
        print(f"  mean wall-clock          {sec/t:.1f}s")
        # Trials share a prompt and differ only by seed. Where the model is
        # confident, different seeds collapse to the same bytes, so nominal
        # N overstates the independent evidence. Report it rather than hide it.
        uniq = [len(distinct[cond][tid]) for tid in by_cond[cond]]
        print(f"  distinct outputs/task    {min(uniq)}-{max(uniq)} of "
              f"{max(sum(by_cond[cond][tid].values()) for tid in by_cond[cond])}"
              "   (seeds often collapse; effective N < nominal N)")

    if details:
        print(f"\n{'='*78}\nFAILURE DETAIL (first example each)\n{'='*78}")
        for (cond, tid, outcome), msgs in sorted(details.items()):
            print(f"\n[{cond}] {tid} -> {outcome}  (n={len(msgs)})")
            print(f"  {msgs[0][:220]}")

    print(f"\nwrote {graded_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
