#!/usr/bin/env python3
"""Mutation test for the differential harness (`bench/difftest.py`).

`difftest.py` reported 2738/2738 agreement on its first run. A test suite that
has never failed has not been shown to work -- the agreement is equally
consistent with a faithful port and with a harness that compares nothing. This
script settles that: it injects one deliberate fault into the Rust core at a
time, reruns the differential test, and asserts that the fault is caught.

A mutation that survives is a fact about coverage, not a pass. It means no case
in the corpus reaches that line with inputs that distinguish the two versions,
which is a gap in the *corpus*, and it gets reported as SURVIVED so the gap is
visible rather than implied.

  python3 bench/mutate.py           # run all mutations
  python3 bench/mutate.py -k width  # only mutations whose name contains "width"

Runs are mutually exclusive (`crates/.mutate.lock`): the script edits the crate
in place, so a second concurrent run would restore the first one's mutation as
if it were the original.

Each mutation is a literal (file, before, after) triple; `before` must occur
exactly once, or the mutation is reported as STALE rather than silently
applying to the wrong place or to nothing -- which is exactly how a mutation
test lies to you.
"""

import argparse
import contextlib
import os
import re
import signal
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE = os.path.join(ROOT, "crates", "incise-core", "src")
LOCK = os.path.join(ROOT, "crates", ".mutate.lock")


@contextlib.contextmanager
def exclusive():
    """Refuse to start while another run holds the tree.

    This script edits the crate's sources in place, so two runs racing each
    other restore the *other* run's mutation as if it were the original and
    leave the tree dirty. It happened: two overlapping full runs produced eight
    bogus STALEs and left four mutations applied, and the second run's results
    were meaningless from the first collision onward.
    """
    try:
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        print(f"another run holds {LOCK}.")
        print("  Wait for it, or delete the file if no mutate.py is running.")
        raise SystemExit(2)
    os.write(fd, f"{os.getpid()}\n".encode())
    os.close(fd)
    try:
        yield
    finally:
        os.unlink(LOCK)


def src(*parts):
    return os.path.join(CORE, *parts)


# (name, file, before, after, what it should break)
MUTATIONS = [
    # -- rendering: the re-pad path, scored 0/10 by the model (§11 Tier 1) ----
    ("width-padding", src("ops", "table.rs"),
     "                + 2;", "                + 1;",
     "aligned cells lose a pad space"),
    ("width-floor", src("ops", "table.rs"),
     "need.max(existing.get(i).copied().unwrap_or(0)).max(5)",
     "need.max(existing.get(i).copied().unwrap_or(0)).max(4)",
     "minimum column width drops below the delimiter's"),
    ("width-shrink", src("ops", "table.rs"),
     "need.max(existing.get(i).copied().unwrap_or(0)).max(5)",
     "need.max(5)",
     "widen-never-shrink is abandoned"),
    ("width-bytes", src("ops", "table.rs"),
     ".map(|r| at(r, i).chars().count())", ".map(|r| at(r, i).len())",
     "non-ASCII cells are measured in bytes"),
    ("loose-row", src("ops", "table.rs"),
     'format!("| {} |", cells.join(" | "))',
     'format!("| {} |", cells.join(" |"))',
     "ragged insertion drops a space"),
    ("crlf", src("ops", "table.rs"),
     'Ok(if crlf { "\\r" } else { "" })', 'Ok("")',
     "a CRLF table is rewritten as LF"),

    # -- refusal text: §5.3 makes the message part of the contract -----------
    ("refusal-wording", src("ops", "table.rs"),
     "  `where` must match one row exactly. Drop the columns you are not \\\n"
     "sure of, and keep enough to be unique.",
     "  `where` must match exactly one row. Drop the columns you are not \\\n"
     "sure of, and keep enough to be unique.",
     "a refusal sentence is reworded"),
    ("near-cutoff", src("ops", "table.rs"),
     "let near = get_close_matches(val, &vals, 3, 0.4);",
     "let near = get_close_matches(val, &vals, 3, 0.6);",
     "near-match suggestions get stricter"),
    ("near-count", src("ops", "table.rs"),
     "let near = get_close_matches(want_h, &headings, 3, 0.4);",
     "let near = get_close_matches(want_h, &headings, 2, 0.4);",
     "one fewer heading suggestion is offered"),

    # -- the difflib port itself --------------------------------------------
    ("difflib-tiebreak", src("similar.rs"),
     "            .then_with(|| y.1.cmp(x.1))",
     "            .then_with(|| x.1.cmp(y.1))",
     "equal-ratio candidates come back in the wrong order"),

    # -- parsers -------------------------------------------------------------
    ("section-end", src("heading.rs"),
     "        sections[n].end = trim_blank(",
     "        sections[n].own_end = trim_blank(",
     "a section's span stops at its own body"),
]

# -- the argument layer (FINDINGS F-args) -----------------------------------
# These exist because the layer has no corpus coverage by construction: every
# case generated from a document is well-typed. The `check_args` and `py_repr`
# case families in difftest.py are hand-written, so they are exactly the kind of
# test that can be green and empty, and these mutations are the check on that.
MUTATIONS += [
    ("arg-string-index", src("args.rs"),
     'if let Some(n) = py_int_from_str(&low) {\n                if fam == PosFamily::List {\n                    return refuse_index(value.unwrap());\n                }\n                return Ok(Position::Index(n));',
     'if let Some(_n) = py_int_from_str(&low) {\n                if fam == PosFamily::List {\n                    return refuse_index(value.unwrap());\n                }\n                return Ok(Position::End);',
     'position: "0" goes back to silently appending at the end'),
    # A guard rather than a deletion, so the arm falls through to the catch-all
    # and the match stays exhaustive. A mutation that does not compile measures
    # nothing.
    ("arg-bool-cell", src("args.rs"),
     "        Value::Bool(_) => Err(OpError::new(format!(",
     "        Value::Bool(_) if false => Err(OpError::new(format!(",
     "a boolean is written into the cell instead of refused"),
    ("arg-where-shape", src("args.rs"),
     "        None | Some(Value::Null) | Some(Value::Object(_)) => Ok(value),",
     "        None | Some(Value::Null) | Some(Value::Object(_)) | Some(_) => Ok(value),",
     "a non-object `where` is waved through"),
    ("arg-quoted-keys", src("args.rs"),
     "if bytes.len() > 1 && bytes[0] == b'\"' && bytes[bytes.len() - 1] == b'\"' {",
     "if false {",
     "stray quotes stay on object keys"),
    ("arg-ordinal-strict", src("args.rs"),
     "            if let Some(n) = py_int_from_str(s) {\n                return Ok(Some(n));",
     "            if let Some(_n) = py_int_from_str(s) {\n                return Ok(None);",
     'ordinal: "0" is read as no ordinal at all'),
    ("arg-bigint", src("args.rs"),
     "        Value::BigInt(s) => Some(PyInt::Big(s.clone())),",
     "        Value::BigInt(_) => None,",
     "an integer too large for i64 is refused instead of carried"),

    # -- json.rs, which writes every `Got:` line -----------------------------
    ("json-float-fixed", src("json.rs"),
     "pub fn py_float_repr(f: f64) -> String {",
     "pub fn py_float_repr(f: f64) -> String {\n    if true {\n        return format!(\"{f}\");\n    }",
     "Python's repr rules for floats are replaced by Rust's Display"),
    ("json-infinity", src("json.rs"),
     'b\'I\' => lit(b, i, "Infinity", Value::Float(f64::INFINITY)),',
     "b'I' => None,",
     "CPython's `Infinity` constant stops parsing"),
    ("json-repr-quote", src("json.rs"),
     "pub fn py_repr_str(s: &str) -> String {",
     "pub fn py_repr_str(s: &str) -> String {\n    if true {\n        return format!(\"{s:?}\");\n    }",
     "Python's repr quoting is replaced by Rust's Debug"),

    # --- dispatch ordering -------------------------------------------------
    # The ordering `ops/dispatch.rs` transcribes is not derivable from Rust, so
    # these are the mutations that ask whether it is actually being tested. The
    # first two are the two mistakes that were really made and really caught by
    # the `apply_op` case family on the run that introduced it.
    ("disp-column-early", src("ops", "dispatch.rs"),
     "            table_update_cell(content, &address, &selector, a.get(\"column\"), a.get(\"value\"))",
     "            let _c = crate::args::check_column(a.get(\"column\"))?;\n"
     "            table_update_cell(content, &address, &selector, a.get(\"column\"), a.get(\"value\"))",
     "`column` is checked at the dispatch instead of inside the op"),
    ("disp-values-shape", src("ops", "dispatch.rs"),
     "        Some(other) => Values::Other(other),",
     "        Some(_other) => Values::Ordered(Vec::new()),",
     "a `values` that is neither shape collapses into `a row is required`"),
    ("disp-position-early", src("ops", "dispatch.rs"),
     "            table_add_row(content, &address, &values, a.get(\"position\"))",
     "            let _p = crate::args::check_position(a.get(\"position\"))?;\n"
     "            table_add_row(content, &address, &values, a.get(\"position\"))",
     "`position` is checked before the table instead of after the cells"),
    # The error the survived `disp-values-late` led to: `check_heading` and
    # `check_ordinal` are statements inside `resolve_table`, not part of
    # extracting the address. Checking a field early is invisible unless another
    # argument is also bad, which is why this mutation and the cases that catch
    # it arrived together.
    ("disp-heading-early", src("ops", "dispatch.rs"),
     "            let address = to_address(args::address(a)?);\n"
     "            let values = to_values(args::values(a, \"values\")?);",
     "            let address = to_address(args::address(a)?);\n"
     "            args::check_heading(address.heading.as_ref(), \"table\")?;\n"
     "            let values = to_values(args::values(a, \"values\")?);",
     "`table.heading` is checked at the dispatch instead of in the resolver"),
    ("disp-values-late", src("ops", "dispatch.rs"),
     "            let address = to_address(args::address(a)?);\n"
     "            let values = to_values(args::values(a, \"values\")?);",
     "            let values = to_values(args::values(a, \"values\")?);\n"
     "            let address = to_address(args::address(a)?);",
     "`address` and `values` swap places in the lambda"),
    ("disp-value-default", src("args.rs"),
     "        None => Err(OpError::new(\n"
     "            \"`value` is required: it is the text the cell becomes.\\n  Send \\\"\\\" to empty the cell.\",\n"
     "        )),",
     "        None => Ok(String::from(\"None\")),",
     "an absent `value` goes back to writing the literal string \"None\""),
    ("disp-truthiness", src("json.rs"),
     "        Value::Int(i) => *i != 0,",
     "        Value::Int(_) => true,",
     "Python truthiness of `0` is dropped, so `values: 0` reports the wrong repair"),

    # -- escaped pipes: the defect that shipped through all of Tier 1 --------
    ("split-naive", src("table.rs"),
     "        if c == '\\\\' {\n"
     "            // The escaped character, whatever its width. A trailing backslash\n"
     "            // escapes nothing and stays content, as it does in the oracle.\n"
     "            it.next();\n"
     "        } else if c == '|' {",
     "        if c == '|' {",
     "`\\|` splits a row, as it did before the fix"),
    ("split-one-byte", src("table.rs"),
     "            it.next();\n"
     "        } else if c == '|' {",
     "        } else if c == '|' {",
     "the escape consumes the backslash but not the character after it"),
    ("split-escape-pipe-only", src("table.rs"),
     "        if c == '\\\\' {\n"
     "            // The escaped character, whatever its width. A trailing backslash\n"
     "            // escapes nothing and stays content, as it does in the oracle.\n"
     "            it.next();",
     "        if c == '\\\\' && s[i + 1..].starts_with('|') {\n"
     "            it.next();",
     "a backslash escapes only a pipe, so `\\\\|` reads as an escaped separator"),
    ("rect-off", src("ops", "table.rs"),
     "    let table = locate_table(content, address)?;\n"
     "    check_rectangular(&table, false)?;",
     "    let table = locate_table(content, address)?;",
     "a table whose rows disagree with its header is edited anyway"),
    ("rect-place", src("ops", "table.rs"),
     'format!("row {}", i - 1)', 'format!("row {}", i)',
     "the row number in the not-rectangular refusal goes 1-based off by one"),
    ("rect-header", src("ops", "table.rs"),
     "    let want = counts[0];", "    let want = counts[1];",
     "the delimiter, not the header, decides the column count"),
    ("cell-pipe-off", src("args.rs"),
     "    if has_bare_pipe(&text) {", "    if false {",
     "a bare `|` goes back to silently starting a new column"),
    ("cell-newline-off", src("args.rs"),
     "    if text.contains('\\n') || text.contains('\\r') {", "    if false {",
     "a line break in a cell goes back to silently ending the table"),
    ("cell-pipe-naive", src("args.rs"),
     "        if c == '\\\\' {\n"
     "            it.next();\n"
     "        } else if c == '|' {",
     "        if c == '|' {",
     "`\\|` is refused too, so a literal pipe becomes unwritable"),

    # -- realign: the one op allowed to rewrite lines nobody named (§6.2) ----
    ("realign-floor", src("ops", "table.rs"),
     "    let new_lines: Vec<String> = if realign {\n"
     "        render_aligned(header, &markers, body, &[])",
     "    let new_lines: Vec<String> = if realign {\n"
     "        render_aligned(header, &markers, body, &table.widths()[0])",
     "realign inherits a width floor from the damaged table it is repairing"),
    ("realign-noop-off", src("ops", "table.rs"),
     "    if table.is_aligned() && !table.has_tabs() {\n"
     "        return Ok(content.to_string());",
     "    if false {\n"
     "        return Ok(content.to_string());",
     "an already-aligned table is re-rendered, shrinking the author's padding"),
    ("realign-tabs-noop", src("ops", "table.rs"),
     "    if table.is_aligned() && !table.has_tabs() {",
     "    if table.is_aligned() {",
     "a tab-padded table counts as aligned, so realign can never repair it"),
    ("realign-width-off", src("ops", "table.rs"),
     "    check_realignable(&table)?;", "    ",
     "a display-width-padded table is re-padded by character count"),
    ("realign-width-narrow", src("ops", "table.rs"),
     "    (0x4E00, 0x9FFF),   // CJK unified ideographs",
     "    (0x4E00, 0x4E00),   // CJK unified ideographs",
     "the CJK range shrinks to one character, so most ideographs read as narrow"),
    ("realign-width-broad", src("ops", "table.rs"),
     "fn not_one_column(c: char) -> bool {\n"
     "    let n = c as u32;",
     "fn not_one_column(c: char) -> bool {\n"
     "    if c as u32 > 127 { return true; }\n"
     "    let n = c as u32;",
     "the guard goes back to refusing any non-ASCII table, em dashes included"),
    # Anchored on the `i + 1` argument together with the line below it: `i + 1`
    # alone occurs several times in this file, and a mutation that can land in
    # more than one place is one that reports on a line it did not test.
    ("row-index", src("ops", "table.rs"),
     "            i + 1,\n            good.join(\", \"),",
     "            i,\n            good.join(\", \"),",
     "the 1-based row number in a refusal goes 0-based"),

    # -- table-get: the read op, where the failure is a false report ---------
    # A read cannot corrupt the document, so every fault here is a statement
    # about a file that is not true -- which is worse than a refusal and much
    # harder to notice, because the output still looks like a table.
    ("get-filter-off", src("ops", "table.rs"),
     "        .filter(|r| supplied.iter().all(|(k, v)| cell_of(&cols, r, k) == v.as_str()))",
     "        .filter(|_r| true)",
     "the filter is accepted and ignored, so every read returns the whole table"),
    ("get-filter-any", src("ops", "table.rs"),
     "        .filter(|r| supplied.iter().all(|(k, v)| cell_of(&cols, r, k) == v.as_str()))",
     "        .filter(|r| supplied.iter().any(|(k, v)| cell_of(&cols, r, k) == v.as_str()))",
     "a multi-column filter matches on any column instead of all of them"),
    ("get-total", src("ops", "table.rs"),
     "    let total = rows.len();", "    let total = rows.len() + 1;",
     "the `of M rows` count overstates the table by one"),
    ("get-rect-off", src("ops", "table.rs"),
     "    check_rectangular(&table, true)?;", "    ",
     "a read reports cells it cannot map to columns rather than refusing"),
    ("get-read-wording", src("ops", "table.rs"),
     '"incise will not report cells it cannot map to columns"',
     '"incise will not rewrite a table it cannot read"',
     "a read borrows the write path's refusal and claims it was going to write"),
    ("get-keyed-rows", src("ops", "table.rs"),
     "        .filter(|r| supplied.iter().all(|(k, v)| cell_of(&cols, r, k) == v.as_str()))\n"
     "        .collect();",
     "        .filter(|r| supplied.iter().all(|(k, v)| cell_of(&cols, r, k) == v.as_str()))\n"
     "        .map(|r| cols.iter().map(|c| cell_of(&cols, &r, c).to_string()).collect())\n"
     "        .collect();",
     "rows go back through name lookup, so a repeated header reports one cell twice"),
    # Reachable only since the `args` hatch. The flat wire format carries string
    # values and nothing else, so before it no case could put a boolean, a null,
    # an array or an object under a filter key, and this branch answered nobody.
    #
    # Confined to the non-string arms on purpose. The obvious mutation -- coerce
    # every filter value with `py_repr` -- was caught by 207 cases *without* the
    # new ones, because `py_repr` quotes a string and every ordinary filter then
    # stops matching. That mutation measures the string path, which was never in
    # question. This one is a no-op on every case that existed before.
    #
    # Numbers are not in it either: `check_cell` already accepts an `Int` or a
    # `Float` and stringifies it (args.rs), so coercing those is what the code
    # does. What it refuses is `Bool`, `Null`, `Array` and `Object`, and those
    # four are the mutation.
    ("filter-value-typed", src("ops", "table.rs"),
     '            .map(|(k, v)| check_cell(v, k, "filter").map(|c| (k.clone(), c)))',
     "            .map(|(k, v)| match v {\n"
     '                json::Value::Str(_) => check_cell(v, k, "filter").map(|c| (k.clone(), c)),\n'
     "                other => Ok((k.clone(), json::py_repr(other))),\n"
     "            })",
     "a filter value that is not text is coerced instead of refused"),
    ("get-empty-columns", src("ops", "table.rs"),
     '            "{head}\\n  No row matches.\\n  Columns: {}",',
     '            "{head}\\n  No row matches.{}",',
     "a zero-match read stops naming the columns the caller got wrong"),
    ("get-plural", src("ops", "table.rs"),
     "        if got.total == 1 { \"\" } else { \"s\" }",
     "        if got.matched == 1 { \"\" } else { \"s\" }",
     "the row/rows plural follows the match count, not the total it is attached to"),

    # -- the duplicate-column guard (FINDINGS F-dupcol) ----------------------
    ("dupcol-off", src("ops", "table.rs"),
     "    if n > 1 {", "    if false {",
     "a repeated header name silently resolves to the first such column again"),
    ("dupcol-threshold", src("ops", "table.rs"),
     "    if n > 1 {", "    if n > 0 {",
     "the guard fires on every column, so no table can be addressed by name"),
    ("dupcol-count", src("ops", "table.rs"),
     "            \"the column \\\"{name}\\\" appears {n} times in this table's header,"
     " so it does not identify one cell.\\n  Columns: {}\\n  Rename one of them in the"
     " document, then retry.\",\n"
     "            cols.join(\" | \")",
     "            \"the column \\\"{name}\\\" appears {} times in this table's header,"
     " so it does not identify one cell.\\n  Columns: {}\\n  Rename one of them in the"
     " document, then retry.\",\n"
     "            n + 1,\n"
     "            cols.join(\" | \")",
     "the refusal misreports how many times the column appears"),

    # -- `filter` argument validation ----------------------------------------
    ("filter-shape-off", src("args.rs"),
     "        Some(Value::Object(pairs)) => Ok(Some(pairs)),\n"
     "        Some(v) => Err(OpError::new(format!(",
     "        Some(Value::Object(pairs)) => Ok(Some(pairs)),\n"
     "        Some(_) => Ok(None),\n"
     "        #[allow(unreachable_patterns)]\n"
     "        Some(v) => Err(OpError::new(format!(",
     "an ill-shaped `filter` is discarded rather than refused, and reads everything"),
    ("filter-empty-null", src("args.rs"),
     "pub fn check_filter(value: Option<&Value>) -> Result<Option<&Vec<(String, Value)>>> {\n"
     "    match value {\n"
     "        None | Some(Value::Null) => Ok(None),",
     "pub fn check_filter(value: Option<&Value>) -> Result<Option<&Vec<(String, Value)>>> {\n"
     "    match value {\n"
     "        None => Ok(None),",
     "an explicit null `filter` falls through to the shape refusal"),
]

# -- lists (Tier 2b) ---------------------------------------------------------
# The list family arrived with 19k new differential cases and 0 mismatches,
# which is the same claim the table family made on its first run and which meant
# nothing until these existed. Three layers get mutated because three layers can
# be wrong independently: the run parser (which lines are one list), the
# conventions (what an inserted item copies from its neighbours), and the
# dispatch (which argument wins).
#
# Two of them are aimed at defects that were really made and really shipped for
# a while -- `list-mixnum` is FINDINGS F-mixnum, where a bullet among ordered
# siblings was arithmetic on `None`, and `list-checkbox-head` is the one-byte
# `m.group(3) or ""` the port first wrote as `or " "`.
MUTATIONS += [
    # -- the run parser: where one list stops and the next begins ------------
    ("list-indent-code", src("list.rs"),
     "            Some(m) if expanded_width(m.indent) < 4 => {",
     "            Some(m) if expanded_width(m.indent) < 8 => {",
     "a four-space-indented block is read as a list rather than as code"),
    ("list-two-blanks", src("list.rs"),
     "            if blanks >= 2 {",
     "            if blanks >= 3 {",
     "two blank lines stop ending a run, so a following list joins it"),
    ("list-loose-detect", src("list.rs"),
     "        .any(|n| (items[n].end + 1..items[n + 1].start).any(|k| py_strip(lines[k]).is_empty()));",
     "        .any(|n| (items[n].end + 2..items[n + 1].start).any(|k| py_strip(lines[k]).is_empty()));",
     "one blank line between items no longer makes the run loose"),
    ("list-subtree-span", src("list.rs"),
     "            if items[k].depth <= items[n].depth {",
     "            if items[k].depth < items[n].depth {",
     "an item's span swallows the sibling after it"),
    ("list-parent-stack", src("list.rs"),
     "        while stack.last().map_or(false, |(w, _)| *w >= ind) {",
     "        while stack.last().map_or(false, |(w, _)| *w > ind) {",
     "items at equal indent are nested under each other"),
    ("list-text-rstrip", src("list.rs"),
     "        text: rest.trim_end_matches(|c: char| c.is_whitespace()).to_string(),",
     "        text: rest.to_string(),",
     "an item's text keeps its trailing whitespace, and a CRLF one its \\r"),

    # -- the two regexes the parser is built on ------------------------------
    ("list-checkbox-space", src("scan.rs"),
     "        _ if b[3] == b' ' => Some((b[1] as char, 4)),",
     "        _ if b[3] == b' ' || true => Some((b[1] as char, 4)),",
     "`[ ]no space` becomes a task item that set-checked will rewrite"),
    ("list-checkbox-state", src("scan.rs"),
     "!matches!(b[1], b' ' | b'x' | b'X')",
     "!matches!(b[1], b' ' | b'x' | b'X' | b'y')",
     "`[y]` is read as a checkbox"),
    ("list-digit-limit", src("scan.rs"),
     "        if digits == 0 || digits > 9 {",
     "        if digits == 0 {",
     "a ten-digit run is accepted as an ordered marker"),

    # -- the conventions: what an inserted item copies ------------------------
    ("list-mixnum", src("ops", "list.rs"),
     "    if nums.iter().any(|n| n.is_none()) {\n"
     "        return Style::Irregular;\n"
     "    }\n"
     "    let v: Vec<i64> = nums.iter().map(|n| n.unwrap()).collect();",
     "    let v: Vec<i64> = nums.iter().map(|n| n.unwrap_or(0)).collect();",
     "a bullet among ordered siblings counts as number 0 (F-mixnum)"),
    ("list-constant-style", src("ops", "list.rs"),
     "        return Style::Constant;",
     "        return Style::Sequential;",
     "an all-ones list is renumbered 1, 2, 3"),
    ("list-sequential-style", src("ops", "list.rs"),
     "    if v.iter().enumerate().all(|(k, n)| *n == v[0] + k as i64) {",
     "    if v.iter().enumerate().all(|(_k, n)| *n >= v[0]) {",
     "an irregular 1, 3, 7 group is read as sequential and renumbered"),
    ("list-group-start", src("ops", "list.rs"),
     "    nums.iter().find_map(|n| *n).or(fallback)",
     "    fallback.or(nums.iter().find_map(|n| *n))",
     "renumbering counts from the anchor's number, not the group's first"),
    ("list-eol-cr", src("ops", "list.rs"),
     '        (true, false) => Ok("\\r"),',
     '        (true, false) => Ok(""),',
     "an item inserted into a CRLF list gets a bare LF"),
    ("list-marker-gap", src("ops", "list.rs"),
     '        Some(m) => m.gap.unwrap_or(" ").to_string(),',
     '        Some(_m) => " ".to_string(),',
     "the gap after the marker is assumed to be one space rather than copied"),
    ("list-add-loose-blank", src("ops", "list.rs"),
     "        if insert_at > lst.items[anchor].start {",
     "        if insert_at >= lst.items[anchor].start {",
     "the loose blank line goes above an item inserted at the top of the list"),
    ("list-add-after-span", src("ops", "list.rs"),
     '        let anchor = resolve_item(&lst, after, "after")?;\n'
     "        (anchor, lst.items[anchor].end + 1)",
     '        let anchor = resolve_item(&lst, after, "after")?;\n'
     "        (anchor, lst.items[anchor].own_end + 1)",
     "`after` a parent lands between its children instead of past them"),
    ("list-add-append-depth", src("ops", "list.rs"),
     "            .filter(|(_, it)| it.depth == 0)",
     "            .filter(|(_, _it)| true)",
     "a plain append anchors on the last item at any depth, so it nests"),
    ("list-checkbox-infer", src("ops", "list.rs"),
     "    } else if !group.is_empty() && group.iter().all(|i| lst.items[*i].checkbox.is_some()) {",
     "    } else if !group.is_empty() && group.iter().any(|i| lst.items[*i].checkbox.is_some()) {",
     "a checkbox is inferred for a mixed group, not only an all-task one"),

    # -- the edits ------------------------------------------------------------
    ("list-add-text-strip", src("ops", "list.rs"),
     "    let text = match text.map(py_strip) {",
     "    let text = match text.map(|t| t) {",
     "the new item keeps the whitespace around its text"),
    ("list-add-checked-null", src("ops", "list.rs"),
     "    let checked = checked.filter(|v| !matches!(v, json::Value::Null));",
     "    let checked = checked;",
     'an explicit `checked: null` unticks instead of meaning "infer"'),
    ("list-remove-loose", src("ops", "list.rs"),
     "    if lst.loose {\n"
     "        // Take one separating blank line with the item, or the list grows a",
     "    if false {\n"
     "        // Take one separating blank line with the item, or the list grows a",
     "removing from a loose list leaves the separating blank line behind"),
    ("list-remove-subtree", src("ops", "list.rs"),
     "    let (mut lo, mut hi) = (it.start, it.end);",
     "    let (mut lo, mut hi) = (it.start, it.own_end);",
     "removing a parent orphans its children"),
    ("list-checked-upper", src("ops", "list.rs"),
     "    if want == (state == 'x' || state == 'X') {",
     "    if want == (state == 'x') {",
     "`[X]` reads as unchecked, so ticking it rewrites a line it should refuse"),
    ("list-checked-yes", src("ops", "list.rs"),
     '        Some(json::Value::Str(s)) => s == "true" || s == "True" || s == "yes",',
     '        Some(json::Value::Str(s)) => s == "true" || s == "True",',
     '`checked: "yes"` unticks instead of ticking'),
    ("list-checked-int", src("ops", "list.rs"),
     "        Some(json::Value::Int(n)) => *n == 1,",
     "        Some(json::Value::Int(n)) => *n != 0,",
     "`checked: 2` ticks, though the oracle's membership test says otherwise"),
    ("list-checkbox-head", src("ops", "list.rs"),
     '    let head = m.marker_end + m.gap.unwrap_or("").len();',
     "    let head = m.marker_end;",
     "the checkbox is written over the space after the marker"),

    # -- the resolvers and the summary ---------------------------------------
    ("list-heading-tail", src("ops", "list.rs"),
     '            lower == norm || lower.rsplit(" > ").next().unwrap_or(&lower) == norm',
     "            lower == norm",
     "a heading path's last segment stops addressing the list under it"),
    ("list-heading-cutoff", src("ops", "list.rs"),
     "    let near = get_close_matches(want_h, &headings, 3, 0.4);",
     "    let near = get_close_matches(want_h, &headings, 3, 0.9);",
     "the near matches offered for a misspelled list heading narrow"),
    ("list-item-substring", src("ops", "list.rs"),
     "        &|t: &str| t.to_lowercase().contains(&lower_want),",
     "        &|t: &str| t.to_lowercase().starts_with(&lower_want),",
     "the third pass matches only a prefix, so a mid-item phrase misses"),
    ("list-item-cutoff", src("ops", "list.rs"),
     "    let near = get_close_matches(want, &texts, 3, 0.4);",
     "    let near = get_close_matches(want, &texts, 3, 0.8);",
     "the near matches offered for a missed item narrow"),
    ("list-summary-marker", src("ops", "list.rs"),
     "                    .map(|it| it.marker.clone())",
     "                    .map(|_it| l.bullet.clone())",
     "the summary reports a tidied marker instead of the first item's"),
    ("list-summary-ordinal", src("ops", "list.rs"),
     "        let n = seen.entry(e.heading.clone()).or_insert(0);",
     "        let n = seen.entry(String::new()).or_insert(0);",
     "list ordinals count across the document instead of per heading"),

    # -- the dispatch: which argument wins ------------------------------------
    ("list-item-null-alias", src("ops", "dispatch.rs"),
     "        .find_map(|f| a.get(f).filter(|v| !matches!(v, Value::Null)))",
     "        .find_map(|f| a.get(f))",
     '`{"item": null, "match": "x"}` stops at the null instead of falling through'),
    ("list-selector-order", src("ops", "dispatch.rs"),
     '            let selector = item(a, &["item", "match"]);\n'
     "            list_remove_item(content, &address, selector.as_deref())",
     '            let selector = item(a, &["match", "item"]);\n'
     "            list_remove_item(content, &address, selector.as_deref())",
     "`match` outranks `item` when a model sends both"),
    ("list-selector-str", src("ops", "dispatch.rs"),
     "        .map(json::py_str)",
     "        .map(json::py_repr)",
     "a text or selector arrives as its repr, quotes and all"),
    ("list-set-checked-default", src("ops", "dispatch.rs"),
     '            list_set_checked(content, &address, selector.as_deref(), a.get("checked"))',
     '            list_set_checked(content, &address, selector.as_deref(),\n'
     '                             a.get("checked").filter(|v| !matches!(v, Value::Null)))',
     "an explicit `checked: null` takes the absent default and ticks"),
]

# -- sections (Tier 2c) ------------------------------------------------------
# The section family arrived with 43k new differential cases and 0 mismatches,
# which by now is a claim that means nothing on its own.
#
# It gets its own emphasis because it has a failure mode the other two families
# cannot have: a section has TWO ends -- `own_end`, where its own prose stops,
# and `end`, where its subtree stops -- and both are correct answers to
# different questions. Every op in the family picks one, and picking the wrong
# one is not a crash or a mangled line, it is a plausible edit in the wrong
# place: a paragraph appended after six subsections instead of before them, a
# `replace-body` that eats the subtree. Six of the mutations below do nothing
# but swap the two, and each of them has to be caught by name.
#
# The rest follow the layers the other blocks use -- the outline, the resolver
# (four narrowest-first passes, and the ordinal comparison that is raw Python
# `==`), the conventions (`section_eol`, `block`, `strip_atx_marker`), the six
# ops, and the dispatch. `section-verify-early` is aimed at `verify_heading`,
# the one guard in the family that exists because an op can otherwise succeed
# and still be wrong in a way nobody can see.
MUTATIONS += [
    # -- the outline: what the model is told before it addresses anything -----
    ("section-ordinal", src("ops", "section.rs"),
     "            ordinal: slugs[..n].iter().filter(|p| *p == slug).count(),",
     "            ordinal: 0,",
     "every duplicate path reports ordinal 0, so no ordinal addresses the second"),
    ("section-unique", src("ops", "section.rs"),
     "            unique: slugs.iter().filter(|p| *p == slug).count() == 1,",
     "            unique: true,",
     "the outline stops flagging the paths that need an ordinal"),
    ("section-subsections", src("ops", "section.rs"),
     "            subsections: secs.iter().filter(|o| o.parent == Some(n)).count(),",
     "            subsections: secs.iter().filter(|o| o.parent.is_some()).count(),",
     "the subsection count counts the whole document, not this section's children"),
    ("section-plural", src("ops", "section.rs"),
     '                if e.subsections > 1 { "s" } else { "" }',
     '                if e.subsections > 0 { "s" } else { "" }',
     '"1 subsections" in the rendered outline'),
    ("section-indent", src("ops", "section.rs"),
     '        out.push(format!("{}{}   ({})", "  ".repeat(e.level), e.text, bits.join(", ")));',
     '        out.push(format!("{}{}   ({})", "  ".repeat(e.level - 1), e.text, bits.join(", ")));',
     "the outline's indent stops showing the level it is indenting for"),

    # -- the resolver: four passes, narrowest first ---------------------------
    ("section-pred-order", src("ops", "section.rs"),
     "    let preds: [&dyn Fn(&Section) -> bool; 4] = [&exact, &folded, &suffix, &suffix_folded];",
     "    let preds: [&dyn Fn(&Section) -> bool; 4] = [&suffix, &folded, &exact, &suffix_folded];",
     "a loose suffix match runs before the exact path it would have widened"),
    ("section-suffix-prefix", src("ops", "section.rs"),
     "            && s.path[s.path.len() - segs.len()..].iter().zip(&segs).all(|(a, b)| a == b)",
     "            && s.path[..segs.len()].iter().zip(&segs).all(|(a, b)| a == b)",
     '"macOS" stops addressing "Install > macOS" and starts addressing by prefix'),
    ("section-path-truthy", src("ops", "section.rs"),
     '        Some(p) if json::py_truthy(p) => (Some(p), "section.path"),',
     '        Some(p) => (Some(p), "section.path"),',
     '`{"path": "", "heading": "Install"}` stops falling through to the heading'),
    ("arg-ordinal-null", src("args.rs"),
     "        None | Some(Value::Null) => return Ok(None),",
     "        None => return Ok(None),",
     "an explicit `ordinal: null` is compared against, and matches nothing"),
    ("section-ordinal-field", src("ops", "section.rs"),
     '    let want_int = check_ordinal(want_o, "section")?;',
     '    let want_int = check_ordinal(want_o, "table")?;',
     "the section ordinal refusal explains itself in terms of tables"),
    ("section-ordinal-plural", src("ops", "section.rs"),
     "                if valid.len() == 1 {",
     "                if valid.len() == 2 {",
     "the rewritten ordinal refusal picks the wrong singular/plural branch"),
    ("arg-ordinal-bigint-eq", src("args.rs"),
     "            PyInt::Big(_) => false,",
     "            PyInt::Big(_) => true,",
     "a 29-digit ordinal matches every section instead of none"),
    ("section-ambiguity-branch", src("ops", "section.rs"),
     "        let distinct = uniq.len() == paths.len();",
     "        let distinct = uniq.len() != paths.len();",
     'the two ambiguity messages swap: "use a longer path" where an ordinal is the only fix'),
    ("section-ordinal-ambiguous", src("ops", "section.rs"),
     "            if distinct && hits.len() > 1 {",
     "            if false {",
     "a missed ordinal against many distinct paths lists one zero per path "
     "instead of naming the ambiguity"),
    ("section-ordinal-dedup", src("ops", "section.rs"),
     "            valid.dedup();",
     "            valid.truncate(valid.len());",
     "the valid-ordinal list repeats a shared ordinal once per matching section"),
    # The single-match branch, which `ordinal_sizing.py` sizes at 206 of the 206
    # recorded ordinal refusals -- the whole population, and until these three
    # landed the only mutation that could reach it was one that deleted it
    # outright. Each guards a different way the sentence can go wrong while
    # still being a sentence: never offering the nested paths, offering the
    # wrong ones, and quietly over-running the cap.
    ("section-unique-branch", src("ops", "section.rs"),
     "            if hits.len() == 1 {",
     "            if hits.len() == 0 {",
     "a missed ordinal against a unique path falls through to the ordinal list "
     "and is told its one valid ordinal is 0"),
    ("section-unique-inner", src("ops", "section.rs"),
     "                    .filter(|s| s.path.len() > base.len() && s.path[..base.len()] == base[..])",
     "                    .filter(|s| s.path.len() > base.len())",
     "the sections offered as longer paths are every deeper section in the "
     "file, not the ones nested under the match"),
    ("section-unique-cap", src("ops", "section.rs"),
     "                            .take(8)",
     "                            .take(12)",
     "the longer-path list overruns the cap it truncates against"),
    ("section-unique-label", src("ops", "section.rs"),
     '                        want_label,\n                        inner',
     '                        "section.path",\n                        inner',
     "a caller addressing by `section.heading` is told to send `section.path`, "
     "which is the tool's file argument in the schema S15 adopted"),
    ("section-candidate-cap", src("ops", "section.rs"),
     '            entries.iter().take(8).map(|e| format!("\\"{}\\"", e.path)).collect::<Vec<_>>().join("; "),',
     '            entries.iter().take(4).map(|e| format!("\\"{}\\"", e.path)).collect::<Vec<_>>().join("; "),',
     "the empty-address refusal lists half the candidates it promises"),
    ("section-near-cutoff", src("ops", "section.rs"),
     "    let near = get_close_matches(&leaf, &texts, 3, 0.4);",
     "    let near = get_close_matches(&leaf, &texts, 3, 0.9);",
     "the near matches offered for a misspelled section path narrow"),
    ("section-leaf", src("ops", "section.rs"),
     "    let leaf = py_strip(want.rsplit('>').next().unwrap_or(want)).to_string();",
     "    let leaf = py_strip(want.split('>').next().unwrap_or(want)).to_string();",
     "the not-found message looks up the first path segment instead of the leaf"),
    ("section-inert-case", src("ops", "section.rs"),
     "        if h.text.to_lowercase() == leaf_lower {",
     "        if h.text == leaf_lower {",
     "a heading inside a fence is only consulted when it is already lowercase"),

    # -- the conventions: line endings, and what a payload contributes --------
    ("section-eol-range", src("ops", "section.rs"),
     "    for ln in &lines[sec.start..=sec.end] {",
     "    for ln in &lines[sec.start..=sec.own_end] {",
     "a subtree that mixes CRLF and LF is no longer refused"),
    ("section-eol-cr", src("ops", "section.rs"),
     '        (true, false) => Ok("\\r"),',
     '        (true, false) => Ok(""),',
     "a CRLF section gains lone-LF lines"),
    ("section-block-lead", src("ops", "section.rs"),
     "    while body.first().is_some_and(|ln| ln.trim().is_empty()) {\n"
     "        body.remove(0);\n"
     "    }",
     "    // the payload's own leading blank line is kept",
     'a model that sends "\\nSuperseded." gets two blank lines where the document uses one'),
    ("section-block-trail", src("ops", "section.rs"),
     "    while body.last().is_some_and(|ln| ln.trim().is_empty()) {\n"
     "        body.pop();\n"
     "    }",
     "    // the payload's own trailing blank line is kept",
     "a payload ending in a newline pushes a blank line into the document"),
    ("section-block-eol", src("ops", "section.rs"),
     '    Ok(body.into_iter().map(|ln| format!("{ln}{eol}")).collect())',
     '    Ok(body.into_iter().map(|ln| format!("{ln}")).collect())',
     "an inserted block is LF inside a CRLF document"),
    ("section-strip-closing", src("ops", "section.rs"),
     "    py_strip(py_strip(text).trim_end_matches('#')).to_string()",
     "    py_strip(text).to_string()",
     'a quoted "## Fixed ##" renames the section to "Fixed ##"'),
    ("section-heading-echo", src("ops", "section.rs"),
     "    if asked.is_empty() || asked == sec.text || asked == sec.slug() {",
     "    if asked.is_empty() || asked == sec.text {",
     "echoing the addressed section's full path is refused instead of ignored (S3)"),

    # -- own_end against end: the whole family's one real question ------------
    ("section-append-end", src("ops", "section.rs"),
     "    let at = sec.own_end + 1;",
     "    let at = sec.end + 1;",
     "append puts the paragraph after the subsections instead of before them"),
    ("section-append-blank", src("ops", "section.rs"),
     "    let mut out: Vec<String> = lines[..at].iter().map(|s| s.to_string()).collect();\n"
     "    out.push(eol.to_string());\n"
     "    out.extend(blk);",
     "    let mut out: Vec<String> = lines[..at].iter().map(|s| s.to_string()).collect();\n"
     "    out.extend(blk);",
     "an appended block runs straight on from the last line of the body"),
    ("section-has-own-body", src("ops", "section.rs"),
     "    lines[sec.heading_end + 1..=sec.own_end].iter().any(|ln| !ln.trim().is_empty())",
     "    lines[sec.start..=sec.own_end].iter().any(|ln| !ln.trim().is_empty())",
     "the heading counts as a body, so replace-body refuses every section (S2)"),
    ("section-overwrite-guard", src("ops", "section.rs"),
     "    if !overwrite && has_own_body(content, &sec) {",
     "    if overwrite && has_own_body(content, &sec) {",
     "the S2 guard inverts: it refuses the acknowledged overwrite and allows the accident"),
    ("section-replace-tail", src("ops", "section.rs"),
     "    out.extend(lines[sec.own_end + 1..].iter().map(|s| s.to_string()));",
     "    out.extend(lines[sec.end + 1..].iter().map(|s| s.to_string()));",
     "replace-body discards the subtree it promises to leave alone"),
    ("section-delete-gap", src("ops", "section.rs"),
     "    let stop = sec.end + 1 + sec.gap_after;",
     "    let stop = sec.end + 1;",
     "deleting a section leaves its separator behind"),
    ("section-delete-last", src("ops", "section.rs"),
     "    if stop >= lines.len() {",
     "    if stop > lines.len() {",
     "the last section in a file keeps the blank line that separated it"),
    ("section-delete-tail", src("ops", "section.rs"),
     "        out.extend_from_slice(&lines[sec.end + 1..]);",
     "        out.extend_from_slice(&lines[sec.own_end + 1..]);",
     "deleting the last section leaves its subsections orphaned in the file"),
    ("section-rename-rebuild", src("ops", "section.rs"),
     "    out.extend(sec.rebuild(Some(&new)));",
     "    out.extend(sec.rebuild(None));",
     "rename reports success and writes the old heading back"),
    ("section-rename-tail", src("ops", "section.rs"),
     "    out.extend(lines[sec.heading_end + 1..].iter().map(|s| s.to_string()));",
     "    out.extend(lines[sec.start + 1..].iter().map(|s| s.to_string()));",
     "renaming a setext heading leaves the old underline behind"),

    # -- insert: the level is derived, and the gap has to compose with delete -
    ("section-insert-level", src("ops", "section.rs"),
     '    let level = if pos_str == "before" || pos_str == "after" { sec.level } else { sec.level + 1 };',
     '    let level = if pos_str == "before" || pos_str == "after" { sec.level + 1 } else { sec.level };',
     "before/after make a child and first-child/last-child make a sibling"),
    ("section-insert-firstchild", src("ops", "section.rs"),
     '        "first-child" => sec.own_end + 1,',
     '        "first-child" => sec.heading_end + 1,',
     "first-child lands between the heading and the section's own prose"),
    ("section-insert-gap", src("ops", "section.rs"),
     "    let gap: Vec<String> = vec![eol.to_string(); heading_gap(&secs).max(1)];",
     "    let gap: Vec<String> = vec![eol.to_string(); 1];",
     "a document that separates its sections with two blank lines gets one"),
    ("section-insert-tail-skip", src("ops", "section.rs"),
     "        let mut tail = at;\n"
     "        while tail < lines.len() && lines[tail].trim().is_empty() {\n"
     "            tail += 1;\n"
     "        }",
     "        let tail = at;",
     "the new gap replaces the document's existing separator instead of following it"),
    ("section-insert-eod-order", src("ops", "section.rs"),
     "            out.extend(gap);\n"
     "            out.extend(blk);",
     "            out.extend(blk);\n"
     "            out.extend(gap);",
     "a section appended at end of document loses the blank line before it"),
    ("section-insert-children", src("ops", "section.rs"),
     '        blk.extend(child_blocks(c, level + 1, eol, "children")?);',
     '        blk.extend(child_blocks(c, level, eol, "children")?);',
     "structured children are written as siblings of the section they belong to"),
    ("section-children-truthy", src("ops", "section.rs"),
     "    if let Some(c) = children.filter(|c| json::py_truthy(c)) {",
     "    if let Some(c) = children {",
     '`{"sections": []}` renders an empty children block instead of none'),
    ("section-child-sep", src("ops", "section.rs"),
     "        if !out.is_empty() {\n"
     "            out.push(eol.to_string());\n"
     "        }",
     "        // consecutive children run together",
     "two structured children are written with no blank line between them"),
    ("section-child-nested", src("ops", "section.rs"),
     '            out.extend(child_blocks(&kids, level + 1, eol, &format!("{field}[{i}].children"))?);',
     '            out.extend(child_blocks(&kids, level, eol, &format!("{field}[{i}].children"))?);',
     "a grandchild is written at its parent's level"),
    ("section-verify-early", src("ops", "section.rs"),
     "    if find_sections(result).iter().any(|s| s.start == line) {",
     "    if !find_sections(result).is_empty() {",
     "an insert into an unterminated fence reports success and creates no section"),

    # -- set-level -----------------------------------------------------------
    ("section-setlevel-subtree", src("ops", "section.rs"),
     "            if secs[k].level <= sec.level {",
     "            if secs[k].level < sec.level {",
     "a same-level sibling is dragged along as if it were a subsection"),
    ("section-setlevel-setext", src("ops", "section.rs"),
     "        if secs[k].style == HeadingStyle::Setext && new_level > 2 {",
     "        if secs[k].style == HeadingStyle::Setext && new_level > 3 {",
     "a setext heading is silently demoted to a level it cannot express"),
    ("section-setlevel-underline", src("ops", "section.rs"),
     "            let ch = if new_level == 1 { '=' } else { '-' };",
     "            let ch = if new_level == 2 { '=' } else { '-' };",
     "a setext heading moved to level 1 gets the level-2 underline"),
    ("section-setlevel-space", src("ops", "section.rs"),
     '            let space = if s.space.is_empty() { " " } else { s.space.as_str() };',
     '            let space = " ";',
     "an unusual run of spaces after the marker is normalized by a level change"),
    ("section-setlevel-noop", src("ops", "section.rs"),
     "    if want as usize == sec.level {",
     "    if want as usize == sec.level + 1 {",
     "the nothing-to-do refusal fires for the wrong level"),
    ("section-int-trunc", src("ops", "section.rs"),
     "            f.is_finite().then(|| PyInt::Small(f.trunc() as i64))",
     "            f.is_finite().then(|| PyInt::Small(f.round() as i64))",
     "`level: 2.9` becomes 3, where Python's `int()` truncates to 2"),
    ("section-type-name", src("ops", "section.rs"),
     '        Value::Null => "NoneType",',
     '        Value::Null => "None",',
     "the `children` type refusal names the JSON type instead of Python's"),

    # -- REQUIREMENTS 6.4's "one habit", reconciled --------------------------
    # Each of these reverts one family to what it did before the three
    # resolvers agreed. Nothing guarded these lines: `grep position` found only
    # table-family entries, and tightening a line no mutation covers is how a
    # fix becomes a regression nobody sees.
    ("section-ordinal-unchecked", src("ops", "section.rs"),
     '    let want_int = check_ordinal(want_o, "section")?;',
     "    let want_int = want_o.and_then(|v| match v {\n         Value::Int(i) => Some(PyInt::Small(*i)),\n         _ => None,\n     });",
     'section `{"ordinal": "0"}` stops addressing, as it did before'),
    ("section-heading-unchecked", src("ops", "section.rs"),
     "    let want_str_checked = check_heading_named(want, want_label)?;",
     "    let want_str_checked = want.map(json::py_str);",
     'section `{"path": 1}` is stringified to "1" instead of refused'),
    ("section-address-label", src("ops", "section.rs"),
     '        Some(p) if json::py_truthy(p) => (Some(p), "section.path"),',
     '        Some(p) if json::py_truthy(p) => (Some(p), "section.heading"),',
     "the address refusal names a key the caller did not send"),
    ("section-ordinal-late", src("ops", "section.rs"),
     '    let want_int = check_ordinal(want_o, "section")?;\n\n    if secs.is_empty() {\n        return Err(OpError::new(\n            "this file has no headings, so no section can be addressed.",\n        ));\n    }',
     '    if secs.is_empty() {\n        return Err(OpError::new(\n            "this file has no headings, so no section can be addressed.",\n        ));\n    }\n    let want_int = check_ordinal(want_o, "section")?;',
     "a malformed section ordinal is answered after the document, not before"),
    ("list-position-literal", src("ops", "list.rs"),
     "    let starts = match check_position_in(position, PosFamily::List)? {",
     "    let starts = match (if position.map(json::py_str).unwrap_or_default()\n"
     "        == \"start\" { Position::Start } else { Position::End }) {",
     'list `position` goes back to a literal "start" comparison'),
    ("list-position-family", src("ops", "list.rs"),
     "    let starts = match check_position_in(position, PosFamily::List)? {",
     "    let starts = match check_position_in(position, PosFamily::Table)? {",
     "a list explains its `position` refusal in terms of table rows"),
    ("arg-position-fold", src("args.rs"),
     "            let low = s.trim().to_lowercase();",
     "            let low = s.to_string();",
     '`position: "Start"` stops meaning start in both families'),
    ("arg-position-index-list", src("args.rs"),
     "                if fam == PosFamily::List {\n                    return refuse_index(value.unwrap());",
     "                if false {\n                    return refuse_index(value.unwrap());",
     "a list silently appends an index instead of refusing it"),

    # -- the dispatch: which argument wins ------------------------------------
    ("section-append-alias", src("ops", "dispatch.rs"),
     '            let text = item(a, &["text", "body"]);\n'
     '            let heading = item(a, &["heading", "new_heading", "title"]);\n'
     "            section_append(",
     '            let text = item(a, &["body", "text"]);\n'
     '            let heading = item(a, &["heading", "new_heading", "title"]);\n'
     "            section_append(",
     "`body` outranks `text` on append when a model sends both"),
    ("section-insert-body-alias", src("ops", "dispatch.rs"),
     '            let body = item(a, &["body", "text"]);',
     '            let body = item(a, &["text", "body"]);',
     "`text` outranks `body` on insert"),
    ("section-insert-heading-alias", src("ops", "dispatch.rs"),
     '            let heading = item(a, &["heading", "title"]);',
     '            let heading = item(a, &["heading", "title", "text"]);',
     "`text` starts naming the new section instead of filling its body"),
    ("section-rename-alias", src("ops", "dispatch.rs"),
     '            let heading = item(a, &["heading", "title", "text"]);',
     '            let heading = item(a, &["heading", "title"]);',
     "`text` stops spelling the new name on a rename"),
    ("section-overwrite-bool", src("ops", "dispatch.rs"),
     '            let overwrite = a.get("overwrite").is_some_and(json::py_truthy);',
     '            let overwrite = a.get("overwrite").is_some();',
     "`overwrite: false` acknowledges the overwrite it denies"),
    ("section-subtree-default", src("ops", "dispatch.rs"),
     '            let subtree = a.get("subtree").map_or(true, json::py_truthy);',
     '            let subtree = a.get("subtree").map_or(false, json::py_truthy);',
     "an absent `subtree` reparents the children instead of carrying them"),
    # `section-children-chain` was here: dropping `.or_else(|| a.get("sections"))`
    # so the falsy last operand arrives as absent. It survived a full run, and it
    # survives every run, because it is an EQUIVALENT MUTANT -- `section_insert`
    # takes `children` through `.filter(json::py_truthy)` at its one use, so
    # `Some(falsy)` and `None` are the same value from there on. The `or_else`
    # tail and the downstream re-test are belt and braces for the same Python
    # `or`, and only one of them can be observed. `section-children-truthy`
    # observes the re-test, so that is the one that is kept.
    #
    # It is replaced by the question the falsy cases cannot ask: the chain's
    # ORDER. Two truthy spellings at once is the only shape that sees it.
    ("section-children-order", src("ops", "dispatch.rs"),
     '            let children = ["children", "subsections", "sections"]',
     '            let children = ["sections", "subsections", "children"]',
     "`sections` outranks `children` when a model sends both"),
]

# -- the difflib port, below the tie-break --------------------------------
#
# Until `describe_change` there was exactly one mutation in `similar.rs` --
# `difflib-tiebreak` -- and it only reached the ranking. `matches`,
# `longest_match` and the autojunk branch had no mutation and no invariant,
# which is how a real defect sat there through three op families: the
# extension loops were missing, and every `b` the port had ever seen was a
# heading or a column name, far below the 200-element threshold that makes
# them observable. The gap was in the mutation list before it was in the code.
#
# One branch of `matching_blocks` is deliberately NOT mutated. The pass that
# collapses adjacent equal blocks cannot fire while the index is complete: two
# blocks abut only when `a[i-1] == b[j-1]` at the second block's start, and the
# first block is the longest run in a region reaching to `(i-1, j-1)`, so that
# equality would have made it one element longer. 0 firings in 20000 trials,
# with the extension loops present and with them removed. FINDINGS F-extend.
#
# **Four mutations were deleted here by F-nearmatch, and the argument has to be
# the right one, because the wrong one was used on two of them once already.**
# `difflib-autojunk`, `difflib-purge`, `difflib-extend-left` and
# `difflib-extend-right` were all caught, by 46, 14, 33 and 29 cases -- nothing
# about them was weak. They are gone because **the code they anchored to is
# gone**: `Matcher` no longer purges, and with a complete index the four
# extension loops can only fire on a match the DP failed to find, which cannot
# happen. Deleting a mutation whose subject was deleted is bookkeeping.
#
# That is emphatically not the earlier argument, which was wrong. F-autojunk
# turned autojunk off for `describe`'s two matchers, both mutations survived the
# next run, and they were deleted as unobservable. They were not: the branch was
# still live through `get_close_matches`, whose oracle was stdlib
# `difflib.get_close_matches` and could not opt out. A survivor is evidence
# about the *harness* first, and the honest reading of two survivors is that no
# case reached the branch, not that no case could. `bench/synthetic/long-cells.md`
# is the document that reached it, and all four came back.
#
# The distinction this file turns on: **a mutation may be retired when its
# subject is unobservable in principle or no longer exists, never because the
# cases stopped reaching it.** The first is a fact about the code; the second is
# a fact about the corpus, and the corpus is the thing under test.
#
# So the branch does not simply disappear from the list. `difflib-autojunk-back`
# puts the heuristic back exactly as difflib writes it, which is the regression
# the whole entry is about and the one state of this file that has been wrong
# twice.
MUTATIONS += [
    ("difflib-autojunk-back", src("similar.rs"),
     "        Matcher { b, b2j }",
     "        let n = b.len();\n"
     "        if n >= 200 { let t = n / 100 + 1; b2j.retain(|_, i| i.len() <= t); }\n"
     "        Matcher { b, b2j }",
     "difflib's autojunk heuristic comes back, without the loops that undo it"),
    ("difflib-blocks-sort", src("similar.rs"),
     "        blocks.sort_unstable();", "        if false { blocks.sort_unstable(); }",
     "the LIFO queue's blocks are left unordered"),
    ("difflib-sentinel", src("similar.rs"),
     "        out.push((la, lb, 0));", "        if false { out.push((la, lb, 0)); }",
     "the terminating block goes missing, so a trailing insert is never emitted"),
    ("difflib-opcode-order", src("similar.rs"),
     "            } else if j < bj {\n                Some(Tag::Insert)",
     "            } else if j < bj {\n                Some(Tag::Delete)",
     "an insert is reported as a delete"),
]

# -- describe_change: the shape of a success (§9 criterion 11) --------------
#
# The response text is under test the same way the refusal text is, and for a
# sharper reason: a description that asserts a change the bytes do not support
# is worse than one that says nothing, because it is the exact input that makes
# a model stop checking.
#
# One branch of the oracle is deliberately NOT mutated. `_lines_delta` returns
# "same line count" when the line tally is (0, 0), and that is unreachable from
# its only caller: the branch guard is `b[i][2] != a[j][2]`, the tally is (0, 0)
# only when the two line lists are equal, and `split("\n")` is injective -- so
# the two conditions cannot both hold. Verified against 200000 random pairs. A
# mutation known in advance to be unreachable measures the harness, not the
# code.
#
# That rule used to keep `filter-value-typed` out of this list as well, because
# `difftest.py` had no way to send a typed value inside a filter. F-read closed
# it -- `table_get` rides the JSON escape hatch, the cases exist, and the
# mutation is at `:348`, proven reachable by running it with those cases
# disabled, where it survives. The exclusion above is the only one left.
MUTATIONS += [
    ("describe-own-end", src("describe.rs"),
     "let (lo, hi) = (sec.heading_end + 1, sec.own_end + 1);",
     "let (lo, hi) = (sec.heading_end + 1, sec.end + 1);",
     "a section's body is read to the end of its subtree, not its own prose"),
    ("describe-noop", src("describe.rs"),
     "    if before == after {", "    if false && before == after {",
     "an unchanged document is reported as if something happened"),
    ("describe-collapse-threshold", src("describe.rs"),
     "if run.len() > 2 && run[1..].iter().all(|e| e.1 > run[0].1) {",
     "if run.len() > 1 && run[1..].iter().all(|e| e.1 > run[0].1) {",
     "a two-heading run collapses instead of staying itemized"),
    ("describe-collapse-nested", src("describe.rs"),
     "run[1..].iter().all(|e| e.1 > run[0].1)",
     "run[1..].iter().any(|e| e.1 > run[0].1)",
     "a run that is not a subtree is described as one"),
    ("describe-promoted", src("describe.rs"),
     'let verb = if new < old { "promoted" } else { "demoted" };',
     'let verb = if new > old { "promoted" } else { "demoted" };',
     "a promotion is announced as a demotion"),
    ("describe-level-run", src("describe.rs"),
     "                    if b[i].1 != a[j].1 {",
     "                    if false && b[i].1 != a[j].1 {",
     "a level shift is never noticed"),
    ("describe-body-delta", src("describe.rs"),
     "                    if b[i].2 != a[j].2 {",
     "                    if false && b[i].2 != a[j].2 {",
     "a changed body goes unreported"),
    ("describe-rename-guard", src("describe.rs"),
     "Tag::Replace if i2 - i1 == 1 && j2 - j1 == 1 => {",
     "Tag::Replace if i2 - i1 == 1 || j2 - j1 == 1 => {",
     "a many-for-one replace is announced as a rename"),
    ("describe-tally", src("describe.rs"),
     "                flush_levels(&mut levels, &mut notes);\n"
     "                tally_wanted = true;",
     "                flush_levels(&mut levels, &mut notes);\n"
     "                tally_wanted = false;",
     "an added or removed section prints no line tally"),
    ("describe-backstop", src("describe.rs"),
     'notes.push("changed text outside any heading".to_string());',
     'notes.push("changed text outside a heading".to_string());',
     "the backstop sentence drifts from the oracle's"),
    ("describe-plural", src("describe.rs"),
     'format!("{n} {noun}{}", if n == 1 { "" } else { "s" })',
     'format!("{n} {noun}{}", if n == 0 { "" } else { "s" })',
     "the singular/plural boundary moves by one"),
    ("describe-counts-removed", src("describe.rs"),
     "        if matches!(tag, Tag::Replace | Tag::Delete) {",
     "        if matches!(tag, Tag::Delete) {",
     "a replaced line is not counted as removed"),
    ("describe-counts-added", src("describe.rs"),
     "        if matches!(tag, Tag::Replace | Tag::Insert) {",
     "        if matches!(tag, Tag::Insert) {",
     "a replaced line is not counted as added"),
    ("describe-direction", src("describe.rs"),
     "    let (b, a) = (describe_entries(before), describe_entries(after));",
     "    let (b, a) = (describe_entries(after), describe_entries(before));",
     "before and after are compared the wrong way round"),
    ("describe-separator", src("describe.rs"),
     'let head = format!("Applied: {}.", notes.join("; "));',
     'let head = format!("Applied: {}.", notes.join(", "));',
     "notes are joined with the wrong separator"),
]


# -- the frontmatter family (front.rs, ops/frontmatter.rs) -------------------
#
# The family with the narrowest edit window in the crate, and so the one where a
# mutation is least likely to show up as a crash and most likely to show up as a
# document that still looks fine. Four of these are the hazards the plan named
# before the port was written -- the per-entry `\r`, `seq_at`'s indent
# comparison, `split_comment`'s quote tracking, and `_yaml_scalar`'s quoting
# predicate -- and they are here because each one produces a file that parses,
# renders, and is wrong.
#
# `front-dupe-first` is the one that is not hypothetical: the port had it,
# `bench/synthetic/front-dupes.md` is the fixture that caught it, and it is
# pinned here so it cannot come back. A dict comprehension keeps the *last*
# value for a repeated key, so a set on a twice-written key must rewrite the
# second line; taking the first rewrites a line the address does not name and
# leaves the effective value untouched.
MUTATIONS += [
    ("front-eol-drop", src("front.rs"),
     '        e.eol = if raw[e.line].ends_with(\'\\r\') { "\\r" } else { "" }.to_string();',
     '        e.eol = String::new();',
     "a rebuilt CRLF line is silently converted to LF"),
    ("front-block-eol", src("front.rs"),
     "        eol: if raw[start].ends_with('\\r') { \"\\r\" } else { \"\" }.to_string(),",
     "        eol: String::new(),",
     "the block's own line ending is lost, so an inserted key is LF"),
    ("front-dupe-first", src("front.rs"),
     "        self.entries.iter().rev().find(|e| e.path == path)",
     "        self.entries.iter().find(|e| e.path == path)",
     "a key written twice resolves to the first line rather than the last"),
    ("front-dupe-map-position", src("front.rs"),
     "                Some(slot) => slot.1 = e,",
     "                Some(_) => {}",
     "a repeated key keeps its first value instead of its last"),
    ("front-seq-at-indent", src("front.rs"),
     "        if ind < indent || (ind == indent && match_seq(raw).is_none()) {",
     "        if ind <= indent {",
     "a sequence written at its key's own indent is not seen as the key's"),
    ("front-seq-at-nonseq", src("front.rs"),
     "        if ind < indent || (ind == indent && match_seq(raw).is_none()) {",
     "        if ind < indent {",
     "a sibling key at the same indent is swallowed into the sequence"),
    ("front-comment-quotes", src("front.rs"),
     "        } else if ch == b'\"' || ch == b'\\'' {",
     "        } else if false {",
     "a `#` inside a quoted value is read as the start of a comment"),
    ("front-comment-boundary", src("front.rs"),
     "        } else if ch == b'#' && (i == 0 || b[i - 1] == b' ' || b[i - 1] == b'\\t') {",
     "        } else if ch == b'#' {",
     "a `#` with no space before it starts a comment"),
    ("front-comment-escape", src("front.rs"),
     "            if ch == b'\\\\' && q == b'\"' {",
     "            if false {",
     "a backslash-escaped quote closes the string it is inside"),
    ("front-comment-sq-escape", src("front.rs"),
     "            if ch == b'\\\\' && q == b'\"' {",
     "            if ch == b'\\\\' {",
     "a backslash escapes inside single quotes, where YAML says it is literal"),

    ("front-quote-colon", src("ops", "frontmatter.rs"),
     '        || s.contains(": ")',
     "        || s.contains(':')",
     "a value holding a bare colon is quoted when the oracle leaves it alone"),
    ("front-quote-empty", src("ops", "frontmatter.rs"),
     "    s.is_empty()\n        || s != crate::scan::py_strip(s)",
     "    false\n        || s != crate::scan::py_strip(s)",
     "the empty string is written bare instead of as `\"\"`"),
    ("front-quote-hash", src("ops", "frontmatter.rs"),
     '        || s.contains(" #")',
     '        || s.contains("#")',
     "a value merely containing `#` is quoted"),
    ("front-quote-escape", src("ops", "frontmatter.rs"),
     '    format!("\\"{}\\"", s.replace(\'\\\\\', "\\\\\\\\").replace(\'"\', "\\\\\\""))',
     '    format!("\\"{}\\"", s.replace(\'"\', "\\\\\\""))',
     "a backslash in a quoted value is not doubled"),
    ("front-key-quote-colon", src("ops", "frontmatter.rs"),
     "        || s.contains(':')\n        || s.contains('#')",
     "        || s.contains(\": \")\n        || s.contains('#')",
     "a new key holding a bare colon is written unquoted"),

    ("front-toml-refusal", src("ops", "frontmatter.rs"),
     "             file are unaffected; only frontmatter ops stop here.",
     "             file are unchanged; only frontmatter ops stop here.",
     "the TOML refusal drifts from the oracle's wording"),
    ("front-value-required", src("ops", "frontmatter.rs"),
     '            "`value` is required: it says what to set the key to.\\n  Send null \\',
     '            "`value` is required: it says what to set the key to.\\n  Pass null \\',
     "the missing-value refusal drifts from the oracle's wording"),
    ("front-null-is-absent", src("ops", "frontmatter.rs"),
     "        None => Err(OpError::new(\n"
     '            "`value` is required',
     "        None | Some(Value::Null) => Err(OpError::new(\n"
     '            "`value` is required',
     "an explicit null value is refused as if the argument were missing"),
    ("front-get-null-key", src("ops", "frontmatter.rs"),
     "    let key = key.filter(|v| !v.is_null());\n    let mut entries",
     "    let key = key.filter(|_| true);\n    let mut entries",
     "`frontmatter-get` refuses an explicit null key instead of ignoring it"),

    ("front-delete-span", src("ops", "frontmatter.rs"),
     "    out.extend_from_slice(&lines[e.end + 1..]);",
     "    out.extend_from_slice(&lines[e.line + 1..]);",
     "deleting a key leaves everything written under it behind"),
    ("front-delete-item-guard", src("ops", "frontmatter.rs"),
     "    if !e.key_text.is_empty() && e.prefix.trim_end_matches(' ').ends_with('-') {",
     "    if false {",
     "deleting the key on a `-` line takes the item marker with it"),
    ("front-set-item-children", src("ops", "frontmatter.rs"),
     "            || (e.kind == Kind::Item && front_children(&fm, &path).is_empty());",
     "            || e.kind == Kind::Item;",
     "setting an item that holds a map flattens it and deletes its keys"),
    ("front-parent-indent", src("ops", "frontmatter.rs"),
     "    let indent = kids.first().map_or(pe.indent() + 2, |k| k.indent());",
     "    let indent = pe.indent() + 2;",
     "a new nested key is indented by convention rather than by its siblings"),
    ("front-created-gap", src("ops", "frontmatter.rs"),
     "        let gap = if content.starts_with('\\n') || content.starts_with(\"\\r\\n\") {",
     "        let gap = if content.starts_with('\\n') {",
     "a created block gains a blank line a CRLF document already had"),
    ("front-created-gap-always", src("ops", "frontmatter.rs"),
     "        let gap = if content.starts_with('\\n') || content.starts_with(\"\\r\\n\") {",
     "        let gap = if false {",
     "a created block gains a blank line any document that opens with one already had"),
    ("front-notes-item", src("ops", "frontmatter.rs"),
     "            if be.value != e.value && e.kind != Kind::Item {",
     "            if be.value != e.value {",
     "a changed sequence item is described as a key that was set"),
    ("front-notes-empty-value", src("ops", "frontmatter.rs"),
     '                        "an empty value"',
     '                        "an empty"',
     "the empty-value phrase drifts from the oracle's"),
]


def run_difftest(expected=None):
    """Return (returncode, mismatch_count, key).

    `-1` means the port crashed: the driver panicked partway through and the
    remaining cases were never compared. That is not the same as a build
    failure, which is why it is not `None` -- a panic is evidence the corpus
    *reaches* the mutated line, and a differential run that dies is a run that
    does not pass. It is weaker evidence than a mismatch count, because it says
    nothing about which case distinguished the two implementations.

    `key` identifies the oracle inputs that produced the expected side, and is
    `None` when the run never got far enough to print one. Every mutation here
    edits Rust, so the key is the same on every run of a full pass; `main`
    treats a key that moves as grounds to stop, because the alternative is a
    run whose later results were compared against a different oracle than its
    earlier ones and which reports that as a pass.
    """
    cmd = [sys.executable, os.path.join(ROOT, "bench", "difftest.py")]
    if expected:
        cmd += ["--expected", expected]
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    k = re.search(r"^expected: \w+ ([0-9a-f]+)$", p.stdout, re.M)
    key = k.group(1) if k else None
    m = re.search(r"^(\d+) mismatches$", p.stdout, re.M)
    if m:
        return p.returncode, int(m.group(1)), key
    if "all " in p.stdout and "agree with the oracle" in p.stdout:
        return p.returncode, 0, key
    if "panicked at" in p.stdout + p.stderr:
        return p.returncode, -1, key
    return p.returncode, None, key  # build failure


def leftover_mutations():
    """Mutations that look already applied to the tree.

    The restore below is in a `finally`, which a SIGKILL does not run — so an
    interrupted run leaves the tree mutated, and the next run fails its baseline
    check with no clue why. It happened once; the diagnosis took longer than it
    should have. A mutation counts as applied when its `before` anchor is gone
    and its `after` text is present.
    """
    found = []
    for name, path, before, after, what in MUTATIONS:
        s = open(path).read()
        if before not in s and after in s:
            found.append((name, path, what))
    return found


def main():
    ap = argparse.ArgumentParser()
    # Comma-separated, because the workflow that needs it is re-running the
    # survivors of the last full run: a handful of unrelated names, each of
    # which would otherwise pay for its own baseline difftest.
    ap.add_argument("-k", help="only run mutations whose name contains any of "
                               "these (comma-separated)")
    args = ap.parse_args()

    keys = [k for k in (args.k or "").split(",") if k]
    muts = [m for m in MUTATIONS if not keys or any(k in m[0] for k in keys)]

    # Anchors first, before the half-hour of difftest runs. A stale anchor is
    # not a pass, and finding out at minute 29 is how one gets treated as one:
    # `rect-off` went stale the moment `check_rectangular` grew a `read`
    # parameter, and nothing said so until the next full run would have.
    #
    # Checked over ALL of MUTATIONS rather than the filtered set, because that
    # is the case `-k` gets wrong: Tier 2c ran `-k section-` and so never looked
    # at the other 92 anchors, several of which point into files that tier had
    # just edited. The mutations that will not run this time are the ones most
    # likely to have gone stale, and the check costs nothing.
    #
    # A mutation whose `after` equals its `before` is checked here for the same
    # reason. It compiles, it runs, and it reports SURVIVED -- indistinguishable
    # from a real gap in the corpus, and one such entry did sit in this list.
    problems = []
    seen = set()
    for name, path, before, after, _what in MUTATIONS:
        n = open(path).read().count(before)
        if n != 1:
            problems.append(f"  {name:<18} anchor occurs {n}x in {os.path.relpath(path, ROOT)}")
        if before == after:
            problems.append(f"  {name:<18} mutates nothing: `after` is identical to `before`")
        if name in seen:
            problems.append(f"  {name:<18} is defined more than once")
        seen.add(name)
    if problems:
        print(f"{len(problems)} problem(s) in the mutation list:")
        print("\n".join(problems))
        print("  Fix the list, then rerun. Nothing was applied to the tree.")
        return 2

    # The baseline run is also the run that computes the oracle's answers. Every
    # mutation below rewrites Rust, so those answers do not change for the rest
    # of the pass and `difftest.py` reuses them from this file -- which is what
    # takes a full run from eight hours to under one. The file lives in a temp
    # directory rather than the tree so that it cannot outlive the run and be
    # picked up by a later one against a different oracle.
    with tempfile.TemporaryDirectory() as tmp:
        expected = os.path.join(tmp, "expected")
        return run_mutations(muts, expected)


def run_mutations(muts, expected):
    rc, n, key = run_difftest(expected)
    if rc != 0 or n != 0:
        print(f"baseline is not clean (rc={rc}, mismatches={n}); fix that first")
        for name, path, what in leftover_mutations():
            print(f"  looks like mutation {name!r} is still applied to {path}")
            print(f"    ({what}) -- an interrupted run does not restore the file")
        return 2
    print(f"baseline clean: 0 mismatches (oracle {key[:12] if key else '?'})\n")

    results = []
    for name, path, before, after, what in muts:
        original = open(path).read()
        if original.count(before) != 1:
            results.append((name, "STALE", original.count(before), what))
            print(f"  {name:<18} STALE (anchor occurs {original.count(before)}x)")
            continue
        try:
            open(path, "w").write(original.replace(before, after, 1))
            rc, n, k = run_difftest(expected)
        finally:
            open(path, "w").write(original)
        if k is not None and k != key:
            # Something the oracle's answers depend on changed underneath the
            # run -- an edit to `bench/` while it was in flight, most likely.
            # Everything after that point would be compared against a different
            # oracle than everything before it, so the pass is void and saying
            # so is the only honest option. The tree is already restored above.
            #
            # `k is None` is a different thing entirely and must not land here:
            # a build failure or a panic aborts `difftest.py` before it reaches
            # the oracle at all, so it prints no key, and those two have their
            # own verdicts below.
            print(f"\n  {name:<18} ABORT: the oracle moved mid-run "
                  f"({key[:12] if key else '?'} -> {k[:12]})")
            print("  Nothing under bench/ may be edited while this is running.")
            print("  The tree is restored; rerun from a quiet tree.")
            return 2
        if n is None:
            # A mutation that does not compile proves nothing about the corpus.
            verdict, detail = "NOBUILD", 0
        elif n < 0:
            # The port panicked. Caught -- the run does not pass -- but recorded
            # under its own name, because an aborted run has no mismatch count
            # and cannot say which case saw the difference.
            verdict, detail = "crashed", 0
        elif n > 0:
            verdict, detail = "caught", n
        else:
            verdict, detail = "SURVIVED", 0
        results.append((name, verdict, detail, what))
        note = f"{detail} mismatches" if verdict == "caught" else ""
        print(f"  {name:<18} {verdict:<9} {note:<16} {what}")

    caught = sum(1 for r in results if r[1] in ("caught", "crashed"))
    bad = [r for r in results if r[1] not in ("caught", "crashed")]
    print(f"\n{caught}/{len(results)} mutations caught")
    for name, verdict, _, what in bad:
        print(f"  {verdict}: {name} -- {what}")
    return 0 if not bad else 1


if __name__ == "__main__":
    # `finally` does not run on SIGTERM, and a killed run leaves the tree
    # mutated -- which the next run then reads as the original. Turning the
    # signal into an exception lets both the restore and the lock release fire.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(130))
    with exclusive():
        raise SystemExit(main())
