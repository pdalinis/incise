#!/usr/bin/env python3
"""Generate bench/tasks/lists.json, goldens included.

The table family graded without goldens: its correctness conditions ("this row
is present", "widths are uniform") are expressible as predicates. The list
family is not like that. Its whole content is formatting -- marker character,
marker delimiter, indent width, blank-line convention, and the number on each
ordered item -- and a predicate for "numbered the way this particular list is
numbered" is just the golden written less legibly.

So the goldens are exact, scoped to the target list's own lines, and produced
here by the reference implementation. That makes Arm B's ceiling 100% by
construction, which is only honest if two things are true, and both are:

  1. Every golden below was read line by line against the fixture before being
     committed. They are in `bench/tasks/lists.json` in full, so a reader can
     check them without running anything.
  2. `test_incise_ops.py` asserts the reference still produces them, so a
     regression in the executor shows up as a test failure rather than as a
     silently re-baselined benchmark.

Arm A is graded against the same goldens, which is the point: both arms are
judged by one definition of correct.

  python3 bench/make_list_tasks.py > bench/tasks/lists.json
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bench"))

from incise_ops import apply_op  # noqa: E402
from mdlist import find_lists  # noqa: E402

N = "corpus/lists/nested-mixed.md"
O = "corpus/lists/ordered-numbering.md"
T = "corpus/lists/tasks.md"

# (id, family, fixture, instruction, target_list, ideal_op, ideal_args,
#  expect_item_delta, require_lines_present, require_texts_absent, note)
SPECS = [
    (
        "add-item-tight-dash", "list-add-item", N,
        'At the end of the list under "Dash markers, two-space indent", add an '
        'item that says "fourth".',
        0,
        "list-add-item",
        {"list": {"heading": "Dash markers, two-space indent"}, "text": "fourth"},
        1, ["- fourth"], [],
        "The list ends with a nested item three levels deep. `at the end` means "
        "after the last TOP-LEVEL item, so the new item takes the outer indent "
        "and not the indent of the line physically above it.",
    ),
    (
        "add-item-nested-asterisk", "list-add-item", N,
        'Under "Asterisk markers, four-space indent", add "beta-three" '
        'immediately after "beta-two".',
        1,
        "list-add-item",
        {"list": {"heading": "Asterisk markers, four-space indent"},
         "text": "beta-three", "after": "beta-two"},
        1, ["    * beta-three"], [],
        "Two conventions at once: the `*` marker and a four-space indent, both "
        "read off the sibling. A house-style editor writes `- ` at two spaces.",
    ),
    (
        "add-item-loose", "list-add-item", N,
        'Add an item "loose four" at the end of the list under "Loose vs tight" '
        "whose items have blank lines between them.",
        7,
        "list-add-item",
        {"list": {"heading": "Loose vs tight", "ordinal": 1}, "text": "loose four"},
        1, ["- loose four"], [],
        "Loose list: the inserted item must be preceded by a blank line or the "
        "list silently becomes tight and every item's rendering changes. Also "
        "requires picking ordinal 1 of the two lists under this heading.",
    ),
    (
        "add-item-ordered-renumber", "list-add-item", O,
        'In the list under "Sequential", insert an item "two and a half" '
        'between "second" and "third".',
        0,
        "list-add-item",
        {"list": {"heading": "Sequential"}, "text": "two and a half",
         "after": "second"},
        1, ["3. two and a half"], [],
        "The re-pad analogue: inserting mid-list forces every following item to "
        "be renumbered. 0/10 direct in the table family was exactly this shape.",
    ),
    (
        "add-item-ordered-all-ones", "list-add-item", O,
        'Add an item "fourth" at the end of the list under "All ones".',
        1,
        "list-add-item",
        {"list": {"heading": "All ones"}, "text": "fourth"},
        1, ["1. fourth"], [],
        "The inverse trap. `1. 1. 1.` is legal CommonMark and renumbering it is "
        "the bug. A rule that always renumbers fails here; a rule that never "
        "renumbers fails the task above.",
    ),
    (
        "add-item-paren-delimiter", "list-add-item", O,
        'Add an item "fourth" at the end of the list under "Paren delimiter".',
        2,
        "list-add-item",
        {"list": {"heading": "Paren delimiter"}, "text": "fourth"},
        1, ["4) fourth"], [],
        "The delimiter is part of the marker. `4.` is a different list.",
    ),
    (
        "add-item-mixed-markers", "list-add-item", N,
        'Under "Mixed markers at the same level", add an item "second star '
        'item" to the list that contains the star item.',
        4,
        "list-add-item",
        {"list": {"heading": "Mixed markers at the same level", "ordinal": 1},
         "text": "second star item"},
        1, ["* second star item"], [],
        "Three single-item lists under one heading, distinguishable only by "
        "marker. The list counterpart of update-cell-multi-table: the other two "
        "lists must be byte-identical.",
    ),
    (
        "remove-item-non-sequential", "list-remove-item", O,
        'Remove the "third" item from the list under "Non-sequential".',
        4,
        "list-remove-item",
        {"list": {"heading": "Non-sequential"}, "item": "third"},
        -1, [], ["third"],
        "Numbers are already 1, 3, 7. Renumbering the survivors to 1, 2 is a "
        "behaviour change nobody asked for, so the correct answer leaves "
        "`7. seventh` alone.",
    ),
    (
        "check-task-nested", "list-set-checked", T,
        'Mark the "child pending" task as done, in the list under "Nested".',
        1,
        "list-set-checked",
        {"list": {"heading": "Nested"}, "item": "child pending", "checked": True},
        0, ["  - [x] child pending"], [],
        "Two-space indent must survive, and the `[X]` capital elsewhere in the "
        "file must not be normalized. Only one line may change.",
    ),
    (
        "remove-item-mixed", "list-remove-item", T,
        'In the list under "Mixed with plain items", remove the item "not a '
        'task, just an item".',
        2,
        "list-remove-item",
        {"list": {"heading": "Mixed with plain items"},
         "item": "not a task, just an item"},
        -1, [], ["not a task, just an item"],
        "The list mixes task items and plain items. Removing the plain one must "
        "not disturb the checkboxes on either side.",
    ),
]


def build():
    tasks = []
    for (tid, family, fixture, instruction, target, op, args, delta,
         present, absent, note) in SPECS:
        before = open(os.path.join(ROOT, fixture)).read()
        after, err = apply_op(before, op, args)
        if err:
            raise SystemExit(f"{tid}: reference implementation refused: {err}")
        lst = find_lists(before)[target]
        b, a = before.split("\n"), after.split("\n")
        shift = len(a) - len(b)
        golden = a[lst.start: lst.end + 1 + shift]
        # The scoped golden is only meaningful if the edit really was scoped.
        assert a[: lst.start] == b[: lst.start], f"{tid}: text before the list changed"
        assert a[lst.end + 1 + shift:] == b[lst.end + 1:], \
            f"{tid}: text after the list changed"
        tasks.append({
            "id": tid,
            "family": family,
            "fixture": fixture,
            "instruction": instruction,
            "target_list": target,
            "expect_item_delta": delta,
            "require_lines_present": present,
            "require_texts_absent": absent,
            "golden": golden,
            "ideal_call": {"op": op, "args": args},
            "note": note,
        })
    return {
        "_comment": (
            "Ten list tasks, graded against goldens scoped to the target list. "
            "Generated and regenerable by bench/make_list_tasks.py, which "
            "explains why this family uses goldens where the table family did "
            "not. Instructions are phrased as a user would phrase them and "
            "avoid incise's op vocabulary."
        ),
        "tasks": tasks,
    }


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
