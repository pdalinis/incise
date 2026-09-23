#!/usr/bin/env python3
"""Differential test: `crates/incise-core` against `bench/incise_ops.py`.

REQUIREMENTS.md §9 criterion 7 makes the Python reference implementation the
oracle for the Rust port, and this is the thing that enforces it. Every case is
run through both and the two outputs are compared byte-for-byte -- both the
resulting document *and* the refusal message, because §5.3 makes the message
part of the contract and Arm B measured recovery against those exact sentences.

The case list is generated from the corpus rather than written by hand, for the
reason the corpus exists: hand-written cases test what the author thought of.
For every table in every fixture it generates adds (short and re-pad-forcing,
at three positions, in both row shapes), updates (short and widening), deletes,
and the eight refusal paths -- plus the structural dumps (`find_sections`,
`find_tables`, `list_tables`, `inert_headings`, `render_table_list`) for every
file, which is what catches a parser that agrees on the ops and disagrees on
where a section ends.

Two case families are *not* generated from the corpus, and cannot be. Arguments
built from a document are well-typed by construction, so the validation layer
(FINDINGS F-args) and the JSON reader underneath it are never on the generated
path -- which is how that layer went three op families without being looked at.
`check_args` runs every value in `ARG_VALUES` through every function in
`ARG_FNS`, and `py_repr` runs `json.loads` + `repr` against `json.rs`, including
inputs neither side should parse. Written by hand, but as a cross product rather
than a list, and `bench/mutate.py` carries mutations aimed at them for the same
reason it carries mutations aimed at everything else here: a green differential
test is not evidence until it has been shown to go red.

  python3 bench/difftest.py            # build, run, compare
  python3 bench/difftest.py -v         # print the first differing case in full
  python3 bench/difftest.py -j 1       # serial oracle, for comparing against
  python3 bench/difftest.py --expected /tmp/exp   # reuse the oracle's answers
"""

import argparse
import hashlib
import json
import multiprocessing
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bench"))

import incise_ops as F  # noqa: E402
from mdsection import find_sections, inert_headings  # noqa: E402
from mdlist import find_lists  # noqa: E402
from mdfront import find_frontmatter, format_path, parse_path  # noqa: E402
from mdtable import find_tables  # noqa: E402

FS, RS, GS = "\x1f", "\x1e", "\x1d"

# Long enough to outgrow any column in the corpus, which is what forces the
# re-pad path -- the one the model scored 0/10 on (§11 Tier 1).
LONG = "a-value-far-wider-than-this-column-ever-was"

# The same, in characters that are wider in bytes than in characters. Column
# width is a character count (§5.2), and the corpus cannot tell the two apart
# on its own: its aligned tables contain non-ASCII cells, but only short ones
# (`—`, `–`), never the widest cell in their column, so a byte-width bug
# changes nothing. Making the widest cell non-ASCII is what distinguishes them.
# Found by `bench/mutate.py`, which is the reason that script exists.
LONG_WIDE = "日本語のとても長い値です-" * 2

# The length at which difflib's autojunk heuristic used to engage, and nowhere
# below it. Neither implementation has the heuristic any more (F-nearmatch), but
# the number outlives it: it is the length above which near-match ranking was
# wrong, so it is the length the probes below still have to reach, and it is why
# `bench/synthetic/long-cells.md` has the cells it has. A shorter fixture would
# not distinguish the two behaviours at all.
LONG_VALUE_N = 200


# Documents the corpus provably cannot reach.
#
# These are NOT corpus fixtures. The corpus is a measured artifact -- FINDINGS
# quotes per-file results against those 26 files -- so it stays frozen, and
# coverage gaps that need a new document get one in `bench/synthetic/` instead.
#
# They are files rather than string constants here because they have a second
# reader: `crates/incise-core/tests/invariants.rs` asserts structural properties
# over the same documents. Holding two copies together with a test is the bet
# that produced F-fence. `bench/synthetic/README.md.txt` says what each one is
# for -- it cannot go in the file itself, because the bytes are the input.
SYNTHETIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "synthetic")


def synthetic_files():
    return sorted(os.path.join(SYNTHETIC_DIR, n)
                  for n in os.listdir(SYNTHETIC_DIR) if n.endswith(".md"))


def esc(s):
    return s.replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "\\r")


def corpus_files():
    out = []
    for dirpath, _, names in os.walk(os.path.join(ROOT, "corpus")):
        for n in sorted(names):
            if n.endswith(".md"):
                out.append(os.path.relpath(os.path.join(dirpath, n), ROOT))
    return sorted(out)


# --------------------------------------------------------------------------
# ill-typed arguments (FINDINGS F-args)
# --------------------------------------------------------------------------
# The corpus cannot generate these. Every case above is built *from* a document,
# so its arguments are well-typed by construction and the validation layer is
# never on the path -- which is precisely how the layer went three families
# without being looked at. These cases are therefore written by hand, and the
# defence against "hand-written cases test what the author thought of" is that
# they are a cross product rather than a list: every value against every check.
#
# `ABSENT` is the wire's way of saying the key was not sent at all, which is a
# distinct input from `null` and behaves differently -- `position` absent means
# `end`, `position` null means `end` too, but `column` absent and `column` null
# produce the same refusal only because that was written deliberately.
ARG_VALUES = [
    "ABSENT", "null", "true", "false",
    "0", "1", "-3", "1.5", "1.0", "0.0", "1e16", "1e17", "1e-4", "1e-5",
    "12345678901234567890123456789",
    '""', '"0"', '" 2 "', '"+7"', '"1.0"', '"start"', '" End "', '"MIDDLE"',
    '"   "', '"Components"', '"it\'s"', '"a\\nb"', '"caf\\u00e9"',
    '"{\\"Component\\": \\"gadget\\"}"', '"[1, 2]"', '"i, j, k, l"',
    "[]", '["Component"]', "[1, [2]]",
    "{}", '{"heading": "H", "ordinal": 0}', '{"a": 1}',
    '{"\\"heading\\"": "H"}', '{"a": null}', '{"a": {"b": 2}}',
    # Text that does not fit in a cell. A bare `|` starts a column and a line
    # break ends the table, and both were measured writing a broken table and
    # reporting success; the escaped form must still pass, or the refusal has
    # eaten the only way to write a literal pipe.
    '"a | b"', '"a \\\\| b"', '"|"', '"a\\\\"', '"a\\r\\nb"', '"a\\\\|b|c"',
    '"a\\\\\\\\|b"', '"a\\\\\\\\\\\\| b"',
]

# --------------------------------------------------------------------------
# dispatch ordering
# --------------------------------------------------------------------------
# The cases above check each validation function in isolation. What they cannot
# check is the order the dispatch runs them in -- and that order is the part
# Rust cannot derive. In Python it is made by the language: `OPS` maps each op
# to a lambda whose arguments are `_address(a)`, `_values(a)`, and so on, so all
# of them are evaluated, left to right, before the op body runs. A malformed
# `values` therefore outranks a nonexistent table while a malformed `position`
# does not. `ops/dispatch.rs` transcribes that, and until these cases existed the
# transcription was asserted by a comment and by unit tests whose expected values
# I had written myself -- which is a test of my beliefs, and two of those beliefs
# turned out to be wrong when finally asked of the oracle.
#
# `{H}` interpolates the fixture's first heading, so the cases that are meant to
# get past the address layer actually do, on every document in the corpus.
#
# One deliberate exclusion, a divergence recorded in FINDINGS rather than
# quietly skipped: the legacy `row` alias, kept in the oracle so scheme_d's
# trials stay regradable and rejected for the shipping schema in
# REQUIREMENTS.md 6.2.
#
# Unknown op names used to be excluded beside it, because the oracle's `OPS` was
# longer than the crate's and the two refusals therefore listed different ops.
# With the frontmatter family ported they are the same fifteen entries in the
# same order, so the exclusion is gone and `UNKNOWN_OPS` below compares that
# sentence directly -- which makes the *order* of the table a tested property
# rather than a convention, since the refusal prints it.
DISPATCH_ARGS = [
    # Not an object at all.
    "ABSENT", "null", '"widget"', "[1, 2]", "7", "true",
    # Nothing but an address, or not even that.
    "{}", '{"table": "{H}"}', '{"table": 7}', '{"table": "{\\"heading\\": 1}"}',
    '{"table": {"heading": "{H}", "ordinal": "0"}}',
    '{"table": {"heading": "{H}", "ordinal": 99}}',
    '{"table": {"heading": "{H}", "ordinal": 1.5}}',
    # Two arguments that BOTH fail at the extraction layer, which is the only
    # way their relative order is observable at all: with one bad argument the
    # lambda produces the same message whichever position it holds. Added after
    # `mutate.py`'s `disp-values-late` survived -- swapping `address` and
    # `values` changed nothing measurable, which is a gap in the cases and not a
    # property of the code.
    '{"table": 7, "values": "not json"}',
    '{"table": "{\\"heading\\": 1}", "values": "not json"}',
    '{"table": 7, "where": 7}',
    '{"table": 7, "values": "not json", "where": 7}',
    '{"table": [1], "values": "x", "where": ["Component"], "column": 7}',
    # `values` against the address: which refusal wins.
    '{"table": "Nonexistent", "values": "not json"}',
    '{"table": "Nonexistent", "values": 7}',
    '{"table": "Nonexistent", "values": ["a"], "position": "middle"}',
    # The three ways `values` fails to be a row, which are three repairs.
    '{"table": "{H}", "values": 7}',
    '{"table": "{H}", "values": 0}',
    '{"table": "{H}", "values": null}',
    '{"table": "{H}", "values": []}',
    '{"table": "{H}", "values": {}}',
    '{"table": "{H}", "values": ["only-one"]}',
    '{"table": "{H}", "values": "[\\"a\\", \\"b\\"]"}',
    '{"table": "{H}", "values": {"NoSuchColumn": "x"}}',
    '{"table": "{H}", "values": {"NoSuchColumn": [1]}}',
    # A bad cell against a bad `position`: the cell wins, because `position` is
    # passed through raw and checked last.
    '{"table": "{H}", "values": {"NoSuchColumn": "x"}, "position": "middle"}',
    '{"table": "{H}", "values": [{"a": 1}], "position": "middle"}',
    # `position` on its own, once the row is good. The clamping cases are the
    # ones `PyInt::insert_index` exists for.
    '{"table": "{H}", "values": [], "position": "middle"}',
    '{"table": "{H}", "values": {"x": "y"}, "position": -1}',
    '{"table": "{H}", "values": {"x": "y"}, "position": "0"}',
    '{"table": "{H}", "values": {"x": "y"}, "position": -99}',
    '{"table": "{H}", "values": {"x": "y"}, "position": 10000000000000000000000000000}',
    '{"table": "{H}", "values": {"x": "y"}, "position": true}',
    # `where`, `column`, `value` -- the update/delete arguments. Emitted against
    # all three ops, so each also sees the arguments it does not use.
    '{"table": "{H}", "where": ["Component"]}',
    '{"table": "{H}", "where": 7}',
    '{"table": "{H}", "where": {}}',
    '{"table": "{H}", "where": null, "column": "x", "value": "y"}',
    '{"table": "{H}", "where": {"NoSuchColumn": "x"}, "column": "y", "value": "z"}',
    '{"table": "{H}", "where": {"NoSuchColumn": [1]}, "column": "y"}',
    '{"table": "{H}", "column": null}',
    '{"table": "{H}", "column": 7}',
    '{"table": "{H}", "column": "   "}',
    # F-args, the defect the dispatch was written after: `value` had no check at
    # all, so an absent one wrote the literal string "None" into the cell.
    '{"table": "{H}", "where": {"C": "v"}, "column": "c"}',
    '{"table": "{H}", "where": {"C": "v"}, "column": "c", "value": null}',
    '{"table": "{H}", "where": {"C": "v"}, "column": "c", "value": {"a": 1}}',
    '{"table": "{H}", "where": {"C": "v"}, "column": "c", "value": true}',
    '{"table": "{H}", "where": {"C": "v"}, "column": "c", "value": 1.0}',
    # A cell that would break out of its cell. The escaped forms must survive,
    # or the refusal has removed the only way to write a literal pipe.
    '{"table": "{H}", "values": {"C": "a | b"}}',
    '{"table": "{H}", "values": {"C": "a \\\\| b"}}',
    '{"table": "{H}", "values": ["a | b"]}',
    '{"table": "{H}", "values": {"C": "one\\ntwo"}}',
    '{"table": "{H}", "values": {"C": "x"}, "position": "|"}',
    '{"table": "{H}", "where": {"C": "a | b"}}',
    '{"table": "{H}", "where": {"C": "a \\\\| b"}, "column": "c", "value": "v"}',
    '{"table": "{H}", "where": {"C": "v"}, "column": "c", "value": "a | b"}',
    '{"table": "{H}", "where": {"C": "v"}, "column": "a | b", "value": "v"}',
]

DISPATCH_OPS = ["table-add-row", "table-update-cell", "table-delete-row",
                "table-realign"]

# Op names that are not ops. The near misses are the ones worth having: a model
# that writes `table_add_row` or `frontmatter-get` has made a recoverable
# mistake, and what it recovers from is the list of valid names in the refusal
# -- so this compares that list, in order, on both sides.
UNKNOWN_OPS = [
    "", "table-sort", "table_add_row", "tableaddrow", "TABLE-ADD-ROW",
    "frontmatter-get", "frontmatter-add", "frontmatter", "front-set",
    "list-item-add", "section", "delete", "table-add-row ", " table-add-row",
]

# The list family's equivalent. `{L}` is the JSON address object of the list the
# case is generated against; the substitution is textual for the same reason the
# table family's is.
#
# Emitted against all three ops, so each one also sees the arguments it does not
# use -- `list-remove-item` given a `text` and no `item` must say what IT needs,
# not inherit the other op's requirement.
LIST_DISPATCH_ARGS = [
    # Not an object at all, and the address shapes. The same ladder the table
    # family gets, because §6.4 makes the two addresses one habit: a difference
    # here would be a difference a model has to learn twice.
    "ABSENT", "null", '"beta"', "[1, 2]", "7", "true",
    "{}", '{"list": "Tasks"}', '{"list": 7}', '{"list": "{\\"heading\\": 1}"}',
    '{"list": {"heading": 1}}',
    '{"list": {"heading": "Tasks", "ordinal": "0"}}',
    '{"list": {"heading": "Tasks", "ordinal": 99}}',
    '{"list": {"heading": "Tasks", "ordinal": 1.5}}',
    '{"list": {"heading": "Tasks", "ordinal": null}}',
    # `text`: absent, blank, and the non-string values `_item`'s `str()` turns
    # into content. A number a model meant as an item is an item.
    '{"list": {L}}',
    '{"list": {L}, "text": null}',
    '{"list": {L}, "text": ""}',
    '{"list": {L}, "text": "   "}',
    '{"list": {L}, "text": "added"}',
    '{"list": {L}, "text": 7}',
    '{"list": {L}, "text": 1.5}',
    '{"list": {L}, "text": true}',
    '{"list": {L}, "text": [1]}',
    '{"list": {L}, "text": {"a": 1}}',
    '{"list": {L}, "text": "  padded  "}',
    # `position`, now the table family's parser with the list family's nouns.
    # This used to be compared only against the literal "start", so every other
    # value meant "end" -- and `"Start"` and `0` therefore meant *start* on a
    # table and *end* on a list, silently, reported as success. The casing and
    # whitespace cases are the ones that were wrong; the index cases are the
    # ones a list refuses rather than coerces, because it has no row numbers.
    '{"list": {L}, "text": "added", "position": "start"}',
    '{"list": {L}, "text": "added", "position": "end"}',
    '{"list": {L}, "text": "added", "position": "Start"}',
    '{"list": {L}, "text": "added", "position": "  START  "}',
    '{"list": {L}, "text": "added", "position": "End"}',
    '{"list": {L}, "text": "added", "position": "middle"}',
    '{"list": {L}, "text": "added", "position": 0}',
    '{"list": {L}, "text": "added", "position": 1}',
    '{"list": {L}, "text": "added", "position": -1}',
    '{"list": {L}, "text": "added", "position": "0"}',
    '{"list": {L}, "text": "added", "position": 1.5}',
    '{"list": {L}, "text": "added", "position": [1]}',
    '{"list": {L}, "text": "added", "position": {"a": 1}}',
    '{"list": {L}, "text": "added", "position": null}',
    '{"list": {L}, "text": "added", "position": true}',
    '{"list": {L}, "text": "added", "position": false}',
    # An ill-typed `position` alongside an `after` that decides the placement.
    # It is refused rather than ignored, which is F-args' rule and is the one
    # case where tightening `position` changed a call that used to succeed.
    '{"list": {L}, "text": "added", "after": "beta", "position": "middle"}',
    # `after`, which is the only way to say "nested" -- §6.4's argument for
    # having no `depth`. A blank one falls back to `position`, and a miss is a
    # refusal that names the field as `after` rather than as `item`.
    '{"list": {L}, "text": "added", "after": ""}',
    '{"list": {L}, "text": "added", "after": "   "}',
    '{"list": {L}, "text": "added", "after": "no-such-item"}',
    '{"list": {L}, "text": "added", "after": 7}',
    # The selector, under both spellings and both at once. L3: `add-item` must
    # NOT read `item`, and that is only observable when `text` is absent.
    '{"list": {L}, "item": "no-such-item"}',
    '{"list": {L}, "match": "no-such-item"}',
    '{"list": {L}, "item": null, "match": "no-such-item"}',
    '{"list": {L}, "item": "", "match": "beta"}',
    '{"list": {L}, "item": 7}',
    '{"list": {L}, "item": true}',
    # `checked`, whose truthiness rule is a membership test and not `bool()`:
    # `1` and `1.0` tick, `0` and `2` and `"1"` and `"TRUE"` do not.
    '{"list": {L}, "match": "no-such-item", "checked": 1}',
    '{"list": {L}, "match": "no-such-item", "checked": 1.0}',
    '{"list": {L}, "match": "no-such-item", "checked": 0}',
    '{"list": {L}, "match": "no-such-item", "checked": 2}',
    '{"list": {L}, "match": "no-such-item", "checked": "1"}',
    '{"list": {L}, "match": "no-such-item", "checked": "TRUE"}',
    '{"list": {L}, "match": "no-such-item", "checked": "yes"}',
    '{"list": {L}, "match": "no-such-item", "checked": []}',
    # Content that would break out of its line, which for a list means a
    # newline: an item text carrying one would forge a second item.
    '{"list": {L}, "text": "one\\ntwo"}',
    '{"list": {L}, "text": "- forged"}',
    '{"list": {L}, "text": "1. forged"}',
    '{"list": {L}, "text": "[x] boxed"}',
    '{"list": {L}, "text": "added", "after": "one\\ntwo"}',
]

LIST_DISPATCH_OPS = ["list-add-item", "list-remove-item", "list-set-checked"]

# The section family's equivalent. `{S}` is the JSON address object of the
# section the case is generated against.
#
# Emitted against all six ops, which matters more here than in the other two
# families: four of the six take a `heading` and two take it only to refuse it,
# so the same argument object has to produce six different sentences. S2 and S3
# are exactly the case where a model sends the arguments of the op it meant to
# call, and what it gets back is decided by the op it did call.
SECTION_DISPATCH_ARGS = [
    # Not an object at all, and the address shapes. A bare string is `path` for
    # this family rather than `heading` -- the one place the three addressing
    # habits differ, so the one place it has to be pinned.
    "ABSENT", "null", '"Install"', "[1, 2]", "7", "true",
    "{}", '{"section": "Install"}', '{"section": 7}',
    '{"section": "{\\"path\\": 1}"}',
    '{"section": {"path": 1}}',
    # A′: the address type check, which this family also skipped. `{"path": 1}`
    # used to be stringified to "1" and hunted for. The label in the refusal has
    # to follow the key the caller sent, so both spellings are emitted -- a
    # message naming `section.heading` when the call said `section.path`
    # describes a key that is not in the call.
    '{"section": {"heading": 1}}',
    '{"section": {"path": true}}',
    '{"section": {"heading": [1]}}',
    '{"section": {"path": {"a": 1}}}',
    '{"section": {"path": 1.5}}',
    # A falsy non-string `path` still falls through to `heading`, which is the
    # one place the truthiness rule and the type check interact.
    '{"section": {"path": 0, "heading": "Install"}}',
    '{"section": {"path": 0, "heading": 1}}',
    '{"section": {"path": ""}}',
    '{"section": {"path": "", "heading": "Install"}}',
    '{"section": {"heading": "Install"}}',
    '{"section": {"path": "Install", "heading": "Usage"}}',
    '{"section": {"path": "   "}}',
    '{"section": {"path": ">"}}',
    '{"section": {"path": " > > "}}',
    # The ordinal, now through `check_ordinal` like the other two families.
    # `resolve_section` used to compare with a raw `==`, so `"0"` addressed a
    # table and a list and refused a section, while `true` and `0.0` addressed
    # a section and were refused by the other two. Both directions close here.
    '{"section": {S}, "ordinal": 0}',
    '{"section": {"path": "Install", "ordinal": 0}}',
    '{"section": {"path": "Install", "ordinal": "0"}}',
    '{"section": {"path": "Install", "ordinal": true}}',
    '{"section": {"path": "Install", "ordinal": 0.0}}',
    '{"section": {"path": "Install", "ordinal": 99}}',
    '{"section": {"path": "Install", "ordinal": null}}',
    '{"section": {"path": "Install", "ordinal": 10000000000000000000000000000}}',
    # `true` and a nonzero float need a path that HAS an ordinal 1 or 2 before
    # they mean anything, and "Install" is unique in every file that has one, so
    # the two above only ever reached the single-match branch, never the one
    # that lists real ordinals. These two land: `Setup` is duplicated in
    # `corpus/sections/duplicate-siblings.md` at ordinals 0 and 1, and `Notes`
    # is there three times. `section-ordinal-bool` survived a full run on
    # exactly this gap.
    '{"section": {"path": "Setup", "ordinal": true}}',
    '{"section": {"path": "Notes", "ordinal": 2.0}}',
    # An ordinal that MISSES has two answers, and which one is right depends on
    # the hits, not the ordinal. "Notes" is three sections sharing one path in
    # `duplicate-siblings.md`, so the message lists the real ordinals. "Errors"
    # is twenty-one sections with twenty-one DIFFERENT paths in
    # `api-reference.md`, so an ordinal cannot tell them apart at all and the
    # repair is a longer path -- listing twenty-one zeroes, which is what the
    # first version of this message did, is advice that cannot be taken.
    '{"section": {"path": "Notes", "ordinal": 9}}',
    '{"section": {"path": "Errors", "ordinal": 9}}',
    # And the third answer, which is the one the whole recorded population
    # actually gets: the path matched exactly ONE section, so neither an
    # ordinal nor a longer sibling path is the repair -- the ordinal itself is
    # the evidence the path is wrong. `bench/ordinal_sizing.py` sizes it, and
    # the figure is that command's output rather than a number kept here: it
    # was published as 206 of 206 over a population that counted replay rows
    # twice, and is 140 of 140 through `bench/population.py`. Its two arms both
    # need a case, because the sentence differs:
    # `Install` is childless in `project-readme.md` (the "nothing is nested
    # under it" arm) and has seven children in `deep-nesting.md` (the arm that
    # quotes them, under the cap); `API reference` has ninety-three, which is
    # the only case in this file that reaches the `; ...` truncation. A cap
    # that no case crosses is a cap two implementations can disagree about
    # silently.
    '{"section": {"path": "API reference", "ordinal": 9}}',
    '{"section": {"path": "License", "ordinal": 9}}',
    # And the same two addressed the other way. The branch quotes `want_label`,
    # so the sentence differs by which key the caller sent, and a case that only
    # ever sends `path` cannot tell a correct label from a hard-coded one. The
    # replay is why this matters rather than being tidiness: the draft that said
    # "the longer path" sent two of 27 models to the tool's *file* argument.
    '{"section": {"heading": "API reference", "ordinal": 9}}',
    '{"section": {"heading": "License", "ordinal": 9}}',
    # `text` and `body`, which are aliases pointing opposite ways: `append` and
    # `replace-body` read text-then-body, `insert` reads body-then-text, and
    # `rename` reads `text` as the new NAME. One object, four readings.
    '{"section": {S}}',
    '{"section": {S}, "text": null}',
    '{"section": {S}, "text": ""}',
    '{"section": {S}, "text": "   "}',
    '{"section": {S}, "text": "added"}',
    '{"section": {S}, "body": "added"}',
    '{"section": {S}, "text": "from-text", "body": "from-body"}',
    '{"section": {S}, "text": 7}',
    '{"section": {S}, "text": true}',
    '{"section": {S}, "text": [1]}',
    '{"section": {S}, "text": "\\nleading blank"}',
    '{"section": {S}, "text": "trailing blank\\n\\n"}',
    '{"section": {S}, "text": "one\\ntwo"}',
    '{"section": {S}, "text": "a\\r\\nb"}',
    # The S3 guard and the echo that has to survive it. The echo cases are
    # generated with a literal heading rather than `{S}`'s path, so they only
    # pass through on the fixtures where that section exists -- which is the
    # point: an echo is only an echo of the section actually addressed.
    '{"section": {S}, "text": "added", "heading": "Examples"}',
    '{"section": {S}, "text": "added", "heading": ""}',
    '{"section": {S}, "text": "added", "heading": "   "}',
    '{"section": {S}, "text": "added", "new_heading": "Examples"}',
    '{"section": {S}, "text": "added", "title": "Examples"}',
    '{"section": {S}, "text": "added", "heading": 7}',
    '{"section": {S}, "heading": "## Quoted"}',
    '{"section": {S}, "heading": "###"}',
    '{"section": {S}, "heading": "### Closed ###"}',
    '{"section": {S}, "heading": "  padded  "}',
    '{"section": {S}, "heading": null}',
    '{"section": {S}, "heading": [1]}',
    # `overwrite` is `bool()` and not the list family's membership test, so
    # every truthy value acknowledges and every falsy one does not.
    '{"section": {S}, "text": "new", "overwrite": true}',
    '{"section": {S}, "text": "new", "overwrite": false}',
    '{"section": {S}, "text": "new", "overwrite": null}',
    '{"section": {S}, "text": "new", "overwrite": 0}',
    '{"section": {S}, "text": "new", "overwrite": 1}',
    '{"section": {S}, "text": "new", "overwrite": "no"}',
    '{"section": {S}, "text": "new", "overwrite": []}',
    # `position`, which decides the new section's level and nothing else can.
    '{"section": {S}, "heading": "New", "position": "before"}',
    '{"section": {S}, "heading": "New", "position": "after"}',
    '{"section": {S}, "heading": "New", "position": "first-child"}',
    '{"section": {S}, "heading": "New", "position": "last-child"}',
    '{"section": {S}, "heading": "New", "position": "inside"}',
    '{"section": {S}, "heading": "New", "position": null}',
    '{"section": {S}, "heading": "New", "position": 0}',
    '{"section": {S}, "heading": "New", "position": true}',
    # S6: a heading inside `body` is refused rather than written at a level the
    # model guessed. The fenced case must NOT be refused -- it is parsed, not
    # pattern-matched, so `# comment` inside a bash block is prose.
    '{"section": {S}, "heading": "New", "body": "### Added\\n\\n- a"}',
    '{"section": {S}, "heading": "New", "body": "prose\\n\\n## Later"}',
    '{"section": {S}, "heading": "New", "body": "```bash\\n# comment\\n```"}',
    '{"section": {S}, "heading": "New", "body": "> # quoted"}',
    '{"section": {S}, "heading": "New", "body": "Setext\\n======"}',
    # `children`, the structured alternative, and the three spellings of it.
    '{"section": {S}, "heading": "New", "children": ["Added", "Fixed"]}',
    '{"section": {S}, "heading": "New", "children": [{"heading": "Added", "body": "- a"}]}',
    '{"section": {S}, "heading": "New", "children": {"heading": "Added"}}',
    '{"section": {S}, "heading": "New", "children": [{"heading": "A", "children": [{"heading": "B"}]}]}',
    '{"section": {S}, "heading": "New", "children": [{"body": "no heading"}]}',
    '{"section": {S}, "heading": "New", "children": [{"heading": "A", "body": "## nested heading"}]}',
    '{"section": {S}, "heading": "New", "children": [7]}',
    '{"section": {S}, "heading": "New", "children": 7}',
    '{"section": {S}, "heading": "New", "children": []}',
    '{"section": {S}, "heading": "New", "subsections": ["Added"]}',
    '{"section": {S}, "heading": "New", "sections": ["Added"]}',
    '{"section": {S}, "heading": "New", "children": [], "sections": ["Added"]}',
    # The falsy LAST operand, which is the only shape that reaches the op with a
    # value at all: `[] or None or []` is `[]`, not `None`, so `section_insert`
    # gets an empty list and has to re-test its truthiness rather than assume a
    # value means children. Nothing above reaches it -- every other spelling
    # either finds a truthy operand or ends on an absent one -- and the port's
    # one real defect lived exactly here.
    '{"section": {S}, "heading": "New", "sections": []}',
    '{"section": {S}, "heading": "New", "sections": 0}',
    '{"section": {S}, "heading": "New", "children": [], "sections": []}',
    '{"section": {S}, "heading": "New", "children": [], "subsections": [], "sections": ""}',
    # Two TRUTHY spellings at once, which is the only shape that can see the
    # chain's ORDER. Everything above either has one truthy operand or none, so
    # `children` before `subsections` before `sections` was unmeasured -- the
    # falsy cases pin the tail of the chain and say nothing about its head.
    '{"section": {S}, "heading": "New", "children": ["From children"], "sections": ["From sections"]}',
    '{"section": {S}, "heading": "New", "subsections": ["From subsections"], "sections": ["From sections"]}',
    # A `null` INSIDE the list, which is the one value whose Python type name
    # (`NoneType`) is not its JSON one (`null`). `children: null` is falsy and
    # never reaches the message; `children: [null]` is a truthy list holding a
    # value that is neither a string nor an object, so it reaches the refusal
    # that names the type. `section-type-name` survived a full run on this.
    '{"section": {S}, "heading": "New", "children": [null]}',
    '{"section": {S}, "heading": "New", "children": [true]}',
    # `text` and `body` together WITH a heading, which is the only way to see
    # which of the two `insert` prefers: without a heading it refuses before it
    # reads either. The generic `text`/`body` case above is exactly that.
    '{"section": {S}, "heading": "New", "text": "from-text", "body": "from-body"}',
    # `level`, which is `int()` and therefore wider than `check_ordinal`: a
    # numeric string parses, a bool is an integer, a float truncates.
    '{"section": {S}, "level": 1}',
    '{"section": {S}, "level": 2}',
    '{"section": {S}, "level": 3}',
    '{"section": {S}, "level": 6}',
    '{"section": {S}, "level": 7}',
    '{"section": {S}, "level": 0}',
    '{"section": {S}, "level": -1}',
    '{"section": {S}, "level": "2"}',
    '{"section": {S}, "level": " 2 "}',
    '{"section": {S}, "level": 2.9}',
    '{"section": {S}, "level": true}',
    '{"section": {S}, "level": null}',
    '{"section": {S}, "level": "two"}',
    '{"section": {S}, "level": [2]}',
    '{"section": {S}, "level": 10000000000000000000000000000}',
    '{"section": {S}, "level": 2, "subtree": false}',
    '{"section": {S}, "level": 2, "subtree": null}',
    '{"section": {S}, "level": 2, "subtree": 0}',
    '{"section": {S}, "level": 2, "subtree": "no"}',
]

SECTION_DISPATCH_OPS = ["section-append", "section-replace-body",
                        "section-insert", "section-delete", "section-rename",
                        "section-set-level"]

# The frontmatter family's equivalent. `{K}` is the first addressable path in
# the fixture, so the cases that are meant to land on a key that exists do so on
# every file that has a block; the hardcoded paths below it are aimed at
# specific shapes and deliberately miss on every other fixture, which is how the
# "no frontmatter key" refusal -- near matches, the key list, the truncation
# past twelve -- gets exercised on documents of every size.
#
# `key` and `value` both ride as real JSON rather than through flat string
# fields, because the type of each is what is being tested: `_check_key` refuses
# a number and `_yaml_scalar` quotes by *text* and not by type, so `8` and `"8"`
# must produce the same byte and only a typed case can say so.
FRONT_DISPATCH_ARGS = [
    # Not an object at all, then the `key` ladder.
    "ABSENT", "null", '"title"', "[1, 2]", "7", "true",
    "{}", '{"key": null}', '{"key": 7}', '{"key": 1.5}', '{"key": true}',
    '{"key": ["a"]}', '{"key": {"a": 1}}',
    '{"key": ""}', '{"key": "a..b"}', '{"key": ".a"}', '{"key": "a."}',
    '{"key": "[0]"}',
    # A key that exists here, with `value` in every shape it can arrive in.
    # The absent one first: it is the refusal, and an explicit null is not.
    '{"key": "{K}"}',
    '{"key": "{K}", "value": null}',
    '{"key": "{K}", "value": 8}',
    '{"key": "{K}", "value": "8"}',
    '{"key": "{K}", "value": true}',
    '{"key": "{K}", "value": false}',
    '{"key": "{K}", "value": 1.5}',
    '{"key": "{K}", "value": 1e16}',
    '{"key": "{K}", "value": 1.0}',
    '{"key": "{K}", "value": 12345678901234567890123456789}',
    '{"key": "{K}", "value": ""}',
    '{"key": "{K}", "value": " padded "}',
    '{"key": "{K}", "value": "plain text"}',
    # Every branch of `_yaml_scalar`'s quoting predicate, one case each.
    '{"key": "{K}", "value": "- leading dash"}',
    '{"key": "{K}", "value": "#hash first"}',
    '{"key": "{K}", "value": "|pipe first"}',
    '{"key": "{K}", "value": ">gt first"}',
    '{"key": "{K}", "value": "@at first"}',
    '{"key": "{K}", "value": "has: a colon"}',
    '{"key": "{K}", "value": "has:no space"}',
    '{"key": "{K}", "value": "a #b"}',
    '{"key": "{K}", "value": "a#b"}',
    '{"key": "{K}", "value": "with\\ttab"}',
    '{"key": "{K}", "value": "with\\nnewline"}',
    '{"key": "{K}", "value": "quote\\" and \\\\slash"}',
    # The line above holds both characters the quoting escapes, and quotes
    # neither: `" ` is not `: `, so the predicate says bare and the escaping
    # never runs. This one is quoted *and* holds a backslash, which is the only
    # way to reach the doubling. `mutate.py:front-quote-escape` survived until
    # it existed.
    '{"key": "{K}", "value": "a: b \\\\ c"}',
    '{"key": "{K}", "value": ["a"]}',
    '{"key": "{K}", "value": {"a": 1}}',
    # Paths aimed at one shape each. Most miss on most fixtures, which is the
    # point: a refusal that has only ever been generated against the file it
    # was written for has been read, not tested.
    '{"key": "title", "value": "New"}',
    '{"key": "build.jobs", "value": 8}',
    '{"key": "build.target", "value": "debug"}',
    '{"key": "tags", "value": "x"}',
    '{"key": "tags[0]", "value": "x"}',
    '{"key": "tags[9]", "value": "x"}',
    '{"key": "authors[0]", "value": "x"}',
    '{"key": "authors[0].name", "value": "x"}',
    '{"key": "authors[0].role", "value": "x"}',
    '{"key": "authors[0].new", "value": "x"}',
    '{"key": "multiline", "value": "x"}',
    '{"key": "multiline.new", "value": "x"}',
    '{"key": "empty_value", "value": "x"}',
    '{"key": "quoted_key", "value": "x"}',
    '{"key": "key with spaces", "value": "x"}',
    '{"key": "nested.deeply.buried", "value": "x"}',
    '{"key": "nested.deeply.new", "value": "x"}',
    '{"key": "build.cache.size", "value": "x"}',
    '{"key": "tags.new", "value": "x"}',
    '{"key": "title.new", "value": "x"}',
    '{"key": "dotted.key", "value": "x"}',
    '{"key": "deep.level.leaf", "value": "x"}',
    '{"key": "deep.sequence[1]", "value": "x"}',
    '{"key": "list_of_maps[0].name", "value": "x"}',
    '{"key": "list_of_maps[1]", "value": "x"}',
    '{"key": "empty_null", "value": "x"}',
    '{"key": "bare_items[0]", "value": "x"}',
    '{"key": "bare_items[1]", "value": null}',
    '{"key": "chomp_strip", "value": "x"}',
    '{"key": "deep_seq.nested[0]", "value": "x"}',
    '{"key": "solo", "value": "x"}',
    '{"key": "only", "value": "x"}',
    # New keys: top level, one needing quotes, and one under a map.
    '{"key": "new_key", "value": "x"}',
    '{"key": "brand new", "value": "x"}',
    '{"key": "-dashy", "value": "x"}',
    # A created key is quoted on a bare `:`, not on `: ` -- a key is not a
    # value and the two predicates differ on exactly this. Every other created
    # key here is clean, so the difference was unreachable.
    '{"key": "new:key", "value": "x"}',
    '{"key": "new#key", "value": "x"}',
    '{"key": "new_key", "value": null}',
    '{"key": "build.new_key", "value": "x"}',
    '{"key": "deep.new_key", "value": "x"}',
    # Host-owned create/update preconditions. False is the unguarded path;
    # true reaches both successful and refusing existence checks. Malformed
    # flags and the contradictory pair pin the repair rather than relying on a
    # router to have behaved perfectly.
    '{"key": "{K}", "value": "x", "must_absent": false}',
    '{"key": "{K}", "value": "x", "must_absent": true}',
    '{"key": "{K}", "value": "x", "must_exist": true}',
    '{"key": "new_key", "value": "x", "must_absent": true}',
    '{"key": "new_key", "value": "x", "must_exist": true}',
    '{"key": "new_key", "value": "x", "must_absent": true, "must_exist": true}',
    '{"key": "new_key", "value": "x", "must_absent": "true"}',
    '{"key": "new_key", "value": "x", "must_exist": null}',
]

FRONT_DISPATCH_OPS = ["frontmatter-set", "frontmatter-delete"]

# `key` for the read, as JSON. A `null` here is NOT a refusal -- the oracle's
# parameter defaults to `None` and it tests `if key is not None`, so an explicit
# null and an absent argument are one call. That is the opposite of
# `frontmatter-set`, where absent is required and null is a value, and the two
# ops sitting a case apart is what keeps the asymmetry honest.
FRONT_GET_KEYS = [
    "null", '""', '"{K}"', '"title"', '"build"', '"build.jobs"',
    '"build.missing"', '"tags"', '"tags[0]"', '"authors"', '"authors[0]"',
    '"authors[0].role"', '"multiline"', '"nested"', '"nested.deeply"',
    '"deep"', '"list_of_maps"', '"dotted.key"', '"solo"', '"only"',
    "7", "true", '["a"]', '{"a": 1}', '"a..b"',
]

# The value is fed to each of these; the payload is `repr()` of what comes back,
# or the refusal. Uniformly `repr` even where the return is already a string, so
# that `'0'` and `0` cannot be confused in a comparison.
ARG_FNS = [
    "unstring_obj", "unstring_obj_plain", "unstring_objarr", "clean_keys",
    "check_address", "check_heading", "check_ordinal", "check_position",
    "check_cell", "check_where", "check_filter", "check_column",
    "address", "values", "where_arg",
]

# Values whose Python `repr` is the thing under test rather than an incidental
# detail of a message. The float spread is aimed at CPython's `repr` switching
# to exponential form -- `1e16` prints as `1e+16` and `1e-5` as `1e-05`, with a
# two-digit exponent and a mandatory `.0` in fixed form -- which is a rule
# `json.rs::py_float_repr` has to reproduce and which no corpus case reaches.
REPR_VALUES = ARG_VALUES + [
    "1e15", "1e22", "123456789012345678", "-0.0", "0.1", "1e-323",
    "1.7976931348623157e308", "3.14159265358979", "100.0", "1e5",
    # Not JSON. Both sides must decline to parse these, which is the only test
    # `json.rs::parse`'s strictness gets.
    "{'a': 1}", "[1,]", "nan", "Infinity", "01", "+1", '"\\x00"', "{a: 1}",
    '"unterminated', "[1 2]", "tru", "",
]


# Frontmatter addresses. Nothing in the corpus reaches the malformed half of
# this list: the parser only ever hands out paths it built, so `parse_path`'s
# refusal branch and its index arithmetic are only testable by calling it.
# `[99999999999999999999]` is the one that decides a representation -- Python's
# `int` holds it, so the port has to as well, and a machine integer does not.
PATH_VALUES = [
    "", "a", "a.b", "a.b.c", "authors[0]", "authors[0].role",
    "a[0][1]", "a[0].b[1].c", "[0]", "[0].a", "a[0]b", "a[0]b[1]",
    # Empty segments, which are unreadable rather than an empty-string key.
    ".", "..", ".a", "a.", "a..b", "...",
    # Brackets that are not an index, and are therefore part of the key name.
    "a[]", "a[x]", "a[-1]", "a[ 1 ]", "a[1", "a1]", "a[1]]", "a[[1]",
    # Leading zeros: `int()` makes `[007]` and `[7]` one address.
    "a[0]", "a[00]", "a[007]", "a[0000000]",
    "a[99999999999999999999]", "a[18446744073709551616]",
    "a[9223372036854775808]", "a[4294967296]",
    # Keys that are not identifiers, since nothing stops one being written.
    " ", " a ", "a b", "a-b", "a b[0]", "#a", "-a", "a:b", '"a"', "'a'",
    "é.ü", "中文[0]",
]


# --------------------------------------------------------------------------
# case generation
# --------------------------------------------------------------------------

class Cases:
    def __init__(self):
        self.rows = []

    def add(self, file, op, **args):
        cid = str(len(self.rows))
        blob = RS.join(f"{k}{GS}{v}" for k, v in args.items())
        self.rows.append((cid, file, op, args))
        return f"{cid}{FS}{file}{FS}{op}{FS}{blob}"


def generate(files):
    cases, lines = Cases(), []

    def emit(file, op, **args):
        lines.append(cases.add(file, op, **args))

    # Document-independent, so emitted once against a nominal fixture. The file
    # is read and ignored by both sides, which keeps the wire format uniform
    # rather than adding a second one for arguments that have no document.
    nominal = files[0]
    for text in REPR_VALUES:
        emit(nominal, "py_repr", text=text)
    for text in PATH_VALUES:
        emit(nominal, "parse_path", text=text)
    for op in UNKNOWN_OPS:
        emit(nominal, "apply_op", opname=op, args='{"table": "x"}')
    for fn in ARG_FNS:
        for text in ARG_VALUES:
            emit(nominal, "check_args", fn=fn, text=text)

    for rel in files:
        content = open(os.path.join(ROOT, rel), newline="").read()
        for op in ("find_sections", "inert_headings", "find_tables",
                   "find_lists", "find_frontmatter", "list_tables",
                   "list_lists"):
            emit(rel, op)
        emit(rel, "render_table_list", path=rel)
        emit(rel, "render_list_summary", path=rel)

        # `describe_change` against the two families that are not sections.
        # It reads headings, so a table or list edit is the case where it has
        # to describe a change to a section's *body* without any heading having
        # moved -- and, on a document with no headings at all, the case where
        # every branch it has stays silent and the backstop is all that speaks.
        # Both are paths the section sweep below cannot reach.
        for e in F.list_tables(content, rel):
            ta = json.dumps({"heading": e["heading"], "ordinal": e["ordinal"]})
            emit(rel, "describe_change", opname="table-add-row",
                 args='{"table": %s, "values": ["zq7"]}' % ta)
        for e in F.list_lists(content, rel):
            la = json.dumps({"heading": e["heading"], "ordinal": e["ordinal"]})
            emit(rel, "describe_change", opname="list-add-item",
                 args='{"list": %s, "text": "zq7"}' % la)

        # The two documents `describe_change` is asked about are usually one op
        # apart. These are the cases where they are not: an identity pair, which
        # must say so rather than report the call back, and an edit to the text
        # before the first heading, which no op in the corpus can produce
        # because no corpus fixture has content there.
        emit(rel, "describe_change", after=json.dumps(content))
        emit(rel, "describe_change", after=json.dumps("zq7 preamble.\n\n" + content))
        emit(rel, "describe_change", after=json.dumps(content + "\nzq7 trailer.\n"))

        # One heading swapped for one is a rename; one swapped for *two*, or two
        # for one, is not, and the guard that tells them apart needs a `replace`
        # opcode whose two sides are different lengths. No op produces one --
        # `rename` is 1:1 by construction and `insert` leaves the old heading
        # standing -- so the after-document is spliced here. Without these the
        # guard can be widened from `and` to `or` and nothing notices.
        atx = [s for s in find_sections(content) if s.style == "atx"]
        doc_lines = content.split("\n")
        if atx:
            s = atx[-1]
            cr = "\r" if doc_lines[s.start].endswith("\r") else ""
            hashes = "#" * s.level
            emit(rel, "describe_change", after=json.dumps("\n".join(
                doc_lines[:s.start]
                + [hashes + " Zq7 One" + cr, cr, hashes + " Zq7 Two" + cr]
                + doc_lines[s.heading_end + 1:])))
        if len(atx) > 1:
            first, last = atx[-2], atx[-1]
            cr = "\r" if doc_lines[first.start].endswith("\r") else ""
            emit(rel, "describe_change", after=json.dumps("\n".join(
                doc_lines[:first.start]
                + ["#" * first.level + " Zq7 Merged" + cr]
                + doc_lines[last.heading_end + 1:])))

        # Three headings appended whose levels are *not* monotone: the first is
        # not an ancestor of the third, so the run has to stay itemized instead
        # of collapsing into "and 2 nested under it". Every subtree an op can
        # produce descends properly, so `all` can be widened to `any` and only
        # this shape notices.
        if atx and atx[-1].level < 6:
            s = atx[-1]
            cr = "\r" if doc_lines[s.start].endswith("\r") else ""
            lv, deeper = "#" * s.level, "#" * (s.level + 1)
            emit(rel, "describe_change", after=json.dumps("\n".join(
                doc_lines + [lv + " Zq7 P" + cr, cr, deeper + " Zq7 Q" + cr, cr,
                             lv + " Zq7 R" + cr, cr])))

        entries = F.list_tables(content, rel)
        tables = find_tables(content)
        # A whole-file address: legal when the file has exactly one table, and
        # a refusal listing candidates when it does not. Both are worth a case.
        emit(rel, "resolve_table")

        # The list resolvers, over every list in the file. Emitted here rather
        # than beside the list edit ops because a resolver divergence would
        # otherwise only surface through whichever op happened to depend on it,
        # and the address forms below (case, path tail, bad ordinal, near miss)
        # are the same six the table family gets -- the two families are meant
        # to teach one addressing habit, so they are tested against one list.
        emit(rel, "resolve_list")
        for l, e in zip(find_lists(content), F.list_lists(content, rel)):
            laddr = {"heading": e["heading"], "ordinal": str(e["ordinal"])}
            emit(rel, "list_get", **laddr)
            emit(rel, "resolve_list", **laddr)
            emit(rel, "resolve_list", heading=e["heading"])
            emit(rel, "resolve_list", heading=e["heading"], ordinal="99")
            emit(rel, "resolve_list", heading=e["heading"][:-1] + "zz")
            emit(rel, "resolve_list", heading=e["heading"].lower())
            emit(rel, "resolve_list", heading=e["heading"].split(" > ")[-1])

            # `resolve_item`'s three passes, each reached deliberately: the
            # exact text, the same text recased, and a substring of it. A blank
            # selector and a miss cover the two refusals, and the empty-string
            # item is the one an empty list item produces -- which matches every
            # item by substring and must refuse as ambiguous, not resolve.
            for it in l.items[:4]:
                emit(rel, "resolve_item", item=it.text, **laddr)
                emit(rel, "resolve_item", item=it.text.upper(), **laddr)
                emit(rel, "resolve_item", item=it.text[:3], **laddr)
                emit(rel, "resolve_item", item=f"  {it.text}  ", **laddr)
            emit(rel, "resolve_item", item="", **laddr)
            emit(rel, "resolve_item", item="   ", **laddr)
            emit(rel, "resolve_item", item="no-such-item-anywhere", **laddr)

            # The three edits, through the dispatch, against every list in the
            # corpus. `apply_op` is the right level for these for the same
            # reason `table-realign` goes through it: they take arguments and
            # return a document, so what gets compared is the document a model
            # would receive and not an intermediate the model never sees.
            #
            # The per-item loop is where the conventions live. Adding after each
            # of the first four items exercises the marker character, the
            # ordered delimiter, the indent of that item's depth, the loose
            # blank line and -- when the group is ordered -- the renumbering,
            # once per shape the corpus contains.
            la = json.dumps({"heading": e["heading"], "ordinal": e["ordinal"]})
            for text in LIST_DISPATCH_ARGS:
                for op in LIST_DISPATCH_OPS:
                    emit(rel, "apply_op", opname=op, args=text.replace("{L}", la))
            for it in l.items[:4]:
                sel = json.dumps(it.text)
                for tail in (
                    '"text": "added", "after": %s' % sel,
                    '"text": "added", "after": %s, "checked": true' % sel,
                    '"text": "added", "after": %s, "checked": false' % sel,
                    '"text": "added", "after": %s, "checked": null' % sel,
                    '"item": %s' % sel,
                    '"match": %s' % sel,
                    '"item": %s, "checked": true' % sel,
                    '"item": %s, "checked": false' % sel,
                    '"item": %s, "checked": null' % sel,
                ):
                    args = '{"list": %s, %s}' % (la, tail)
                    for op in LIST_DISPATCH_OPS:
                        emit(rel, "apply_op", opname=op, args=args)

            # `list-set-checked` needs task items, and the loop above finds
            # almost none: the first four items of a corpus list are usually
            # plain prose, so the op refuses "not a task item" and the line
            # rewrite -- the only thing it does -- is never compared. Ticking
            # and unticking every checkbox in the file is what actually exercises
            # it, and it also pins the `[X]` case: unticking a capital box must
            # produce `[ ]`, and re-ticking it must produce lowercase `[x]`
            # rather than restore the author's capital.
            for it in [o for o in l.items if o.checkbox is not None][:6]:
                sel = json.dumps(it.text)
                # The truthiness rule gets its real-item cases here rather than
                # in LIST_DISPATCH_ARGS, where every `checked` rides on a
                # selector that misses: a refusal is decided before the value is
                # ever read, so those cases cannot tell `"yes"` from `"TRUE"`.
                # They are the same four values, aimed at an item that exists.
                for tail in ('"item": %s, "checked": true' % sel,
                             '"item": %s, "checked": false' % sel,
                             '"item": %s, "checked": "yes"' % sel,
                             '"item": %s, "checked": "TRUE"' % sel,
                             '"item": %s, "checked": 1' % sel,
                             '"item": %s, "checked": 2' % sel,
                             '"match": %s' % sel):
                    emit(rel, "apply_op", opname="list-set-checked",
                         args='{"list": %s, %s}' % (la, tail))

        # The section family. The resolvers first, over every section in the
        # file: a resolver divergence would otherwise surface only through
        # whichever op happened to depend on it, and this family's resolver does
        # more work than the other two -- four narrowest-first passes, an
        # ordinal comparison that is a raw `==`, and a not-found path that
        # consults the inert headings before it gives up.
        emit(rel, "section_outline")
        emit(rel, "render_section_outline", path=rel)
        emit(rel, "resolve_section")
        # The inert headings BY NAME. Nothing else in this file asks for one:
        # every other query is built from a real section's path, a lowercasing
        # of it, or a deliberate misspelling, so in 63584 cases the branch that
        # answers "that heading is inside a code fence" ran zero times. The
        # feature had prose, a mutation and no coverage, and `section-inert-case`
        # survived a full run because of it. Both cases are needed: the fold is
        # the whole point of the lookup, and the corpus's six inert headings are
        # all mixed case, so the unfolded query is the one that must still work
        # and the folded one is the one that proves the fold is there.
        for h in F.inert_headings(content):
            emit(rel, "resolve_section", spath=h["text"])
            emit(rel, "resolve_section", spath=h["text"].lower())
        outline = F.section_outline(content)
        for e in outline:
            p = e["path"]
            leaf = p.split(" > ")[-1]
            emit(rel, "resolve_section", spath=p, sordinal=str(e["ordinal"]))
            emit(rel, "resolve_section", spath=p)
            emit(rel, "resolve_section", spath=p, sordinal="99")
            emit(rel, "resolve_section", spath=p.lower())
            emit(rel, "resolve_section", spath=leaf)
            emit(rel, "resolve_section", spath=leaf.lower())
            emit(rel, "resolve_section", spath=p[:-1] + "zz")
            # `path` absent and `heading` carrying what `path` usually does,
            # which is the branch `path or heading` exists for.
            emit(rel, "resolve_section", sheading=p)

            # The six ops against every section in the corpus, with arguments
            # good enough to reach the edit. This is where the conventions live:
            # `own_end` against `end`, the trailing gap `delete` absorbs, the
            # heading syntax `rename` has to rebuild, the level arithmetic
            # `set-level` does to a whole subtree, and the four insertion points
            # -- once per section shape the corpus contains.
            sa = json.dumps({"path": p, "ordinal": e["ordinal"]})
            for op, tail in (
                ("section-append", '"text": "Appended."'),
                ("section-append", '"text": "One.\\n\\nTwo."'),
                # The echo that has to pass the S3 guard: this section's own
                # name, which is only an echo against this section.
                ("section-append",
                 '"text": "Appended.", "heading": %s' % json.dumps(e["text"])),
                ("section-append", '"text": "Appended.", "heading": %s' % json.dumps(p)),
                ("section-replace-body", '"text": "Replaced."'),
                ("section-replace-body", '"text": "Replaced.", "overwrite": true'),
                ("section-delete", None),
                ("section-rename", '"heading": "Renamed"'),
                ("section-rename", '"heading": "## Renamed"'),
                ("section-set-level", '"level": 1'),
                ("section-set-level", '"level": 2'),
                ("section-set-level", '"level": 3'),
                ("section-set-level", '"level": 3, "subtree": false'),
                ("section-set-level", '"level": 6'),
                ("section-insert", '"heading": "Inserted", "position": "before"'),
                ("section-insert", '"heading": "Inserted", "position": "after"'),
                ("section-insert", '"heading": "Inserted", "position": "first-child"'),
                ("section-insert", '"heading": "Inserted", "position": "last-child"'),
                ("section-insert",
                 '"heading": "Inserted", "position": "after", "body": "Prose."'),
                ("section-insert",
                 '"heading": "Inserted", "position": "last-child",'
                 ' "children": ["Added", "Fixed"]'),
            ):
                args = ('{"section": %s}' % sa if tail is None
                        else '{"section": %s, %s}' % (sa, tail))
                emit(rel, "apply_op", opname=op, args=args)

            # The same sections again, through `describe_change` (§9 criterion
            # 11). A subset of the ops above rather than all of them: the
            # description branches on what the *documents* differ by, so a
            # second `set-level` target says nothing a first one did not, while
            # each op below reaches a branch no other one does -- a body delta,
            # a one-for-one rename, a removed subtree that collapses, a level
            # run with descendants, a plain addition, and two additions that
            # must stay itemized. The full 21 would triple this file's runtime
            # to re-answer the same questions.
            for op, tail in (
                ("section-append", '"text": "One.\\n\\nTwo."'),
                ("section-replace-body", '"text": "Replaced.", "overwrite": true'),
                ("section-delete", None),
                ("section-rename", '"heading": "Renamed"'),
                ("section-set-level", '"level": 1'),
                ("section-set-level", '"level": 3'),
                ("section-insert", '"heading": "Inserted", "position": "after"'),
                ("section-insert", '"heading": "Inserted", "position": "first-child"'),
                ("section-insert",
                 '"heading": "Inserted", "position": "last-child",'
                 ' "children": ["Added", "Fixed"]'),
            ):
                args = ('{"section": %s}' % sa if tail is None
                        else '{"section": %s, %s}' % (sa, tail))
                emit(rel, "describe_change", opname=op, args=args)

        for t, e in zip(tables, entries):
            cols = list(t.cells(t.header))
            rows = t.rows()
            if not cols:
                continue
            addr = {"heading": e["heading"], "ordinal": str(e["ordinal"])}
            named = {f"vk{i}": c for i, c in enumerate(cols)}
            named.update({f"vv{i}": f"n{i}" for i in range(len(cols))})
            ordered = {f"vo{i}": f"o{i}" for i in range(len(cols))}

            emit(rel, "resolve_table", **addr)
            emit(rel, "resolve_table", heading=e["heading"])
            emit(rel, "resolve_table", heading=e["heading"], ordinal="99")
            emit(rel, "resolve_table", heading=e["heading"][:-1] + "zz")
            emit(rel, "resolve_table", heading=e["heading"].lower())
            emit(rel, "resolve_table", heading=e["heading"].split(" > ")[-1])

            for pos in ("end", "start", "1"):
                emit(rel, "add_row", position=pos, **addr, **named)
            emit(rel, "add_row", position="end", **addr, **ordered)
            # The re-pad: one value wider than its column, which is what
            # rewrites every line of an aligned table and must rewrite none of
            # a ragged one.
            wide = dict(named)
            wide["vv0"] = LONG
            emit(rel, "add_row", position="end", **addr, **wide)
            # The same re-pad, driven by a cell that is wider in bytes than in
            # characters -- which is the only way to tell a character-count
            # width from a byte-count one.
            wide_utf8 = dict(named)
            wide_utf8["vv0"] = LONG_WIDE
            emit(rel, "add_row", position="end", **addr, **wide_utf8)

            # Refusal paths.
            emit(rel, "add_row", position="end", shape="named", **addr)
            short = {k: v for k, v in ordered.items() if k != f"vo{len(cols)-1}"}
            emit(rel, "add_row", position="end", **addr, **short)
            bad = dict(named)
            bad["vk0"] = "NoSuchColumn"
            emit(rel, "add_row", position="end", **addr, **bad)

            for i, row in enumerate(rows[:3]):
                sel = {"wk0": cols[0], "wv0": row[0] if row else ""}
                emit(rel, "delete_row", **addr, **sel)
                emit(rel, "update_cell", column=cols[-1], value="short",
                     **addr, **sel)
                emit(rel, "update_cell", column=cols[-1], value=LONG,
                     **addr, **sel)
                emit(rel, "update_cell", column="NoSuchColumn", value="x",
                     **addr, **sel)
                emit(rel, "resolve_row", **addr, **sel)
                # The B2 failure: a selector where one key matches and another
                # does not, which the naive message pointed the wrong way.
                if len(cols) > 1:
                    emit(rel, "resolve_row", **addr, **sel,
                         **{"wk1": cols[-1], "wv1": "definitely-not-this"})
            emit(rel, "resolve_row", **addr, wk0=cols[0], wv0="no-such-value")
            emit(rel, "resolve_row", **addr, wk0="NoSuchColumn", wv0="x")
            emit(rel, "resolve_row", **addr)

            # The near-match path on a value long enough to have been broken.
            #
            # These probes were added to reach difflib's autojunk heuristic,
            # which engaged at 200 characters of the *caller's value* -- `b` is
            # the word, not the candidate list -- and which no corpus cell came
            # within a tenth of. They found what they were aimed at: at that
            # length the heuristic purged the spaces and vowels out of the
            # index and the message came back `Near matches: none` with a 98%
            # match in the column. F-nearmatch took the heuristic out of both
            # implementations, so there is no longer a branch here to reach.
            #
            # The probes stay, and are now the cases that pin what replaced it.
            # 46 of them changed answer when the heuristic came out, so they are
            # the whole of the differential evidence for that change, and
            # `difflib-autojunk-back` is the mutation that puts it back.
            #
            # The probe is one word short of a real cell. That keeps it far
            # above the cutoff against its own row and leaves the *paraphrase*
            # next to it sitting near 0.4, which is what makes a ranking
            # decision observable in the message rather than merely taken.
            # Deleting each word in turn rather than one chosen word is the
            # difference between a probe and a magic string.
            for ci, col in enumerate(cols):
                for row in rows:
                    cell = row[ci] if ci < len(row) else ""
                    if len(cell) < LONG_VALUE_N:
                        continue
                    words = cell.split(" ")
                    for wi in range(len(words)):
                        probe = " ".join(words[:wi] + words[wi + 1:])
                        if len(probe) < LONG_VALUE_N:
                            continue
                        emit(rel, "resolve_row", **addr, wk0=col, wv0=probe)

            # A value that lands *between* the two cutoffs anyone would pick.
            #
            # The ops ask `get_close_matches` for `cutoff=0.4`; difflib's own
            # default is 0.6. A case only sees the difference if some candidate
            # scores between them, and almost nothing does by accident: a value
            # taken from a document either matches its own cell near 1.0 or is
            # unrelated to every cell and scores near 0. `near-cutoff` was
            # caught by a single case for exactly that reason.
            #
            # A prefix of `f` of a cell scores `2f / (1 + f)` against it, so a
            # third of a cell lands at ~0.5 -- inside the gap by construction,
            # from any cell, without a threshold written into the harness. 95 of
            # the corpus's 1177 cells land in (0.4, 0.6) this way; the rest are
            # ordinary refusals and cost nothing.
            for ci, col in enumerate(cols):
                for row in rows:
                    cell = row[ci] if ci < len(row) else ""
                    words = cell.split(" ")
                    if len(words) < 3:
                        continue
                    emit(rel, "resolve_row", **addr, wk0=col,
                         wv0=" ".join(words[:len(words) // 3]))

            # The read op. Six shapes, because a read has failure modes an
            # edit does not: matching nothing is an ordinary answer here and a
            # refusal there, and an empty filter reaches `check_filter` by a
            # different route than an absent one.
            emit(rel, "table_get", **addr)
            emit(rel, "table_get", shape="filter", **addr)
            if rows and rows[0]:
                emit(rel, "table_get", **addr, fk0=cols[0], fv0=rows[0][0])
                if len(cols) > 1:
                    emit(rel, "table_get", **addr,
                         fk0=cols[0], fv0=rows[0][0],
                         fk1=cols[-1], fv1=rows[0][-1])
            emit(rel, "table_get", **addr, fk0=cols[0], fv0="no-such-value")
            emit(rel, "table_get", **addr, fk0="NoSuchColumn", fv0="x")

            # Typed arguments, through the `args` hatch: the whole object as one
            # JSON string. These are the cases the flat wire format could never
            # send. `check_cell` refuses a boolean, a number, a null, an array
            # and a nested object *inside* a filter, and until now not one of
            # those refusals was ever compared against the port -- which is the
            # stated reason `filter-value-typed` was kept out of `mutate.py`.
            #
            # The ordinal goes in as an int here and as a decimal string on the
            # flat path above, because `py_run` does `int(args["ordinal"])`
            # before it calls and this hatch does not.
            taddr = {"heading": e["heading"], "ordinal": e["ordinal"]}
            typed = [{"table": taddr, "filter": {cols[0]: bad}}
                     for bad in (True, 3, None, ["a"], {"x": 1})]
            # A typed value under a column that does not exist. This settles an
            # order: the value is checked before the column is looked up, so a
            # port that resolved the column first would answer with a different
            # sentence.
            typed.append({"table": taddr, "filter": {"NoSuchColumn": True}})
            # `filter` itself typed wrongly. `check_filter`'s own refusals are
            # in the `check_args` cross product; what is new here is reaching
            # them in the op's argument order, where a dispatch that checked
            # things in the wrong sequence shows and isolation does not.
            # `null` is absent, deliberately -- see `typed_filter`.
            typed += [{"table": taddr, "filter": bad}
                      for bad in (True, 3, "a string", ["a"])]
            # What the hatch also makes reachable, now that it exists: an
            # address whose heading or ordinal is not a string, again in the
            # op's own order rather than in `check_args`'s isolation.
            for bad in (True, 3, None, {"a": 1}):
                typed.append({"table": {"heading": bad}})
                typed.append({"table": {"heading": e["heading"], "ordinal": bad}})
            for payload in typed:
                emit(rel, "table_get", args=json.dumps(payload))
            # A whole-file address, which is a read against a table this loop
            # located by heading -- legal only where the file has one table, and
            # a candidate list otherwise.
            emit(rel, "table_get", heading=e["heading"])

            # Realign, through the dispatch rather than as its own case kind:
            # it takes one argument and returns a document, so `apply_op`
            # already compares exactly the right thing. Every table in the
            # corpus goes through it, which is the coverage that matters --
            # the op rewrites every line of the table it touches, so a
            # divergence anywhere in the renderer shows up here.
            emit(rel, "apply_op", opname="table-realign",
                 args=json.dumps({"table": {"heading": e["heading"],
                                            "ordinal": e["ordinal"]}}))

        # Dispatch ordering, against this document's first table. `{H}` is a
        # plain substitution rather than `.format()` because the cases are JSON
        # and full of braces.
        if entries:
            h = entries[0]["heading"]
            for text in DISPATCH_ARGS:
                for op in DISPATCH_OPS:
                    emit(rel, "apply_op", opname=op, args=text.replace("{H}", h))
            # The same ordering, but with arguments good enough to reach the end
            # of it -- a real heading, a real column, a real cell value. Without
            # these the whole family would refuse before the last check ran, and
            # a suite that only ever takes the refusal path proves the refusals
            # and nothing else.
            t0 = find_tables(content)[0]
            c0 = list(t0.cells(t0.header))
            r0 = t0.rows()
            if c0 and r0 and r0[0]:
                col, cell = json.dumps(c0[0]), json.dumps(r0[0][0])
                sel = '"where": {%s: %s}' % (col, cell)
                for tail in (
                    '"column": %s, "value": "written"' % col,
                    '"column": %s, "value": ""' % col,
                    '"column": %s' % col,
                    '"column": %s, "value": null' % col,
                    '"column": %s, "value": 1.5' % col,
                    '"column": %s, "value": [1]' % col,
                    '"column": %s, "value": true' % col,
                    '"column": "NoSuchColumn", "value": [1]',
                ):
                    args = '{"table": %s, %s, %s}' % (json.dumps(h), sel, tail)
                    for op in DISPATCH_OPS:
                        emit(rel, "apply_op", opname=op, args=args)

        # The same ordering question for the section family, against this
        # document's first section. All six ops see every argument object,
        # because four of them take a `heading` and two take it only to refuse
        # it -- one object, six sentences, and S2/S3 are precisely the case where
        # a model sends the arguments of the op it meant to call.
        # A document with no sections still gets every case that does not need
        # one. The guard used to cover the whole block, so `no-headings.md` saw
        # no section case at all and "this file has no headings, so no section
        # can be addressed." was reached by nothing -- which is also why the
        # order that refusal is answered in relative to a malformed `ordinal`
        # was unguarded. `{S}` is the only part that needs a real section.
        sa = (json.dumps({"path": outline[0]["path"],
                          "ordinal": outline[0]["ordinal"]}) if outline else None)
        for text in SECTION_DISPATCH_ARGS:
            if sa is None and "{S}" in text:
                continue
            for op in SECTION_DISPATCH_OPS:
                emit(rel, "apply_op", opname=op, args=text.replace("{S}", sa or ""))

        # The frontmatter family. `{K}` is this document's first addressable
        # path; a file with no block still gets every case that does not need
        # one, for the reason the section family does -- "this file has no
        # frontmatter block" is a refusal with its own ordering against a
        # malformed `key`, and a guard around the whole block would leave it
        # unreached.
        fm = find_frontmatter(content)
        k = json.dumps(format_path(fm.entries[0].path))[1:-1] if fm.entries else None
        for text in FRONT_DISPATCH_ARGS:
            if k is None and "{K}" in text:
                continue
            args = text.replace("{K}", k or "")
            for op in FRONT_DISPATCH_OPS:
                emit(rel, "apply_op", opname=op, args=args)
                # Every call that lands is also described, which is the only
                # comparison `describe_frontmatter_change` gets -- it is not
                # `describe_change`, so the sweep above does not reach it.
                emit(rel, "describe_front", opname=op, args=args)

        emit(rel, "render_frontmatter", path=rel)
        for text in FRONT_GET_KEYS:
            if k is None and "{K}" in text:
                continue
            emit(rel, "frontmatter_get", path=rel, key=text.replace("{K}", k or ""))
        # The read with no `key` argument at all, which is a different call from
        # `key: null` on the Rust side and must not be on this one.
        emit(rel, "frontmatter_get", path=rel)

    return cases, "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# the oracle side
# --------------------------------------------------------------------------

def dump_sections(content):
    out = []
    for s in find_sections(content):
        out.append("|".join(str(x) for x in [
            s.start, s.heading_end, s.own_end, s.end, s.level, s.style,
            s.gap_after, s.parent, esc(s.indent), s.marker, esc(s.space),
            s.closing, esc(s.raw_text), " > ".join(s.path)]))
    return "\n".join(out)


def dump_lists(content):
    """The list parser, field by field.

    One line per list, then one indented line per item. `own_end` and `parent`
    are in here because nothing else reads them, so a divergence in either would
    otherwise wait for an op that happens to depend on it.
    """
    out = []
    for l in find_lists(content):
        out.append("|".join(str(x) for x in [
            l.start, l.end, str(l.ordered).lower(), l.bullet, esc(l.indent),
            str(l.loose).lower()]))
        for it in l.items:
            out.append("  " + "|".join(str(x) for x in [
                it.start, it.own_end, it.end, it.depth, esc(it.indent),
                it.marker, str(it.ordered).lower(),
                "-" if it.number is None else it.number,
                "-" if it.delim is None else it.delim,
                "-" if it.checkbox is None else it.checkbox,
                it.parent, esc(it.text)]))
    return "\n".join(out)


def dump_front(content):
    """The frontmatter parser, field by field.

    Every byte of an entry's own line is in here -- `prefix`, `gap`, `pad` and
    `comment` as well as the value -- because those four are what make an edit
    byte-preserving, and a divergence in any of them would otherwise only show
    up as a corrupted line under whichever op happened to rebuild it. `eol` is
    per-entry for the same reason: it is the field a CRLF file loses silently.
    """
    fm = find_frontmatter(content)
    if not fm.present:
        return "absent"
    out = ["|".join(str(x) for x in [
        fm.fmt, fm.start, fm.end, fm.delim, fm.close, esc(fm.eol)])]
    for e in fm.entries:
        out.append("  " + "|".join(str(x) for x in [
            format_path(e.path), e.line, e.end, e.kind, esc(e.prefix),
            esc(e.key_text), esc(e.gap), esc(e.value), esc(e.pad),
            esc(e.comment), esc(e.eol), esc(e.rebuilt())]))
    return "\n".join(out)


def py_path_case(text):
    """`parse_path` on one address string, typed, then round-tripped.

    Its own case op because no fixture can reach most of this. The parser only
    ever hands out paths it built itself, so every malformed address -- and
    every index too large for a machine integer, which Python's `int` holds and
    a `usize` does not -- is reachable only by calling it directly. The segment
    *kind* is in the dump because `a.0` and `a[0]` are two different addresses
    that `format_path` prints the same way apart from the brackets, and a port
    that lost the distinction would still round-trip.
    """
    p = parse_path(text)
    if p is None:
        return "NONE"
    kinds = "|".join(
        (f"i:{s}" if isinstance(s, int) else f"k:{s}") for s in p)
    return f"{format_path(p)}\n{kinds}"


def indexed(args, kp, vp):
    out, i = {}, 0
    while f"{kp}{i}" in args and f"{vp}{i}" in args:
        out[args[f"{kp}{i}"]] = args[f"{vp}{i}"]
        i += 1
    return out


def ordered_values(args):
    out, i = [], 0
    while f"vo{i}" in args:
        out.append(args[f"vo{i}"])
        i += 1
    return out


def py_arg_case(fn, text):
    """One validation function against one JSON value, as Python sees it."""
    absent = text == "ABSENT"
    v = None if absent else json.loads(text)
    key = lambda name: {} if absent else {name: v}  # noqa: E731

    if fn == "unstring_obj":
        return repr(F._unstring(v, dict, "table"))
    if fn == "unstring_obj_plain":
        return repr(F._unstring(v, dict, "table", plain_ok=True))
    if fn == "unstring_objarr":
        return repr(F._unstring(v, (dict, list), "values"))
    if fn == "clean_keys":
        return repr(F._clean_keys(v))
    if fn == "check_address":
        return repr(F._check_address(v, "table"))
    if fn == "check_heading":
        return repr(F._check_heading(v, "table"))
    if fn == "check_ordinal":
        return repr(F._check_ordinal(v, "table"))
    if fn == "check_position":
        return repr(F._check_position(v))
    if fn == "check_cell":
        return repr(F._check_cell(v, "Component", "values"))
    if fn == "check_where":
        return repr(F._check_where(v))
    if fn == "check_filter":
        return repr(F._check_filter(v))
    if fn == "check_column":
        return repr(F._check_column(v))
    # The three composed helpers, which is where the ORDER of the checks shows:
    # unstring, then clean_keys, then the type check, on one argument object.
    if fn == "address":
        return repr(F._address(key("table")))
    if fn == "values":
        return repr(F._values(key("values")))
    if fn == "where_arg":
        return repr(F._where(key("where")))
    raise AssertionError(f"unknown arg fn {fn}")


def py_repr_case(text):
    """`json.loads` then `repr`, or the fact that it does not parse.

    Two contracts in one case: that `json.rs::parse` accepts exactly what
    CPython accepts, and that `json.rs::py_repr` prints exactly what CPython
    prints. Both are load-bearing -- `parse` decides whether a serialized
    argument is recovered or refused, and `py_repr` writes the `Got:` line of
    every refusal in `args.rs`.
    """
    try:
        v = json.loads(text)
    except ValueError:
        return "UNPARSED"
    return repr(v)


def py_run(content, rel, op, args):
    addr = {}
    if "heading" in args:
        addr["heading"] = args["heading"]
    if "ordinal" in args:
        addr["ordinal"] = int(args["ordinal"])
    # The section family's address, kept on its own wire keys: `path` and
    # `heading` are two different fields here, and a bare string means `path`
    # rather than `heading`, so folding it into `addr` would test neither.
    saddr = {}
    if "spath" in args:
        saddr["path"] = args["spath"]
    if "sheading" in args:
        saddr["heading"] = args["sheading"]
    if "sordinal" in args:
        saddr["ordinal"] = int(args["sordinal"])
    where = indexed(args, "wk", "wv")
    # Absent, empty-but-present, and populated are three different inputs to
    # `check_filter`; `shape=filter` on the wire is how a case says the second.
    fpairs = indexed(args, "fk", "fv")
    filt = fpairs if (fpairs or args.get("shape") == "filter") else None
    named = indexed(args, "vk", "vv")
    values = named if (named or args.get("shape") == "named") else ordered_values(args)
    position = args.get("position", "end")
    if position not in ("end", "start"):
        position = int(position)

    if op == "render_table_list":
        return "ok", F.render_table_list(content, args.get("path", ""))
    if op == "table_get":
        # Through the rendered form, which is the whole result: the heading, the
        # matched/total counts, the columns and every cell all appear in the
        # text. Comparing the dict instead would compare a `repr` no caller sees.
        #
        # `args` is the typed escape hatch -- the whole argument object as one
        # JSON string, the convention `apply_op` and `describe_change` already
        # use. The flat `fk`/`fv` keys can only carry strings, which left
        # `check_cell`'s refusals on a boolean, a null or a nested object
        # *inside* a filter reached by no case. A case that carries `args` takes
        # its address from there too, or an untyped address would override the
        # typed one on this side and not on the other.
        if "args" in args:
            a = json.loads(args["args"])
            addr = a.get("table")
            # `a.get` and not `a["filter"]`: an explicit `null` and an absent
            # key are the same call at this signature, and the Rust side
            # collapses them for that reason. A null *filter* belongs to
            # `check_args`; this hatch is for a filter that holds a value no
            # string can be.
            filt = a.get("filter")
        try:
            return "ok", F.render_table_get(content, addr, filt)
        except F.OpError as e:
            return "err", str(e)
    if op == "list_tables":
        return "ok", "\n".join(
            f'{e["ordinal"]}|{e["heading"]}|{e["caption"]}|'
            f'{" | ".join(e["columns"])}|{e["rows"]}'
            for e in F.list_tables(content, rel))
    if op == "find_tables":
        return "ok", "\n".join(
            f"{t.start}|{t.end}|{str(t.is_aligned()).lower()}|"
            f"{str(F._has_tabs(t)).lower()}" for t in find_tables(content))
    if op == "find_sections":
        return "ok", dump_sections(content)
    if op == "find_lists":
        return "ok", dump_lists(content)
    if op == "find_frontmatter":
        return "ok", dump_front(content)
    if op == "list_lists":
        return "ok", "\n".join(
            f'{e["ordinal"]}|{e["heading"]}|{e["kind"]}|{e["marker"]}|'
            f'{e["items"]}|{e["levels"]}|{str(e["loose"]).lower()}|{e["tasks"]}'
            for e in F.list_lists(content, rel))
    if op == "render_list_summary":
        return "ok", F.render_list_summary(content, args.get("path", ""))
    if op == "list_get":
        try:
            got = F.list_get(content, addr)
            text = F.render_list_get(content, addr)
        except F.OpError as e:
            return "err", str(e)
        dump = [f'{got["heading"]}|{got["ordinal"]}|{len(got["items"])}']
        for item in got["items"]:
            parent = "-" if item["parent"] is None else str(item["parent"])
            checked = ("-" if item["checked"] is None
                       else str(item["checked"]).lower())
            dump.append(f'{esc(item["text"])}|{item["depth"]}|{parent}|{checked}')
        dump.extend(["--", text])
        return "ok", "\n".join(dump)
    if op == "section_outline":
        return "ok", "\n".join(
            f'{e["level"]}|{e["path"]}|{e["text"]}|{e["style"]}|{e["ordinal"]}|'
            f'{str(e["unique"]).lower()}|{str(e["has_body"]).lower()}|'
            f'{e["subsections"]}'
            for e in F.section_outline(content))
    if op == "render_section_outline":
        return "ok", F.render_section_outline(content, args.get("path", ""))
    if op == "inert_headings":
        return "ok", "\n".join(
            f'{h["line"]}|{h["reason"]}|{h["text"]}' for h in inert_headings(content))
    if op == "py_repr":
        return "ok", py_repr_case(args["text"])
    if op == "parse_path":
        return "ok", py_path_case(args["text"])
    if op == "check_args":
        try:
            return "ok", py_arg_case(args["fn"], args["text"])
        except F.OpError as e:
            return "err", str(e)

    if op == "apply_op":
        # The whole dispatch, arguments and all -- so what is compared is the
        # message a model would actually receive, not the return of some
        # function chosen because it was convenient to call.
        text = args["args"]
        a = None if text == "ABSENT" else json.loads(text)
        out, err = F.apply_op(content, args["opname"], a)
        return ("err", err) if err is not None else ("ok", out)

    if op == "describe_front":
        # `describe_change`'s case, for the family it does not describe. The
        # same shape deliberately: both sides apply the op and describe
        # before-vs-after, so a divergence in either half shows here.
        text = args["args"]
        a = None if text == "ABSENT" else json.loads(text)
        out, err = F.apply_op(content, args["opname"], a)
        if err is not None:
            return "err", err
        return "ok", F.describe_frontmatter_change(content, out)

    if op == "render_frontmatter":
        return "ok", F.render_frontmatter(content, args.get("path", ""))

    if op == "frontmatter_get":
        # Through the rendered form for `render_table_get`'s reason -- it is
        # what a model receives -- and through the dict as well, because the
        # structure is what `keys --json` carries and `grade.py` scores. `state`
        # and `format` appear in neither rendering, so a port that got them
        # wrong would pass on the text alone.
        key = json.loads(args["key"]) if "key" in args else None
        try:
            got = F.frontmatter_get(content, key)
            text = F.render_frontmatter_get(content, args.get("path", ""), key)
        except F.OpError as e:
            return "err", str(e)
        head = f'{got["state"]}|{got["format"]}|{len(got["keys"])}'
        rows = [f'{k["path"]}|{k["kind"]}|{k["type"]}|{esc(k["value"])}|{k["lines"]}'
                for k in got["keys"]]
        return "ok", "\n".join([head] + rows + ["--"] + [text])

    if op == "describe_change":
        # Two documents, one fixture field. The case carries the op that
        # produces the second one; both sides apply it and describe
        # before-vs-after. A refusal is returned as itself -- the `apply_op`
        # family already compares those messages, so the case costs nothing and
        # is not wasted.
        #
        # `after` is the escape hatch for branches no op reaches, and it rides
        # as a JSON string for the reason `apply_op`'s arguments do: a raw
        # newline would break the line-framed case file.
        if "after" in args:
            return "ok", F.describe_change(content, json.loads(args["after"]))
        text = args["args"]
        a = None if text == "ABSENT" else json.loads(text)
        out, err = F.apply_op(content, args["opname"], a)
        if err is not None:
            return "err", err
        return "ok", F.describe_change(content, out)

    try:
        if op == "resolve_table":
            t = F.resolve_table(content, addr)
            return "ok", f"{t.start}|{t.end}"
        if op == "resolve_row":
            t = F.resolve_table(content, addr)
            return "ok", str(F.resolve_row(t, where))
        if op == "resolve_list":
            l = F.resolve_list(content, addr)
            return "ok", f"{l.start}|{l.end}"
        if op == "resolve_item":
            l = F.resolve_list(content, addr)
            return "ok", str(F.resolve_item(l, args.get("item", "")))
        if op == "resolve_section":
            # Three ends, not one: `own_end` and `end` are the field the ops
            # disagree about, and a resolver that returned the right section
            # with the wrong subtree boundary would look correct here if only
            # `start` were compared.
            s = F.resolve_section(content, saddr)
            return "ok", f"{s.start}|{s.heading_end}|{s.own_end}|{s.end}|{s.level}"
        if op == "add_row":
            return "ok", F.table_add_row(content, addr, values, position)
        if op == "update_cell":
            return "ok", F.table_update_cell(content, addr, where,
                                             args.get("column", ""),
                                             args.get("value", ""))
        if op == "delete_row":
            return "ok", F.table_delete_row(content, addr, where)
    except F.OpError as e:
        return "err", str(e)
    return "err", f"unknown op {op}"


# --------------------------------------------------------------------------
# the expected side: computed in parallel, and reused across mutation runs
# --------------------------------------------------------------------------
# The oracle loop is 93% of a run's wall clock -- 156 s of 168 s over 77580
# cases -- and `bench/mutate.py` pays it 173 times, which is where the eight
# hours of a full mutation run go. Both halves are avoidable. Neither is a
# shortcut around the comparison: what changes is how the *expected* side is
# obtained, not what it is compared against.
#
# Parallel is safe because `py_run` is pure. It reads a document string and an
# argument dict, and `incise_ops` holds no mutable module state -- only the
# read-only `_WIDE_RANGES`, `_MISSING`, `POSITIONS` and `OPS` -- and no RNG. So
# the cases are independent, and order is the only thing that has to survive,
# which `imap` preserves.
#
# Reuse is safe because every mutation in `bench/mutate.py` rewrites a file
# under `crates/incise-core/src/`. Not one touches Python, so the oracle's
# answers are identical across all 173 runs and are being recomputed 172 times
# for nothing.
#
# The danger is entirely in the second one, and it is worse than a wrong
# answer: a stale expected-file turns every mutation green for a reason that
# has nothing to do with the port, and reports it as a clean run. That is the
# precise failure the mutation discipline exists to prevent, so the file is
# keyed on a hash of everything the answers depend on -- the generated case
# blob, the source of every module loaded out of this repository, and the bytes
# of every fixture. A key that does not match is not an error; it recomputes
# and rewrites, so the worst a stale file can cost is time.
#
# One hole remains, and it is closed in `mutate.py` rather than here: editing
# the oracle *while* a run is in flight saves answers from the old code under
# the new code's key. The key is printed on every run for that reason, and
# `mutate.py` aborts if it ever moves mid-run.

def expected_key(blob, files):
    """Hash of every input the expected answers depend on."""
    h = hashlib.sha256()
    h.update(blob.encode())
    # Discovered rather than listed: a new import under `bench/` joins the key
    # without anyone remembering to add it, which is the failure mode a literal
    # list of filenames has.
    srcs = set()
    for mod in list(sys.modules.values()):
        path = getattr(mod, "__file__", None)
        if path and path.endswith(".py") and os.path.abspath(path).startswith(ROOT + os.sep):
            srcs.add(os.path.abspath(path))
    for path in sorted(srcs):
        h.update(open(path, "rb").read())
    for rel in files:
        h.update(open(os.path.join(ROOT, rel), "rb").read())
    return h.hexdigest()


_DOCS = {}


def _expect_init(docs):
    global _DOCS
    _DOCS = docs


def _expect_one(row):
    _cid, rel, op, args = row
    status, payload = py_run(_DOCS[rel], rel, op, args)
    return status, esc(payload)


def compute_expected(cases, docs, jobs):
    """`[(status, escaped_payload)]`, positionally parallel to `cases.rows`."""
    if jobs <= 1:
        _expect_init(docs)
        return [_expect_one(r) for r in cases.rows]
    with multiprocessing.Pool(jobs, _expect_init, (docs,)) as pool:
        return list(pool.imap(_expect_one, cases.rows, chunksize=256))


def load_expected(path, key, n):
    """The saved answers, or `None` if the file is absent, foreign or short."""
    try:
        fh = open(path)
    except OSError:
        return None
    with fh:
        if fh.readline().rstrip("\n") != key:
            return None
        # `esc` has already removed every newline and carriage return from the
        # payload, so one case per line is a safe framing. Status never
        # contains FS, so a single split is enough even if a payload does.
        rows = [tuple(line.rstrip("\n").split(FS, 1)) for line in fh]
    return rows if len(rows) == n and all(len(r) == 2 for r in rows) else None


def save_expected(path, key, rows):
    # Written aside and renamed: an interrupted write must not leave a
    # half-file that the length check would have to catch after the fact.
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        fh.write(key + "\n")
        for status, payload in rows:
            fh.write(f"{status}{FS}{payload}\n")
    os.replace(tmp, path)


# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="print the first mismatch in full")
    ap.add_argument("--max-show", type=int, default=3)
    ap.add_argument("-j", "--jobs", type=int, default=os.cpu_count() or 1,
                    help="processes for the oracle loop (1 = serial)")
    ap.add_argument("--expected", metavar="PATH",
                    help="reuse the oracle's answers from PATH when its key "
                         "still matches, and write them there when it does not")
    args = ap.parse_args()

    # Synthetic documents are addressed by absolute path, which both sides join
    # against their root harmlessly (an absolute join wins in Python and in Rust
    # alike), so they need no special case downstream.
    synth = synthetic_files()
    files = corpus_files() + synth

    with tempfile.TemporaryDirectory() as tmp:
        cases, blob = generate(files)
        print(f"{len(cases.rows)} cases over {len(files)} fixtures "
              f"({len(synth)} synthetic)")

        cpath = os.path.join(tmp, "cases")
        rpath = os.path.join(tmp, "results")
        with open(cpath, "w") as fh:
            fh.write(blob)
        build = subprocess.run(
            ["cargo", "run", "--quiet", "--release", "--example", "oracle_cases",
             "--", cpath, ROOT, rpath],
            cwd=ROOT, capture_output=True, text=True,
            env=dict(os.environ, PATH=os.path.expanduser("~/.cargo/bin") + ":"
                     + os.environ.get("PATH", "")))
        if build.returncode != 0:
            print(build.stdout + build.stderr)
            return 2
        rust = {}
        for line in open(rpath):
            cid, status, payload = line.rstrip("\n").split(FS, 2)
            rust[cid] = (status, payload)

        docs = {rel: open(os.path.join(ROOT, rel), newline="").read()
                for rel in files}

    key = expected_key(blob, files)
    want = load_expected(args.expected, key, len(cases.rows)) if args.expected else None
    if want is None:
        want = compute_expected(cases, docs, args.jobs)
        if args.expected:
            save_expected(args.expected, key, want)
        print(f"expected: computed {key[:12]}")
    else:
        print(f"expected: cached {key[:12]}")

    mismatches, by_op = [], {}
    for (cid, rel, op, cargs), (want_status, want_payload) in zip(cases.rows, want):
        got = rust.get(cid)
        by_op.setdefault(op, [0, 0, 0])
        by_op[op][1] += 1
        if want_status == "err":
            by_op[op][2] += 1
        if got == (want_status, want_payload):
            by_op[op][0] += 1
        else:
            mismatches.append((cid, rel, op, cargs, (want_status, want_payload), got))

    # The `refused` column answers a question the `agree` column cannot: whether
    # the refusal messages -- which 5.3 calls the product -- were compared at
    # all. An op whose cases all succeed agrees about nothing else, and that is
    # invisible in a row reading 36/36.
    print(f"{'op':<20}{'agree':>10}{'refused':>10}")
    for op in sorted(by_op):
        ok, n, err = by_op[op]
        mark = "" if ok == n else "   <-- MISMATCH"
        print(f"  {op:<18}{ok:>5}/{n}{err:>10}{mark}")

    if not mismatches:
        print(f"\nall {len(cases.rows)} cases agree with the oracle")
        return 0

    print(f"\n{len(mismatches)} mismatches")
    for cid, rel, op, cargs, want, got in mismatches[:args.max_show]:
        print(f"\n--- case {cid}  {rel}  {op}\n    args {cargs}")
        if args.verbose:
            print(f"    python: {want}")
            print(f"    rust:   {got}")
        else:
            print(f"    python: {str(want)[:160]}")
            print(f"    rust:   {str(got)[:160]}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
