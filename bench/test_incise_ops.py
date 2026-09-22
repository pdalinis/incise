#!/usr/bin/env python3
"""Invariant tests for the reference implementation.

`incise_ops.py` is the differential-testing oracle for the Rust
(REQUIREMENTS.md section 9, criterion 7) and the executor Arm B's numbers were
measured against (FINDINGS.md B1). Both roles mean a silent regression here
invalidates results elsewhere, so the invariants are asserted rather than
spot-checked.

  python3 bench/test_incise_ops.py

No test framework, to match the rest of bench/. Exit code is the result.
"""

import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bench"))

from incise_ops import (  # noqa: E402
    OPS, OpError, apply_op, describe_change, list_lists, list_tables,
    resolve_list, resolve_section, resolve_table, section_outline,
)
import mdlist  # noqa: E402
from mdlist import find_lists  # noqa: E402
import mdfront  # noqa: E402
from mdsection import (  # noqa: E402
    LINKREF_RE, _footer_start, fence_mask, find_sections, inert_headings)
from mdtable import find_tables, outside_table, split_row  # noqa: E402

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name}  {detail}")
        FAILURES.append(name)


def eol_profile(s):
    """(crlf_count, lone_lf_count). Counting '\\n' alone cannot see a lost '\\r'."""
    return s.count("\r\n"), len(re.findall(r"(?<!\r)\n", s))


def corpus_files():
    for dirpath, _, names in os.walk(os.path.join(ROOT, "corpus")):
        for n in sorted(names):
            if n.endswith(".md"):
                yield os.path.join(dirpath, n)


# --------------------------------------------------------------------------

def test_benchmark_tasks():
    """The six Arm B tasks must be reachable and correct through apply_op.

    This is the harness-ceiling check from FINDINGS.md B1: if an ideal call does
    not grade `correct`, every Arm B number is measuring the mock, not the model.
    """
    from grade import check_result

    ops = {
        "add-row-aligned-short": ("table-add-row", {
            "table": {"heading": "Components"},
            "values": {"Component": "sprocket", "Status": "active", "Owner": "rowan"}}),
        "add-row-aligned-repad": ("table-add-row", {
            "table": {"heading": "Components"},
            "values": {"Component": "hyperwidget-assembly", "Status": "active",
                       "Owner": "dana"}}),
        "add-row-ragged": ("table-add-row", {
            "table": {"heading": "Components"},
            "values": {"Component": "sprocket", "Status": "active", "Owner": "rowan"}}),
        "add-row-alignment-markers": ("table-add-row", {
            "table": {"heading": "All four forms"},
            "values": {"Default": "i", "Left": "j", "Center": "k", "Right": "l"}}),
        "delete-row-aligned": ("table-delete-row", {
            "table": {"heading": "Components"}, "where": {"Component": "gadget"}}),
        "update-cell-multi-table": ("table-update-cell", {
            "table": {"heading": "Environments", "ordinal": 1},
            "where": {"Host": "stage-1"}, "column": "Size", "value": "t3.l"}),
    }
    tasks = {t["id"]: t for t in
             json.load(open(os.path.join(ROOT, "bench/tasks/tables.json")))["tasks"]}
    for tid, (op, args) in ops.items():
        task = tasks[tid]
        before = open(os.path.join(ROOT, task["fixture"]), newline="").read()
        after, err = apply_op(before, op, args)
        if err:
            check(f"task {tid}", False, err.replace("\n", " "))
            continue
        outcome, detail = check_result(task, before, after)
        check(f"task {tid}", outcome == "correct", f"{outcome}: {detail}")


def test_corpus_roundtrip():
    """Adding then deleting a row must restore the file byte-for-byte.

    The strongest single invariant available without goldens: it catches lost
    CRLF, dropped final newlines, shifted padding, and mangled delimiter rows in
    one assertion, across every table in the corpus.
    """
    checked = 0
    for path in corpus_files():
        content = open(path, newline="").read()
        rel = os.path.relpath(path, ROOT)
        for entry in list_tables(content, rel):
            addr = {"heading": entry["heading"], "ordinal": entry["ordinal"]}
            cols = entry["columns"]
            if not cols or len(set(cols)) != len(cols):
                continue  # duplicate column names cannot be addressed by name
            probe = {c: "zzq" for c in cols}
            added, err = apply_op(content, "table-add-row",
                                  {"table": addr, "values": probe})
            if err and "not rectangular" in err:
                # The one table in the corpus whose rows disagree with its
                # header. It is a fixture for exactly that, and the refusal is
                # the decision the fixture asks for; there is nothing to
                # round-trip.
                check(f"non-rectangular {rel} refuses", "row 1 has 2" in err, err)
                continue
            if err:
                check(f"add {rel} [{entry['heading']}#{entry['ordinal']}]", False,
                      err.replace("\n", " "))
                continue
            back, err = apply_op(added, "table-delete-row",
                                 {"table": addr, "where": {cols[0]: "zzq"}})
            if err:
                check(f"del {rel} [{entry['heading']}#{entry['ordinal']}]", False,
                      err.replace("\n", " "))
                continue
            checked += 1
            if back != content:
                check(f"roundtrip {rel} [{entry['heading']}#{entry['ordinal']}]",
                      False, f"eol {eol_profile(content)} -> {eol_profile(back)}")
    check(f"add+delete round-trips byte-identical ({checked} tables)", checked > 0)


def test_identity_update_roundtrip():
    r"""Writing a cell's own value back must leave the file byte-identical.

    The add+delete round-trip above never rewrites a row that was already there,
    so it says nothing about whether the tool reads existing rows correctly. This
    one touches every cell of every table in the corpus and asserts the null edit
    is null.

    It is the test that would have caught the escaped-pipe defect, and did not
    exist while that defect shipped. `corpus/tables/cell-edge-cases.md` row 1 is

        | escaped pipe    | a \| b                   | literal pipe, backslashed  |

    and a naive split on `|` read four cells in a three-column table, so
    `table-update-cell` on column `Note` overwrote the fragment `b` and emitted a
    four-column row -- reported as success, on the fixture whose stated purpose is
    "Any operation on this table must round-trip every cell exactly."
    """
    checked = skipped = 0
    for path in corpus_files():
        content = open(path, newline="").read()
        rel = os.path.relpath(path, ROOT)
        # `list_tables` walks `find_tables`, so the two lists are parallel.
        for entry, table in zip(list_tables(content, rel), find_tables(content)):
            addr = {"heading": entry["heading"], "ordinal": entry["ordinal"]}
            cols = entry["columns"]
            if not cols or len(set(cols)) != len(cols):
                continue
            if len({len(split_row(ln)) for ln in table.lines}) != 1:
                # Refused outright, and `test_corpus_roundtrip` asserts that
                # refusal. Nothing here can be written back.
                continue
            for row in table.rows():
                sel = dict(zip(cols, row))
                for col, val in sel.items():
                    after, err = apply_op(content, "table-update-cell", {
                        "table": addr, "where": sel, "column": col, "value": val})
                    if err and "must identify exactly one" in err:
                        # Two identical rows. Not this test's subject, and the
                        # only refusal a well-formed table may legitimately give
                        # to a selector built from its own contents -- every
                        # other one is the tool failing to read what it wrote.
                        skipped += 1
                        continue
                    if err:
                        check(f"identity update {rel} [{entry['heading']}"
                              f"#{entry['ordinal']}] {col}={val!r}", False,
                              err.replace("\n", " "))
                        continue
                    checked += 1
                    if after != content:
                        check(f"identity update {rel} [{entry['heading']}"
                              f"#{entry['ordinal']}] {col}={val!r}", False,
                              _first_diff(content, after))
    check(f"writing a cell's own value back changes nothing ({checked} cells)",
          checked > 0)


def _first_diff(before, after):
    b, a = before.split("\n"), after.split("\n")
    for i in range(max(len(b), len(a))):
        x = b[i] if i < len(b) else "<eof>"
        y = a[i] if i < len(a) else "<eof>"
        if x != y:
            return f"line {i + 1}: {x!r} -> {y!r}"
    return "no line differs"


def test_outside_bytes_untouched():
    """Everything outside the target table is byte-identical after a mutation."""
    for rel in ("corpus/tables/aligned.md", "corpus/tables/ragged.md",
                "corpus/tables/multiple-per-section.md"):
        content = open(os.path.join(ROOT, rel), newline="").read()
        entry = list_tables(content, rel)[0]
        after, err = apply_op(content, "table-add-row", {
            "table": {"heading": entry["heading"], "ordinal": entry["ordinal"]},
            "values": {c: "zzq" for c in entry["columns"]}})
        if err:
            check(f"outside {rel}", False, err.replace("\n", " "))
            continue
        tb, ta = find_tables(content)[0], find_tables(after)[0]
        check(f"outside bytes unchanged: {rel}",
              outside_table(content, tb) == outside_table(after, ta))


def test_widen_never_shrink():
    """A short add must not rewrite existing rows (REQUIREMENTS.md 5.2).

    corpus/tables/aligned.md pads Owner to 9 where its content needs 7. A
    minimum-width renderer would rewrite all three existing rows to append one
    short one -- this caught exactly that bug.
    """
    rel = "corpus/tables/aligned.md"
    content = open(os.path.join(ROOT, rel)).read()
    after, err = apply_op(content, "table-add-row", {
        "table": {"heading": "Components"},
        "values": {"Component": "sprocket", "Status": "active", "Owner": "rowan"}})
    check("short add: no error", not err, err or "")
    if err:
        return
    kept = [ln for ln in find_tables(content)[0].lines]
    after_lines = find_tables(after)[0].lines
    check("short add rewrites no existing line",
          all(ln in after_lines for ln in kept),
          str([ln for ln in kept if ln not in after_lines][:1]))

    # And a genuinely wider value must widen every line, to exactly 22.
    wide, err = apply_op(content, "table-add-row", {
        "table": {"heading": "Components"},
        "values": {"Component": "hyperwidget-assembly", "Status": "active",
                   "Owner": "dana"}})
    check("repad: no error", not err, err or "")
    if not err:
        w = find_tables(wide)[0].widths()[0]
        check("repad widens column 0 to exactly 22", w[0] == 22, f"got {w[0]}")


def test_alignment_markers_survive():
    rel = "corpus/tables/alignment-markers.md"
    content = open(os.path.join(ROOT, rel)).read()
    after, err = apply_op(content, "table-add-row", {
        "table": {"heading": "All four forms"},
        "values": {"Default": "iiiiiiiiiiii", "Left": "j", "Center": "k", "Right": "l"}})
    check("markers: no error", not err, err or "")
    if err:
        return
    delim = find_tables(after)[0].delimiter
    cells = [c.strip() for c in delim.strip().strip("|").split("|")]
    check("alignment markers preserved through a re-pad",
          not cells[0].startswith(":") and not cells[0].endswith(":")
          and cells[1].startswith(":") and not cells[1].endswith(":")
          and cells[2].startswith(":") and cells[2].endswith(":")
          and not cells[3].startswith(":") and cells[3].endswith(":"),
          delim)


def test_crlf_preserved():
    for rel in ("corpus/hazards/crlf.md", "corpus/hazards/mixed-endings.md"):
        path = os.path.join(ROOT, rel)
        content = open(path, newline="").read()
        tables = list_tables(content, rel)
        if not tables:
            continue
        e = tables[0]
        before_p = eol_profile(content)
        after, err = apply_op(content, "table-add-row", {
            "table": {"heading": e["heading"], "ordinal": e["ordinal"]},
            "values": {c: "zz" for c in e["columns"]}})
        if err:
            check(f"crlf {rel}", False, err.replace("\n", " "))
            continue
        got = eol_profile(after)
        crlf_table = find_tables(content)[0].lines[0].endswith("\r")
        want = (before_p[0] + 1, before_p[1]) if crlf_table else (before_p[0], before_p[1] + 1)
        check(f"line endings preserved: {rel}", got == want, f"{before_p} -> {got}, want {want}")


def test_refusals():
    """Ambiguity and misses must refuse, and say something actionable."""
    rel = "corpus/tables/multiple-per-section.md"
    content = open(os.path.join(ROOT, rel)).read()

    try:
        resolve_table(content, {"heading": "Environments"})
        check("ambiguous heading refuses", False, "returned a table")
    except OpError as e:
        check("ambiguous heading refuses", "ordinal" in str(e), str(e)[:80])

    _, err = apply_op(content, "table-update-cell", {
        "table": {"heading": "Environments", "ordinal": 1},
        "where": {"Host": "stage-1", "Region": "us-east-1"},
        "column": "Size", "value": "t3.l"})
    check("over-specified selector refuses", bool(err))
    check("error names the conflicting column", err and "us-west-2" in err, (err or "")[:120])
    check("error suggests a working selector",
          err and '{"Host": "stage-1"}' in err, (err or "")[:200])

    _, err = apply_op(content, "table-add-row", {
        "table": {"heading": "Environments", "ordinal": 1},
        "values": {"Hostname": "x"}})
    check("unknown column refuses with near match",
          err and "Host" in err, (err or "")[:120])

    _, err = apply_op(content, "table-frobnicate", {})
    check("unknown op refuses", err and "unknown operation" in err)


def test_ordered_values():
    """The array row form must be equivalent to the named form, and strict."""
    rel = "corpus/tables/alignment-markers.md"
    content = open(os.path.join(ROOT, rel)).read()
    addr = {"heading": "All four forms"}

    named, e1 = apply_op(content, "table-add-row", {
        "table": addr,
        "values": {"Default": "i", "Left": "j", "Center": "k", "Right": "l"}})
    ordered, e2 = apply_op(content, "table-add-row", {
        "table": addr, "values": ["i", "j", "k", "l"]})
    check("ordered form: no error", not (e1 or e2), (e1 or e2 or ""))
    check("ordered row is byte-identical to the named row", named == ordered)

    viarow, e3 = apply_op(content, "table-add-row", {
        "table": addr, "row": ["i", "j", "k", "l"]})
    check("`row` parameter is equivalent to `values`", not e3 and viarow == named,
          e3 or "")

    # Strictness: a short array must refuse, never pad. Padding silently puts
    # every value in the wrong column and yields a well-formed, wholly wrong row.
    _, err = apply_op(content, "table-add-row", {"table": addr, "row": ["i", "j"]})
    check("short ordered row refuses", bool(err) and "4 columns" in (err or ""),
          (err or "")[:120])

    # Both fields at once: refuse only when they actually disagree. Measured in
    # scheme_d -- the model fills in both, and usually identically.
    _, err = apply_op(content, "table-add-row", {
        "table": addr, "values": {"Default": "i"}, "row": ["i", "j", "k", "l"]})
    check("both fields, disagreeing, refuses", bool(err), (err or "")[:80])

    both, err = apply_op(content, "table-add-row", {
        "table": addr, "row": ["i", "j", "k", "l"],
        "values": {"Default": "i", "Left": "j", "Center": "k", "Right": "l"}})
    check("both fields, agreeing, is accepted", not err and both == named, err or "")

    _, err = apply_op(content, "table-add-row", {"table": addr})
    check("supplying neither refuses", bool(err), (err or "")[:80])

    wrapped_args = {
        "table": addr,
        "values": [{"Default": "i", "Left": "j", "Center": "k", "Right": "l"}],
    }
    before_args = json.loads(json.dumps(wrapped_args))
    wrapped, err = apply_op(content, "table-add-row", wrapped_args)
    check("singleton object array is accepted as a named row",
          not err and wrapped == named, err or "")
    check("singleton object normalization does not mutate its caller",
          wrapped_args == before_args, repr(wrapped_args))

    _, err = apply_op(content, "table-add-row", {
        "table": addr, "values": [{}]})
    check("wrapped empty named row still refuses as empty",
          bool(err) and "a row is required" in err, err or "")

    _, err = apply_op(content, "table-add-row", {
        "table": addr, "values": [{"NoSuchColumn": "x"}]})
    check("wrapped named row still validates column names",
          bool(err) and "no column" in err, err or "")


def test_string_address():
    """A bare heading string must be equivalent to {"heading": ...}."""
    rel = "corpus/tables/alignment-markers.md"
    content = open(os.path.join(ROOT, rel)).read()
    row = ["i", "j", "k", "l"]

    obj, e1 = apply_op(content, "table-add-row",
                       {"table": {"heading": "All four forms"}, "values": row})
    txt, e2 = apply_op(content, "table-add-row",
                       {"table": "All four forms", "values": row})
    check("string address: no error", not (e1 or e2), (e1 or e2 or ""))
    check("string address is byte-identical to the object form", obj == txt)

    # The shorthand must not weaken ambiguity detection: multiple-per-section.md
    # has three tables under one heading, and a bare string cannot disambiguate.
    multi = open(os.path.join(ROOT, "corpus/tables/multiple-per-section.md")).read()
    _, err = apply_op(multi, "table-delete-row",
                      {"table": "Environments", "where": {"Host": "stage-1"}})
    check("string address still refuses when ambiguous",
          bool(err) and "ordinal" in (err or ""), (err or "")[:100])

    _, err = apply_op(content, "table-add-row",
                      {"table": "No Such Heading", "values": row})
    check("string address refuses with near matches", bool(err), (err or "")[:80])


def test_stringified_arguments():
    """JSON-in-a-string must be recovered; a non-JSON string must refuse well.

    All three shapes here were emitted by the model in Arm B (FINDINGS.md B7).
    """
    rel = "corpus/tables/aligned.md"
    content = open(os.path.join(ROOT, rel)).read()
    addr = {"heading": "Components"}

    want, err = apply_op(content, "table-delete-row",
                         {"table": addr, "where": {"Component": "gadget"}})
    check("baseline delete: no error", not err, err or "")
    got, err = apply_op(content, "table-delete-row",
                        {"table": addr, "where": '{"Component": "gadget"}'})
    check("stringified `where` is recovered", not err and got == want, err or "")

    got, err = apply_op(content, "table-add-row",
                        {"table": addr, "values": '["a", "b", "c"]'})
    check("stringified `values` array is recovered", not err, err or "")

    got, err = apply_op(content, "table-add-row", {"table": '"Components"'[1:-1],
                                                   "values": {"Component": "z"}})
    check("plain string address still works", not err, err or "")

    # `{"\"heading\"": ...}` -- quoted key, seen once in scheme_g.
    got, err = apply_op(content, "table-add-row",
                        {"table": {'"heading"': "Components"},
                         "values": {"Component": "z"}})
    ref, _ = apply_op(content, "table-add-row",
                      {"table": addr, "values": {"Component": "z"}})
    check("quoted object key is recovered", not err and got == ref, err or "")

    # Not JSON: refuse, and say what shape was wanted rather than reporting a
    # downstream symptom like `no column "{"`.
    _, err = apply_op(content, "table-add-row",
                      {"table": addr, "values": "a, b, c"})
    check("non-JSON string refuses", bool(err), (err or "")[:80])
    check("refusal names the wanted shape",
          err and ("object" in err or "array" in err), (err or "")[:100])
    check("refusal does not report a downstream symptom",
          err and 'no column' not in err, (err or "")[:100])


# --------------------------------------------------------------------------
# lists
# --------------------------------------------------------------------------

def test_list_goldens():
    """The reference must still produce every golden in bench/tasks/lists.json.

    This is the honesty condition promised in `make_list_tasks.py`. The list
    goldens were generated by this same implementation, so a regression here
    would otherwise be invisible: the executor and the answer key would drift
    together and the benchmark would quietly re-baseline itself to whatever the
    code now does. Asserting it turns that into a test failure.
    """
    from grade import check_result

    tasks = json.load(open(os.path.join(ROOT, "bench/tasks/lists.json")))["tasks"]
    for task in tasks:
        before = open(os.path.join(ROOT, task["fixture"]), newline="").read()
        ic = task["ideal_call"]
        after, err = apply_op(before, ic["op"], ic["args"])
        if err:
            check(f"golden {task['id']}", False, err.replace("\n", " "))
            continue
        outcome, detail = check_result(task, before, after)
        check(f"golden {task['id']}", outcome == "correct", f"{outcome}: {detail}")


def test_list_roundtrip():
    """Add then remove must restore the file byte-for-byte, for every list.

    The list counterpart of `test_corpus_roundtrip`, and the same bet: one
    assertion over the whole corpus catches lost indentation, a marker rewritten
    to house style, a loose list gone tight, a dropped final newline and a
    botched renumber, without anyone having to enumerate them.

    Ordered lists are the interesting case. Adding to `1. 3. 7.` renumbers
    nothing, adding to `1. 2. 3.` renumbers from the insertion point, and both
    must undo exactly.
    """
    checked, skipped = 0, 0
    probe = "zzq-roundtrip-probe"
    for path in corpus_files():
        content = open(path, newline="").read()
        rel = os.path.relpath(path, ROOT)
        for e in list_lists(content, rel):
            addr = {"heading": e["heading"], "ordinal": e["ordinal"]}
            tag = f"{rel} [{e['heading']}#{e['ordinal']}]"
            added, err = apply_op(content, "list-add-item",
                                  {"list": addr, "text": probe})
            if err:
                check(f"add {tag}", False, err.replace("\n", " "))
                continue
            back, err = apply_op(added, "list-remove-item",
                                 {"list": addr, "item": probe})
            if err:
                check(f"remove {tag}", False, err.replace("\n", " "))
                continue
            checked += 1
            if back != content:
                check(f"roundtrip {tag}", False,
                      f"eol {eol_profile(content)} -> {eol_profile(back)}")
    check(f"list add+remove round-trips byte-identical ({checked} lists)",
          checked > 0, f"{skipped} skipped")


def test_numbering_styles():
    """Three numbering styles, three different correct behaviours.

    A rule that always renumbers and a rule that never renumbers are both wrong,
    which is why this is asserted rather than left to the benchmark: `1. 2. 3.`
    must renumber on a mid-list insert, `1. 1. 1.` must not (it is legal
    CommonMark and renumbering is the bug), and `1. 3. 7.` must not (renumbering
    survivors of a removal is a behaviour change nobody asked for).
    """
    rel = "corpus/lists/ordered-numbering.md"
    content = open(os.path.join(ROOT, rel)).read()

    seq, err = apply_op(content, "list-add-item", {
        "list": {"heading": "Sequential"}, "text": "two and a half",
        "after": "second"})
    check("sequential: no error", not err, err or "")
    if not err:
        markers = [it.marker for it in find_lists(seq)[0].items]
        check("sequential list renumbers after a mid-list insert",
              markers == ["1.", "2.", "3.", "4.", "5."], str(markers))

    ones, err = apply_op(content, "list-add-item", {
        "list": {"heading": "All ones"}, "text": "fourth"})
    check("all-ones: no error", not err, err or "")
    if not err:
        markers = [it.marker for it in find_lists(ones)[1].items]
        check("all-ones list is not renumbered",
              markers == ["1.", "1.", "1.", "1."], str(markers))

    irr, err = apply_op(content, "list-remove-item", {
        "list": {"heading": "Non-sequential"}, "item": "third"})
    check("non-sequential: no error", not err, err or "")
    if not err:
        markers = [it.marker for it in find_lists(irr)[4].items]
        check("irregular numbering survives a removal untouched",
              markers == ["1.", "7."], str(markers))

    paren, err = apply_op(content, "list-add-item", {
        "list": {"heading": "Paren delimiter"}, "text": "fourth"})
    check("paren: no error", not err, err or "")
    if not err:
        markers = [it.marker for it in find_lists(paren)[2].items]
        check("`)` delimiter is preserved on an added item",
              markers == ["1)", "2)", "3)", "4)"], str(markers))

    start, err = apply_op(content, "list-add-item", {
        "list": {"heading": "Non-one start"}, "text": "eighth"})
    check("non-one start: no error", not err, err or "")
    if not err:
        markers = [it.marker for it in find_lists(start)[3].items]
        check("a list starting at 5 continues at 8, not 4",
              markers == ["5.", "6.", "7.", "8."], str(markers))


def test_marker_and_indent_inference():
    """A new item copies the conventions of the sibling it joins.

    Marker character and indent width are per-list, not house style. The `after`
    form is what makes nesting expressible without a `depth` argument, so it has
    to take the indent of the item it follows and not of the list.
    """
    rel = "corpus/lists/nested-mixed.md"
    content = open(os.path.join(ROOT, rel)).read()

    nested, err = apply_op(content, "list-add-item", {
        "list": {"heading": "Asterisk markers, four-space indent"},
        "text": "beta-three", "after": "beta-two"})
    check("nested add: no error", not err, err or "")
    if not err:
        check("new item takes the sibling's `*` marker and four-space indent",
              "    * beta-three" in nested.split("\n"),
              str([l for l in nested.split("\n") if "beta-three" in l]))

    plus, err = apply_op(content, "list-add-item", {
        "list": {"heading": "Plus markers"}, "text": "third"})
    check("plus add: no error", not err, err or "")
    if not err:
        check("`+` marker is not normalized to `-`",
              "+ third" in plus.split("\n"),
              str([l for l in plus.split("\n") if "third" in l]))

    # "at the end" means after the last TOP-LEVEL item, not after the last line
    # of the list -- which here is three levels deep.
    tight, err = apply_op(content, "list-add-item", {
        "list": {"heading": "Dash markers, two-space indent"}, "text": "fourth"})
    check("tight add: no error", not err, err or "")
    if not err:
        check("end-of-list add lands at top level, not inside the last subtree",
              "- fourth" in tight.split("\n"),
              str([l for l in tight.split("\n") if "fourth" in l]))


def test_loose_list_spacing():
    """Inserting into a loose list must keep it loose.

    Loose vs tight is a property of the whole list: one missing blank line
    changes how *every* item renders, which is the kind of collateral damage
    this project exists to prevent. `Loose vs tight` ordinal 1 is the loose one.
    """
    rel = "corpus/lists/nested-mixed.md"
    content = open(os.path.join(ROOT, rel)).read()
    addr = {"heading": "Loose vs tight", "ordinal": 1}

    after, err = apply_op(content, "list-add-item", {"list": addr, "text": "loose four"})
    check("loose add: no error", not err, err or "")
    if err:
        return
    lst = [l for l in find_lists(after)
           if any(it.text == "loose four" for it in l.items)]
    check("the added item landed in the loose list", len(lst) == 1)
    if lst:
        check("list is still loose after the insert", lst[0].loose)
        lines = after.split("\n")
        i = lines.index("- loose four")
        check("added item is preceded by a blank line", not lines[i - 1].strip(),
              repr(lines[i - 1]))

    tight_addr = {"heading": "Loose vs tight", "ordinal": 0}
    after, err = apply_op(content, "list-add-item",
                          {"list": tight_addr, "text": "tight three"})
    check("tight add: no error", not err, err or "")
    if not err:
        lines = after.split("\n")
        i = lines.index("- tight three")
        check("a tight list is not loosened", bool(lines[i - 1].strip()),
              repr(lines[i - 1]))


def test_checkbox_handling():
    """Checkbox state changes; checkbox spelling does not.

    `[X]` and `[x]` both mean done and the corpus contains both. Normalizing one
    to the other is a diff the user did not ask for, so an untouched item must
    come back byte-identical even when a sibling is toggled.
    """
    rel = "corpus/lists/tasks.md"
    content = open(os.path.join(ROOT, rel)).read()

    after, err = apply_op(content, "list-set-checked", {
        "list": {"heading": "Nested"}, "item": "child pending", "checked": True})
    check("set-checked: no error", not err, err or "")
    if not err:
        check("nested indent survives a toggle",
              "  - [x] child pending" in after.split("\n"),
              str([l for l in after.split("\n") if "child pending" in l]))
        b, a = content.split("\n"), after.split("\n")
        differing = [i for i in range(min(len(a), len(b))) if a[i] != b[i]]
        check("exactly one line changed", len(differing) == 1 and len(a) == len(b),
              str(differing))
        check("`[X]` elsewhere in the file is not normalized",
              content.count("[X]") == after.count("[X]"))

    # Toggling off and on again must be a no-op at the byte level.
    off, err1 = apply_op(content, "list-set-checked", {
        "list": {"heading": "Flat"}, "item": "checked item", "checked": False})
    if err1:
        check("untick: no error", False, err1.replace("\n", " "))
    else:
        back, err2 = apply_op(off, "list-set-checked", {
            "list": {"heading": "Flat"}, "item": "checked item", "checked": True})
        check("untick+retick is byte-identical", not err2 and back == content,
              err2 or "differs")

    # The near-miss forms are not task items and must not acquire a checkbox.
    _, err = apply_op(content, "list-set-checked", {
        "list": {"heading": "Near misses"}, "item": "not a checkbox", "checked": True})
    check("a non-task item refuses set-checked", bool(err), (err or "")[:100])


def test_list_refusals():
    """Ambiguity and misses refuse with something actionable, as tables do."""
    rel = "corpus/lists/nested-mixed.md"
    content = open(os.path.join(ROOT, rel)).read()

    try:
        resolve_list(content, {"heading": "Mixed markers at the same level"})
        check("ambiguous list heading refuses", False, "returned a list")
    except OpError as e:
        check("ambiguous list heading refuses", "ordinal" in str(e), str(e)[:80])

    _, err = apply_op(content, "list-remove-item", {
        "list": {"heading": "Plus markers"}, "item": "no such item"})
    check("unknown item refuses", bool(err), (err or "")[:100])
    check("unknown-item error names candidates",
          err and "one" in err and "two" in err, (err or "")[:160])

    _, err = apply_op(content, "list-add-item", {
        "list": {"heading": "No Such Heading"}, "text": "x"})
    check("unknown list heading refuses", bool(err), (err or "")[:80])

    # A bare string address must work here too, or the two families teach the
    # model two different addressing habits.
    obj, e1 = apply_op(content, "list-add-item",
                       {"list": {"heading": "Plus markers"}, "text": "third"})
    txt, e2 = apply_op(content, "list-add-item",
                       {"list": "Plus markers", "text": "third"})
    check("bare-string list address is byte-identical to the object form",
          not (e1 or e2) and obj == txt, (e1 or e2 or "differs"))


def test_list_address_fields_are_checked():
    """`list.heading` and `list.ordinal` get the table family's checks.

    They did not until the Rust port. `resolve_list` read both fields raw, so an
    ill-typed `heading` fell through to `.strip()` and came back from
    `apply_op`'s backstop as `AttributeError: 'int' object has no attribute
    'strip'` -- a stack-trace fragment where 5.3 requires a repair -- and
    `ordinal: "0"` failed to match where the table family coerces it.

    Neither shape occurs anywhere in the 5674 recorded calls, which is why every
    suite was green and silent about it. Found by reading `_locate_table` beside
    `resolve_list`, not by testing; the corpus cannot contain an argument a model
    never sent.
    """
    content = open(os.path.join(ROOT, "corpus/lists/nested-mixed.md")).read()

    _, err = apply_op(content, "list-add-item",
                      {"list": {"heading": 7}, "text": "x"})
    check("an ill-typed list.heading is repaired, not a traceback",
          err is not None and err.startswith("`list.heading` must be a string"),
          (err or "")[:120])

    _, err = apply_op(content, "list-add-item",
                      {"list": {"heading": "Plus markers", "ordinal": 1.5},
                       "text": "x"})
    check("an ill-typed list.ordinal is repaired",
          err is not None and err.startswith("`list.ordinal` must be a whole number"),
          (err or "")[:120])
    # The remedy line names lists, not tables. The message is shared with the
    # table family and said "tables" for every caller until this one existed.
    check("the ordinal remedy names the family it is talking about",
          err is not None and "Ordinals count lists under the same heading" in err,
          (err or "")[:160])

    # `"0"` and `0` are the same ordinal, as they are for tables.
    a, e1 = apply_op(content, "list-add-item",
                     {"list": {"heading": "Plus markers", "ordinal": 0}, "text": "z"})
    b, e2 = apply_op(content, "list-add-item",
                     {"list": {"heading": "Plus markers", "ordinal": "0"}, "text": "z"})
    check("a numeric-string list ordinal coerces", not (e1 or e2) and a == b,
          (e1 or e2 or "differs"))


# --------------------------------------------------------------------------
# sections
# --------------------------------------------------------------------------

def test_heading_identity():
    """Every heading in the corpus rebuilds byte-identically from its fields.

    The precondition for `section-rename` being safe. A rename writes the
    heading line back through `Section.rebuild`, so anything `rebuild` cannot
    reproduce unchanged is something a rename would silently destroy: setext
    underlines, closed ATX hashes, the odd `###    ` run of spaces in
    `setext-and-atx.md`, three-space indents, and CRLF endings.
    """
    n = bad = 0
    for path in corpus_files():
        content = open(path, newline="").read()
        lines = content.split("\n")
        for sec in find_sections(content):
            n += 1
            if sec.rebuild() != lines[sec.start:sec.heading_end + 1]:
                bad += 1
                check(f"identity {os.path.relpath(path, ROOT)} {sec.text!r}",
                      False, f"{sec.rebuild()} != {lines[sec.start:sec.heading_end+1]}")
    check(f"every heading rebuilds byte-identically ({n} headings)",
          bad == 0 and n > 200)


def test_fence_scanners_agree():
    """One fence scanner, and it holds the closing-fence rule.

    This test used to check that `mdsection.fence_mask` agreed with a second
    copy of the logic inside `find_lists`, over the corpus. It carried an honest
    limit: `fence_mask` is the stricter of the two, no corpus file distinguishes
    them on that point, so a divergence there would go unseen. That is exactly
    where they diverged -- the Rust port's differential test supplied the input
    the corpus lacked, and ``` with trailing words closed a block in one scanner
    and not the other (FINDINGS F-fence).

    So the duplicate is gone and the test asks a different question. `is` is the
    first assertion because a corpus-wide agreement check on one function is
    vacuous; what can still regress is someone re-introducing a copy. The rest
    pins the rule the copies disagreed about, on inputs written for it rather
    than found.
    """
    check("both parsers use the same fence scanner",
          fence_mask is mdlist.fence_mask)

    cases = [
        # An info string opens a block; it can never close one. This is the
        # line that drifted.
        (["```", "code", "``` trailing words", "after"],
         [True, True, True, True]),
        (["```", "code", "```", "after"], [True, True, True, False]),
        # Trailing whitespace is not content, so this one does close.
        (["```", "code", "```   ", "after"], [True, True, True, False]),
        # Run length: a three-backtick fence cannot close a four-backtick one.
        (["````md", "```", "x", "```", "````", "after"],
         [True, True, True, True, True, False]),
        # A longer closing run is allowed.
        (["```", "x", "`````", "after"], [True, True, True, False]),
        # Tildes and backticks are different fences and do not close each other.
        (["~~~", "```", "~~~", "after"], [True, True, True, False]),
        # An unclosed fence runs to end of document (`mdsection` docstring).
        (["```", "x", "y"], [True, True, True]),
        # Indentation is allowed on both ends.
        (["  ```", "x", "  ```", "after"], [True, True, True, False]),
    ]
    for lines, want in cases:
        got = fence_mask(lines)
        check(f"fence_mask {lines!r}", got == want, f"got {got}, want {want}")


def test_frontmatter_is_not_content():
    """A YAML comment is not a heading and a YAML sequence is not a list.

    `corpus/frontmatter/rich.md` opens with `# Build configuration for the
    example project` and a `tags:` block sequence. Before `mdsection` existed
    both parsers were fooled, and `render_list_summary` offered the model two
    lists that were really document metadata. No task used that fixture, so no
    measured result moved -- but the next family's might have.
    """
    content = open(os.path.join(ROOT, "corpus/frontmatter/rich.md"),
                   newline="").read()
    texts = [s.text for s in find_sections(content)]
    check("YAML comment is not a heading",
          "Build configuration for the example project" not in texts, texts)
    check("real headings still found", "Rich frontmatter" in texts, texts)
    check("YAML sequences are not lists", len(find_lists(content)) == 1,
          f"{len(find_lists(content))} lists")
    reasons = {h["reason"] for h in inert_headings(content)}
    check("the YAML comment is reported as inert, not dropped",
          "frontmatter" in reasons, reasons)


def test_link_reference_footer():
    """A trailing link-reference block belongs to the document, not a section.

    `documents/changelog.md` ends with six `[1.4.2]: https://...` definitions.
    By CommonMark they are inside the last section, `[1.2.0] > Security`,
    because nothing follows them -- so "delete the 1.2.0 release" deleted every
    link definition in the file, including the ones for releases that were still
    there. Structurally correct and silent data loss, which is the exact pairing
    this project exists to eliminate.

    The rule is narrow on purpose (`mdsection._footer_start`), so this pins both
    halves: that it fires where it should, and that it does not fire anywhere
    else in the corpus.
    """
    rel = "corpus/documents/changelog.md"
    content = open(os.path.join(ROOT, rel)).read()
    refs = [ln for ln in content.split("\n") if LINKREF_RE.match(ln)]
    check("fixture still has the link-reference block", len(refs) == 6, len(refs))

    last = find_sections(content)[-1]
    body = content.split("\n")[last.start: last.end + 1]
    check("the last section stops before the footer",
          not any(LINKREF_RE.match(ln) for ln in body), body[-1])

    out, err = apply_op(content, "section-delete",
                        {"section": "[1.2.0] - 2026-04-01", "subtree": True})
    check("and does delete the release",
          not err and "## [1.2.0] - 2026-04-01" not in out, err)
    # Including `[1.2.0]:` itself, now unreferenced. Cleaning that up would mean
    # guessing at what else in the file might still want it; the op deletes the
    # section it was asked to delete and nothing else.
    check("deleting the oldest release keeps every link definition",
          not err and all(ln in out for ln in refs), err)

    # The narrowness half. Every other corpus file must be unaffected, which is
    # checkable without naming them: a footer is only recognised when the last
    # non-blank line is a link reference definition.
    fired = []
    for path in corpus_files():
        lines = open(path, newline="").read().split("\n")
        if _footer_start(lines, fence_mask(lines)) < len(lines):
            fired.append(os.path.relpath(path, ROOT))
    check("the footer rule fires on exactly the files that have one",
          fired == [rel], fired)


def test_destructive_action_guards():
    """The two S2/S3 guards, pinned in both directions.

    Both exist because of measured failures, not anticipated ones, so both are
    tested for what they refuse *and* for what they must still allow. A guard
    that only ever refuses would score well on the tasks that motivated it and
    break the task that says the destructive action is sometimes correct.

    S2 -- `replace-body` discards a section's text. In five trials of ten the
    model reached for it when asked to *add* a line, and the body was gone.
    S3 -- `append` cannot create a section, but in five trials the model called
    it with a heading and a position and got prose where a section belonged.
    """
    deep = open(os.path.join(ROOT, "corpus/sections/deep-nesting.md")).read()
    changelog = open(os.path.join(ROOT, "corpus/documents/changelog.md")).read()

    # --- S2 ---------------------------------------------------------------
    _, err = apply_op(deep, "section-replace-body",
                      {"section": "Install", "text": "new"})
    check("replacing a non-empty body refuses without acknowledgement",
          err and "overwrite=true" in err and "action=append" in err, err)
    out, err = apply_op(deep, "section-replace-body",
                        {"section": "Install", "text": "new",
                         "overwrite": True})
    check("and goes through with it",
          not err and "Preamble text belonging to Install" not in out
          and "### macOS" in out, err)
    out, err = apply_op(changelog, "section-replace-body",
                        {"section": "[1.4.2] - 2026-08-14", "text": "new"})
    check("an empty body needs no acknowledgement -- nothing to lose",
          not err and "### Fixed" in out, err)
    out2, _ = apply_op(changelog, "section-append",
                       {"section": "[1.4.2] - 2026-08-14", "text": "new"})
    check("and there it is identical to append", out == out2)

    # --- S3 ---------------------------------------------------------------
    _, err = apply_op(deep, "section-append",
                      {"section": "Install", "heading": "FreeBSD",
                       "body": "Use pkg.", "position": "after"})
    check("append refuses a heading and names the action that takes one",
          err and "position=last-child" in err and "action=insert" in err, err)
    _, err = apply_op(deep, "section-append",
                      {"section": "Install", "new_heading": "FreeBSD",
                       "text": "Use pkg."})
    check("under either spelling of the payload",
          err and "action=insert" in err, err)
    out, err = apply_op(deep, "section-append",
                        {"section": "Install", "body": "Use pkg."})
    check("but `body` alone is still prose, not a section",
          not err and "Use pkg." in out, err)
    _, err = apply_op(deep, "section-replace-body",
                      {"section": "Install", "text": "x", "overwrite": True,
                       "heading": "Renamed"})
    check("replace-body refuses a heading too, and points at rename",
          err and "action=rename" in err, err)

    # --- the payload's own whitespace is not an instruction ----------------
    # Four trials in the fix arm wrapped their prose in newlines, supplying by
    # hand the separator the op already inserts. Both ends are stripped, so all
    # four spellings produce the same document.
    base, err = apply_op(deep, "section-append",
                         {"section": "Install > macOS", "text": "Note."})
    check("a payload with no padding appends cleanly", not err, err)
    for spelling in ("\nNote.", "Note.\n", "\n\nNote.\n\n", "  \nNote.\n  "):
        out, err = apply_op(deep, "section-append",
                            {"section": "Install > macOS", "text": spelling})
        check(f"and {spelling!r} produces the identical document",
              not err and out == base, err)
    _, err = apply_op(deep, "section-append",
                      {"section": "Install > macOS", "text": "\n\n  \n"})
    check("but padding alone is still an empty payload",
          err and "must not be empty" in err, err)

    # --- the echo exception -----------------------------------------------
    # Six trials in the first re-grade passed the addressed section's own name
    # back in the heading field. That asks for no rename, so it is not S2 or S3
    # and must not be refused. Both spellings of the address are accepted,
    # because a model that reads the outline sees the full path.
    out, err = apply_op(changelog, "section-replace-body",
                        {"section": "[1.4.2] - 2026-08-14", "text": "new",
                         "heading": "[1.4.2] - 2026-08-14"})
    check("echoing the section's own name back is not a rename request",
          not err and "## [1.4.2] - 2026-08-14" in out and "new" in out, err)
    out2, err = apply_op(changelog, "section-append",
                         {"section": "[1.4.2] - 2026-08-14", "text": "new",
                          "heading": "Changelog > [1.4.2] - 2026-08-14"})
    check("under the full path too, and on append as well", out == out2, err)
    _, err = apply_op(changelog, "section-append",
                      {"section": "[1.4.2] - 2026-08-14", "text": "new",
                       "heading": "[1.4.2] - 2026-08-15"})
    check("but one character off is a different heading, and refuses",
          err and "action=insert" in err, err)


def test_section_goldens():
    """The reference must still produce every golden in tasks/sections.json.

    The honesty condition promised in `make_section_tasks.py`, and the same one
    `test_list_goldens` enforces for lists: the goldens were generated by this
    implementation, so without this the executor and the answer key would drift
    together and the benchmark would quietly re-baseline itself to whatever the
    code now does.

    Stricter than its list counterpart, because the section goldens pin the
    whole document. A stray blank line anywhere in `api-reference.md` fails
    here; in the list family it would fall outside the scoped region.
    """
    from grade import check_result

    path = os.path.join(ROOT, "bench/tasks/sections.json")
    tasks = json.load(open(path))["tasks"]
    for task in tasks:
        before = open(os.path.join(ROOT, task["fixture"]), newline="").read()
        # `ideal_calls` is a sequence: S6 made "a new section with a subsection
        # in it" two calls, because the one-call form wrote a raw `### Added`
        # into `body` and the executor now refuses that. The golden document
        # did not change, so this test still pins the same bytes.
        after, err = before, None
        for i, ic in enumerate(task["ideal_calls"]):
            args = dict(ic["args"])
            if ic["op"] == "section-delete":
                args["subtree"] = True
            after, err = apply_op(after, ic["op"], args)
            if err:
                err = f"call {i + 1}: {err}"
                break
        if err:
            check(f"golden {task['id']}", False, err.replace("\n", " "))
            continue
        outcome, detail = check_result(task, before, after)
        check(f"golden {task['id']}", outcome == "correct", f"{outcome}: {detail}")
    check(f"all {len(tasks)} section goldens reproduce", len(tasks) == 15,
          len(tasks))


def test_section_grader():
    """The section grader must separate the outcome classes it claims to.

    A grader that returns `correct` for the reference and something-not-correct
    for everything else is not yet evidence: the headline number is a breakdown
    by class, so each class has to be reachable. These are hand-built wrong
    answers to `delete-install-macos`, one per rung of the ladder.
    """
    from grade import check_result

    tasks = {t["id"]: t for t in
             json.load(open(os.path.join(ROOT, "bench/tasks/sections.json")))["tasks"]}
    task = tasks["delete-install-macos"]
    before = open(os.path.join(ROOT, task["fixture"]), newline="").read()

    # The edit not made at all.
    check("grader: unchanged file is not correct",
          check_result(task, before, before)[0] == "wrong",
          check_result(task, before, before))

    # Deleted the right section, then also lost one nobody asked about.
    over, err = apply_op(before, "section-delete",
                         {"section": "Install > macOS", "subtree": True})
    over, err2 = apply_op(over, "section-delete",
                          {"section": "Uninstall", "subtree": True})
    check("grader: an extra deletion grades destructive",
          not err and not err2
          and check_result(task, before, over)[0] == "destructive",
          err or err2 or check_result(task, before, over))

    # Deleted only the heading and its paragraph, orphaning the subsections --
    # the exact near-miss the task exists to catch.
    b = before.split("\n")
    partial = "\n".join(b[:10] + b[14:])
    check("grader: orphaned subsections grade wrong",
          check_result(task, before, partial)[0] == "wrong",
          check_result(task, before, partial))

    # The right deletion plus a blank line left behind.
    good, _ = apply_op(before, "section-delete",
                       {"section": "Install > macOS", "subtree": True})
    g = good.split("\n")
    loose = "\n".join(g[:10] + [""] + g[10:])
    check("grader: a stray blank line grades collateral:formatting",
          check_result(task, before, loose)[0] == "collateral:formatting",
          check_result(task, before, loose))

    check("grader: the reference answer grades correct",
          check_result(task, before, good)[0] == "correct",
          check_result(task, before, good))

    # A paragraph break lost *outside* the golden window. The Arm A sections run
    # produced ten of these on one task, and the window rungs called them
    # `collateral:content` -- an assertion that content changed, when the
    # document's visible text is byte-for-byte the golden's. Formatting damage
    # is still corruption; it is just not content damage.
    ordinal = tasks["notes-second-ordinal"]
    src = open(os.path.join(ROOT, ordinal["fixture"]), newline="").read()
    ref, err = apply_op(src, "section-append",
                        {"section": {"path": "Notes", "ordinal": 1},
                         "text": "Superseded."})
    check("grader: the reference answer grades correct (ordinal task)",
          not err and check_result(ordinal, src, ref)[0] == "correct", err)
    joined = src.replace(
        "Second Notes section, same level, same parent, identical text.",
        "Second Notes section, same level, same parent, identical text.\n"
        "Superseded.")
    outcome, detail = check_result(ordinal, src, joined)
    check("grader: a lost paragraph break is formatting, not content",
          outcome == "collateral:formatting", (outcome, detail))
    # ...and the distinction has to hold in the other direction, or the new rung
    # is just a blanket amnesty for everything outside the window. Added text,
    # not altered text -- altering an existing line trips the destructive rung
    # long before this one, so it would not test what it looks like it tests.
    r = ref.split("\n")
    at = r.index("First Notes section.") + 1
    noise = "\n".join(r[:at] + ["", "Hm."] + r[at:])
    outcome, detail = check_result(ordinal, src, noise)
    check("grader: real text added outside the window is still content",
          outcome == "collateral:content", (outcome, detail))


def test_section_roundtrip():
    """Insert a section then delete it: byte-identical, for every section.

    The strongest invariant available for this family and the direct analogue of
    the table add+delete and list add+remove round-trips. It catches lost CRLF,
    doubled or dropped blank lines between sections, a delete that takes the
    wrong span, and an insert that lands inside the anchor's subtree instead of
    after it -- in one assertion, across the whole corpus.
    """
    checked = 0
    for path in corpus_files():
        content = open(path, newline="").read()
        rel = os.path.relpath(path, ROOT)
        for sec in find_sections(content):
            if not sec.slug or sec.level >= 6:
                continue
            for position in ("before", "after", "last-child"):
                addr = {"path": sec.slug, "ordinal": 0}
                added, err = apply_op(content, "section-insert", {
                    "section": addr, "position": position,
                    "heading": "Zzq Probe", "body": "probe body"})
                if err:
                    # Three designed refusals, all of them properties of the
                    # anchor rather than of the round trip. Tolerated by name so
                    # that a new failure mode cannot hide behind them:
                    #   ambiguous  -- ordinal 0 only resolves a unique path
                    #   mixes CRLF -- `mixed-endings.md`, no convention to match
                    #   refusing   -- the insertion point is inside an unclosed
                    #                 fence, so the new section would not exist
                    if any(k in err for k in
                           ("ambiguous", "ordinal", "mixes CRLF",
                            "refusing to insert")):
                        continue
                    check(f"insert {rel} [{sec.slug}] {position}", False,
                          err.replace("\n", " "))
                    continue
                back, err2 = apply_op(added, "section-delete",
                                      {"section": "Zzq Probe"})
                if err2:
                    check(f"delete probe {rel} [{sec.slug}] {position}", False,
                          err2.replace("\n", " "))
                    continue
                checked += 1
                if back != content:
                    check(f"roundtrip {rel} [{sec.slug}] {position}", False,
                          f"eol {eol_profile(content)} -> {eol_profile(back)}; "
                          f"len {len(content)} -> {len(back)}")
    check(f"insert+delete round-trips byte-identical ({checked} probes)",
          checked > 100)


def test_section_spans():
    """`own_end` stops at the next heading; `end` covers the subtree.

    The pair is what separates "append to this section" from "delete this
    section", and getting `end` wrong by one heading silently orphans or eats a
    subtree. `## Install` in `deep-nesting.md` is the case with the most to
    lose: two lines of its own, thirty-one including its six subsections.
    """
    content = open(os.path.join(ROOT, "corpus/sections/deep-nesting.md")).read()
    secs = {s.text: s for s in find_sections(content)}
    install = secs["Install"]
    check("own body stops before the first subsection",
          install.own_end == 8, install.own_end)
    check("subtree end stops before the next same-level heading",
          install.end == 36, install.end)

    # Appending goes to the own body, so it lands above `### macOS`.
    out, err = apply_op(content, "section-append",
                        {"section": "Install", "text": "Extra preamble."})
    check("append to a parent lands in its own body, not after its subtree",
          not err and out.split("\n")[10] == "Extra preamble."
          and out.split("\n")[12].startswith("### macOS"),
          err or out.split("\n")[9:13])

    # Deleting takes the subtree with it.
    out, err = apply_op(content, "section-delete",
                        {"section": "Install", "subtree": True})
    left = [s.text for s in find_sections(out)] if not err else []
    for gone in ("Apple Silicon", "Intel", "Debian", "Fedora", "Windows"):
        check(f"delete removes subtree member {gone!r}", gone not in left)
    check("delete leaves the siblings alone",
          "Upgrade" in left and "Uninstall" in left, left)


def test_heading_syntax_preserved():
    """A rename must not change how the heading is written.

    Three syntaxes address identically and must stay distinct on disk
    (`corpus/sections/setext-and-atx.md`). This is §5.2's byte-preservation rule
    applied to headings: incise is not a formatter, so it never converts setext
    to ATX or drops decoration it did not add.
    """
    path = os.path.join(ROOT, "corpus/sections/setext-and-atx.md")
    content = open(path).read()

    out, err = apply_op(content, "section-rename",
                        {"section": "Setext H2", "heading": "Renamed H2"})
    lines = out.split("\n") if not err else []
    check("setext stays setext", not err and lines[7] == "Renamed H2"
          and set(lines[8]) == {"-"}, err or lines[7:9])
    check("setext underline is re-run to the new width",
          not err and len(lines[8]) == len("Renamed H2"), err or lines[8])

    out, err = apply_op(content, "section-rename",
                        {"section": "Closed ATX level 3", "heading": "Renamed"})
    check("closed ATX keeps its trailing hashes",
          not err and "### Renamed ###" in out, err)

    out, err = apply_op(content, "section-rename",
                        {"section": "Indented three spaces", "heading": "Still indented"})
    check("three-space indent survives a rename",
          not err and "   ### Still indented" in out, err)

    # A model that quotes the whole line rather than naming the text is
    # tolerated, but the level it quoted is ignored -- set-level owns that.
    out, err = apply_op(content, "section-rename",
                        {"section": "ATX level 3", "heading": "###### Loud"})
    check("a quoted marker in `heading` does not change the level",
          not err and "### Loud" in out and "###### Loud" not in out, err)

    back, err = apply_op(out, "section-rename",
                         {"section": "Loud", "heading": "ATX level 3"})
    check("rename round-trips byte-identically", not err and back == content, err)


def test_section_level_changes():
    """Promote/demote, and the two refusals that have no earlier analogue."""
    content = open(os.path.join(ROOT, "corpus/sections/deep-nesting.md")).read()

    out, err = apply_op(content, "section-set-level",
                        {"section": "Upgrade", "level": 3})
    levels = {s.text: s.level for s in find_sections(out)} if not err else {}
    check("subtree moves with the heading by default",
          not err and levels.get("Upgrade") == 3 and levels.get("Linux") == 4,
          err or levels)
    back, err = apply_op(out, "section-set-level",
                         {"section": "Upgrade", "level": 2})
    check("promote/demote round-trips byte-identically",
          not err and back == content, err)

    out, err = apply_op(content, "section-set-level",
                        {"section": "Upgrade", "level": 3, "subtree": False})
    levels = [(s.text, s.level) for s in find_sections(out)] if not err else []
    check("subtree=false moves only the heading",
          not err and ("Upgrade", 3) in levels and ("Linux", 3) in levels,
          err or levels)

    _, err = apply_op(content, "section-set-level",
                      {"section": "Install", "level": 6})
    check("refuses when the subtree would exceed level 6",
          err and "level 7" in err, err)

    setext = open(os.path.join(ROOT, "corpus/sections/setext-and-atx.md")).read()
    _, err = apply_op(setext, "section-set-level",
                      {"section": "Setext H2", "level": 3})
    check("refuses to rewrite a setext heading as ATX",
          err and "setext" in err.lower(), err)
    out, err = apply_op(setext, "section-set-level",
                        {"section": "Setext H2", "level": 1})
    check("setext H2 -> H1 stays setext, underline char changes",
          not err and out.split("\n")[8] == "=" * len("Setext H2"),
          err or out.split("\n")[8])


def test_section_refusals():
    """Every refusal names what to do instead, and inert is not 'not found'."""
    dup = open(os.path.join(ROOT, "corpus/sections/duplicate-siblings.md")).read()
    deep = open(os.path.join(ROOT, "corpus/sections/deep-nesting.md")).read()
    fences = open(os.path.join(ROOT, "corpus/hazards/code-fences.md")).read()
    quoted = open(os.path.join(ROOT, "corpus/hazards/nested-blocks.md")).read()

    _, err = apply_op(deep, "section-append", {"section": "macOS", "text": "x"})
    check("a repeated leaf name refuses with full paths, not ordinals",
          err and "Install > macOS" in err and "Upgrade > macOS" in err
          and "ordinal" not in err, err)

    _, err = apply_op(dup, "section-append", {"section": "Notes", "text": "x"})
    check("genuinely identical siblings refuse with ordinals",
          err and "ordinal 0" in err and "ordinal 2" in err, err)
    out, err = apply_op(dup, "section-append",
                        {"section": {"path": "Notes", "ordinal": 1}, "text": "x"})
    check("an ordinal resolves identical siblings",
          not err and "Second Notes section, same level" in out
          and out.count("\nx") == 1, err)

    _, err = apply_op(fences, "section-append",
                      {"section": "Not a real heading", "text": "x"})
    check("a heading inside a fence refuses as inert, not absent",
          err and "fenced code block" in err and "no section at path" not in err,
          err)
    _, err = apply_op(fences, "section-append",
                      {"section": "Trailing heading inside an unclosed fence",
                       "text": "x"})
    check("an unclosed fence runs to end of document",
          err and "fenced code block" in err, err)
    # The converse, and the more dangerous half: the heading is not there yet,
    # so nothing refuses it on the way in. Only re-parsing the *output* shows
    # that the file would change and no section would exist. Without this the
    # op reports success and lies.
    out, err = apply_op(fences, "section-insert",
                        {"section": "Unclosed fence", "position": "after",
                         "heading": "New Section", "body": "x"})
    check("refuses to insert where the new heading would be inside a fence",
          err and "refusing to insert" in err and "never closed" in err
          and out is None, err)
    _, err = apply_op(quoted, "section-append",
                      {"section": "Quoted heading", "text": "x"})
    check("a heading inside a blockquote refuses as inert",
          err and "blockquote" in err, err)

    # `duplicate-siblings.md` says explicitly that whether the three `Setup`
    # variants count as duplicates "is a decision the implementation must make
    # explicitly." It is made here, and it is two decisions, not one:
    # trailing whitespace is not part of a heading (CommonMark strips it, so
    # `### Setup` and `### Setup ` are the same address and need ordinals), and
    # case IS part of it (`setup` is a different heading, addressable on its
    # own). Case-folding is offered as a fallback pass in `resolve_section`, so
    # a model that writes the wrong case still lands -- but only when that is
    # unambiguous, which here it is not.
    from incise_ops import section_outline
    by_path = {e["path"]: e for e in section_outline(dup)}
    base = "Duplicate sibling headings > Trailing whitespace variants > "
    check("trailing whitespace does not make a distinct heading",
          by_path[base + "Setup"]["unique"] is False)
    check("case does make a distinct heading",
          by_path[base + "setup"]["unique"] is True)
    _, err = apply_op(dup, "section-append",
                      {"section": "Trailing whitespace variants > setup",
                       "text": "x"})
    check("the lowercase variant is addressable without an ordinal", not err, err)
    _, err = apply_op(dup, "section-append",
                      {"section": "Trailing whitespace variants > Setup",
                       "text": "x"})
    check("the two Setup variants are not", err and "ordinal" in err, err)

    _, err = apply_op(deep, "section-append", {"section": "Instal", "text": "x"})
    check("a typo gets near matches", err and "Install" in err, err)
    _, err = apply_op(deep, "section-append", {"section": "Install"})
    check("a missing payload says which field is missing",
          err and "`text` is required" in err, err)
    _, err = apply_op(deep, "section-insert",
                      {"section": "Install", "position": "sideways",
                       "heading": "X"})
    check("an unknown position lists the valid ones",
          err and "first-child" in err, err)
    _, err = apply_op(deep, "section-insert",
                      {"section": "Reference > API > Endpoints > Authentication",
                       "position": "first-child", "heading": "X"})
    check("a child of a level-5 heading is fine, a child of level 6 is not",
          not err, err)

    # A bare string must behave exactly like the object form, as in the other
    # two families -- one addressing habit, not three.
    a, _ = apply_op(deep, "section-append",
                    {"section": "Install > macOS", "text": "x"})
    b, _ = apply_op(deep, "section-append",
                    {"section": {"path": "Install > macOS"}, "text": "x"})
    check("bare-string section address is byte-identical to the object form",
          a == b and a is not None)


def test_insert_body_and_children():
    """S6: `body` cannot smuggle a heading, and `children` is how to say one.

    `insert` promises the model never counts levels, and `body` was the hole in
    that promise -- markdown source, so the model had to write `### Added` by
    hand and get the 3 right. Across 30 `insert-release-at-top` trials it wrote
    that heading at levels 1, 2 and 4 and never at 3.

    Two things are asserted. `body` containing a heading is refused, *parsed*
    rather than pattern-matched, so a `#` in a fenced block is still prose and a
    heading on the third line is still a heading. And `children` reaches the
    same bytes in one call that two calls reach, which is the whole claim of the
    structured payload -- if it did not, the two S6 arms would not be measuring
    the same document.
    """
    deep = open(os.path.join(ROOT, "corpus/sections/deep-nesting.md"),
                newline="").read()

    def ins(**kw):
        return apply_op(deep, "section-insert",
                        dict({"section": "Reference > API",
                              "position": "last-child",
                              "heading": "Rate limits"}, **kw))

    for label, body in (
            ("atx first line", "### Headers\n\nText."),
            ("atx after a stray line", "| | |\n## Headers\n\nText."),
            ("setext", "Headers\n---\n\nText."),
            ("h1", "# Headers")):
        out, err = ins(body=body)
        check(f"insert refuses a heading in `body`: {label}",
              out is None and err and "contains a heading" in err,
              (err or "accepted").replace("\n", " ")[:90])
    ok, err = ins(body="Text with a # hash and a `# comment` in it.")
    check("insert accepts a body that only looks like a heading", not err,
          (err or "").replace("\n", " ")[:90])
    ok, err = ins(body="Text.\n\n```bash\n# not a heading\n```")
    check("insert accepts a `#` line inside a fence", not err,
          (err or "").replace("\n", " ")[:90])

    # `children` must reach exactly what the two-call sequence reaches.
    one, err = ins(children=[{"heading": "Headers",
                              "body": "Every response carries `X-RateLimit-*`."}])
    check("children: no error", not err, (err or "").replace("\n", " ")[:90])
    two, err = apply_op(deep, "section-insert",
                        {"section": "Reference > API", "position": "last-child",
                         "heading": "Rate limits"})
    if not err:
        two, err = apply_op(two, "section-insert",
                            {"section": "Reference > API > Rate limits",
                             "position": "last-child", "heading": "Headers",
                             "body": "Every response carries `X-RateLimit-*`."})
    check("children in one call == the same two calls", one == two and one,
          "differ")

    # Levels are derived for children too, and a child of a child goes deeper.
    nested, err = ins(children=[{"heading": "Headers", "children": [
        {"heading": "Retry-After", "body": "Seconds."}]}])
    check("nested children: no error", not err, (err or "").replace("\n", " ")[:90])
    if not err:
        paths = [e["path"] for e in section_outline(nested)]
        check("nested children derive both levels",
              "Deep heading nesting > Reference > API > Rate limits > Headers > "
              "Retry-After" in paths,
              str([p for p in paths if "Rate limits" in p]))

    # A child whose level would exceed 6 is refused, not silently clamped.
    deep_out, err = apply_op(deep, "section-insert",
                             {"section": "Reference > API > Endpoints > Authentication",
                              "position": "last-child", "heading": "Scopes",
                              "children": [{"heading": "Too deep"}]})
    check("children refuse a level-7 heading",
          deep_out is None and err and "markdown stops at 6" in err,
          (err or "accepted").replace("\n", " ")[:90])
    # ... and a child with no heading is a refusal, not an empty section.
    _, err = ins(children=[{"body": "orphan"}])
    check("children refuse a missing heading",
          err and "missing `heading`" in err,
          (err or "accepted").replace("\n", " ")[:90])

    # The two S6 schemes must be graded against the same bytes, or the arm is
    # comparing two benchmarks rather than two vocabularies. `section_2call`
    # reaches these tasks through the `ideal_calls` sequence; `section_kids`
    # reaches them in one call. Both have to hit the golden exactly.
    from grade import check_result

    one_call = {
        "insert-release-at-top": {
            "section": "[1.4.2] - 2026-08-14", "position": "before",
            "heading": "[1.5.0] - 2026-09-06",
            "children": [{"heading": "Added",
                          "body": "- `plan --explain` flag."}]},
        "insert-troubleshooting": {
            "section": "Deep heading nesting", "position": "last-child",
            "heading": "Troubleshooting",
            "children": [{"heading": "Logs",
                          "body": "Written to `~/.incise/log`."},
                         {"heading": "Common errors", "body": "See the FAQ."}]},
    }
    tasks = {t["id"]: t for t in
             json.load(open(os.path.join(ROOT, "bench/tasks/sections.json")))["tasks"]}
    for tid, call in one_call.items():
        task = tasks[tid]
        before = open(os.path.join(ROOT, task["fixture"]), newline="").read()
        after, err = apply_op(before, "section-insert", call)
        if err:
            check(f"children reach the {tid} golden in one call", False,
                  err.replace("\n", " ")[:90])
            continue
        outcome, detail = check_result(task, before, after)
        check(f"children reach the {tid} golden in one call",
              outcome == "correct", f"{outcome}: {detail}")


def test_close_matches_tracks_stdlib():
    """`_close_matches` is stdlib everywhere autojunk could not have engaged.

    This is the one test in the file that exists because differential testing
    cannot do its job. `difftest.py` compares the Rust port against this oracle,
    and turning autojunk off changes *both* -- so they keep agreeing, and the
    agreement says nothing about whether the new answer is right. That is the
    first of the three blindnesses (FINDINGS): a differential test cannot see an
    assumption both implementations share.

    So the oracle is pinned to something that did not move. `_close_matches` is
    `difflib.get_close_matches` with one keyword added, and below 200 characters
    that keyword cannot do anything -- the heuristic does not engage. Every
    probe under the threshold must therefore return exactly what stdlib returns,
    character for character, and the divergence is confined to inputs where it
    was argued for.

    At and above the threshold the divergence is checked for *direction* rather
    than for a golden. Purging can only remove matches from the index, so it can
    only lower a ratio and shrink the qualifying set: stdlib's answer must be a
    subset of ours, never the reverse. A probe set where nothing differs would
    make this test vacuous on exactly the point at issue, so the count is
    asserted non-zero.
    """
    import difflib
    from incise_ops import _close_matches

    files = list(corpus_files()) + sorted(
        glob.glob(os.path.join(ROOT, "bench/synthetic/*.md")))

    # Candidate pools taken from documents rather than invented, for the reason
    # the corpus exists: the interesting inputs are the ones a real table has.
    pools = []
    for path in files:
        content = open(path, newline="").read()
        headings = [s.text for s in find_sections(content)]
        if headings:
            pools.append(headings)
        for t in find_tables(content):
            cols = list(t.cells(t.header))
            if cols:
                pools.append(cols)
            for ci in range(len(cols)):
                col = [r[ci] for r in t.rows() if ci < len(r) and r[ci]]
                if col:
                    pools.append(col)

    def probes(word):
        """A value, and the near misses a model actually produces."""
        out = [word, word.lower(), word.upper()]
        parts = word.split(" ")
        if len(parts) > 1:
            out += [" ".join(parts[1:]), " ".join(parts[:-1]),
                    " ".join(parts[:len(parts) // 2] + parts[len(parts) // 2 + 1:])]
        if len(word) > 2:
            out.append(word[:len(word) // 2] + word[len(word) // 2 + 1:])
        return out

    short_checked = short_bad = 0
    long_checked = long_moved = long_bad = 0
    first_bad = ""
    for pool in pools:
        uniq = list(dict.fromkeys(pool))
        for word in uniq:
            for probe in probes(word):
                for n, cutoff in ((2, 0.4), (3, 0.4), (3, 0.6)):
                    mine = _close_matches(probe, uniq, n=n, cutoff=cutoff)
                    theirs = difflib.get_close_matches(probe, uniq, n=n, cutoff=cutoff)
                    if len(probe) < 200:
                        short_checked += 1
                        if mine != theirs:
                            short_bad += 1
                            first_bad = first_bad or f"{probe[:60]!r}: {theirs} vs {mine}"
                    else:
                        long_checked += 1
                        if mine != theirs:
                            long_moved += 1
                        # Widened past `n` so truncation cannot mask the
                        # containment the purge argument predicts.
                        wide_mine = _close_matches(probe, uniq, n=len(uniq), cutoff=cutoff)
                        wide_theirs = difflib.get_close_matches(probe, uniq,
                                                                n=len(uniq), cutoff=cutoff)
                        if not set(wide_theirs) <= set(wide_mine):
                            long_bad += 1
                            first_bad = first_bad or f"{probe[:60]!r}: lost {set(wide_theirs) - set(wide_mine)}"

    check("under 200 chars, _close_matches is stdlib exactly",
          short_bad == 0 and short_checked > 10000,
          f"{short_bad} differ of {short_checked} checked; {first_bad}")
    check("at 200+ chars, stdlib's matches are a subset of ours",
          long_bad == 0 and long_checked > 0,
          f"{long_bad} violations of {long_checked} checked; {first_bad}")
    check("at 200+ chars, the two actually diverge (test is not vacuous)",
          long_moved > 0, f"{long_moved} of {long_checked} moved")

    # F-nearmatch's fixed point, stated as the message rather than the ranking:
    # this exact shape came back as "Near matches: none" with a 98% match in the
    # column, which is the refusal a model cannot recover from.
    cell = ("Returning the heading outline alongside the one-line description was "
            "statistically identical to returning the outline alone, so the omission "
            "is the deliverable and the sentence on its own is what the measurement "
            "actually adopted here.")
    probe = cell.replace("Returning ", "", 1)
    check("a long value one word short still finds its cell",
          _close_matches(probe, [cell], n=3, cutoff=0.4) == [cell],
          f"stdlib gives {difflib.get_close_matches(probe, [cell], n=3, cutoff=0.4)}")


def test_describe_change():
    """The tool result must name the change, and never claim one that is absent.

    S13's 32x finding (REQUIREMENTS §6.3.2) is about what comes *back* from a
    successful call, so the response text is under test the same way the
    refusal text is. Two properties matter and they are different: the
    description has to be specific enough to be worth reading, and it must
    never assert something the bytes do not support -- a response that says a
    section was added when none was is a worse failure than one that says
    nothing, because it is the exact input that makes a model stop checking.
    """
    changelog = os.path.join(ROOT, "corpus/documents/changelog.md")
    api = os.path.join(ROOT, "corpus/documents/api-reference.md")
    cases = [
        # (file, op, args, substrings that must appear, must NOT appear)
        (changelog, "section-append",
         {"section": "[Unreleased] > Added", "text": "- New note."},
         ['changed the body of "Added"', "+2 lines"], ["removed", "added the"]),
        (changelog, "section-rename",
         {"section": "[Unreleased]", "heading": "[1.5.0]"},
         ['renamed "[Unreleased]" to "[1.5.0]"'], ["removed", "added the"]),
        (changelog, "section-insert",
         {"section": "[Unreleased]", "position": "after",
          "heading": "[1.4.3]", "body": "Patch."},
         ['added the section "[1.4.3]"', "level 2"], ["removed"]),
        (changelog, "section-replace-body",
         {"section": "[1.4.2] - 2026-08-14", "text": "Nothing.",
          "overwrite": True},
         ['changed the body of "[1.4.2] - 2026-08-14"'], ["removed the"]),
        (api, "section-set-level",
         {"section": "API reference > Accounts > list", "level": 2},
         ['promoted "list" and 3 descendants', "level 3 to level 2"],
         ["removed", "added"]),
        # The one that has to carry a warning: `delete` on a section with
        # children removes four headings, and the response says so.
        (api, "section-delete",
         {"section": "API reference > Accounts > list", "subtree": True},
         ['removed the section "list"', "3 sections nested under it"],
         ["added"]),
    ]
    for path, op, args, want, unwanted in cases:
        before = open(path).read()
        after, err = apply_op(before, op, args)
        if err:
            check(f"describe {op}", False, err.replace("\n", " ")[:80])
            continue
        text = describe_change(before, after, path)
        for w in want:
            check(f"describe {op}: says {w!r}", w in text, text)
        for u in unwanted:
            check(f"describe {op}: does not say {u!r}", u not in text, text)

    # It is derived from the documents, so a no-op says so rather than
    # reporting the call back as if it had done something.
    doc = open(changelog).read()
    check("describe of an unchanged document does not claim a change",
          describe_change(doc, doc, changelog)
          == "Applied, but the document is unchanged.",
          describe_change(doc, doc, changelog))

    # Every mutating op on every corpus file: the description must be
    # non-empty, must not be the no-op string, and must not name a heading the
    # after-document does not contain. That last one is the property the whole
    # response shape rests on.
    checked = 0
    for path in sorted(glob.glob(os.path.join(ROOT, "corpus/**/*.md"),
                                 recursive=True)):
        before = open(path).read()
        entries = section_outline(before, path)
        if not entries:
            continue
        target = entries[-1]["path"]
        for op, args in (
                ("section-append", {"section": target, "text": "Probe."}),
                ("section-rename", {"section": target, "heading": "Probe"}),
                ("section-insert", {"section": target, "position": "after",
                                    "heading": "Probe", "body": "Body."}),
                ("section-delete", {"section": target})):
            after, err = apply_op(before, op, args)
            if err:
                continue
            text = describe_change(before, after, path)
            checked += 1
            if not text.startswith("Applied:"):
                check(f"describe {op} on {os.path.basename(path)}", False, text)
                continue
            # Any heading it says it *added* must actually be there.
            for name in re.findall(r'added the section "([^"]*)"', text):
                present = any(e["text"] == name
                              for e in section_outline(after, path))
                check(f"describe claims only real additions "
                      f"({os.path.basename(path)} {op})", present,
                      f"{name!r} not in the resulting document")
    check("every corpus description is specific", checked > 40,
          f"only {checked} descriptions exercised")


def test_section_crlf():
    """Section ops must not convert line endings, in either direction."""
    path = os.path.join(ROOT, "corpus/hazards/crlf.md")
    content = open(path, newline="").read()
    before = eol_profile(content)
    for op, args in (("section-append", {"section": "Steps", "text": "Note."}),
                     ("section-rename", {"section": "Steps", "heading": "Stages"}),
                     ("section-set-level", {"section": "Steps", "level": 3}),
                     ("section-insert", {"section": "Steps", "position": "after",
                                         "heading": "Extra", "body": "Body."})):
        out, err = apply_op(content, op, args)
        if err:
            check(f"crlf {op}", False, err.replace("\n", " "))
            continue
        after = eol_profile(out)
        # Every line the op added or rewrote must be CRLF too, so the count of
        # lone LFs is what must not move.
        check(f"{op} adds no lone LF to a CRLF file",
              after[1] == before[1], f"{before} -> {after}")


# --------------------------------------------------------------------------
# frontmatter -- the family whose whole requirement is the bytes it leaves alone
# --------------------------------------------------------------------------

def _front_blocks():
    """(rel, content, FrontMatter) for every YAML block the family can edit.

    The corpus carries three of these and `bench/synthetic/front-*.md` carries
    three more, and the synthetic ones are in scope on purpose: `rich.md` is the
    entire positive corpus, so a sweep that stopped at `corpus/` would be one
    file wide and would prove almost nothing about a family whose claim is
    "every block, every shape".
    """
    paths = list(corpus_files()) + sorted(
        glob.glob(os.path.join(ROOT, "bench/synthetic/*.md")))
    for path in paths:
        content = open(path, newline="").read()
        fm = mdfront.find_frontmatter(content)
        if fm.present and fm.fmt == "yaml":
            yield os.path.relpath(path, ROOT), content, fm


def test_frontmatter_goldens():
    """The reference must still produce every golden in tasks/frontmatter.json.

    `test_list_goldens`'s honesty condition, one family over: the goldens were
    generated by this implementation, so without this assertion the executor and
    the answer key would drift together and the benchmark would re-baseline
    itself to whatever the code now does.
    """
    from grade import check_result

    tasks = json.load(
        open(os.path.join(ROOT, "bench/tasks/frontmatter.json")))["tasks"]
    for task in tasks:
        before = open(os.path.join(ROOT, task["fixture"]), newline="").read()
        after, err = before, None
        for call in task["ideal_calls"]:
            after, err = apply_op(after, call["op"], call["args"])
            if err:
                break
        if err:
            check(f"golden {task['id']}", False, err.replace("\n", " "))
            continue
        outcome, detail = check_result(task, before, after)
        check(f"golden {task['id']}", outcome == "correct", f"{outcome}: {detail}")


def test_frontmatter_roundtrip():
    """Set then delete must restore the file byte-for-byte, for every block.

    `test_list_roundtrip`'s bet, and the one PLAN.md:1276-1278 asks for: insert
    and delete are tested as inverses rather than each against a golden, because
    a golden can only say what one edit looks like and the failure this family
    is built around is a byte somewhere else in the block.

    Only files that already have a YAML block are swept. `absent.md` is excluded
    deliberately and not by accident: a set there *creates* the delimiters, and
    delete does not un-create them, so the pair is not an inverse on that file
    and pretending otherwise would be asserting something untrue.
    """
    probe = "zzq_roundtrip_probe"
    checked = 0
    for rel, content, fm in _front_blocks():
        added, err = apply_op(content, "frontmatter-set",
                              {"key": probe, "value": "x"})
        if err:
            check(f"set {rel}", False, err.replace("\n", " "))
            continue
        back, err = apply_op(added, "frontmatter-delete", {"key": probe})
        if err:
            check(f"delete {rel}", False, err.replace("\n", " "))
            continue
        checked += 1
        if back != content:
            check(f"roundtrip {rel}", False,
                  f"eol {eol_profile(content)} -> {eol_profile(back)}")
    check(f"frontmatter set+delete round-trips byte-identical ({checked} blocks)",
          checked > 0)


def test_frontmatter_touches_one_line():
    """A set rewrites the key's own line and no other, for every settable key.

    This is `corpus/frontmatter/rich.md:37-43` asserted over the whole family
    rather than over the one edit that file names. Key order, the leading
    comment, the inline comment on a sibling, the block scalar styles and the
    quoting of `quoted_key` are not five separate checks here -- they are lines,
    and a set that moves exactly one line cannot have touched any of them.

    Containers refuse, and that is the other half of the claim: `build` and
    `tags` hold things, and a set that flattened one to a scalar would delete
    what is under it and still pass a one-line window check, because the window
    would be the lines it deleted.
    """
    settable = refused = 0
    for rel, content, fm in _front_blocks():
        before = content.split("\n")
        order = [e.path for e in fm.entries]
        for e in fm.entries:
            key = mdfront.format_path(e.path)
            after, err = apply_op(content, "frontmatter-set",
                                  {"key": key, "value": "zzqprobe"})
            if err:
                refused += 1
                # A container is the only thing allowed to refuse here. Anything
                # else is a key the family can address and cannot edit, which is
                # the shape of refusal 5.3 exists to rule out.
                check(f"refusal names a container: {rel} {key}",
                      e.kind in ("map", "seq", "block", "item")
                      or "." in key,
                      err.replace("\n", " ")[:80])
                continue
            settable += 1
            lines = after.split("\n")
            moved = [i for i in range(max(len(before), len(lines)))
                     if (before[i] if i < len(before) else None)
                     != (lines[i] if i < len(lines) else None)]
            # Against the line the *address* resolves to, not `e.line`. A key
            # written twice in one block has two entries and one address:
            # `by_path` is a dict comprehension, so it keeps the last, and a set
            # on the first one's path rewrites the second one's line. That is
            # the behaviour; `bench/synthetic/front-dupes.md` is the fixture
            # that falsified the simpler claim this line used to make.
            target = fm.by_path()[e.path].line
            check(f"one line moved: {rel} {key}", moved == [target], str(moved))
            check(f"key order held: {rel} {key}",
                  [x.path for x in mdfront.find_frontmatter(after).entries]
                  == order)
    check(f"every settable key moves its own line only ({settable} keys, "
          f"{refused} containers refused)", settable > 0 and refused > 0)


def test_frontmatter_states():
    """Absent, empty and null are three states, not two spellings of falsy.

    `corpus/frontmatter/absent.md:17` and `empty.md:6` both require a caller to
    be able to tell absent from empty, and `rich.md:52` requires null to be
    distinct from the empty string. The distinction is cheap to lose -- a
    `if not fm.entries` anywhere in the read path collapses the first pair, and
    any round trip through a YAML loader collapses the second -- so it is
    asserted at the boundary a caller actually sees.
    """
    from incise_ops import frontmatter_get

    states = {}
    for rel in ("corpus/frontmatter/absent.md", "corpus/frontmatter/empty.md",
                "corpus/frontmatter/rich.md"):
        content = open(os.path.join(ROOT, rel), newline="").read()
        states[rel] = frontmatter_get(content)["state"]
    check("absent, empty and present are three distinct states",
          [states["corpus/frontmatter/absent.md"],
           states["corpus/frontmatter/empty.md"],
           states["corpus/frontmatter/rich.md"]] == ["absent", "empty",
                                                     "present"], str(states))

    shapes = open(os.path.join(ROOT, "bench/synthetic/front-shapes.md"),
                  newline="").read()
    by = {k["path"]: k for k in frontmatter_get(shapes)["keys"]}
    check("null and the empty string are different values",
          by["empty_null"]["kind"] == "null" and by["empty_null"]["value"] == ""
          and by["empty_string"]["kind"] == "scalar"
          and by["empty_string"]["value"] == '""',
          f'{by["empty_null"]} {by["empty_string"]}')

    # And setting a key to null must write the key, not remove it, and must not
    # write the quotes that would make it an empty string instead.
    rich = open(os.path.join(ROOT, "corpus/frontmatter/rich.md"),
                newline="").read()
    cleared, err = apply_op(rich, "frontmatter-set",
                            {"key": "title", "value": None})
    if err:
        check("set to null", False, err.replace("\n", " "))
    else:
        got = {k["path"]: k for k in frontmatter_get(cleared)["keys"]}
        check("a key set to null stays, holding nothing",
              got["title"]["kind"] == "null" and got["title"]["value"] == "",
              str(got.get("title")))
        check("a key set to null gains no trailing space",
              "title:\n" in cleared.replace("\r", ""))


def test_frontmatter_refusals():
    """TOML is refused by every frontmatter op, in a sentence a model can use.

    `corpus/hazards/toml-frontmatter.md` names the failure: a YAML parser
    accepting some of this by accident and writing back a mangled block.
    `mdlist.frontmatter_span` accepts `+++` on purpose -- skipping a TOML block
    is as correct as skipping a YAML one -- so the refusal has to be the ops'
    own, and the file's tables and sections have to keep working around it.
    """
    from incise_ops import frontmatter_get, render_frontmatter

    rel = "corpus/hazards/toml-frontmatter.md"
    content = open(os.path.join(ROOT, rel), newline="").read()
    for op, args in (("frontmatter-set", {"key": "title", "value": "x"}),
                     ("frontmatter-delete", {"key": "title"})):
        after, err = apply_op(content, op, args)
        # A refused op returns no document at all, which is the guarantee that
        # matters: there is no partially-edited TOML block to write back.
        check(f"{op} refuses TOML", bool(err) and after is None)
        if err:
            check(f"{op} names both formats", "TOML" in err and "---" in err
                  and "+++" in err, err.replace("\n", " "))
    try:
        frontmatter_get(content)
        check("frontmatter-get refuses TOML", False)
    except OpError as exc:
        check("frontmatter-get refuses TOML", "TOML" in str(exc))
    check("the renderer says TOML rather than nothing",
          "TOML" in render_frontmatter(content, rel))

    # The other families are unaffected, which is half of what the fixture is
    # for: a TOML block must stop frontmatter ops and nothing else.
    check("sections in a TOML-frontmatter file still work",
          bool(section_outline(content, rel)))

    # A path that cannot be addressed refuses rather than inventing a key, and
    # says what is there. `dotted.key` in front-shapes.md is the sharp case: the
    # key exists, is quoted, and contains the separator, so no path reaches it.
    shapes = open(os.path.join(ROOT, "bench/synthetic/front-shapes.md"),
                  newline="").read()
    _, err = apply_op(shapes, "frontmatter-set",
                      {"key": "dotted.key", "value": "x"})
    check("a key whose name contains a dot is refused, and explained",
          bool(err) and "dotted.key" in err and "separates" in err,
          (err or "").replace("\n", " "))


def test_frontmatter_existence_guards():
    """Create/update intent refuses a wrong-path write before bytes can move."""
    content = "---\nbuild:\n  target: release\n---\n\n# Project\n"

    after, err = apply_op(content, "frontmatter-set", {
        "key": "build.target", "value": True, "must_absent": True,
    })
    check("create-only refuses an existing key",
          after is None and bool(err) and "requires an absent" in err,
          (err or "").replace("\n", " "))

    after, err = apply_op(content, "frontmatter-set", {
        "key": "build.cache", "value": True, "must_exist": True,
    })
    check("update-only refuses an absent key",
          after is None and bool(err) and "requires an existing" in err,
          (err or "").replace("\n", " "))

    created, err = apply_op(content, "frontmatter-set", {
        "key": "build.cache", "value": True, "must_absent": True,
    })
    ordinary_create, ordinary_err = apply_op(
        content, "frontmatter-set", {"key": "build.cache", "value": True})
    check("create-only preserves a valid create",
          err is None and ordinary_err is None and created == ordinary_create)

    updated, err = apply_op(content, "frontmatter-set", {
        "key": "build.target", "value": "debug", "must_exist": True,
    })
    ordinary_update, ordinary_err = apply_op(
        content, "frontmatter-set", {"key": "build.target", "value": "debug"})
    check("update-only preserves a valid update",
          err is None and ordinary_err is None and updated == ordinary_update)

    _, err = apply_op(content, "frontmatter-set", {
        "key": "build.cache", "value": True,
        "must_absent": True, "must_exist": True,
    })
    check("contradictory existence guards refuse", bool(err) and "cannot both" in err,
          (err or "").replace("\n", " "))

    _, err = apply_op(content, "frontmatter-set", {
        "key": "build.cache", "value": True, "must_absent": "true",
    })
    check("existence guards require booleans",
          bool(err) and "must be a boolean" in err,
          (err or "").replace("\n", " "))


def test_frontmatter_read():
    """The read tool answers what the summary withholds, and nothing else.

    `render_frontmatter` omits scalar values by design -- Arm B's premise is
    that the model addresses an edit it cannot see -- and F-frontmatter measured
    what that costs when the family publishes no way to ask: `set-dana-role`
    needs to know which of two authors is Dana, the summary lists
    `authors[0].name` and `authors[1].name` with no values, and the two arms
    guessed 3/10 and 7/10 in mirror image.

    So the property under test is a *difference* between the two renderers, and
    it is asserted as one rather than by matching a fixed string: whatever the
    summary says, the read must additionally say what the keys hold.
    """
    from incise_ops import (frontmatter_get, render_frontmatter,
                            render_frontmatter_get)
    import armb

    rel = "corpus/frontmatter/rich.md"
    content = open(os.path.join(ROOT, rel), newline="").read()
    summary = render_frontmatter(content, rel)
    read = render_frontmatter_get(content, rel)

    # The premise, stated as the fact the broken task needed: the summary
    # cannot distinguish the two authors and the read can.
    check("the summary withholds the author names",
          "Dana" not in summary and "Peter" not in summary)
    check("the read supplies them",
          "Dana" in read and "Peter" in read)

    # Every scalar the read prints is the value the document holds, verbatim --
    # no re-quoting, no type coercion. `quoted_key` is the case that matters:
    # its value is `"value: with a colon"` *including* the quotes, and a
    # renderer that stripped them would be teaching the model to send back a
    # value the document does not contain.
    fm = mdfront.find_frontmatter(content)
    lines = read.split("\n")
    missed = []
    for e in fm.entries:
        if e.kind not in ("scalar", "item") or not e.value:
            continue
        # A sequence item that is itself a map (`authors[0]`) has no value of
        # its own: `e.value` holds the mapping's first line, and the renderer
        # signposts to the children that carry the two facts instead of
        # printing `name: Peter` beside a path whose children print it again.
        if e.kind == "item" and fm.children_of(e.path):
            continue
        p = mdfront.format_path(e.path)
        if not any(ln.startswith(f"  {p:<24s} ") and ln.strip().endswith(e.value)
                   for ln in lines):
            missed.append(p)
    check("every scalar is rendered as stored", not missed, str(missed[:4]))
    check("the quoting is not stripped",
          '"value: with a colon"' in read)

    # A block scalar's value is on the lines below its key, so a renderer that
    # printed `e.value` alone would answer `|` to "what is in `multiline`".
    check("a block scalar's body is shown",
          "Second line, newlines preserved." in read)

    # The read is a read. This is the claim the grader relies on when it lets a
    # `frontmatter_get` call pass through without touching `doc`.
    got, text, err = armb.read_call(content, "frontmatter_get", {"path": rel})
    check("read_call returns a report and a rendering",
          err is None and text == read and got["state"] == "present")
    check("frontmatter_get leaves the document alone",
          open(os.path.join(ROOT, rel), newline="").read() == content)

    # A subtree read, which is the call `set-dana-role` actually wants.
    sub = render_frontmatter_get(content, rel, key="authors")
    check("a keyed read narrows to the subtree",
          "Dana" in sub and "quoted_key" not in sub)

    # Refusals travel the same path as the edit ops'. `read_call` catches
    # OpError and hands back the sentence, so the model sees a message and not
    # a stack trace -- the same contract `table_get` has.
    toml = open(os.path.join(ROOT, "corpus/hazards/toml-frontmatter.md"),
                newline="").read()
    _got, _text, err = armb.read_call(toml, "frontmatter_get", {"path": "x"})
    check("a TOML read refuses through read_call", bool(err) and "TOML" in err)
    _got, _text, err = armb.read_call(content, "frontmatter_get",
                                      {"path": rel, "key": "nope"})
    check("an unknown key refuses through read_call", bool(err))

    # Absent and empty stay distinguishable through the renderer, which is the
    # distinction `corpus/frontmatter/absent.md:17` and `empty.md:6` require a
    # caller to be able to make.
    states = {}
    for f in ("corpus/frontmatter/absent.md", "corpus/frontmatter/empty.md"):
        c = open(os.path.join(ROOT, f), newline="").read()
        states[f] = render_frontmatter_get(c, f)
        check(f"{os.path.basename(f)} reads as {frontmatter_get(c)['state']}",
              frontmatter_get(c)["state"] in states[f]
              or "none" in states[f])
    check("absent and empty read differently",
          len(set(states.values())) == 2)


def test_frontmatter_read_scheme():
    """`front_r` is `front_p` plus a read tool, and the prompt follows.

    Two schemes that differ in more than one place cannot attribute a
    difference, so the edit tool is asserted byte-identical between them: what
    `front_r` adds is a tool and the sentence that makes it usable, and nothing
    else. The prompt has to move with it -- `frontmatter`'s "you do not need
    them" would be instructing the model not to use the tool it was just
    handed, which is the same trap `table_read` was written to avoid.
    """
    import armb

    p = {t["name"]: t for t in armb.SCHEMES["front_p"]}
    r = {t["name"]: t for t in armb.SCHEMES["front_r"]}
    check("front_r adds exactly the read tool",
          set(r) - set(p) == {"frontmatter_get"} and not set(p) - set(r))
    check("the edit tool is byte-identical between them",
          json.dumps(p["frontmatter_edit"], sort_keys=True)
          == json.dumps(r["frontmatter_edit"], sort_keys=True))
    check("the read tool does not require a key",
          r["frontmatter_get"]["parameters"]["required"] == ["path"])

    task = {"family": "frontmatter-set"}
    check("front_p keeps the edit prompt",
          armb.prompt_of(task, "front_p") == "frontmatter")
    check("front_r gets the read-capable prompt",
          armb.prompt_of(task, "front_r") == "frontmatter_read")
    check("the read prompt drops 'you do not need them'",
          "do not need them"
          not in armb.SYSTEM_PROMPTS["frontmatter_read"])
    check("the edit prompt still says it",
          "do not need them" in armb.SYSTEM_PROMPTS["frontmatter"])

    # The table read schemes publish `table_get` *alone*, so they were only ever
    # run on `table-get` tasks and take the branch above the new one. Asserted
    # because the new branch is what could have moved their recorded numbers.
    for s in ("table_read_naive", "table_read_g"):
        check(f"{s} still selects table_read",
              armb.prompt_of({"family": "table-get"}, s) == "table_read")
        check(f"{s} publishes no edit tool",
              all(t["name"] in armb.READS for t in armb.SCHEMES[s]))
    for s in ("front_naive", "front_p", "list_naive", "section_g"):
        check(f"{s} is unaffected by the scheme argument",
              armb.prompt_of({"family": "frontmatter-set"}
                             if s.startswith("front") else
                             {"family": "list-add-item"}
                             if s.startswith("list") else
                             {"family": "section-rename"}, s)
              == armb.prompt_of({"family": "frontmatter-set"}
                                if s.startswith("front") else
                                {"family": "list-add-item"}
                                if s.startswith("list") else
                                {"family": "section-rename"}))


# --------------------------------------------------------------------------
# the generated task files still match their generators
# --------------------------------------------------------------------------

def test_tasks_are_regenerable():
    """Every generated task file is byte-identical to what its generator emits.

    Three task files are built by a script and committed beside it, and until
    this check existed nothing compared the two. They drifted: a late fix to
    `make_frontmatter_tasks.py` -- `delete-draft`'s note cited `release-bump` as
    the opposite verb on `draft`, which is `set-draft-true` -- was committed
    without regenerating, so the tracked `frontmatter.json` had been generated
    by a script that no longer existed. Nothing failed, because the drift was in
    a note.

    That is exactly why it is worth a test. The generators are not
    documentation: `make_section_tasks.py:28-31` is the rule that a task whose
    hand-written expectation is wrong must **fail to generate** rather than
    quietly redefine correct, and `make_frontmatter_tasks.py` re-derives every
    golden from the reference implementation. A committed file that no longer
    comes out of its generator has none of that -- the checks ran against a spec
    nobody can see any more, and the next drift lands in a `golden` instead of a
    `note`.

    Compared as parsed JSON rather than as text, because the question is whether
    the tasks are the same tasks, not whether `json.dumps` chose the same
    spacing.
    """
    import subprocess

    for gen, name in (("make_list_tasks.py", "lists.json"),
                      ("make_section_tasks.py", "sections.json"),
                      ("make_frontmatter_tasks.py", "frontmatter.json")):
        proc = subprocess.run([sys.executable, os.path.join(ROOT, "bench", gen)],
                              capture_output=True, text=True)
        if proc.returncode != 0:
            check(f"{gen} runs", False, proc.stderr.strip().split("\n")[-1])
            continue
        tracked = json.load(open(os.path.join(ROOT, "bench", "tasks", name)))
        fresh = json.loads(proc.stdout)
        if tracked == fresh:
            check(f"{name} matches {gen}", True)
            continue
        # Name the first task that moved and the field it moved in. "The file
        # is stale" is not actionable; "`release-bump`.instruction" is.
        old = {t["id"]: t for t in tracked["tasks"]}
        new = {t["id"]: t for t in fresh["tasks"]}
        drift = [f"{tid} gone" for tid in old if tid not in new]
        drift += [f"{tid} new" for tid in new if tid not in old]
        for tid in old.keys() & new.keys():
            drift += [f"{tid}.{k}" for k in old[tid]
                      if old[tid][k] != new[tid].get(k)]
        check(f"{name} matches {gen}", False,
              f"regenerate it -- moved: {', '.join(drift[:6])}")


# --------------------------------------------------------------------------
# the front end's `action` check (divergence C)
# --------------------------------------------------------------------------

def test_file_argument_is_inert():
    """`apply_op`'s result does not depend on `path`, and Arm B inherits that.

    This pins a *limitation*, which is unusual and deliberate. `armb.run_trial`
    opens the task's fixture and hands the content to `apply_op`; the model's
    `path` rides along in `op_args` and the core never reads it. So every Arm B
    grade in FINDINGS.md was produced by an executor for which the file argument
    is decorative -- a call naming a file that does not exist grades exactly like
    a correct one (F-fileblind, caveat 19).

    That is the right design for a schema comparison: pointing every trial at a
    known fixture is what makes the arms comparable. What it cost was invisible
    until it was looked for -- `section-insert` drifted to naming no file on 92%
    of calls under the adopted schema, under zero selection pressure.

    The assertion is here so the property cannot change silently. If a future
    executor *did* read `path`, every recorded Arm B grade would have been
    produced under different semantics than the ones in the tree, and this test
    failing is the notice. It is not a licence to leave it this way: closing it
    is an Arm C question, and Arm C does pass the path to a real binary.
    """
    import armb

    tasks = json.load(open(os.path.join(ROOT, "bench/tasks/sections.json")))
    task = [t for t in tasks["tasks"] if t["id"] == "insert-subsection-last"][0]
    doc = open(os.path.join(ROOT, task["fixture"]), newline="").read()
    base = {"action": "insert", "new_heading": "FreeBSD",
            "position": "last-child", "body": "Use pkg.",
            "section": {"heading": "Deep heading nesting > Install"}}

    results = {}
    for label, extra in (("absent", {}),
                         ("correct", {"path": task["fixture"]}),
                         ("nonexistent", {"path": "/nowhere/absent.md"}),
                         ("a heading, not a file",
                          {"path": "Deep heading nesting > Install"})):
        op, op_args = armb.normalize("section_edit", dict(base, **extra))
        results[label] = apply_op(doc, op, op_args)

    check("the executor never reads `path`: every spelling gives one result",
          len({(a, e) for a, e in results.values()}) == 1,
          {k: v[1] for k, v in results.items()})
    check("and that one result is a real edit, not a refusal",
          results["absent"][1] is None and results["absent"][0] != doc)
    # The other direction: the argument does survive into `op_args`, which is
    # what `plugins/hermes/__init__.py` relies on and what Arm C hands the CLI.
    _op, op_args = armb.normalize("section_edit",
                                  dict(base, path=task["fixture"]))
    check("`path` still reaches op_args, which is what Arm C uses",
          op_args.get("path") == task["fixture"], op_args.get("path"))


# --------------------------------------------------------------------------


def test_action_check():
    """`armb.normalize`'s optional `action` check: off by default, and correct.

    The flag is the whole point. `regrade_snapshot.py` replays every recorded
    call through `normalize`, so a check that fired by default would move
    digests on import; the default-off half of this test is what keeps those
    replays trustworthy, and it is asserted rather than assumed.

    The messages are pinned because they were written against a population that
    turned out not to be the documented one. Divergence C says a *missing or
    misspelled* `action` gets fifteen cross-family op names. Across every
    edit-tool call `bench/population.py` reports under `bench/results/`, not one
    `action` was missing or misspelled: every value that arrived as its own key
    was a valid op name, and every `*-None` case was a JSON failure --
    `"action=add-item,item"` as a single fused key. A message telling that
    caller `action` is required would be false, so the fused key gets its own
    sentence. That count is `bench/action_sizing.py`'s
    output and is not restated here as a number to be checked, because a figure
    quoted into a comment is exactly how this one went stale the first time.

    The generic sentence is not dead code: the live hermes runs R2 and R4 both
    produced `list_edit` with no `action`. Both branches have a real caller,
    which is why both are asserted here.
    """
    import armb

    assert not armb.CHECK_ACTION, "the flag must ship off"
    check("the check is off by default", armb.CHECK_ACTION is False)

    # Two directions, and they are different guarantees.
    #
    # Down: every name offered is one `apply_op` would accept, so a refusal
    # cannot send the model to an op that refuses again. `_actions_from_schemes`
    # asserts this at import; restated here because that assertion only runs on
    # the schemes as they are, and this is the invariant, not the mechanism.
    #
    # Up: the offered set is exactly what the *calling tool published*, which is
    # the guarantee the old `OPS` derivation did not have -- it offered
    # `table-realign`, in `OPS` and in no published enum, so the condition would
    # have widened the offered surface as well as changing the sentence. The
    # enums are re-read from `armb.SCHEMES` rather than from `armb.ACTIONS`,
    # which is built from them; reading those back would pass vacuously.
    offered = {f"{fam}-{a}" for tool, fam in (("table_edit", "table"),
                                              ("list_edit", "list"),
                                              ("section_edit", "section"),
                                              ("frontmatter_edit",
                                               "frontmatter"))
               for a in armb.ACTIONS[tool]}
    check("every action named is a real op", offered <= set(OPS),
          offered - set(OPS))
    published = {}
    for tools in armb.SCHEMES.values():
        for t in tools:
            enum = ((t.get("parameters") or {}).get("properties")
                    or {}).get("action", {}).get("enum")
            if enum:
                published.setdefault(t["name"], set()).update(enum)
    check("every tool offers exactly the actions its schemas published",
          published == {k: set(v) for k, v in armb.ACTIONS.items()},
          (published, armb.ACTIONS))
    # The specific drift that motivated the change, named so it cannot come back
    # quietly: `OPS` had an op no tool ever offered a model. That op was
    # `table-realign`, and F-realign's gate shipped it -- 60/60 both ways on the
    # six existing table tasks, 0/29 -> 30/30 on the three ragged ones -- so the
    # assertion is now its own converse and is strictly stronger. Fifteen ops,
    # fifteen reachable, and equality in both directions: an op the enums cannot
    # reach is a capability only a CLI caller has (the old defect), and an action
    # the executor cannot run sends the model somewhere that refuses again (the
    # check above). Adding a sixteenth op without an enum entry fails here.
    offered_ops = {f"{fam}-{a}"
                   for tool, fam in (("table_edit", "table"),
                                     ("list_edit", "list"),
                                     ("section_edit", "section"),
                                     ("frontmatter_edit", "frontmatter"))
                   for a in armb.ACTIONS[tool]}
    check("every op in OPS is reachable from a published action enum",
          set(OPS) == offered_ops,
          (sorted(set(OPS) - offered_ops), sorted(offered_ops - set(OPS))))

    fused = {"action=add-item,item": "loose four", "path": "f.md"}
    omitted = {"path": "f.md", "text": "x"}
    typo = {"action": "add_row"}
    typed = {"action": 3}
    good = {"action": "add-item", "path": "f.md",
            "list": {"heading": "Plus markers"}, "text": "z"}

    # Off: every shape reaches the core exactly as it does today.
    for label, name, a, want in (
            ("fused key", "list_edit", fused, "list-None"),
            ("omission", "list_edit", omitted, "list-None"),
            ("typo", "table_edit", typo, "table-add_row"),
            ("non-string", "section_edit", typed, "section-3"),
            ("valid", "list_edit", good, "list-add-item")):
        op, _ = armb.normalize(name, a)
        check(f"off: {label} still reaches the core as {want}", op == want, op)

    armb.CHECK_ACTION = True
    try:
        def msg(name, a):
            try:
                armb.normalize(name, a)
            except armb.ArgError as e:
                return armb.err_text(e)
            return None

        m = msg("list_edit", fused)
        check("on: the fused key is named, not reported as missing",
              m is not None and m.startswith("`action=add-item,item` arrived")
              and "is required" not in m, m)
        # The value belongs to whichever key it was meant for and runs to
        # hundreds of characters; quoting it truncated would put a broken JSON
        # fragment in a refusal, so the key alone is the evidence.
        check("on: the fused message quotes no value", "loose four" not in m, m)
        # Defect 1, fixed: this used to end `Send `action` as add-item,
        # remove-item, set-checked, and repeat the other arguments.` -- a list
        # and an instruction fused into one clause, in the message whose whole
        # subject is two things fused into one. Every other branch says
        # `Valid:` or `One of:`; this one now does too.
        check("on: the fused message lists actions the way the others do",
              "Valid: add-item, remove-item, set-checked." in m
              and "as add-item, remove-item" not in m, m)
        # Defect 2, fixed: the example echoed the value the model *sent* and
        # then listed the calling tool's valid values, so a cross-family fusion
        # told the model to send a value the next line called invalid. No
        # recorded call does this -- all 21 fuse a value their own tool takes --
        # but F-front's R2 is exactly a cross-family absorption.
        cross = {"action=add-row,values": "x", "path": "f.md"}
        m2 = msg("list_edit", cross)
        check("on: a cross-family fusion does not recommend an invalid action",
              m2 is not None and '"action": "add-row"' not in m2
              and '"action": "add-item"' in m2, m2)
        check("on: it still names the key that actually arrived",
              m2.startswith("`action=add-row,values` arrived"), m2)

        m = msg("list_edit", omitted)
        check("on: a genuine omission names `action` and only this tool's ops",
              m is not None and m.startswith("`action` is required")
              and "add-item, remove-item, set-checked" in m
              and "table-add-row" not in m, m)

        m = msg("table_edit", typo)
        check("on: a typo is answered with the spelling, not a diagnosis",
              m is not None and '"add-row"' in m and "underscore" not in m, m)

        m = msg("section_edit", typed)
        check("on: a non-string action quotes what was sent",
              m is not None and "Got: 3" in m, m)

        check("on: a valid action is untouched",
              armb.normalize("list_edit", good)[0] == "list-add-item")

        # Every refusal is 5.3-shaped: statement, then two-space continuations.
        for label, name, a in (("fused", "list_edit", fused),
                               ("cross-family fused", "list_edit", cross),
                               ("omitted", "list_edit", omitted),
                               ("typo", "table_edit", typo),
                               ("typed", "section_edit", typed)):
            lines = msg(name, a).split("\n")
            check(f"on: {label} is one statement then indented continuations",
                  not lines[0].startswith(" ")
                  and all(l.startswith("  ") for l in lines[1:]), lines)

        # `err_text` is the reason a refusal does not read `ArgError: ...`.
        check("err_text drops the class name for a written refusal",
              not armb.err_text(armb.ArgError("plain")).startswith("ArgError"))
        check("err_text keeps it for a crash, where it is the useful part",
              armb.err_text(ValueError("boom")) == "ValueError: boom")
    finally:
        armb.CHECK_ACTION = False


# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# reads -- the family whose failure is a false report rather than a lost byte
# --------------------------------------------------------------------------

def _corpus_tables():
    """(rel, content, address, table) for every table in the corpus."""
    for path in corpus_files():
        content = open(path, newline="").read()
        rel = os.path.relpath(path, ROOT)
        for t, e in zip(find_tables(content), list_tables(content, rel)):
            yield rel, content, {"heading": e["heading"], "ordinal": e["ordinal"]}, t


def test_read_invariants():
    """The three read claims `invariants.rs:407-479` makes, in the oracle.

    `difftest.py` already pins `render_table_get` to the Rust on every corpus
    table, so these are not a second copy of that check. Difftest proves the two
    implementations *agree*; this proves the thing they agree on is true. Two
    ports that lost the same row would pass one and fail the other.
    """
    from incise_ops import render_table_get, table_get

    n_read = n_filter = n_render = 0
    for rel, content, addr, t in _corpus_tables():
        try:
            got = table_get(content, addr, None)
        except OpError:
            continue  # a table a read refuses -- a correct outcome, not this claim
        n_read += 1
        check(f"unfiltered read: {rel} {addr['heading']}#{addr['ordinal']}",
              got["columns"] == list(t.cells(t.header))
              and got["rows"] == t.rows()
              and got["total"] == len(t.rows())
              and got["matched"] == len(got["rows"]),
              f"{got['matched']}/{got['total']} vs {len(t.rows())} rows")

        # A filter selects; it never invents, reorders or edits. Two distinct
        # failures: a filter that rebuilds rows, and a filter that does not
        # filter. Taken from the table itself, so it must match at least once.
        if not got["rows"]:
            continue
        col, want = got["columns"][0], got["rows"][0][0]
        try:
            sub = table_get(content, addr, {col: want})
        except OpError:
            continue  # a repeated header name is refused (F-dupcol), correctly
        n_filter += 1
        idx = got["columns"].index(col)
        it = iter(got["rows"])
        check(f"filter is a matching subsequence: {rel} {addr['heading']}#{addr['ordinal']}",
              all(r in got["rows"] and r[idx] == want for r in sub["rows"])
              and all(any(x == r for x in it) for r in sub["rows"])
              and sub["matched"] == len(sub["rows"]) >= 1,
              f"{sub['rows']!r} out of {got['rows']!r}")

        # The render is the product, and it is markdown, so it can be fed back
        # through the parser. Closes on the read side what F-pipes left open on
        # the write side: a cell holding `a \| b` has to survive being written
        # into a table and read out of it again.
        text = render_table_get(content, addr, None)
        parsed = find_tables(text)
        n_render += 1
        check(f"rendered read parses back: {rel} {addr['heading']}#{addr['ordinal']}",
              len(parsed) == 1
              and list(parsed[0].cells(parsed[0].header)) == got["columns"]
              and parsed[0].rows() == got["rows"],
              f"{len(parsed)} tables parsed back")
    check("every corpus table was read", n_read >= 20, f"{n_read} reads")
    check("filters and renders were exercised", n_filter >= 15 and n_render >= 15,
          f"{n_filter} filters, {n_render} renders")


def test_read_tasks():
    """The six read tasks must be reachable and correct through `armb.grade_one`.

    `test_benchmark_tasks`'s premise, restated for reads: if an ideal call does
    not grade `correct`, every read number measures the harness. It matters more
    here than there, because the read path is new -- `table_get` is not an `OPS`
    entry, so a read reaches the executor through `armb.READS` and is graded by
    a different predicate, and neither of those existed when the six write tasks
    were written.
    """
    import armb

    tasks = json.load(open(os.path.join(ROOT, "bench/tasks/tables_read.json")))["tasks"]
    check("read task file is not empty", len(tasks) == 6, f"{len(tasks)} tasks")
    for task in tasks:
        call = task["ideal_call"]
        check(f"read task {task['id']} is a read", call["op"] == "table-get",
              call["op"])
        trial = {"tool_calls": [{"function": {
            "name": "table_get",
            "arguments": json.dumps(dict(call["args"], path=task["fixture"]))}}]}
        outcome, detail = armb.grade_one(task, trial)
        check(f"read task {task['id']}", outcome == "correct", f"{outcome}: {detail}")


def test_framings():
    """`armc.frame`: the three ways a refusal reaches a model, as the host does them.

    This guards an *unrun* condition, which is the point. `armc.replay` has only
    ever been run at `plain`, so nothing has ever exercised `json` or `cap`, and
    both were wrong in ways that would have silently become results:

      - `cap` sliced `"Error: " + err` at 2048 with no marker. The host caps the
        *message*, before the JSON encoding and with no prefix in front of it,
        and appends `"… [truncated]"`. The old form cut seven characters early
        and told the model nothing had been cut.
      - `cap` was offered as an alternative to `json` when the host composes
        them: `tool_error` bounds the body and then encodes it, so a truncated
        bare string is a program nobody runs.
      - `json` omitted `ensure_ascii=False`, which `tool_error` passes.

    The last one changes nothing on this corpus and is asserted anyway. A
    condition that exists to say what a host does is worth running only while it
    is an accurate transcription, and the cheapest time to find out it is not is
    before the GPU time, not after.
    """
    import armc

    plain = armc.frame("plain", 'no section "Setup" with ordinal 0.\n  Valid: 0, 1')

    # `run_trial` passes the literal "plain" (armc.py:352), so this framing is
    # the arm's baseline by construction. What must hold is that it does not
    # touch the message: §5.3's recovery rates were measured on these bytes, and
    # the shape -- statement, then `\n  ` continuations -- is the thing measured.
    check("plain is the prefix and the message verbatim",
          plain == 'Error: no section "Setup" with ordinal 0.\n  Valid: 0, 1')
    check("plain keeps the line structure", plain.count("\n") == 1)
    check("plain does not escape a quoted name", '\\"' not in plain)

    # What the plugin's framing actually does to a refusal, stated as the two
    # transformations rather than as "the framing moves": every newline becomes
    # a two-character escape (so a multi-line message arrives as one line), and
    # every quoted identifier is backslash-escaped.
    js = armc.frame("json", 'no section "Setup" with ordinal 0.\n  Valid: 0, 1')
    check("json is the host's wrapper",
          js == '{"error": "no section \\"Setup\\" with ordinal 0.\\n  Valid: 0, 1"}')
    check("json collapses the message to one line", "\n" not in js)
    check("json escapes every quoted name", js.count('\\"') == 2)
    check("json round-trips to the original message",
          json.loads(js)["error"]
          == 'no section "Setup" with ordinal 0.\n  Valid: 0, 1')

    # The chain. `cap` is `json` plus the bound, so below the cap they are the
    # same bytes -- which is what makes the 1-in-353 population claim checkable
    # rather than argued (`bench/refusal_pool.py` is the count).
    short = "x" * (armc.CAP - 1)
    check("at the cap, cap and json are identical",
          armc.frame("cap", short) == armc.frame("json", short))
    check("exactly at the cap, still identical",
          armc.frame("cap", "y" * armc.CAP) == armc.frame("json", "y" * armc.CAP))

    long_err = "z" * (armc.CAP + 100)
    capped = json.loads(armc.frame("cap", long_err))["error"]
    check("over the cap, the marker is appended",
          capped.endswith(armc.TRUNCATION_MARKER))
    check("the cut is at the cap, on the message, with no prefix",
          capped == "z" * armc.CAP + armc.TRUNCATION_MARKER)
    check("everything below the cut is verbatim",
          long_err.startswith(capped[:armc.CAP]))
    check("bound is a no-op at or below the cap",
          armc.bound(short) is short and armc.bound("y" * armc.CAP) == "y" * armc.CAP)

    # The refusal the cap exists for, reproduced rather than described. Two
    # things are asserted about it because the comment it replaces got the
    # second one wrong: the length, and *which part* goes. §5.3's repair line is
    # `Near matches:`, and it survives -- what the cap removes is the tail of a
    # list whose own opening still reads as exhaustive.
    api = open(os.path.join(ROOT, "corpus/documents/api-reference.md"),
               newline="").read()
    _out, err = apply_op(api, "table-add-row",
                         {"table": "zzz", "values": {"A": "1"}})
    check("the documented long refusal is still over the cap",
          err is not None and len(err) > armc.CAP, len(err or ""))
    delivered = json.loads(armc.frame("cap", err))["error"]
    check("the statement line survives", delivered.startswith('no table under heading "zzz"'))
    check("the repair line survives whole", "Near matches: none" in delivered)
    check("what is lost is the tail of the heading list",
          err[armc.CAP:].count(",") >= 3 and "Headings with tables:" in delivered,
          repr(err[armc.CAP:])[:80])

    # The transcription, against the real thing when it is installed. Same skip
    # as `plugins/hermes/test_plugin.py:230-242`, which asserts the other
    # direction: that the plugin does not truncate on its own account.
    try:
        from tools.registry import (_MAX_TOOL_ERROR_CHARS as host_cap,
                                    _bound_error_text, tool_error)
    except Exception:  # noqa: BLE001
        print("  skip  the host's cap (hermes-agent not installed)")
        return
    check("the transcribed cap is the host's", armc.CAP == host_cap, host_cap)
    check("the transcribed bound is the host's",
          all(armc.bound(s) == _bound_error_text(s)
              for s in (short, "y" * armc.CAP, long_err, err)))
    check("the cap framing is the host's tool_error", armc.frame("cap", err) == tool_error(err))
    check("the json framing is the host's tool_error below the cap",
          armc.frame("json", short) == tool_error(short))


def test_refusal_pool_rule():
    """`refusal_pool.is_artifact`: which `unknown operation` is not a refusal.

    F-framing published a population figure five times too large because it
    counted every exit-1 first call in `bench/results/` as a refusal. Most are
    not: re-executing an Arm A `patch` call, or a frontmatter call, or a read
    through the release binary asks the binary a question the row was never
    asked, and it answers `unknown operation`.

    The rule is checked here rather than by re-running the count, because the
    count is 6445 subprocesses and this is the only part of it that is a
    judgement. What it has to get right is the case a file-name blocklist gets
    wrong: `list-None` and `frontmatter-None` are implemented by **nobody**, so
    a model really did read them, and they are the only rows in the project that
    measure a call sent with no `action`. An op-name rule keeps them; a rule
    that dropped whole files would not.
    """
    import refusal_pool as rp
    from incise_ops import OPS as REFERENCE_OPS

    UNKNOWN = 'unknown operation "x". Valid: table-add-row, …'
    REAL = 'no table under heading "zzz".\n  Near matches: none'

    # artifacts: the executor that produced the row implemented the op
    for op in ("patch", "frontmatter-set", "frontmatter-delete",
               "table_get", "frontmatter_get"):
        check(f"{op} is an artifact", rp.is_artifact(op, UNKNOWN) is True)

    # genuine: nobody implements these, so the refusal is one a model really read
    for op in ("list-None", "frontmatter-None", "table-None", "section-updat"):
        check(f"{op} is a real refusal", rp.is_artifact(op, UNKNOWN) is False)

    # a real refusal is never an artifact, whatever op produced it
    for op in ("table-add-row", "patch", "frontmatter-set"):
        check(f"a non-unknown-operation error from {op} is real",
              rp.is_artifact(op, REAL) is False)

    # the rule has to cover every op the reference implements, not a list that
    # drifts when a family is added
    check("every reference op is an artifact when the core does not know it",
          all(rp.is_artifact(op, UNKNOWN) for op in REFERENCE_OPS))


def test_realign_width_refusal_keeps_its_promise():
    """The width refusal makes a factual claim, and nothing checked it.

    `table-realign` counts column width in characters, so a table holding a cell
    it cannot measure that way -- CJK, fullwidth forms, combining marks, emoji --
    is declined rather than re-padded to a count that is ragged on screen. The
    last line of that refusal is a remedy:

        Realign is refused. Add, update and delete still work on this table and
        leave its existing lines byte-for-byte intact.

    Until F-realign that sentence was read by operators. `table_edit` now
    publishes `action=realign`, so a model can draw it, which makes it product
    text under REQUIREMENTS §5.3 on a path no arm has measured -- `headroom.py`
    prices it at k=0 of 2217, and no fixture provokes it.

    That is precisely the F-remedy class: a refusal whose remedy is unchecked is
    a refusal that may send a model somewhere that refuses again. So the claim is
    asserted here instead of measured. All three named actions must work, and
    the rows they did not touch must come back byte-for-byte -- including the
    ragged padding, which is the whole reason realign declined.
    """
    from incise_ops import apply_op

    # Ragged on purpose: `Name` is padded to 6 and `Width` to 5, and the body
    # rows are padded to neither. A realign is exactly what this table wants.
    doc = (
        "| Name   | Width |\n"
        "| --- | --- |\n"
        "| plain | narrow |\n"
        "| 値 | wide |\n"
    )
    addr = {"table": {"heading": None}}

    out, err = apply_op(doc, "table-realign", dict(addr))
    check("realign refuses a table it cannot measure", out is None and bool(err))
    check("and the refusal names the character it could not measure",
          bool(err) and '"値"' in err, err)
    check("and it ends with the remedy this test exists to check",
          bool(err) and err.rstrip().endswith(
              "Add, update and delete still work on this table and leave its "
              "existing lines byte-for-byte intact."), err)

    untouched = doc.split("\n")[:4]   # every line the table already has
    for op, args, keep in (
        ("table-add-row", {"values": {"Name": "new", "Width": "narrow"}}, 4),
        ("table-update-cell", {"where": {"Name": "plain"},
                               "column": "Width", "value": "changed"}, 2),
        ("table-delete-row", {"where": {"Name": "値"}}, 3),
    ):
        got, err = apply_op(doc, op, dict(addr, **args))
        check(f"{op} still works on a table realign declined",
              got is not None, err)
        if got is None:
            continue
        # `keep` is how many of the first three lines this op leaves alone:
        # update-cell rewrites the `plain` row, delete-row removes a later one,
        # add-row appends. None of them may re-pad what they did not edit.
        check(f"{op} leaves the lines it did not edit byte-for-byte intact",
              got.split("\n")[:keep] == untouched[:keep],
              got.split("\n")[:keep])


def test_read_grading():
    """Every rung of `check_table_read_result`, on one task, by construction.

    Written against the ladder rather than against recorded trials because no
    read trial exists yet: this is the grader that will decide what the first
    read arm measured, and a grader nobody has seen fail is a grader nobody has
    seen. Each case below is the *only* thing wrong with an otherwise correct
    answer, so a rung that stopped firing would show up as one failure and not
    as a cascade.
    """
    import armb

    tasks = {t["id"]: t for t in json.load(
        open(os.path.join(ROOT, "bench/tasks/tables_read.json")))["tasks"]}
    task = tasks["get-filter-one-column"]          # 2 of 5 rows, Priority=high
    fixture = os.path.join(ROOT, task["fixture"])
    ideal = dict(task["ideal_call"]["args"], path=task["fixture"])

    def trial(*calls):
        return {"tool_calls": [
            {"function": {"name": n, "arguments": json.dumps(a)}} for n, a in calls]}

    def grade(*calls):
        return armb.grade_one(task, trial(*calls))

    check("correct: the ideal read", grade(("table_get", ideal))[0] == "correct",
          grade(("table_get", ideal)))
    check("malformed: no call at all",
          armb.grade_one(task, {"tool_calls": []})[0] == "malformed")
    # An edit tool on a read task, refused by the core. The document is where it
    # was and no read happened, so what the trial has to show for itself is a
    # refusal -- which is `op_error` here exactly as it is on an edit task. Only
    # a trial that made a call and got nothing back at all is `malformed`.
    check("op_error: an edit tool, refused, and nothing read",
          grade(("table_edit", {"action": "add-row", "path": task["fixture"],
                                "table": {"heading": "Packages"},
                                "values": []}))[0] == "op_error")

    # A read task is never satisfied by an edit, and the two severities the
    # taxonomy already draws still apply: a lost line outranks a gained one.
    check("collateral:content: a read that added a row",
          grade(("table_edit", {"action": "add-row", "path": task["fixture"],
                                "table": {"heading": "Packages"},
                                "values": ["zulu", "0.1", "2020-01-01", "0", "high"]}),
                ("table_get", ideal))[0] == "collateral:content",
          grade(("table_edit", {"action": "add-row", "path": task["fixture"],
                                "table": {"heading": "Packages"},
                                "values": ["zulu", "0.1", "2020-01-01", "0", "high"]}),
                ("table_get", ideal)))
    check("destructive: a read that deleted a row",
          grade(("table_edit", {"action": "delete-row", "path": task["fixture"],
                                "table": {"heading": "Packages"},
                                "where": {"Name": "alpha"}}),
                ("table_get", ideal))[0] == "destructive")

    check("op_error: every read refused",
          grade(("table_get", dict(ideal, table={"heading": "No Such Table"})))[0]
          == "op_error")
    check("op_error is the last refusal, not the first",
          "No Such Table" in str(grade(
              ("table_get", dict(ideal, table={"heading": "Nonexistent"})),
              ("table_get", dict(ideal, table={"heading": "No Such Table"})))[1]))
    check("a refusal then a good read is recovery, not failure",
          grade(("table_get", dict(ideal, table={"heading": "No Such Table"})),
                ("table_get", ideal))[0] == "correct")

    check("misreported: the wrong table",
          grade(("table_get", dict(ideal, table={"heading": "Stability"},
                                   filter={"Group": "b"})))[0] == "misreported")
    check("misreported: the wrong filter value",
          grade(("table_get", dict(ideal, filter={"Priority": "low"})))[0]
          == "misreported")
    check("unfiltered: the right table, no filter",
          grade(("table_get", {"path": task["fixture"],
                               "table": {"heading": "Packages"}}))[0] == "unfiltered")

    # `where` is `table_read_naive`'s spelling and must reach the same place,
    # or that scheme would measure the rename rather than the word.
    check("the naive scheme's `where` is the same filter",
          grade(("table_get", {"path": task["fixture"],
                               "table": {"heading": "Packages"},
                               "where": {"Priority": "high"}}))[0] == "correct")

    # The rungs the fixture cannot reach: a port that miscounts while returning
    # the right rows, and one whose `matched` contradicts them. Fed to the
    # predicate directly, because no argument to `table_get` produces them.
    from grade import check_result

    before = open(fixture, newline="").read()
    good = {"heading": task["expect_heading"], "columns": task["expect_columns"],
            "rows": task["expect_rows"], "matched": len(task["expect_rows"]),
            "total": task["expect_total"]}
    check("misreported: `total` overstates the table",
          check_result(task, before, before, dict(good, total=good["total"] + 1))[0]
          == "misreported")
    check("misreported: `matched` disagrees with the rows",
          check_result(task, before, before, dict(good, matched=99))[0]
          == "misreported")
    check("misreported: the right rows in the wrong order",
          check_result(task, before, before,
                       dict(good, rows=list(reversed(good["rows"]))))[0]
          == "misreported")
    check("correct: the structure the task records",
          check_result(task, before, before, good)[0] == "correct")


def main():
    for fn in (test_benchmark_tasks, test_corpus_roundtrip, test_outside_bytes_untouched,
               test_widen_never_shrink, test_alignment_markers_survive,
               test_crlf_preserved, test_ordered_values, test_string_address,
               test_stringified_arguments, test_refusals,
               test_list_goldens, test_list_roundtrip, test_numbering_styles,
               test_marker_and_indent_inference, test_loose_list_spacing,
               test_checkbox_handling, test_list_refusals,
               test_list_address_fields_are_checked,
               test_heading_identity, test_fence_scanners_agree,
               test_frontmatter_is_not_content, test_link_reference_footer,
               test_section_goldens,
               test_section_grader, test_section_roundtrip,
               test_section_spans, test_heading_syntax_preserved,
               test_section_level_changes, test_section_refusals,
               test_destructive_action_guards, test_insert_body_and_children,
               test_close_matches_tracks_stdlib,
               test_describe_change, test_section_crlf,
               test_frontmatter_goldens, test_frontmatter_roundtrip,
               test_frontmatter_touches_one_line, test_frontmatter_states,
               test_frontmatter_refusals, test_frontmatter_existence_guards,
               test_frontmatter_read, test_frontmatter_read_scheme,
               test_tasks_are_regenerable,
               test_action_check,
               test_file_argument_is_inert,
               test_framings,
               test_refusal_pool_rule,
               test_read_invariants, test_read_tasks,
               test_realign_width_refusal_keeps_its_promise,
               test_read_grading):
        print(f"\n{fn.__name__}")
        fn()
    print(f"\n{'-'*60}")
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {', '.join(FAILURES[:5])}")
        return 1
    print("all invariants hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
