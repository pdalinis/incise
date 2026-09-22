#!/usr/bin/env python3
"""Arm B: can the model *address* an edit it cannot see?

Arm A gave the model the whole document and a find/replace tool, and it scored
60% (FINDINGS.md). Arm B removes the document entirely. The model sees only a
structural summary -- headings, captions, column names, row counts -- and must
emit one incise op that names the table and row by content.

This is the load-bearing claim in REQUIREMENTS.md section 2: *a small model
performs a routine markdown edit in one tool call, with no document content in
its context*. If addressing fails here, content-addressed ops are the wrong
design and we should know before any Rust exists.

The op is executed by `incise_ops.py` and the result is graded by
`grade.check_result` -- the same function that graded Arm A, so the two arms are
comparable by construction rather than by assertion.

Two tool vocabularies are run against identical tasks, because section 12.1 asks
which naming scheme a small model handles better and that is cheaper to measure
than to argue:

  scheme_a   three narrow tools:  table-add-row / table-update-cell / table-delete-row
  scheme_b   one broad tool:      table_edit(action=add-row|update-cell|delete-row)

  python3 bench/armb.py --scheme scheme_a --trials 10
  python3 bench/armb.py --scheme scheme_b --trials 10
  python3 bench/armb.py --grade
"""

import argparse
import json
import os
import subprocess
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bench"))

from incise_ops import (  # noqa: E402
    OPS, OpError, apply_op, describe_change, describe_frontmatter_change,
    frontmatter_get, list_get, render_frontmatter, render_frontmatter_get,
    render_list_get, render_list_summary, render_section_outline, render_table_get,
    render_table_list, table_get,
)
from grade import check_result  # noqa: E402
from runner import call, record  # noqa: E402

# --------------------------------------------------------------------------
# shared parameter shapes
# --------------------------------------------------------------------------

TABLE_ARG = {
    "type": "object",
    "description": (
        "Which table to edit, addressed by content. Never by line number."
    ),
    "properties": {
        "heading": {
            "type": "string",
            "description": (
                "The heading the table sits under. Either the last heading "
                '(e.g. "Environments") or the full path '
                '(e.g. "Deployment > Environments").'
            ),
        },
        "ordinal": {
            "type": "integer",
            "description": (
                "0-based index among tables under that same heading, in "
                "document order. Required only when more than one table shares "
                "the heading. The table list shows the ordinal of each."
            ),
        },
    },
    "required": ["heading"],
}

WHERE_ARG = {
    "type": "object",
    "description": (
        "Selects one existing row by its cell values, as "
        '{"ColumnName": "cell value"}. Must match exactly one row. '
        'Example: {"Host": "stage-1"}.'
    ),
    "additionalProperties": {"type": "string"},
}

VALUES_ARG = {
    "type": "object",
    "description": (
        'The new row, as {"ColumnName": "cell value"} for each column. '
        "Omitted columns are left empty."
    ),
    "additionalProperties": {"type": "string"},
}

POSITION_ARG = {
    "type": "string",
    "description": 'Where to insert: "end" (default) or "start".',
    "enum": ["end", "start"],
}

# --------------------------------------------------------------------------
# scheme A -- one tool per operation
# --------------------------------------------------------------------------

SCHEME_A = [
    {
        "name": "table-add-row",
        "description": (
            "Append a row to a markdown table. Column widths and alignment are "
            "maintained automatically; you do not need to pad anything."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File to edit."},
                "table": TABLE_ARG,
                "values": VALUES_ARG,
                "position": POSITION_ARG,
            },
            "required": ["path", "table", "values"],
        },
    },
    {
        "name": "table-update-cell",
        "description": (
            "Change one cell of one existing row in a markdown table. Column "
            "widths and alignment are maintained automatically."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File to edit."},
                "table": TABLE_ARG,
                "where": WHERE_ARG,
                "column": {
                    "type": "string",
                    "description": "Name of the column whose cell changes.",
                },
                "value": {"type": "string", "description": "The new cell value."},
            },
            "required": ["path", "table", "where", "column", "value"],
        },
    },
    {
        "name": "table-delete-row",
        "description": (
            "Remove one existing row from a markdown table. Column widths and "
            "alignment are maintained automatically."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File to edit."},
                "table": TABLE_ARG,
                "where": WHERE_ARG,
            },
            "required": ["path", "table", "where"],
        },
    },
]

# --------------------------------------------------------------------------
# scheme B -- one tool, action enum
# --------------------------------------------------------------------------

SCHEME_B = [
    {
        "name": "table_edit",
        "description": (
            "Edit a markdown table. Column widths and alignment are maintained "
            "automatically; you do not need to pad anything.\n"
            "  action=add-row      requires `values`\n"
            "  action=update-cell  requires `where`, `column`, `value`\n"
            "  action=delete-row   requires `where`"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File to edit."},
                "action": {
                    "type": "string",
                    "description": "The operation to perform.",
                    "enum": ["add-row", "update-cell", "delete-row"],
                },
                "table": TABLE_ARG,
                "values": VALUES_ARG,
                "where": WHERE_ARG,
                "column": {
                    "type": "string",
                    "description": "For update-cell: the column whose cell changes.",
                },
                "value": {
                    "type": "string",
                    "description": "For update-cell: the new cell value.",
                },
                "position": POSITION_ARG,
            },
            "required": ["path", "action", "table"],
        },
    },
]

SCHEMES = {"scheme_a": SCHEME_A, "scheme_b": SCHEME_B}

# --------------------------------------------------------------------------
# schemes C and D -- ordered row values (B4)
# --------------------------------------------------------------------------
# B4 measured `scheme_b` at 3/10 on an instruction that supplies values
# positionally ("add a row with the values i, j, k and l"), because a
# column-keyed object forces a positional->named translation the model gets
# wrong. Both schemes below add an ordered form; they differ only in how it is
# offered, and that difference is the thing being measured:
#
#   scheme_c   one `values` field, oneOf [object, array]
#   scheme_d   two fields, `values` (named) and `row` (ordered)
#
# `oneOf` is the tidier schema but grammar-constrained decoding often flattens
# or mishandles union types, in which case scheme_c would measure the server
# rather than the model. Running both is the only way to tell those apart.
#
# Both are run over all six tasks, not just the failing one: adding a second way
# to express a row can degrade the five tasks that were already at 10/10, and
# testing only the task that motivated the change would hide exactly that.

_ORDERED_DESC = (
    "The row's values in column order, one per column, all columns required. "
    'For the table Default | Left | Center | Right, the values i, j, k, l are '
    '["i", "j", "k", "l"]. Use this when the request lists values in order '
    "rather than naming a column for each."
)


def _with_values(values_prop, extra=None, desc=None):
    """SCHEME_B's single tool with its `values` property swapped out."""
    tool = json.loads(json.dumps(SCHEME_B[0]))  # deep copy
    tool["parameters"]["properties"]["values"] = values_prop
    if extra:
        tool["parameters"]["properties"].update(extra)
    if desc:
        tool["description"] = desc
    return [tool]


SCHEME_C = _with_values({
    "description": (
        "The new row. Either an object keyed by column name, or an array of "
        "values in column order. " + _ORDERED_DESC
    ),
    "oneOf": [
        {"type": "object", "additionalProperties": {"type": "string"}},
        {"type": "array", "items": {"type": "string"}},
    ],
})

SCHEME_D = _with_values(
    {
        "type": "object",
        "description": (
            'The new row, as {"ColumnName": "cell value"}. Use when the request '
            "names a column for each value. Omitted columns are left empty."
        ),
        "additionalProperties": {"type": "string"},
    },
    {"row": {"type": "array", "description": _ORDERED_DESC,
             "items": {"type": "string"}}},
    desc=(
        "Edit a markdown table. Column widths and alignment are maintained "
        "automatically; you do not need to pad anything.\n"
        "  action=add-row      requires `values` OR `row` (exactly one)\n"
        "  action=update-cell  requires `where`, `column`, `value`\n"
        "  action=delete-row   requires `where`"
    ),
)

SCHEMES.update({"scheme_c": SCHEME_C, "scheme_d": SCHEME_D})

# scheme_e isolates *what carries the affordance* in scheme_c: the `oneOf` union,
# or the prose describing both shapes? The distinction is not academic. `oneOf`
# is not uniformly supported -- some constrained decoders flatten it and some MCP
# clients reject it -- so if the description alone is sufficient, the portable
# schema is also the recommended one. Identical to scheme_c with the union
# removed, leaving `values` untyped.
SCHEME_E = _with_values({
    "description": (
        "The new row. Either an object keyed by column name, or an array of "
        "values in column order. " + _ORDERED_DESC
    ),
})

SCHEMES["scheme_e"] = SCHEME_E

# --------------------------------------------------------------------------
# The `table` address is the only failure left in scheme_e -- 3/60, all on the
# two-table file, and being in `required` did not prevent it (FINDINGS.md B6).
# Two candidate fixes, both built on scheme_e so the comparison is clean.
# --------------------------------------------------------------------------

def _from_e(table_arg=None, desc=None):
    tool = json.loads(json.dumps(SCHEME_E[0]))
    if table_arg:
        tool["parameters"]["properties"]["table"] = table_arg
    if desc:
        tool["description"] = desc
    return [tool]


# scheme_f -- prose only. B6 established that the description, not the type
# constraint, is what this model actually reads; so say the quiet part loudly
# and name `table` on every action line rather than only in `required`.
SCHEME_F = _from_e(desc=(
    "Edit a markdown table. Column widths and alignment are maintained "
    "automatically; you do not need to pad anything.\n"
    "`table` says WHICH table in the file and is required for every action. "
    "Copy it from the table list in the request; the last heading segment on "
    'its own is enough (e.g. "All four forms").\n'
    "  action=add-row      requires `table`, `values`\n"
    "  action=update-cell  requires `table`, `where`, `column`, `value`\n"
    "  action=delete-row   requires `table`, `where`"
))

# scheme_g -- shape. Same hypothesis as B6's `values` fix applied to the
# address: if the nested object is friction, let the heading be a bare string.
# Untyped for the same reason `values` is (oneOf measured inert).
SCHEME_G = _from_e(table_arg={
    "description": (
        "Which table to edit, addressed by content -- never by line number. "
        'Either the heading as a plain string (e.g. "All four forms" -- the '
        "last segment on its own is enough), or, when several tables share one "
        'heading, an object {"heading": "...", "ordinal": 0} where ordinal is '
        "the 0-based index among them in document order. The table list in the "
        "request shows the heading and ordinal of every table."
    ),
})

SCHEMES.update({"scheme_f": SCHEME_F, "scheme_g": SCHEME_G})

# --------------------------------------------------------------------------
# tables, read side -- the first read tool offered to a model in this project
# --------------------------------------------------------------------------
# Every tool in the seventeen schemes above is a write. `render_table_list` was
# injected as prompt context instead, and the table system prompt says so
# outright ("You do NOT have the file contents, and you do not need them"), so
# every rate in FINDINGS was produced by a model handed the table summary for
# free and never asked to go and look.
#
# The variable is one word, and it is the one FINDINGS left open: REQUIREMENTS
# 6.1 named the read-side row selector `filter` rather than `where` because
# `where` on the write ops must match exactly one row or refuse, and putting two
# contracts on one word is the failure S15 measured for `path`. The *lesson* is
# measured. This word is not.
#
#   table_read_naive   `where`, described exactly as the write ops describe it
#   table_read_g       `filter`, with the leniency stated
#
# Naive first, per PLAN 12: the naive schema here is not a strawman but the
# choice a schema author who already has `where` would actually make, and
# running it first is what stopped the list family adopting prose that cost 19
# points. If `where` wins or ties, the rename is friction with a rationale and
# no effect, and that is worth knowing before a second read family inherits it.

_READ_DESC = (
    "Read rows out of a markdown table. This does not change the file.\n"
    "`table` says WHICH table and is required. Copy it from the table list in "
    'the request; the last heading segment on its own is enough (e.g. '
    '"Packages").'
)

SCHEMES["table_read_naive"] = [{
    "name": "table_get",
    "description": _READ_DESC,
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File to read."},
            "table": TABLE_ARG,
            "where": WHERE_ARG,
        },
        "required": ["path", "table"],
    },
}]

SCHEMES["table_read_g"] = [{
    "name": "table_get",
    "description": _READ_DESC + (
        "\n`filter` narrows the rows. Leave it out to get the whole table."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File to read."},
            "table": TABLE_ARG,
            "filter": {
                "type": "object",
                "description": (
                    "Keeps only the rows whose cells match, as "
                    '{"ColumnName": "cell value"}. Several columns are ANDed. '
                    "Any number of rows may match, including none -- matching "
                    "nothing is an answer, not an error. "
                    'Example: {"Priority": "high"}.'
                ),
                "additionalProperties": {"type": "string"},
            },
        },
        "required": ["path", "table"],
    },
}]

# ==========================================================================
# lists -- the second op family
# ==========================================================================
# The table family took 433 trials to settle on: one tool, an action enum, one
# untyped `values`, and a description that names the address on every action
# line (FINDINGS.md B7). Two questions that only a second family can answer:
#
#   1. Does that design transfer, or was it fitted to six table tasks?
#   2. Was the B7 description fix a real effect, or a lucky 3/60?
#
# So the list family is run as a paired A/B of exactly the B7 contrast, on a
# vocabulary it has never seen. `list_naive` writes its description the way
# SCHEME_B did -- per-action argument lines, address left to `required`.
# `list_f` adds the one sentence B7 adopted, and nothing else. Everything
# else -- parameters, types, system prompt, tasks, seeds -- is identical, so a
# difference between them is that sentence and only that sentence.

LIST_ARG = {
    "type": "object",
    "description": "Which list to edit, addressed by content. Never by line number.",
    "properties": {
        "heading": {
            "type": "string",
            "description": (
                "The heading the list sits under. Either the last heading "
                '(e.g. "All ones") or the full path '
                '(e.g. "Ordered list numbering > All ones").'
            ),
        },
        "ordinal": {
            "type": "integer",
            "description": (
                "0-based index among lists under that same heading, in document "
                "order. Required only when more than one list shares the "
                "heading. The list summary shows the ordinal of each."
            ),
        },
    },
    "required": ["heading"],
}

LIST_PROPS = {
    "path": {"type": "string", "description": "File to edit."},
    "action": {
        "type": "string",
        "description": "The operation to perform.",
        "enum": ["add-item", "remove-item", "set-checked"],
    },
    "list": LIST_ARG,
    "text": {
        "type": "string",
        "description": (
            "For add-item: the content of the new item. Text only -- no marker, "
            "no number, no checkbox, no indentation."
        ),
    },
    "item": {
        "type": "string",
        "description": (
            "For remove-item and set-checked: the text of the existing item to "
            "act on. Must identify exactly one item."
        ),
    },
    "after": {
        "type": "string",
        "description": (
            "For add-item: put the new item immediately after this existing "
            "item. The new item copies that item's indentation and marker, so "
            "this is also how an item is added inside a nested list."
        ),
    },
    "position": {
        "type": "string",
        "description": 'For add-item, when `after` is not given: "end" (default) or "start".',
        "enum": ["end", "start"],
    },
    "checked": {
        "type": "boolean",
        "description": "For set-checked: true to tick the box, false to untick it.",
    },
}

_LIST_PREAMBLE = (
    "Edit a markdown list. Marker character, marker delimiter, indentation, "
    "blank-line spacing and ordered-list numbering are all maintained "
    "automatically; you do not need to format anything.\n"
)

_LIST_ACTIONS_NAIVE = (
    "  action=add-item     requires `text`\n"
    "  action=remove-item  requires `item`\n"
    "  action=set-checked  requires `item`, `checked`"
)

_LIST_ACTIONS_ADDRESSED = (
    "`list` says WHICH list in the file and is required for every action. "
    "Copy it from the list summary in the request; the last heading segment on "
    'its own is enough (e.g. "All ones").\n'
    "  action=add-item     requires `list`, `text`\n"
    "  action=remove-item  requires `list`, `item`\n"
    "  action=set-checked  requires `list`, `item`, `checked`"
)


def _list_tool(actions):
    return [{
        "name": "list_edit",
        "description": _LIST_PREAMBLE + actions,
        "parameters": {
            "type": "object",
            "properties": json.loads(json.dumps(LIST_PROPS)),
            "required": ["path", "action", "list"],
        },
    }]


SCHEMES.update({
    "list_naive": _list_tool(_LIST_ACTIONS_NAIVE),
    "list_f": _list_tool(_LIST_ACTIONS_ADDRESSED),
})

# --------------------------------------------------------------------------
# scheme list_g -- the selector renamed so it cannot be read as the payload
# --------------------------------------------------------------------------
# L2 came out backwards: `list_f`, the B7 fix ported verbatim, scored 61% against
# `list_naive`'s 80% (McNemar exact p = 0.0009). Reading the calls, the model got
# the *addressing* right almost every time -- `list` was supplied and correct.
# What it got wrong was where to put the new item's content: it wrote `item`
# where the tool wanted `text`, 39 times.
#
# `text` and `item` are synonyms in English. The table family never had this
# problem and never could: its payload is `values` and its selector is `where`,
# two words that cannot be confused for each other. The list vocabulary was
# named without noticing that, and the naming is doing more damage than any
# schema structure measured so far.
#
# So `list_g` is `list_f` with ONE change -- the selector is renamed `item` ->
# `match` -- holding the prose, the action lines and everything else fixed. If
# the synonym-collision reading is right, list_g recovers what list_f lost. If
# list_g still fails, the prose sentence itself is the problem and B7's result
# does not generalize at all.

LIST_PROPS_G = json.loads(json.dumps(LIST_PROPS))
LIST_PROPS_G["match"] = {
    "type": "string",
    "description": (
        "For remove-item and set-checked: selects an existing item by its text. "
        "Must match exactly one item."
    ),
}
del LIST_PROPS_G["item"]

_LIST_ACTIONS_G = (
    "`list` says WHICH list in the file and is required for every action. "
    "Copy it from the list summary in the request; the last heading segment on "
    'its own is enough (e.g. "All ones").\n'
    "  action=add-item     requires `list`, `text`\n"
    "  action=remove-item  requires `list`, `match`\n"
    "  action=set-checked  requires `list`, `match`, `checked`"
)

SCHEMES["list_g"] = [{
    "name": "list_edit",
    "description": _LIST_PREAMBLE + _LIST_ACTIONS_G,
    "parameters": {
        "type": "object",
        "properties": LIST_PROPS_G,
        "required": ["path", "action", "list"],
    },
}]

# --------------------------------------------------------------------------
# scheme list_h -- tell the model not to guess a selector it cannot see
# --------------------------------------------------------------------------
# list_g's nine remaining failures have a single cause, and it is B2 again in a
# new family: the model invents the text of an item it was never shown. It asked
# for `after: "* current item"` and `after: "third child"` against lists whose
# item text the summary deliberately withholds.
#
# B2 left this open -- the 13/13 recovery in B3 used the improved error message
# on the *second* turn, so whether a description can prevent the failure in the
# first turn was never measured. `after` is the ideal place to measure it: it is
# optional, nothing in these tasks requires it, and offering it at all is what
# invites the guess.
#
# list_h is list_g plus one sentence in `after`'s description. Nothing else
# moves.

LIST_PROPS_H = json.loads(json.dumps(LIST_PROPS_G))
LIST_PROPS_H["after"]["description"] += (
    " Use it ONLY when you know an existing item's exact text -- normally "
    "because the instruction quotes it. If you do not, omit `after` and use "
    "`position` instead. Never guess an item's text: a guess does not match and "
    "the edit is rejected."
)

SCHEMES["list_h"] = [{
    "name": "list_edit",
    "description": _LIST_PREAMBLE + _LIST_ACTIONS_G,
    "parameters": {
        "type": "object",
        "properties": LIST_PROPS_H,
        "required": ["path", "action", "list"],
    },
}]

# --------------------------------------------------------------------------
# scheme list_i -- the missing cell of the 2x2
# --------------------------------------------------------------------------
# Two things vary across list_naive / list_f / list_g, and three cells of the
# four are measured:
#
#                       selector `item`     selector `match`
#   no address prose    list_naive  80%     list_i  ?
#   address prose       list_f      61%     list_g  91%
#
# Without list_i the prose sentence cannot be scored: naive -> f says it costs
# 19 points and naive -> g says it gains 11, and both readings are confounded
# with the rename. B7 adopted that sentence on the strength of 3/60 in the table
# family, so whether it earns its place is worth one run to settle.

SCHEMES["list_i"] = [{
    "name": "list_edit",
    "description": _LIST_PREAMBLE + (
        "  action=add-item     requires `text`\n"
        "  action=remove-item  requires `match`\n"
        "  action=set-checked  requires `match`, `checked`"),
    "parameters": {
        "type": "object",
        "properties": LIST_PROPS_G,
        "required": ["path", "action", "list"],
    },
}]

# --------------------------------------------------------------------------
# section schemes -- the third family
# --------------------------------------------------------------------------
# The list family's transferable result was not a schema, it was a rule:
# **name the parameters before writing the descriptions.** L2/L3 found the
# model writing the *payload* into the *selector* field (`item`), a failure no
# amount of description fixed and a one-word rename did; §12.8 then confirmed
# that a description can move where the model puts a value but cannot stop one
# being manufactured.
#
# The section vocabulary has that same shape, worse. `section-rename` and
# `section-insert` each take a selector and a payload that are both heading
# text: `section` (which one) and `heading` (what to call it / what to create).
# "Rename Install to Setup" has two heading strings in it and no syntactic clue
# which field each belongs in.
#
# So the contrast run here is a single factor on exactly that pair:
#
#   section_naive  selector `section`, payload `heading`  -- reference names
#   section_p      selector `section`, payload `new_heading`
#
# Everything else is identical. `section_naive` runs first regardless of which
# looks better on paper, because L1 is the reason: had `list_f` been adopted on
# the table family's evidence and run alone at 61%, the result would have read
# as "lists are hard" instead of "that prose hurts here."
#
# One parameter is deliberately ABSENT from both: there is no `level`. The new
# heading's level is derived from the anchor and the position, which is L4's
# result carried across -- a number the model cannot see is a number it will
# invent, and a level that is never asked for cannot be supplied wrong.

SECTION_ARG = {
    "type": "object",
    "description": "Which section to act on, addressed by heading path. Never by line number.",
    "properties": {
        "path": {
            "type": "string",
            "description": (
                "The heading path, from the outline. Either the last segment "
                '(e.g. "macOS") or the full path (e.g. "Install > macOS"). Use '
                "the full path when the last segment appears more than once."
            ),
        },
        "ordinal": {
            "type": "integer",
            "description": (
                "0-based index among sections that share an identical path, in "
                "document order. Required only for those; the outline marks "
                "them DUPLICATE PATH."
            ),
        },
    },
    "required": ["path"],
}

SECTION_PROPS = {
    "path": {"type": "string", "description": "File to edit."},
    "action": {
        "type": "string",
        "description": "The operation to perform.",
        "enum": ["append", "replace-body", "insert", "delete", "rename",
                 "set-level"],
    },
    "section": SECTION_ARG,
    "text": {
        "type": "string",
        "description": (
            "For append and replace-body: the markdown to put in the section's "
            "own body -- the part above its first subsection. Not its heading."
        ),
    },
    "heading": {
        "type": "string",
        "description": (
            "For rename: the new heading text. For insert: the heading text of "
            "the new section. Text only -- no `#` marks; the level is worked "
            "out from `section` and `position`."
        ),
    },
    "body": {
        "type": "string",
        "description": "For insert: the new section's body. Optional.",
    },
    "position": {
        "type": "string",
        "description": (
            "For insert: where the new section goes relative to `section`. "
            "before/after make it a sibling; first-child/last-child make it a "
            "subsection. after and last-child go past the whole subtree."
        ),
        "enum": ["before", "after", "first-child", "last-child"],
    },
    "level": {
        "type": "integer",
        "description": "For set-level: the heading level to move to, 1 to 6.",
    },
    "subtree": {
        "type": "boolean",
        "description": (
            "For set-level: move the subsections too. Default true. False "
            "reparents them, which is rarely what is wanted."
        ),
    },
}

_SECTION_PREAMBLE = (
    "Edit a markdown document's sections. Heading syntax, heading level, "
    "blank-line spacing and the boundaries of each section are all maintained "
    "automatically; you do not need to format anything or count levels.\n"
)

_SECTION_ACTIONS = (
    "  action=append        requires `text`\n"
    "  action=replace-body  requires `text`\n"
    "  action=insert        requires `position`, {h}\n"
    "  action=delete        requires nothing else -- takes the subtree with it\n"
    "  action=rename        requires {h}\n"
    "  action=set-level     requires `level`"
)

# The S2/S3 variant. Two changes, both aimed at measured failures:
#   S2 -- five trials in ten used `replace-body` to *add* a line and destroyed
#         the section's existing text. `append` is now named as the one that
#         keeps it, and `overwrite` is named as the price of the other.
#   S3 -- five trials used `append` to add a subsection, passing it a heading it
#         ignores. `insert` is now the only line that mentions creating one.
# Both also refuse in the executor, which is the half that does not depend on
# the model reading this.
_SECTION_ACTIONS_GUARDED = (
    "  action=append        requires `text`. Adds to the section's existing "
    "text, keeping it. Cannot create a section.\n"
    "  action=replace-body  requires `text`. DISCARDS the section's existing "
    "text; also requires `overwrite`=true if it has any.\n"
    "  action=insert        requires `position`, {h}. The only action that "
    "creates a section; use position=last-child for a new subsection.\n"
    "  action=delete        requires nothing else -- takes the subtree with it\n"
    "  action=rename        requires {h}\n"
    "  action=set-level     requires `level`"
)


def _section_tool(payload, guard=False, file_arg="path", addr_arg="path"):
    """The section tool, with the new-heading payload named `payload`.

    `payload` is the single factor in the naive/p contrast. `SECTION_PROPS` is
    deep-copied rather than shared so a rename in one scheme cannot leak into
    the other -- the list family's `LIST_PROPS_G` learned that the same way.

    `guard` adds the S2/S3 vocabulary: an `overwrite` flag on `replace-body`,
    and action lines that say which action creates sections. Kept as a flag
    rather than edited into `SECTION_PROPS` so `section_naive` and `section_p`
    remain exactly the schemas that produced S1-S6. A scheme is a measurement
    condition; silently improving one retroactively invalidates the result it
    produced.

    `file_arg` and `addr_arg` are the two sides of S15's name collision. The
    word `path` currently means the file at the top level and the heading path
    inside `section` -- the same word, two meanings, one call -- and S12 found
    the model putting the heading path into the file argument in 6 of 15
    unrecovered failures, reproducing identically on the retry turn. Each side
    is renamed on its own so the arms stay single-factor. Only the *name*
    moves: every description string is left byte-identical, because §1.3
    result 8 is that parameter names outweigh the prose describing them, and a
    scheme that also rewrote the prose would not be measuring a rename.
    """
    props = json.loads(json.dumps(SECTION_PROPS))
    if payload != "heading":
        props[payload] = props.pop("heading")
    # Order-preserving, unlike the payload rename above: a renamed key that
    # also moved to the end of the properties object would be two changes, and
    # `path` is the first field the model reads. The payload rename keeps its
    # pop/reassign because that is the form that produced S1-S13's numbers.
    if file_arg != "path":
        props = {(file_arg if k == "path" else k): v for k, v in props.items()}
    if addr_arg != "path":
        sec = props["section"] = json.loads(json.dumps(props["section"]))
        sec["properties"] = {(addr_arg if k == "path" else k): v
                             for k, v in sec["properties"].items()}
        sec["required"] = [addr_arg]
    actions = _SECTION_ACTIONS
    if guard:
        props["overwrite"] = {
            "type": "boolean",
            "description": (
                "For replace-body: confirms that discarding the section's "
                "existing text is intended. Required when it has any."
            ),
        }
        actions = _SECTION_ACTIONS_GUARDED
    return [{
        "name": "section_edit",
        "description": _SECTION_PREAMBLE + actions.format(h=f"`{payload}`"),
        "parameters": {
            "type": "object",
            "properties": props,
            "required": [file_arg, "action", "section"],
        },
    }]


SCHEMES.update({
    "section_naive": _section_tool("heading"),
    "section_p": _section_tool("new_heading"),
    "section_g": _section_tool("new_heading", guard=True),
    # S15. Two ways to break the `path` collision, one factor each, both
    # against `section_g` as the control.
    "section_g_file": _section_tool("new_heading", guard=True, file_arg="file"),
    "section_g_hpath": _section_tool("new_heading", guard=True,
                                     addr_arg="heading"),
    # S16. The cell S15's design left empty. Single factors were right for
    # S15's question -- which side of the collision to break -- and are wrong
    # for the one F-fileblind asks, because the two sides turned out to buy
    # different things: on `insert` only `file` moves the file-naming endpoint
    # (0-16, p = 3.1e-5) and on `rename` it is the only arm that moves
    # backwards (10-1). This takes both renames at once. `_section_tool`
    # already composed them; nothing here is new machinery, and `normalize`
    # already maps `file` -> `path` and `section.heading` -> `section.path`,
    # so the executor sees exactly what it saw in S15.
    "section_g_both": _section_tool("new_heading", guard=True,
                                    file_arg="file", addr_arg="heading"),
})

# --------------------------------------------------------------------------
# F-anchor: the one argument `section_edit` never names
# --------------------------------------------------------------------------
# `section_edit` loses its address 34 times in 450 composed trials, and the other
# four shipped tools lose theirs 0 times in 700. The difference is in the text:
# `table_edit`, `list_edit` and `frontmatter_edit` all name their address on
# every action line and again in a sentence of their own; `_SECTION_PREAMBLE`
# and `_SECTION_ACTIONS*` between them never write the word `section` once.
#
# So the treatment is a transcription, not an invention. Both halves are copied
# from schemes already adopted: the anchor sentence is `scheme_f`'s and
# `list_g`'s, with *outline* in place of *table list* / *list summary*, and the
# per-action naming is theirs too. The one sentence that is not a transcription
# is the `action=insert` clause, and it is there because 16 of the 17 offending
# calls are inserts -- a model that omits `section` on an insert is not
# forgetting an argument, it is failing to see that a creation has an anchor.
#
# *outline* and not *path*: S15 settled that the address is spelled `heading`
# and that `path` means the file, and a sentence reintroducing the word would be
# a second factor.
_SECTION_ANCHOR = (
    "`section` says WHICH section in the file and is required for every "
    "action. Copy it from the outline in the request; the last heading segment "
    "on its own is enough (e.g. \"macOS\"). For action=insert it is the "
    "EXISTING section the new one goes relative to, not the new one.\n"
)

# Derived from the guarded actions rather than retyped, so the two texts cannot
# drift in anything but the `section` naming. Each substring below occurs on
# exactly the lines it is meant to: `` requires `text` `` on append and
# replace-body, `` requires `position`, `` on insert (which is why the bare
# `` requires {h} `` that follows matches rename alone).
_SECTION_ACTIONS_ANCHORED = (
    _SECTION_ACTIONS_GUARDED
    .replace("requires `text`", "requires `section`, `text`")
    .replace("requires `position`,", "requires `section`, `position`,")
    .replace("requires nothing else", "requires `section` and nothing else")
    .replace("requires {h}", "requires `section`, {h}")
    .replace("requires `level`", "requires `section`, `level`")
)


def _section_anchored():
    """`section_g_hpath` with its description replaced, and nothing else.

    Deep-copied from the adopted scheme rather than rebuilt through
    `_section_tool`, so "one factor" is a property of the code and not a claim
    about two strings someone typed twice: `parameters` is the same object graph
    by construction, and only `description` is reassigned. `schematest.py`
    compares `schema.rs` against `section_g_hpath`, which this does not touch.
    """
    tool = json.loads(json.dumps(SCHEMES["section_g_hpath"]))
    tool[0]["description"] = (
        _SECTION_PREAMBLE
        + _SECTION_ANCHOR
        + _SECTION_ACTIONS_ANCHORED.format(h="`new_heading`")
    )
    return tool


SCHEMES["section_h"] = _section_anchored()


# --------------------------------------------------------------------------
# S6: the two candidate answers to the `body` payload
# --------------------------------------------------------------------------
# `body` takes raw markdown, so the schema's promise -- "you do not need to
# count levels" -- stops at its boundary, in the one place the model most needs
# it. Across 30 `insert-release-at-top` trials the model wrote the `Added`
# heading into `body` at level 1, 2 and 4, and never at 3. S6 named two ways
# out; these are them, as measurable conditions rather than opinions.
#
#   section_2call  -- `body` is prose only, and the schema says so. A section
#                     that contains a subsection is two calls. Levels stay
#                     derived everywhere; the cost is a round trip.
#   section_kids   -- `body` is prose only, and `children` takes the shape:
#                     [{heading, body}], levels computed from the parent. One
#                     call; the model supplies a structure instead of a number.
#
# Both keep every other field of `section_g`, so the contrast is the payload
# and nothing else. Both are run under the same multi-turn loop as the control,
# because otherwise `section_2call` would be measuring whether the harness
# allows a second call rather than whether the model makes one.

_BODY_PROSE = (
    "For insert: the new section's own body text. Optional. Prose only -- it "
    "is inserted literally, so it cannot contain a heading. To give the new "
    "section a subsection, insert that separately."
)


# Lifted out of `_section_s6` so F-narrow's two schemes can carry the *same*
# property object instead of a second copy of it. The extraction is byte-exact
# -- `section_2call` and `section_kids` are the schemas that produced S13 and a
# reformatting here would silently retire that result.
_CHILDREN_PROP = {
    "type": "array",
    "description": (
        "For insert: subsections to create inside the new section, in "
        "order. Their heading levels are worked out for you, the same "
        "way the new section's own is."
    ),
    "items": {
        "type": "object",
        "properties": {
            "heading": {
                "type": "string",
                "description": (
                    "The subsection's heading text. Text only -- no "
                    "`#` marks."
                ),
            },
            "body": {
                "type": "string",
                "description": "The subsection's body text. Optional.",
            },
        },
        "required": ["heading"],
    },
}

_KIDS_CLAUSE = (
    "use position=last-child for a new subsection.",
    "use position=last-child for a new subsection, or `children` to "
    "create the new section's subsections with it.",
)


def _section_s6(children=False, addr_arg="path"):
    tool = json.loads(json.dumps(
        _section_tool("new_heading", guard=True, addr_arg=addr_arg)))
    props = tool[0]["parameters"]["properties"]
    props["body"]["description"] = _BODY_PROSE
    if children:
        props["children"] = json.loads(json.dumps(_CHILDREN_PROP))
        tool[0]["description"] = tool[0]["description"].replace(*_KIDS_CLAUSE)
    return tool


SCHEMES.update({
    "section_2call": _section_s6(),
    "section_kids": _section_s6(children=True),
})


# --------------------------------------------------------------------------
# F-narrow: where `children` lives
# --------------------------------------------------------------------------
# S13's conclusion was a design constraint, not a verdict: `children` more than
# doubled the score on the three tasks it exists for (12 -> 26 of 30) and cost
# twelve points on the twelve that ignore it (115 -> 103), with `malformed`
# rising 0 -> 3 and single-call correctness 98% -> 94%. "A field costs something
# to every task in the tool, including the ones that ignore it ... a nested
# payload belongs on a tool narrow enough that the tasks paying for it are the
# tasks using it." That sentence has never been tested. These schemes test it.
#
# Three cells, all at the *adopted* address spelling. S13 ran before S15, so
# `section_kids` spells the section address `path`; re-running it as-is would
# answer a question about a schema that lost its own comparison. Each cell here
# is `section_g_hpath` plus a stated delta:
#
#   section_g_hpath     the control, and what ships today.
#   section_kids_hpath  + `body` documented prose-only, + `children` on
#                       `section_edit`. S13's two changes, carried forward.
#   section_split_hpath + `body` documented prose-only, + a second tool,
#                       `section_create`, that does nothing but insert and is
#                       the only thing carrying `children`.
#
# `kids` against `split` is one factor: which tool `children` sits on. Both
# document `body` as prose-only, so that half of S13 is held constant and is
# not re-measured here.
#
# **`section_create` is derived, not written.** It is `section_g_hpath`'s tool
# with the fields an insert cannot use removed (`action`, `text`, `level`,
# `subtree`, `overwrite`), `children` added from `_CHILDREN_PROP`, and three
# mechanical transforms on the descriptions that survive:
#
#   1. the literal prefix "For insert: " is dropped and the sentence
#      re-capitalised, because a tool with no other action has nothing to
#      distinguish it from;
#   2. `new_heading` loses its rename clause, for the same reason;
#   3. `section` says which EXISTING section the new one goes relative to,
#      instead of "which section to act on" -- which on a creation tool names
#      the wrong section. This is the `table_get` wart (FINDINGS, F-wart) seen
#      early enough to not ship it. The byte-identical rule binds text that
#      already has a number attached to it; `section_create` has none.
#
# Nothing else is reworded. In particular **no anchor sentence is added to the
# tool description.** The temptation was real -- F-anchor found `section_edit`
# losing its address 34 times in 450 composed trials, and a creation is where
# that happens -- but F-anchor's own treatment priced at k=5 against a floor of
# 6 and did not ship, and importing its sentence here would make a positive
# result mean "a narrow tool *with* an anchor sentence".
#
# **What transform 3 does to each endpoint, stated before the run.** The primary
# endpoint is the twelve tasks that never insert anything; they cannot call
# `section_create` at all, so no wording of it can move them and the tax
# measurement is immune. The secondary endpoint is the three target tasks, which
# do call it -- so a win there reads as "a narrow tool, described for its one
# job", and not as "a narrow tool".
#
# The enum invariant is not in the way this time, and it is worth saying why
# after F-realign spent two worlds on it. `section_create` publishes no `action`
# at all, so `_actions_from_schemes` skips it (`if not enum: continue`) and the
# `section_edit` beside it keeps the one enum every other scheme publishes --
# `insert` included. That is a confound and it is the honest one: shipping
# `section_create` would not remove `insert` from `section_edit`, because the
# invariant says that is a new world for every scheme in the file. So the
# treatment offers two routes to a new section, which is exactly what shipping
# it would offer, and the question it asks is whether the narrow one gets found.

_SECTION_CREATE_DESC = (
    _SECTION_PREAMBLE.replace(
        "Edit a markdown document's sections.",
        "Create a new section in a markdown document.")
    + "  Requires `position`, `new_heading`. "
    + _KIDS_CLAUSE[1].replace("use position", "Use position").rstrip(".")
    + "."
)

# The fields an insert cannot reach. `overwrite` guards `replace-body`, `text`
# is append/replace-body's payload, and `level`/`subtree` are `set-level`'s.
_CREATE_DROPS = ("action", "text", "level", "subtree", "overwrite")


def _section_create():
    tool = json.loads(json.dumps(SCHEMES["section_g_hpath"][0]))
    props = tool["parameters"]["properties"]
    for dead in _CREATE_DROPS:
        props.pop(dead, None)
    props["body"]["description"] = _BODY_PROSE
    props["children"] = json.loads(json.dumps(_CHILDREN_PROP))
    props["new_heading"]["description"] = props["new_heading"]["description"].replace(
        "For rename: the new heading text. For insert: the heading text of "
        "the new section.",
        "The heading text of the new section.")
    props["section"]["description"] = props["section"]["description"].replace(
        "Which section to act on,",
        "Which EXISTING section the new one goes relative to,")
    for spec in props.values():
        text = spec["description"].replace("For insert: ", "")
        spec["description"] = text[:1].upper() + text[1:]
    tool["name"] = "section_create"
    tool["description"] = _SECTION_CREATE_DESC
    tool["parameters"]["required"] = ["path", "section", "position",
                                      "new_heading"]
    return tool


SCHEMES.update({
    "section_kids_hpath": _section_s6(children=True, addr_arg="heading"),
    "section_split_hpath": (_section_s6(addr_arg="heading")
                            + [_section_create()]),
})

# --------------------------------------------------------------------------
# the frontmatter family -- naive, then tuned
# --------------------------------------------------------------------------
# PLAN §12's transferable order, and the list family is why it is not optional:
# `list_f` was B7's fix ported verbatim into a new family without first
# measuring what the family did unaided, and it scored 19 points *below* the
# naive schema it was supposed to improve on. The naive schema here is what an
# author who already knows the answer would write -- one tool, three named
# arguments, and a `key` whose description says what a key is and nothing about
# how to spell a path.
#
# The tuned schema changes exactly one thing: `key`'s description spells out
# the dotted path, says to copy it from the summary, and gives the index form.
# That is the variable, and it is chosen from the tasks rather than from taste
# -- `set-build-jobs` fails as a refusal when the model sends `jobs`, and
# `set-dana-role` cannot be reached at all without the bracket syntax. If the
# naive schema already reaches them, the prose is surface area and the
# measurement says so.

_FRONT_PREAMBLE = (
    "Edit the YAML frontmatter of a markdown file -- the block between `---` "
    "lines at the very top. This does not touch the document below it.\n"
    "  action=set     requires `key`, `value`. Creates the key if it is not "
    "there, and creates the whole block if the file has none.\n"
    "  action=delete  requires `key`. Removes the key and everything under "
    "it.\n"
)

FRONT_PROPS = {
    "path": {"type": "string", "description": "File to edit."},
    "action": {
        "type": "string",
        "enum": ["set", "delete"],
        "description": "Which edit to make.",
    },
    "key": {
        "type": "string",
        "description": "Which frontmatter key to edit.",
    },
    "value": {
        "description": (
            "For set: the new value, as one scalar. Send null to empty the key "
            "without removing it. The tool decides YAML quoting; send the "
            "value, not a quoted spelling of it."
        ),
    },
}

_FRONT_KEY_TUNED = (
    "Which frontmatter key to edit, as a full path from the top of the block. "
    "Copy it from the frontmatter summary in the request. A nested key is "
    'written with dots -- "build.jobs", not "jobs" -- and an item in a '
    'sequence is indexed from 0 -- "authors[0].role".'
)


def _front_tool(key_desc):
    props = json.loads(json.dumps(FRONT_PROPS))
    props["key"]["description"] = key_desc
    return [{
        "name": "frontmatter_edit",
        "description": _FRONT_PREAMBLE,
        "parameters": {
            "type": "object",
            "properties": props,
            "required": ["path", "action", "key"],
        },
    }]


# The read tool, offered *beside* the edit tool rather than instead of it.
# `table_read_naive` and `table_read_g` publish `table_get` alone, so F-read
# measured a model that had no other move; this is the first scheme in the
# project where a model holding a summary can choose to look before it writes,
# which is the question `set-dana-role` turned out to be asking.
#
# `key` is optional here and required on the edit tool, which is the difference
# between the two acts: an edit must say what it is editing, and a read with no
# key is the reasonable opening move -- "show me the block". Making it required
# would have priced the first look at the cost of guessing an address, which is
# the thing the read exists to avoid.
_FRONT_GET_TOOL = {
    "name": "frontmatter_get",
    "description": (
        "Read the YAML frontmatter of a markdown file, with the values. The "
        "summary in the request names the keys but not what they hold; this "
        "returns what they hold. Changes nothing."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File to read."},
            "key": {
                "type": "string",
                "description": (
                    "Optional. One key path, to read it and everything under "
                    "it. Omit to read the whole block."
                ),
            },
        },
        "required": ["path"],
    },
}


SCHEMES.update({
    "front_naive": _front_tool(FRONT_PROPS["key"]["description"]),
    "front_p": _front_tool(_FRONT_KEY_TUNED),
    # `front_p` plus the read tool, and identical to it in every other byte, so
    # the pair isolates one variable: whether the model can look.
    "front_r": _front_tool(_FRONT_KEY_TUNED) + [_FRONT_GET_TOOL],
})

# Every scheme above publishes one tool or two. The shipping product publishes a
# *set*, and no trial has ever shown a model more than three -- `scheme_a` is
# the record holder and it lost. So the set that `crates/incise-cli/src/schema.rs`
# would publish after the frontmatter family ships is itself unmeasured, and
# each member's number is evidence for a condition that is not the one it would
# be used in.
#
# `compose_5` is that set. Its members are *referenced*, not retyped: a copy
# would let the composition drift from the schemes whose numbers license it,
# and the whole claim being tested is that these exact five sit together.
# Order is the order `schema.rs` publishes them in, which is also the order
# `schematest.ADOPTED` checks.
SCHEMES["compose_5"] = (
    SCHEMES["scheme_f"]              # table_edit
    + SCHEMES["list_g"]              # list_edit
    + SCHEMES["section_g_hpath"]     # section_edit
    + SCHEMES["front_p"]             # frontmatter_edit
    + SCHEMES["table_read_g"]        # table_get
)

# `compose_5` minus the read, for localizing a loss rather than predicting one.
# It exists because `compose_5` lost (F-compose): the pre-registered rule said a
# significant loss buys this arm and nothing else, so it was added after the
# result and is named here as such. Run on the four *edit* task files only --
# `tables_read.json` under a scheme with no read tool is not a weaker condition,
# it is an impossible one.
SCHEMES["compose_4"] = SCHEMES["compose_5"][:4]

# The set `schema.rs` publishes **today**, and the one thing this whole
# comparison was missing. F-compose was pre-registered as `solo` (one tool)
# against `compose_5` (five), and that is not the ship decision: nobody is
# choosing between one tool and five. The product already ships three, and
# three had never been measured as a set either -- each of the three has a
# number from a scheme that published it alone. So `solo` is not the status quo,
# it is a condition the product left behind before any of this started, and the
# 5.4 points between `solo` and `compose_5` are partly already being paid.
#
# Post-hoc, and labelled as such wherever it is quoted.
SCHEMES["compose_3"] = SCHEMES["compose_5"][:3]

# F-anchor's treatment arm: `compose_5` with `section_h` in place of
# `section_g_hpath`, built by slicing the composition it is being compared
# against rather than by re-listing five tools. The other four objects are the
# *same objects* `compose_5` holds, so the only difference the model can see is
# `section_edit`'s description -- which is the whole claim.
SCHEMES["compose_5h"] = (
    SCHEMES["compose_5"][:2]
    + SCHEMES["section_h"]
    + SCHEMES["compose_5"][3:]
)

# --------------------------------------------------------------------------
# `scheme_f_realign` -- the op no model could invoke, offered, gated, shipped.
#
# `table-realign` is in `OPS`, in `dispatch.rs`, and has a CLI subcommand; no
# `action` enum in any scheme above publishes it. Fifteen ops, fourteen
# reachable from a tool. §5.2 calls it the pawl of the ratchet: the ratchet
# turns when anything other than incise leaves a table ragged, every later
# incise edit preserves the raggedness faithfully, and realign is the only op
# licensed to undo it.
#
# Built by *adding to* `scheme_f` rather than by retyping it, for the same
# reason `compose_5` references its members: the question is what one extra
# enum entry costs, and a re-typed description would make it two changes. The
# only edits are the enum and one action line in the same format as the other
# three.
#
# This exists to price the *gain* with `ceiling.py`, which needs no GPU. What
# it cannot price is the cost, and the cost is the reason the ship question is
# open: B7 moved this family by rewording one paragraph, and F-framing found
# that changing the surface a refusal offers confounds a wording measurement.
#
# **It was behind an env var, and finding out why is half of what this scheme
# established.** `_actions_from_schemes` builds `ACTIONS` from *every* scheme in
# this file and raises if one tool name publishes two different enums -- which
# is right, because `ACTIONS` is what the `action` refusal reads its list of
# valid actions out of, and a tool with two enums has no one list to name. Nine
# scheme entries publish `table_edit` (scheme_b through scheme_g, and the three
# `compose_*` that reference `scheme_f`'s object), so the candidate could not be
# one more entry beside them: defining it unconditionally *while the three-action
# enum also existed* broke the import for the whole benchmark.
#
# **So it could not be A/B'd, and that was a finding about the ship question
# rather than an inconvenience.** Every other schema decision in this file was
# settled by running two schemes against the same seeds in one process. This one
# could not be: the enum is a property of the whole world the harness holds, so
# `scheme_f` and `scheme_f_realign` were two worlds and the comparison was two
# runs sharing no process, `INCISE_BENCH_REALIGN=1` holding the second.
#
# **The gate ran and it ships, so there is one world again** (FINDINGS,
# F-realign). 180 trials: the six existing table tasks are **60/60 both ways,
# trial for trial**, and the new action was reached for **zero times** on them;
# the three realign tasks are 0/29 without it -- eight of those *destructive* --
# and **30/30** with it, p = 3.7e-09. The augmentation below is therefore
# unconditional, and the env var is gone. `scheme_f_realign` stays as an alias
# so the gate's own result files still resolve by name.
#
# What that costs, stated rather than buried: every scheme's `table_edit` now
# carries a line the pools recorded before 2026-09-17 were not shown. The
# invariant admits no half-measure -- one tool name, one enum -- so the harness
# holds one world and after a ship that world is the shipped one. The text a
# given pool was shown is in git, beside the commit that ran it.
#
# `ceiling.py` could not price the *unreachable* side, and it is worth saying
# why rather than reporting a number that looks like it did. `as_tool_call`
# builds the tool call from the ideal op without consulting the enum, and the
# executor runs `table-realign` whether or not any schema published it -- so
# running these tasks under the old three-action `scheme_f` graded `correct` and
# meant nothing. That a model cannot emit `action: "realign"` when the enum does
# not contain it is a fact about the schema, established by reading it. Same
# shape as F-rows: `ceiling.py` proves the reachable side, the schema settles
# the other. The gate's control cell is what turned that reading into a
# measurement: 30 trials that could not say `realign` said `update-cell` 54
# times instead and destroyed the document 8 times.
_REALIGN_LINE = (
    "\n  action=realign      requires `table`. Re-pads a table whose columns "
    "were left ragged by some other editor. Changes no cell text."
)
# Every `table_edit`, not just `scheme_f`'s, because the invariant above admits
# no half-measure. This mutates the tool dicts in place so the three
# `compose_*`, which hold references rather than copies, move with them --
# which is also the right answer on the merits: the op ships, so it ships
# inside the composition too.
for _tools in SCHEMES.values():
    for _t in _tools:
        if _t["name"] != "table_edit":
            continue
        _enum = _t["parameters"]["properties"]["action"]["enum"]
        if "realign" not in _enum:
            _enum.append("realign")
            _t["description"] += _REALIGN_LINE
SCHEMES["scheme_f_realign"] = SCHEMES["scheme_f"]

# Evaluation-only composition generated by the candidate binary. It stays
# behind an explicit switch so importing historical pools never changes their
# scheme universe. The canonical candidate schemas live in the binary because
# the Hermes and Pi adapters consume the same source.
if os.environ.get("INCISE_BENCH_SAFE_SMALL") == "1":
    exe = os.environ.get("INCISE_BIN") or os.path.join(ROOT, "target", "debug", "incise")
    loaded = subprocess.run(
        [exe, "schema", "--profile", "safe-small"],
        capture_output=True, text=True, timeout=10, check=True)
    candidate = json.loads(loaded.stdout)
    if not isinstance(candidate, list) or len(candidate) != 12:
        raise RuntimeError("safe-small schema profile did not contain twelve tools")
    SCHEMES["safe_small"] = candidate

SYSTEM_PROMPTS = {
    "table": (
        "You are a helpful coding agent. You edit markdown files using incise table "
        "tools.\n\n"
        "You do NOT have the file contents, and you do not need them. You are given "
        "a list of the tables in the file. Address the table by its heading (and "
        "ordinal, if the heading has more than one table), and address a row by the "
        "values in its cells.\n\n"
        "The tool handles all formatting: column padding, alignment, and delimiter "
        "rows. Supply values only. Make only the edit that was asked for."
    ),
    "list": (
        "You are a helpful coding agent. You edit markdown files using incise list "
        "tools.\n\n"
        "You do NOT have the file contents, and you do not need them. You are given "
        "a summary of the lists in the file. Address the list by its heading (and "
        "ordinal, if the heading has more than one list), and address an item by "
        "its text.\n\n"
        "The tool handles all formatting: marker characters, indentation, blank "
        "lines between items, and ordered-list numbering. Supply text only. Make "
        "only the edit that was asked for."
    ),
    "section": (
        "You are a helpful coding agent. You edit markdown files using incise "
        "section tools.\n\n"
        "You do NOT have the file contents, and you do not need them. You are "
        "given an outline of the document's headings. Address a section by its "
        "heading path.\n\n"
        "The tool handles all structure: heading syntax, heading level, and "
        "where each section starts and ends. Never write `#` marks and never "
        "state a level. Make only the edit that was asked for."
    ),
    "frontmatter": (
        "You are a helpful coding agent. You edit markdown files using incise "
        "frontmatter tools.\n\n"
        "You do NOT have the file contents, and you do not need them. You are "
        "given a summary of the file's frontmatter: every key that exists and "
        "what kind of thing it holds. Address a key by its path.\n\n"
        "The tool handles all YAML: quoting, indentation, key order, and the "
        "comments in the block. Supply the value, never YAML text. Make only "
        "the edit that was asked for."
    ),
    # The read condition. Its second paragraph is the edit prompts' second
    # paragraph with the load-bearing sentence inverted: "you do not need them"
    # is true of an edit addressed by content and false of a question about a
    # cell, and leaving it in would be instructing the model not to do the task.
    # Everything else is held as close to the table prompt as the change allows,
    # because the thing under test is the schema, not the prose.
    "table_read": (
        "You are a helpful coding agent. You answer questions about markdown "
        "files using incise table tools.\n\n"
        "You do NOT have the file contents. You are given a list of the tables "
        "in the file, which names each table's heading and columns but none of "
        "its cells. To see cells, read the table with the tool. Address the "
        "table by its heading (and ordinal, if the heading has more than one "
        "table).\n\n"
        "Answer from what the tool returns and nothing else. Do not guess a "
        "cell value, and do not edit the file."
    ),
    # The same inversion, one family over, and a narrower one. `table_read`
    # replaces an edit prompt wholesale because its tasks are questions; these
    # tasks are still edits, so this is the `frontmatter` prompt with one
    # sentence changed -- "you do not need them" becomes the conditions under
    # which the model does. The last paragraph is byte-identical to the edit
    # prompt's, because the schema is the variable and the prose is not.
    #
    # It says *when* to read rather than to read first. "Always read before
    # editing" would buy `set-dana-role` at the price of testing obedience
    # instead of judgement, and S14 is the standing evidence that an extra call
    # on a task that did not need one is not free.
    "frontmatter_read": (
        "You are a helpful coding agent. You edit markdown files using incise "
        "frontmatter tools.\n\n"
        "You do NOT have the file contents. You are given a summary of the "
        "file's frontmatter: every key that exists and what kind of thing it "
        "holds, but not the values. If the edit you were asked for depends on "
        "a value -- which of several entries to change, or what the current "
        "value is -- read the frontmatter first. Address a key by its path.\n\n"
        "The tool handles all YAML: quoting, indentation, key order, and the "
        "comments in the block. Supply the value, never YAML text. Make only "
        "the edit that was asked for."
    ),
}

# Kept for the table runs already on disk, which reference it by name.
SYSTEM_PROMPT = SYSTEM_PROMPTS["table"]


# Divergence C, behind a switch. `regrade_snapshot.py` replays every recorded
# call through `normalize`, so anything that changes what it returns moves every
# digest by construction -- the flag is what keeps those replays honest while
# the condition is measured. Default off is not a formality: the plugin passes a
# missing `action` through *deliberately* (`plugins/hermes/__init__.py`), on the
# grounds that rejecting it here would replace a measured refusal with an
# unmeasured one, and that reasoning holds until this has beaten the core's
# sentence in an arm. `bench/action_sizing.py` is why it has not: three of the
# four messages below have no caller in any recorded trial, and the fourth's
# callers are two seeds.
CHECK_ACTION = False

# The three families' op names, by tool, taken from **the enum each scheme
# actually published**. The core composes its `unknown operation` sentence from
# all fifteen at once, which is right for the CLI -- Arm C names the op
# directly and any of them could have been meant -- and wrong here, where the
# model called `list_edit` and cannot reach the other twelve whatever it does.
#
# This used to be derived from `OPS`, on the stated grounds that naming what the
# executor accepts was "the lesser evil -- the alternative is a list that can be
# wrong." That was a false choice, and it cost something real: `OPS` contains
# `table-realign`, which no scheme's `action` enum publishes, so the refusal
# offered a capability the tool did not -- the condition changed the offered
# surface as well as the sentence, which would have confounded any measurement
# of it. The schemes are in this process and all 24 agree, so the list can be
# both correct and confined to what was offered. The two assertions below are
# what keep it that way: a scheme that disagreed with another, or that published
# an action the executor cannot run, stops the harness rather than shipping a
# refusal that names an unreachable op.
def _actions_from_schemes():
    by_tool = {}
    for tools in SCHEMES.values():
        for t in tools:
            enum = ((t.get("parameters") or {}).get("properties")
                    or {}).get("action", {}).get("enum")
            if not enum:
                continue
            prev = by_tool.setdefault(t["name"], tuple(enum))
            if prev != tuple(enum):
                raise SystemExit(
                    f"schemes disagree on {t['name']}'s action enum: "
                    f"{list(prev)} vs {list(enum)}; `_action_of` cannot name "
                    "one list for a tool that publishes two")
    for tool, acts in by_tool.items():
        family = tool[:-len("_edit")]
        unreachable = [a for a in acts if f"{family}-{a}" not in OPS]
        if unreachable:
            raise SystemExit(
                f"{tool} publishes {unreachable}, which the executor cannot "
                "run; a refusal naming them would send the model somewhere "
                "that refuses again")
    return by_tool


ACTIONS = _actions_from_schemes()


class ArgError(Exception):
    """A fault `normalize` can see and the core cannot.

    Raised only with `CHECK_ACTION` on. Every call site renders it through
    `err_text`, which drops the class name -- a refusal that reads
    `ArgError: ...` is leaking a Python type into the product, and §5.3 governs
    these sentences the same as the core's.
    """


def err_text(e):
    """The model-facing text for an exception caught around `normalize`.

    `ArgError` is a written refusal and stands alone; anything else is a crash,
    and its type name is the most useful thing about it.
    """
    return str(e) if isinstance(e, ArgError) else f"{type(e).__name__}: {e}"


def _action_of(name, args):
    """The `action` value, or raise `ArgError` saying what went wrong.

    Four messages, because the fault has four shapes and they need different
    repairs. The split is not invented, and it is not evenly used: run
    `bench/action_sizing.py`, which replays every edit-tool call in
    `bench/results/` through this function. *Every* `action` that arrived as its
    own key was a valid op name -- no typos, no non-strings, no omissions -- and
    every refusal it can raise on recorded data is the fused-key one, the key
    being `"action=add-item,item"` because the model wrote `action=add-item,` in
    a syntax that is not JSON and the next key name fused onto it. Telling that
    caller `action` is required would be false; it sent `action`. No count is
    quoted here on purpose: the figure this docstring used to carry went stale
    by two thousand calls before anything recomputed it.

    The omission is real all the same, just not in the arm files: the live
    hermes runs R2 and R4 both produced `list_edit` with no `action` at all
    (FINDINGS F-front, F-action). So both sentences have a caller, and writing
    only one of them would be wrong for somebody.

    A misspelled `action` is answered here too rather than falling through. The
    core's own first act is to dispatch on the op name, so this is the same
    check in the same position -- nothing is pre-validated that the core would
    have seen first -- only better informed about which family is calling.
    """
    act = args.get("action")
    valid = ", ".join(ACTIONS[name])
    if isinstance(act, str) and act:
        if act in ACTIONS[name]:
            return act
        near = [a for a in ACTIONS[name]
                if a.replace("-", "") == act.replace("-", "").replace("_", "")]
        raise ArgError(
            f'no action "{act}" on this tool.\n'
            # No diagnosis of *why* it differs: `setlevel` and `set_level`
            # reach this the same way and only one of them is an underscore,
            # so naming the cause is a guess. The spelling is the repair.
            + (f'  Did you mean "{near[0]}"?\n' if near else "")
            + f"  Valid: {valid}.")
    if act is None and "action" not in args:
        fused = [k for k in args if isinstance(k, str)
                 and k.startswith("action=")]
        if fused:
            # The key is the whole fault and the first line already quotes it,
            # so there is no `Got:` line: the value belongs to whatever key it
            # was meant for, and echoing it truncated -- these run to hundreds
            # of characters -- would put a broken JSON fragment in a refusal.
            k = fused[0]
            sent = k[len("action="):].split(",")[0]
            # The example echoes what was sent only when this tool would accept
            # it. A cross-family fusion -- `action=add-row` arriving on
            # `list_edit` -- would otherwise produce a refusal that instructs
            # the model to send a value the next line declares invalid.
            example = sent if sent in ACTIONS[name] else ACTIONS[name][0]
            raise ArgError(
                f"`{k}` arrived as one JSON key, not two.\n"
                f"  Every argument is its own key: "
                f'`"action": "{example}"`, then the next one beside it, not '
                "packed into the name.\n"
                # "Valid:" rather than "Send `action` as add-item, remove-item,
                # set-checked, and repeat ...", which reads as four instructions
                # in a row and not as one list followed by one instruction.
                f"  Valid: {valid}. Send the call again with each argument as "
                "its own key.")
        raise ArgError(
            "`action` is required: which edit to make.\n"
            f"  One of: {valid}.\n"
            "  Everything else you sent is fine -- add `action` and send the "
            "call again.")
    raise ArgError(
        f"`action` must be one of {valid}.\n"
        f"  Got: {json.dumps(act)}.\n"
        "  Send the name on its own, as a string.")


def normalize(name, args):
    """Map a tool call in any scheme onto (op_name, op_args), or raise KeyError.

    Kept separate from the schemas so every vocabulary is graded by exactly the
    same executor -- otherwise the A/B would be measuring the harness.
    """
    if CHECK_ACTION and name in ACTIONS:
        _action_of(name, args)
    if name == "table_edit":
        return "table-" + str(args.get("action")), args
    if name == "list_edit":
        return "list-" + str(args.get("action")), args
    if name in ("section_edit", "section_create"):
        args = dict(args)
        # F-narrow's `section_create` is `section_edit` with one action and no
        # `action` key, so it joins here rather than getting a second copy of
        # the three renames below. The action is supplied, not read: a tool
        # that publishes no enum has nothing for the model to get wrong, and
        # `_action_of` never sees it (`section_create` is not in `ACTIONS`).
        if name == "section_create":
            args["action"] = "insert"
        # `section_p` spells the payload `new_heading`; the executor knows one
        # name for it. Undone here rather than in `incise_ops`, because the
        # whole point of the contrast is that both schemes reach the same
        # executor -- a scheme that also changed the op would not be a rename,
        # it would be a different tool.
        if "new_heading" in args:
            args["heading"] = args.pop("new_heading")
        # S15's two renames, undone the same way and for the same reason.
        # `file` is only accepted when `path` is absent: a model that supplied
        # both has made an error the executor must not paper over by picking
        # one, and letting `path` win keeps that trial gradeable as whatever it
        # actually was.
        if "file" in args and "path" not in args:
            args["path"] = args.pop("file")
        sec = args.get("section")
        if isinstance(sec, dict) and "heading" in sec and "path" not in sec:
            sec = dict(sec)
            sec["path"] = sec.pop("heading")
            args["section"] = sec
        return "section-" + str(args.get("action")), args
    if name == "frontmatter_edit":
        return "frontmatter-" + str(args.get("action")), args
    narrow = {
        "table_add_row": "table-add-row",
        "table_update_cell": "table-update-cell",
        "list_add_item": "list-add-item",
        "section_append": "section-append",
        "frontmatter_set": "frontmatter-set",
        # Evaluation-only routed MiniCPM tools. Their schemas constrain the
        # value type; execution still reaches the one existing core op so the
        # arm changes model choice, not executor semantics.
        "frontmatter_set_string": "frontmatter-set",
        "frontmatter_set_integer": "frontmatter-set",
        "frontmatter_set_boolean": "frontmatter-set",
        "frontmatter_set_null": "frontmatter-set",
    }
    if name in narrow:
        return narrow[name], args
    if name == "section_insert":
        args = dict(args)
        if "parent" in args:
            args["section"] = args.pop("parent")
        if "new_heading" in args:
            args["heading"] = args.pop("new_heading")
        if "body" in args:
            args["text"] = args.pop("body")
        sec = args.get("section")
        if isinstance(sec, dict) and "heading" in sec and "path" not in sec:
            sec = dict(sec)
            sec["path"] = sec.pop("heading")
            args["section"] = sec
        return "section-insert", args
    return name, args


def family_of(task):
    for fam in ("list", "section", "frontmatter"):
        if task["family"].startswith(fam + "-"):
            return fam
    return "table"


# The read tools, by tool name. Routed here rather than through `apply_op`, and
# that is not an optimisation: every entry in `OPS` takes a document and returns
# a document or a refusal, and `table_get` returns text *about* a document
# (incise_ops.py:173). Adding it to `OPS` to get a model's hands on it would
# also move the `unknown operation "..." Valid: ...` sentence, which is measured
# data -- F-dupcol is the precedent for what proving that harmless costs.
#
# The value is the task family a scheme's read tool grades under, so the two
# names stay tied together in one place instead of in `grade.check_result` and
# here separately.
READS = {
    "md_tables": "md-tables",
    "table_get": "table-get",
    "md_lists": "md-lists",
    "list_get": "list-get",
    "md_outline": "md-outline",
    "frontmatter_get": "frontmatter-get",
}

# Schemes whose read-capable system prompt is part of what was measured, by
# name rather than by "publishes something in READS".
#
# `front_r` is the whole list and the reason the list exists: its result is the
# read tool *and* the sentence in `SYSTEM_PROMPTS["frontmatter_read"]` telling
# the model when to reach for it, measured together on edit tasks. A scheme not
# named here gets its family's ordinary prompt however many reads it publishes.
#
# Keyed on the scheme and not on the toolset because the two are not the same
# question, and the difference is destructive rather than cosmetic: a scheme
# publishing `table_get` *beside* the edit tools would otherwise hand a table
# **edit** task the `table_read` prompt, whose last line is "Answer from what
# the tool returns and nothing else ... do not edit the file." That is a
# condition in which the task cannot be done, scored as if the model had
# declined to do it.
READ_PROMPT_SCHEMES = {"front_r"}
if "safe_small" in SCHEMES:
    READ_PROMPT_SCHEMES.add("safe_small")


def prompt_of(task, scheme=None):
    """Which system prompt a task gets. Not the same question as `family_of`.

    `family_of` chooses a *renderer*, and a read task is given the same table
    list every write task is given -- that is the point of the experiment, since
    the open question is whether a model holding the summary reaches for the
    tool at all. The system prompt is the thing that has to differ, and only
    because one sentence in it would otherwise instruct the model not to do the
    task. Keeping the two questions in two functions is what stops a later read
    family quietly acquiring a renderer it never asked for.

    `scheme` arrived with `front_r`, where the same *task* is run with and
    without a read tool: "you do not need the file contents" has to go when the
    scheme publishes something that returns them, and the task cannot tell you
    that.

    The selection is by scheme name (`READ_PROMPT_SCHEMES`) and not by what the
    scheme publishes. It was the latter until `compose_5`, and that worked only
    because the table schemes published `table_get` *alone* and were therefore
    only ever run on `table-get` tasks, which take the branch above this one.
    A composition scheme breaks that assumption in the one direction nothing
    would have caught -- see the comment on `READ_PROMPT_SCHEMES`. Every
    recorded scheme takes the same branch it took when its numbers were
    recorded; the swap is inert over all 25 of them.
    """
    if task["family"].startswith("table-get"):
        return "table_read"
    fam = family_of(task)
    if scheme in READ_PROMPT_SCHEMES and f"{fam}_read" in SYSTEM_PROMPTS:
        return f"{fam}_read"
    return fam


def read_args(name, args):
    """A read tool call's arguments in the reference op's vocabulary.

    `normalize`'s job, for the ops that are off `apply_op`. Split out because
    Arm C needs the same mapping and must not transcribe it: a rename that drifted
    between the arms would put the difference in the harness rather than in the
    port, which is the one thing this comparison cannot survive.

    `where` is `table_read_naive`'s spelling of the same field and is renamed
    here for the same reason `normalize` renames `new_heading`: the scheme
    publishes one word, the reference op takes another, and without the rename
    every naive-scheme call would refuse for a filter the model did supply -- a
    ceiling of zero on a schema that is not what failed. `filter` wins when a
    call carries both, so a scheme cannot smuggle in the other vocabulary.

    Everything else is passed through untouched, `path` included, exactly as
    `normalize` passes `path` and `action` through: the callers that do not need
    it ignore it, and dropping it would change the bytes Arm C puts on argv.
    """
    if name not in READS:
        raise ValueError(f"not a read tool: {name}")
    args = dict(args)
    if name == "table_get" and "where" in args:
        if "filter" not in args:
            args["filter"] = args["where"]
        del args["where"]
    return READS[name], args


def read_call(doc, name, args):
    """One read tool call -> (report, rendered, error).

    Returns both forms on purpose. The rendered string is what the model is
    handed back, and the structure is what `check_table_read_result` grades, so
    a renderer change cannot move a grade and a grader change cannot move what
    the model saw. They cannot disagree about the document either: `table_get`
    is pure, and calling it twice on the same `(doc, address, filter)` is the
    same call, not two samples.
    """
    op, args = read_args(name, args)
    try:
        if op == "md-tables":
            rendered = render_table_list(doc, args.get("path", ""))
            return rendered, rendered, None
        if op == "md-lists":
            rendered = render_list_summary(doc, args.get("path", ""))
            return rendered, rendered, None
        if op == "md-outline":
            rendered = render_section_outline(doc, args.get("path", ""))
            return rendered, rendered, None
        if op == "frontmatter-get":
            # `path` is the file, which the caller already resolved into `doc`;
            # it is passed to the renderer only because the string names the
            # file back to the model, the way every other summary does.
            key = args.get("key")
            return (frontmatter_get(doc, key),
                    render_frontmatter_get(doc, args.get("path", ""), key),
                    None)
        if op == "list-get":
            address = args.get("list")
            return (list_get(doc, address), render_list_get(doc, address), None)
        address = args.get("table")
        filt = args.get("filter")
        return table_get(doc, address, filt), render_table_get(doc, address, filt), None
    except OpError as e:
        return None, None, str(e)


# --------------------------------------------------------------------------
# run
# --------------------------------------------------------------------------

RESULT_SHAPES = ("outline", "delta", "both")


def tool_result(shape, doc, fixture, before=None, fam="section"):
    """What a successful call sends back to the model.

    The variable S14 tests. `outline` is what every arm before S14 used -- the
    document's new summary, the same view the first turn was given. S13
    measured its cost: on the twelve single-call section tasks, a model that
    called again after a call that had already worked was 32x more likely to
    destroy the document (REQUIREMENTS §6.3.2). A summary that already
    reflects an edit cannot testify that the edit happened.

    `delta` replaces it with `describe_change`, which is derived from the two
    documents. `both` is the third arm and exists because the two are not
    obviously exclusive: dropping the summary could cost the model the address
    of a section it just created, and a result that is *worse* on the
    multi-call tasks while better on the single-call ones is a result this
    experiment has to be able to see.

    `describe_change` reads headings, so on a table or list task `delta` would
    describe the wrong structure. Those families have never run multi-turn;
    rather than let that stay a silent assumption, they fall back to the
    summary and say so.

    Frontmatter takes `describe_frontmatter_change` rather than
    `describe_change`, and needs the delta more than the section family does:
    `render_frontmatter` omits scalar values on purpose, so the summary is
    byte-identical before and after a `frontmatter-set` and cannot testify that
    anything happened at all.
    """
    summary = {"list": render_list_summary, "section": render_section_outline,
               "table": render_table_list,
               "frontmatter": render_frontmatter}[fam](doc, fixture)
    if fam not in ("section", "frontmatter") or before is None:
        return "Applied. The file now looks like:\n\n" + summary
    delta = (describe_frontmatter_change(before, doc) if fam == "frontmatter"
             else describe_change(before, doc, fixture))
    outline = ("The file's frontmatter is now:" if fam == "frontmatter"
               else "The document's headings are now:") + "\n\n" + summary
    if shape == "outline":
        return "Applied. " + outline
    if shape == "delta":
        return delta
    return f"{delta}\n\n{outline}"


def build_payload(task, scheme, seed):
    with open(os.path.join(ROOT, task["fixture"]), newline="") as fh:
        content = fh.read()
    fam = family_of(task)
    summary = {"list": render_list_summary,
               "section": render_section_outline,
               "table": render_table_list,
               "frontmatter": render_frontmatter}[fam](content, task["fixture"])
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPTS[prompt_of(task, scheme)]},
            {"role": "user", "content": f"{summary}\n\n{task['instruction']}"},
        ],
        "tools": [{"type": "function", "function": s} for s in SCHEMES[scheme]],
        "tool_choice": "auto",
        "cache_prompt": True,
        "seed": seed,
        # Matches the `reasoning_off` baseline condition. FINDINGS.md F5 shows
        # reasoning buys nothing on this workload at 16x the cost, so Arm B is
        # compared against the cheap arm, which is the honest comparison.
        "chat_template_kwargs": {"enable_thinking": False},
    }


def run_trial(endpoint, task, scheme, seed, max_turns, shape="outline"):
    """One trial, up to `max_turns` assistant turns, as one recorded row.

    Arm B was single-turn until S6, and for nine of the thirteen section tasks
    it still effectively is: the model calls once, the loop sees no second call
    and stops. What changed is that a task needing two calls can now be
    attempted. `insert-release-at-top` is that task -- a new release with an
    `Added` subsection -- and reading its 30 single-turn trials showed the
    dominant failure was not the level arithmetic S6 blamed but the model
    making one call and stopping, which single-turn Arm B cannot distinguish
    from choosing not to.

    What comes back to the model after a call is deliberately *not* the
    document: Arm B's premise is that the model never sees file contents, and
    breaking that here would make the two-call arm win for the wrong reason.
    It gets the refreshed outline -- the same view the first turn was given --
    or the error, which is what a real agent would have.

    `max_turns=1` reproduces the old behaviour exactly.
    """
    fixture = os.path.join(ROOT, task["fixture"])
    payload = build_payload(task, scheme, seed)
    doc = open(fixture, newline="").read()
    calls, turns, tokens, elapsed = [], [], 0, 0.0
    finish = None
    for _ in range(max_turns):
        resp, took = call(endpoint, payload)
        row = record(resp, took)
        turns.append({k: row.get(k) for k in
                      ("content", "tool_calls", "finish_reason",
                       "completion_tokens", "elapsed_s")})
        tokens += row.get("completion_tokens") or 0
        elapsed += row.get("elapsed_s") or 0
        finish = row.get("finish_reason")
        made = row.get("tool_calls") or []
        if not made:
            break
        calls += made
        payload["messages"].append(
            {"role": "assistant", "content": row.get("content"), "tool_calls": made})
        for c in made:
            fn = c.get("function", {})
            text = None
            try:
                a = json.loads(fn.get("arguments") or "{}")
                if fn.get("name") in READS:
                    after, err = None, None
                    _got, text, err = read_call(doc, fn.get("name"), a)
                else:
                    op, op_args = normalize(fn.get("name"), a)
                    after, err = apply_op(doc, op, op_args)
            except Exception as e:  # noqa: BLE001
                after, text, err = None, None, err_text(e)
            if err:
                result = "Error: " + err
            elif text is not None:
                # A read's result is the renderer's string, and `doc` is
                # deliberately not reassigned: the whole claim a read makes is
                # that the file is where the model left it.
                result = text
            else:
                result = tool_result(shape, after, task["fixture"], doc,
                                     family_of(task))
                doc = after
            payload["messages"].append(
                {"role": "tool", "tool_call_id": c.get("id", "0"),
                 "content": result})
    return {
        "model": resp.get("model"),
        "finish_reason": finish,
        "elapsed_s": round(elapsed, 2),
        "completion_tokens": tokens,
        "tool_calls": calls,
        "turns": turns,
        "n_turns": len(turns),
        # The two run-level settings that change what a trial *is* and were not
        # recoverable from the file. `armb.jsonl`, `armb_lists.jsonl` and
        # `armb_read_g.jsonl` are pre-S6/S14 and `armb_front_p_v3.jsonl` is not,
        # and nothing in any of them says so -- an absent `turns` field was the
        # only clue, and it is an accident of when multi-turn landed rather than
        # a record of anything. A pool that cannot say which condition it ran
        # under cannot be the control for a later one.
        "result_shape": shape,
        "max_turns": max_turns,
    }


def run(args):
    tasks = json.load(open(args.tasks))["tasks"]
    os.makedirs(os.path.dirname(args.out), exist_ok=True)

    done = set()
    if os.path.exists(args.out):
        for line in open(args.out):
            try:
                t = json.loads(line)
                # A row that errored is not a measurement, so re-running the
                # command retries it. This matters more than it looks in a
                # paired design: the server returns an occasional HTTP 500, and
                # a trial lost in one arm but not the others drops that whole
                # (task, trial) pair from the comparison -- asymmetrically, and
                # invisibly. Retrying appends a second row for the same key, so
                # readers must take the last one per (task, scheme, trial).
                if t.get("error") is None:
                    done.add((t["task_id"], t["scheme"], t["trial"]))
            except (json.JSONDecodeError, KeyError):
                continue
    if done:
        print(f"resuming: {len(done)} trials already recorded")

    work = [
        (task, trial)
        for task in tasks
        for trial in range(args.trials)
        if (task["id"], args.scheme, trial) not in done
    ]
    if not work:
        print("nothing to do")
        return

    print(f"{len(work)} trials to run, scheme={args.scheme}")
    import time

    started = time.time()
    with open(args.out, "a") as fh:
        for n, (task, trial) in enumerate(work, 1):
            try:
                if args.turns > 1:
                    row = run_trial(args.endpoint, task, args.scheme, trial,
                                    args.turns, args.result_shape)
                else:
                    resp, elapsed = call(args.endpoint, build_payload(task, args.scheme, trial))
                    row = record(resp, elapsed)
                    # Null rather than the flag's value: a single-turn trial is
                    # never handed a tool result, so the shape did not take
                    # effect and recording it would name a condition the trial
                    # did not run under.
                    row["result_shape"] = None
                row.update(task_id=task["id"], scheme=args.scheme, trial=trial,
                           error=None, max_turns=args.turns)
            except Exception as e:  # noqa: BLE001
                row = {
                    "task_id": task["id"], "scheme": args.scheme, "trial": trial,
                    "error": f"{type(e).__name__}: {e}", "elapsed_s": None,
                }
            fh.write(json.dumps(row) + "\n")
            fh.flush()
            el = time.time() - started
            eta = (el / n) * (len(work) - n) / 60
            print(
                f"[{n:3d}/{len(work)}] {task['id']:26s} t{trial:<2d} "
                f"{(row.get('elapsed_s') or 0):6.1f}s  "
                f"tok={row.get('completion_tokens') or 0:5d}  "
                f"{'ERR ' + row['error'][:40] if row.get('error') else ''}  eta {eta:.0f}m",
                flush=True,
            )


# --------------------------------------------------------------------------
# grade
# --------------------------------------------------------------------------

# Exception types that mean the request never produced a completion. Matched on
# the type name because that is what the run loop writes into `error`
# (`f"{type(e).__name__}: {e}"`), and kept to an explicit list rather than a
# catch-all: anything raised *after* a completion arrived is a fault in this
# harness or in what the model sent, and both of those belong in `malformed`
# where they are somebody's problem. Every instance recorded so far is
# `HTTPError: HTTP Error 500`; the rest are here because a local server that
# dies mid-arm produces them and the next arm should not have to rediscover
# this.
TRANSPORT_ERRORS = frozenset({
    "HTTPError", "URLError", "RemoteDisconnected", "IncompleteRead",
    "ConnectionResetError", "ConnectionRefusedError", "TimeoutError",
    "socket.timeout", "BadStatusLine",
})


def grade_one(task, trial):
    """Return (outcome, detail).

    Outcome classes match grade.py, plus one Arm B can produce and Arm A cannot:

      op_error   the call named something that does not exist -- wrong heading,
                 wrong column, no matching row, or an op name the executor does
                 not have. incise rejects it with a message and the document is
                 untouched. A *loud* failure: it costs a turn, not a document.
                 Tracked separately from `malformed` because the fix is
                 different (better error text vs. a better schema).

                 The last of those -- `unknown operation "table-None"`, from an
                 `action` the model fused into the next key -- used to be graded
                 `malformed` and to end the trial. It is here now because the
                 model reads that sentence and recovers from it like any other;
                 see the comment at the branch and FINDINGS F-terminal.

    Read families (`table-get`) add `misreported` and reach it by a different
    route: see the branch below the call loop.

    And one class that is not about the model at all:

      transport  the request never produced a completion -- the model server
                 answered 500, or the connection failed. `turns` is empty, so
                 no schema could have changed the outcome and no wording is
                 being tested. Graded `malformed` until 2026-09-17, which
                 charged a server fault to the model and moved a published
                 number: F-compose's sections row was 14-1, p = 0.00098 and is
                 13-1, p = 0.00183, the one `compose_4` instance being
                 concordant.

                 It is a class rather than a silent drop because a dropped
                 trial is invisible and these were found by grepping for
                 `malformed` with an `HTTPError` detail. `stats.py` excludes
                 the *pair* from both arms -- a fault in one arm says nothing
                 about the other -- and prints the count and the distinct
                 messages, so a 4xx (which would be a harness fault, not a
                 server one) shows up rather than being absorbed.
    """
    if trial.get("error"):
        kind = trial["error"].split(":", 1)[0]
        return ("transport" if kind in TRANSPORT_ERRORS else "malformed",
                trial["error"])
    calls = trial.get("tool_calls") or []
    if not calls:
        return "malformed", "no tool call"

    # Every call the trial made, applied in order to one working document.
    # Single-call trials -- which is every trial run before S6 -- travel the
    # identical path, because the loop body is what `calls[0]` used to do. A
    # task that legitimately needs two calls (S6: a new section that contains a
    # subsection) is then graded on the document it ends with, exactly like a
    # task that needs one. The alternative, grading each call separately, would
    # make "correct" mean something different for different tasks.
    #
    # A call that errors leaves the document untouched -- that is the op's
    # contract, and the multi-turn loop hands the model the error and lets it
    # try again -- so an error is collected and the sequence continues rather
    # than aborting. With one call that is indistinguishable from the old
    # behaviour.
    before = open(os.path.join(ROOT, task["fixture"]), newline="").read()
    doc = before
    errors = []
    report = None
    for i, c in enumerate(calls):
        fn = c.get("function", {})
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except json.JSONDecodeError as e:
            return "malformed", f"call {i + 1}: unparseable arguments: {e}"
        if not isinstance(args, dict):
            return "malformed", f"call {i + 1}: arguments not an object: {type(args).__name__}"
        where = f"call {i + 1}: " if len(calls) > 1 else ""
        if fn.get("name") in READS:
            # A read that refused is collected exactly as a failed edit is, and
            # a later read that succeeds replaces it -- the model was handed the
            # refusal and tried again, which is recovery wherever else it
            # happens. The *last* successful read is the answer, because that is
            # the one a caller would act on.
            got, _text, err = read_call(doc, fn.get("name"), args)
            if err:
                errors.append(where + err.replace("\n", " | "))
            else:
                report = got
            continue
        op, op_args = normalize(fn.get("name"), args)
        after, err = apply_op(doc, op, op_args)
        if err:
            # `unknown operation` used to return `malformed` here, aborting the
            # trial. It was the only refusal class treated as terminal, and it
            # disagreed with both the docstring above ("an error is collected
            # and the sequence continues rather than aborting") and with the
            # loop that produced these rows: `run_trial` hands *every* error
            # back as `"Error: " + err` and lets the model try again.
            #
            # The two returns above -- unparseable arguments, arguments not an
            # object -- are properly terminal, and the difference is the reason
            # this one is not. They produce no refusal, so there is nothing for
            # the model to read; this one produces a sentence, hands it over,
            # and gets acted on. Of the 31 recorded tool-arm trials that ever
            # drew it, 22 went on to produce the correct document -- 71%,
            # against B3's 13/13 for tables and S12's 75% for sections. It was
            # the only class denied the credit every other class gets.
            #
            # See FINDINGS F-terminal for what crediting it moved: the
            # composition cost from 4.5 points to 3.2, the table family to
            # 60/60 in all three composed arms, `front_p` to 105/110, and
            # F-framing's `list_i` to 30/30.
            errors.append(where + err.replace("\n", " | "))
            continue
        doc = after

    if task["family"].startswith("table-get"):
        # Past the `doc == before` ladder below, which reads an unchanged
        # document as "nothing happened". For a read an unchanged document is
        # the success condition, and the ladder that applies is in
        # `check_table_read_result`. A string `report` is a refusal; `None` is a
        # trial that never made a read call at all, and those are two different
        # outcomes there.
        return check_result(task, before, doc,
                            report if report is not None
                            else (errors[-1] if errors else None))

    if doc == before:
        if errors:
            return "op_error", errors[-1]
        return "wrong", "op applied but changed nothing"

    outcome, detail = check_result(task, before, doc)
    if outcome == "wrong" and errors:
        # A partial edit the model was *told* about is a loud failure, not a
        # silent one -- the dividing line the taxonomy actually draws. Only
        # `wrong` is re-filed this way: `destructive` and `collateral:*` mean
        # the document lost or gained bytes nobody asked for, and an error
        # message on a later call does not give those back.
        return "op_error", f"{detail}; after: {errors[-1]}"
    return outcome, detail


def replay(args):
    """Re-run only the turn under test, holding everything before it fixed.

    S14's question is what a model does *after* a call that already worked, and
    a full re-run answers it badly: the behaviour appears in about 3.5% of
    trials, so most of the sampling is spent re-deriving first calls that were
    never in question, and the two arms differ in those first calls by chance
    as much as by treatment.

    So the prefix is taken from trials already on disk -- the system prompt,
    the user turn, and the assistant message containing a first call that
    applies cleanly -- and only the tool message varies. Each prefix is
    replayed under every `--shape`, which makes the comparison *paired*: the
    same document, the same first call, the same seed, one string different.

    Two things this buys beyond cost. The `outline` arm is a replication check
    -- it must reproduce the continuation rate the original run measured, or
    the replay is not sampling the state it claims to be. And a prefix whose
    first call failed is excluded rather than graded, because "the model kept
    going after an error" is correct behaviour and pooling it with the
    behaviour under test is what made the effect hard to see in S13.
    """
    tasks = {t["id"]: t for t in json.load(open(args.tasks))["tasks"]}
    src = [json.loads(l) for l in open(args.replay) if l.strip()]
    shapes = [s.strip() for s in args.shapes.split(",")]
    for s in shapes:
        if s not in RESULT_SHAPES:
            print(f"unknown shape {s!r}; valid: {', '.join(RESULT_SHAPES)}")
            return 1

    prefixes = []
    skipped = Counter()
    for tr in src:
        task = tasks.get(tr["task_id"])
        calls = tr.get("tool_calls") or []
        if not task or not calls:
            skipped["no first call"] += 1
            continue
        before = open(os.path.join(ROOT, task["fixture"]), newline="").read()
        fn = calls[0].get("function", {})
        try:
            a = json.loads(fn.get("arguments") or "{}")
            op, op_args = normalize(fn.get("name"), a)
            after, err = apply_op(before, op, op_args)
        except Exception as e:  # noqa: BLE001
            after, err = None, str(e)
        if err:
            skipped["first call errored"] += 1
            continue
        prefixes.append((task, tr, calls[0], before, after))

    print(f"{len(prefixes)} usable prefixes from {len(src)} trials"
          + (f" (skipped: {dict(skipped)})" if skipped else ""))

    done = set()
    if os.path.exists(args.out):
        for line in open(args.out):
            try:
                t = json.loads(line)
                done.add((t["task_id"], t["scheme"], t["trial"]))
            except (json.JSONDecodeError, KeyError):
                continue
    work = [(task, tr, c, b, a, shape)
            for shape in shapes
            for (task, tr, c, b, a) in prefixes
            if (task["id"], f'{tr["scheme"]}:{shape}', tr["trial"]) not in done]
    if not work:
        print("nothing to do")
        return 0
    print(f"{len(work)} replays to run ({len(shapes)} shapes)")

    import time
    started = time.time()
    with open(args.out, "a") as fh:
        for n, (task, tr, first, before, after, shape) in enumerate(work, 1):
            scheme = f'{tr["scheme"]}:{shape}'
            try:
                row = replay_one(args.endpoint, task, tr, first, before, after,
                                 shape, args.turns)
                row.update(task_id=task["id"], scheme=scheme,
                           trial=tr["trial"], shape=shape, error=None)
            except Exception as e:  # noqa: BLE001
                row = {"task_id": task["id"], "scheme": scheme,
                       "trial": tr["trial"], "shape": shape,
                       "error": f"{type(e).__name__}: {e}", "elapsed_s": None}
            fh.write(json.dumps(row) + "\n")
            fh.flush()
            el = time.time() - started
            print(f"[{n:4d}/{len(work)}] {shape:8s} {task['id']:26s} "
                  f"t{tr['trial']:<2d} "
                  f"{'CONTINUED' if row.get('continued') else 'stopped':9s} "
                  f"eta {(el / n) * (len(work) - n) / 60:5.1f}m", flush=True)
    return 0


def replay_one(endpoint, task, tr, first, before, after, shape, max_turns):
    """Sample the turns that follow one already-successful call."""
    payload = build_payload(task, tr["scheme"], tr["trial"])
    payload["messages"].append({"role": "assistant", "content": None,
                                "tool_calls": [first]})
    payload["messages"].append(
        {"role": "tool", "tool_call_id": first.get("id", "0"),
         "content": tool_result(shape, after, task["fixture"], before,
                                family_of(task))})

    doc, calls, tokens, elapsed = after, [first], 0, 0.0
    finish = None
    # `max_turns` counts the whole trial, and one turn is already spent.
    for _ in range(max(1, max_turns - 1)):
        resp, took = call(endpoint, payload)
        row = record(resp, took)
        tokens += row.get("completion_tokens") or 0
        elapsed += row.get("elapsed_s") or 0
        finish = row.get("finish_reason")
        made = row.get("tool_calls") or []
        if not made:
            break
        calls += made
        payload["messages"].append(
            {"role": "assistant", "content": row.get("content"),
             "tool_calls": made})
        for c in made:
            fn = c.get("function", {})
            try:
                a = json.loads(fn.get("arguments") or "{}")
                op, op_args = normalize(fn.get("name"), a)
                nxt, err = apply_op(doc, op, op_args)
            except Exception as e:  # noqa: BLE001
                nxt, err = None, err_text(e)
            result = ("Error: " + err if err
                      else tool_result(shape, nxt, task["fixture"], doc,
                                       family_of(task)))
            if not err:
                doc = nxt
            payload["messages"].append(
                {"role": "tool", "tool_call_id": c.get("id", "0"),
                 "content": result})
    return {
        "model": resp.get("model"),
        "finish_reason": finish,
        "elapsed_s": round(elapsed, 2),
        "completion_tokens": tokens,
        "tool_calls": calls,
        # The primary endpoint, recorded per trial rather than derived later:
        # did the model call again after being told the first call worked?
        "continued": len(calls) > 1,
        "n_extra_calls": len(calls) - 1,
    }


def grade(args, grader=None):
    """Grade a results file. `grader` is the executor-specific ladder.

    Parameterised so Arm C can report through this function rather than keep a
    second copy of it: the report is not a measurement, but a divergence in how
    two arms are *summarised* is exactly the kind of thing that gets mistaken
    for one. `armc.grade_one` is the only other value this takes.
    """
    grader = grader or grade_one
    tasks = {t["id"]: t for t in json.load(open(args.tasks))["tasks"]}
    if not os.path.exists(args.out):
        print(f"no trials at {args.out} -- run the arm without --grade first")
        return 1
    trials = [json.loads(l) for l in open(args.out) if l.strip()]

    by = defaultdict(lambda: defaultdict(Counter))
    totals = defaultdict(Counter)
    cost = defaultdict(lambda: [0, 0, 0])
    details = defaultdict(list)
    distinct = defaultdict(lambda: defaultdict(set))

    graded_path = args.graded
    with open(graded_path, "w") as out:
        for tr in trials:
            task = tasks.get(tr["task_id"])
            if not task:
                continue
            outcome, detail = grader(task, tr)
            s = tr["scheme"]
            by[s][tr["task_id"]][outcome] += 1
            totals[s][outcome] += 1
            c = cost[s]
            c[0] += 1
            c[1] += tr.get("completion_tokens") or 0
            c[2] += tr.get("elapsed_s") or 0
            calls = tr.get("tool_calls") or []
            distinct[s][tr["task_id"]].add(
                calls[0].get("function", {}).get("arguments") if calls else None)
            if outcome != "correct":
                details[(s, tr["task_id"], outcome)].append(detail)
            out.write(json.dumps({"task_id": tr["task_id"], "scheme": s,
                                  "trial": tr["trial"], "outcome": outcome,
                                  "detail": detail}) + "\n")

    for s in sorted(by):
        n = sum(totals[s].values())
        # Out of the denominator, for the reason `grade_one` gives: the request
        # produced no completion, so it is not a trial of anything. Printed
        # first and by count, so it can never be read as a rate.
        gone = totals[s]["transport"]
        n -= gone
        print(f"\n{'='*78}\nSCHEME: {s}   ({n} trials)\n{'='*78}")
        if gone:
            print(f"  {gone} transport failure(s) excluded from every rate below")
        for tid in tasks:
            counts = by[s].get(tid)
            if not counts:
                continue
            summary = "  ".join(f"{k}={v}" for k, v in counts.most_common())
            print(f"{tid:28s} {sum(counts.values()):3d}  {summary}")
        print(f"\n{'-'*78}\nTOTALS ({n} trials)")
        for k, v in totals[s].most_common():
            if k == "transport":
                continue
            print(f"  {k:24s} {v:4d}   {100*v/n:5.1f}%")
        dest = totals[s]["destructive"]
        coll = totals[s]["collateral:formatting"] + totals[s]["collateral:content"]
        wrong = totals[s]["wrong"]  # silent too -- see grade.py and FINDINGS.md B6
        print(f"\n  correct                  {100*totals[s]['correct']/n:5.1f}%")
        print(f"  DATA LOSS                {100*dest/n:5.1f}%")
        print(f"  SILENT CORRUPTION        {100*(coll+dest+wrong)/n:5.1f}%")
        print(f"  loud failure (op_error)  {100*totals[s]['op_error']/n:5.1f}%")
        # Read families only, and printed only when non-zero so every edit
        # arm's report is unchanged. Deliberately *not* added to SILENT
        # CORRUPTION: that line counts bytes the caller did not ask for, and a
        # misreport leaves the file exactly as it found it. It is the same
        # hazard one layer up -- a false answer rather than a false document --
        # and pooling the two would make the percentage mean neither.
        if totals[s]["misreported"]:
            print(f"  FALSE REPORT             {100*totals[s]['misreported']/n:5.1f}%"
                  "   (document intact, answer untrue)")
        if totals[s]["unfiltered"]:
            print(f"  unnarrowed read          {100*totals[s]['unfiltered']/n:5.1f}%"
                  "   (right table, no filter applied)")
        # Arm C only, and printed only when non-zero so Arm B's report is
        # unchanged. `usage_error` is a wrong or missing `path` -- inert in this
        # arm, because the document was never on disk. `escaped` is a path
        # outside the sandbox, which should be structurally impossible.
        if totals[s]["usage_error"]:
            print(f"  loud failure (usage)     {100*totals[s]['usage_error']/n:5.1f}%")
        if totals[s]["escaped"]:
            print(f"  !! SANDBOX ESCAPES       {totals[s]['escaped']}")
        t, tok, sec = cost[s]
        print(f"  mean completion tokens   {tok/t:.0f}")
        print(f"  mean wall-clock          {sec/t:.1f}s")
        uniq = [len(distinct[s][tid]) for tid in by[s]]
        print(f"  distinct outputs/task    {min(uniq)}-{max(uniq)}")

    if details:
        print(f"\n{'='*78}\nFAILURE DETAIL (first example each)\n{'='*78}")
        for (s, tid, outcome), msgs in sorted(details.items()):
            print(f"\n[{s}] {tid} -> {outcome}  (n={len(msgs)})")
            print(f"  {msgs[0][:300]}")

    print(f"\nwrote {graded_path}")
    return 0


def retry(args):
    """Measure whether an `op_error` is actually recoverable in one turn.

    The safety case for content-addressed ops (FINDINGS.md B3) is that their
    failures are *loud*: incise refuses, the document is untouched, and the
    model gets an error it can act on. "Can act on" is an empirical claim about
    the error text, not a property of refusing, so it is measured here rather
    than asserted: replay each failed trial with the tool result appended and
    see whether the second call lands.

    Cheap by construction -- only trials that actually failed are replayed.
    """
    tasks = {t["id"]: t for t in json.load(open(args.tasks))["tasks"]}
    trials = [json.loads(l) for l in open(args.out) if l.strip()]
    graded = {
        (g["task_id"], g["scheme"], g["trial"]): g
        for g in (json.loads(l) for l in open(
            args.graded))
    }

    out_path = args.retry_out
    results = Counter()
    with open(out_path, "w") as fh:
        for tr in trials:
            key = (tr["task_id"], tr["scheme"], tr["trial"])
            g = graded.get(key)
            if not g or g["outcome"] != "op_error":
                continue
            task = tasks[tr["task_id"]]
            payload = build_payload(task, tr["scheme"], tr["trial"])
            call_obj = (tr.get("tool_calls") or [])[0]
            payload["messages"] += [
                {"role": "assistant", "content": None, "tool_calls": tr["tool_calls"]},
                {
                    "role": "tool",
                    "tool_call_id": call_obj.get("id", "0"),
                    "content": "Error: " + g["detail"].replace(" | ", "\n"),
                },
            ]
            try:
                resp, elapsed = call(args.endpoint, payload)
                row = record(resp, elapsed)
                outcome, detail = grade_one(task, row)
            except Exception as e:  # noqa: BLE001
                row, outcome, detail = {}, "malformed", f"{type(e).__name__}: {e}"
            results[outcome] += 1
            calls = row.get("tool_calls") or []
            fh.write(json.dumps({
                "task_id": tr["task_id"], "scheme": tr["scheme"], "trial": tr["trial"],
                "outcome": outcome, "detail": detail,
                "arguments": calls[0]["function"]["arguments"] if calls else None,
            }) + "\n")
            print(f"{tr['task_id']:26s} {tr['scheme']} t{tr['trial']:<2d} -> {outcome}")

    n = sum(results.values())
    if not n:
        print("no op_error trials to retry")
        return 0
    print(f"\n{'-'*60}\nRETRY AFTER ONE ERROR TURN ({n} trials)")
    for k, v in results.most_common():
        print(f"  {k:24s} {v:4d}   {100*v/n:5.1f}%")
    print(f"\n  recovered                {100*results['correct']/n:5.1f}%")
    print(f"\nwrote {out_path}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", default="http://127.0.0.1:8081/v1/chat/completions")
    ap.add_argument("--tasks", default=os.path.join(ROOT, "bench/tasks/tables.json"))
    ap.add_argument("--out", default=os.path.join(ROOT, "bench/results/armb.jsonl"))
    ap.add_argument("--graded", default=os.path.join(ROOT, "bench/results/armb_graded.jsonl"))
    ap.add_argument("--retry-out", default=os.path.join(ROOT, "bench/results/armb_retry.jsonl"))
    ap.add_argument("--trials", type=int, default=10)
    ap.add_argument("--turns", type=int, default=1,
                    help="max assistant turns per trial; 1 is the pre-S6 behaviour")
    ap.add_argument("--scheme", default="scheme_a", choices=list(SCHEMES))
    # S14: `delta` is the shipping behaviour and the default from here on.
    # Every arm through S13 ran at `outline`; pass it explicitly to reproduce
    # them, and expect a lower redundant-continuation rate at the default.
    ap.add_argument("--result-shape", default="delta", choices=RESULT_SHAPES,
                    help="what a successful call sends back; `delta` says what "
                         "changed, `outline` echoes the document (pre-S14) (S14)")
    ap.add_argument("--replay", metavar="RESULTS",
                    help="re-sample the turns after each successful first call "
                         "in RESULTS, once per --shapes (S14)")
    ap.add_argument("--shapes", default=",".join(RESULT_SHAPES),
                    help="comma-separated result shapes to replay")
    ap.add_argument("--grade", action="store_true")
    ap.add_argument("--retry", action="store_true")
    ap.add_argument("--show-prompt", action="store_true")
    ap.add_argument("--check-action", action="store_true",
                    help="divergence C: answer a missing or malformed `action` "
                         "in the front end, naming the argument and only the "
                         "calling tool's own op names, instead of letting the "
                         "core answer `unknown operation \"list-None\"` with "
                         "all fifteen. Off by default -- `regrade_snapshot.py` "
                         "replays through `normalize`.")
    args = ap.parse_args()

    if args.check_action:
        global CHECK_ACTION
        CHECK_ACTION = True

    if args.show_prompt:
        tasks = json.load(open(args.tasks))["tasks"]
        for t in tasks:
            p = build_payload(t, args.scheme, 0)
            print(f"\n{'='*78}\n{t['id']}\n{'='*78}")
            print(p["messages"][1]["content"])
        return 0
    if args.grade:
        return grade(args)
    if args.retry:
        return retry(args)
    if args.replay:
        return replay(args)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
