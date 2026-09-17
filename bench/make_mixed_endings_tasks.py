#!/usr/bin/env python3
"""Generate bench/tasks/sections_mixed_endings.json, goldens included.

Three section tasks on a section whose body mixes CRLF and LF, built for
F-remedy's second unperformable remedy -- *"this section mixes CRLF and LF line
endings, so there is no convention to match. Normalize the section's line
endings first, then retry."* `headroom.py` priced that branch UNTESTED at k = 0
because no fixture reached it. `bench/synthetic/mixed-endings-section.md` is the
fixture, and this is the task set.

**The remedy turns out to be performable, and that is why these tasks have a
golden at all.** No single op normalizes line endings -- `section-append`,
`section-replace-body` and `section-insert` all call `_section_eol` and all
refuse -- but `section-delete` does not, and a section deleted and re-inserted
comes back written in one convention. So the correct document is reachable in
two calls, and the price is that the model must retype the body it deleted. The
refusal does not say any of that, which is the open question this set exists to
put a number on rather than to settle by argument.

The goldens are therefore generated the way `make_section_tasks.py` generates
its own, by running the reference implementation and trimming the common prefix
and suffix, and this module borrows `_window` from it rather than keeping a
second copy of that arithmetic. Every hand-written expectation is asserted
against the reference before it is written out: a task whose expectation is
wrong fails to generate rather than quietly redefining correct.

  python3 bench/make_mixed_endings_tasks.py > bench/tasks/sections_mixed_endings.json
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bench"))

from incise_ops import apply_op, section_outline  # noqa: E402
from make_section_tasks import _window  # noqa: E402

M = "bench/synthetic/mixed-endings-section.md"

BODY = ("This paragraph opens with CRLF lines, as does the heading above it.\n"
        "This line ends LF, and it is the only thing that makes the section "
        "mixed.\n"
        "The paragraph then goes back to CRLF and stays there.")

# (id, family, instruction, calls, section_delta, paths_present, paths_absent,
#  note)
SPECS = [
    (
        "append-mixed-body", "section-append",
        'Add the line "A new line." to the end of the "Mixed body" section.',
        [
            {"op": "section-delete", "args": {"section": "Mixed body"}},
            {"op": "section-insert", "args": {
                "section": "CRLF body",
                "position": "before",
                "heading": "Mixed body",
                "body": BODY + "\n\nA new line.",
            }},
        ],
        0,
        ["Mixed endings inside one section > Mixed body"],
        [],
        "The provoking task. `section-append` is refused because the section's "
        "span holds one LF line among CRLF ones, and the refusal's only named "
        "remedy is a document change it does not say how to make. The two "
        "calls here are that remedy, performed: delete the section, re-insert "
        "it against an anchor whose endings are uniform, and the body comes "
        "back CRLF throughout with the new line on the end. A model that "
        "reads the refusal and stops grades `op_error`, which is the loud "
        "failure and the outcome most trials should be expected to reach. A "
        "model that finds this route grades `correct` and has falsified the "
        "word `unperformable` in F-remedy's title for this half of the "
        "finding.",
    ),
    (
        "replace-mixed-body", "section-replace-body",
        'Replace the body of the "Mixed body" section with the single line '
        '"Superseded; see CRLF body."',
        [
            {"op": "section-delete", "args": {"section": "Mixed body"}},
            {"op": "section-insert", "args": {
                "section": "CRLF body",
                "position": "before",
                "heading": "Mixed body",
                "body": "Superseded; see CRLF body.",
            }},
        ],
        0,
        ["Mixed endings inside one section > Mixed body"],
        [],
        "The same refusal on the other body-writing op, and the easier half of "
        "the recovery: the instruction supplies the replacement text, so the "
        "delete-and-re-insert route costs nothing but the two calls. The task "
        "above has to retype three lines it was never given. If the pair "
        "separates, the cost of the remedy is the retyping and not the "
        "discovery.",
    ),
    (
        "append-crlf-control", "section-append",
        'Add the line "A new line." to the end of the "CRLF body" section.',
        [
            {"op": "section-append", "args": {
                "section": "CRLF body",
                "text": "A new line.",
            }},
        ],
        0,
        ["Mixed endings inside one section > CRLF body"],
        [],
        "The control, in the same file and with the same instruction one "
        "section over. Every line of this section ends CRLF, so there is a "
        "convention to match, `section-append` applies in one call, and the "
        "line it writes ends CRLF too. Without it a drop on the two tasks "
        "above could be a model that mishandles an unfamiliar fixture rather "
        "than one that mishandles this refusal.",
    ),
]


def build():
    tasks = []
    path = os.path.join(ROOT, M)
    for (tid, family, instruction, calls, delta, present, absent,
         note) in SPECS:
        before = open(path, newline="").read()
        after = before
        for i, c in enumerate(calls):
            after, err = apply_op(after, c["op"], c["args"])
            if err:
                raise SystemExit(
                    f"{tid}: reference implementation refused call {i + 1}: "
                    f"{err}")
        if after == before:
            raise SystemExit(f"{tid}: reference implementation changed nothing")

        paths_before = [e["path"] for e in section_outline(before)]
        paths_after = [e["path"] for e in section_outline(after)]
        got = len(paths_after) - len(paths_before)
        if got != delta:
            raise SystemExit(
                f"{tid}: expected section delta {delta:+d}, reference gives "
                f"{got:+d}")
        for p in present:
            if p not in paths_after:
                raise SystemExit(f"{tid}: expected path {p!r} in the result; "
                                 f"reference produced {paths_after}")
        for p in absent:
            if p in paths_after:
                raise SystemExit(f"{tid}: path {p!r} should be gone, it is not")

        # The golden reassembles byte for byte, `\r` included. That assertion
        # is doing more here than it does in `make_section_tasks.py`: these
        # documents differ from each other in line *endings* as well as in
        # content, so a window computed on lines that had been stripped of
        # their `\r` would reassemble into a document that looks right and is
        # not the one the reference produced.
        pre, suf, lines = _window(before, after)
        b = before.split("\n")
        rebuilt = "\n".join(b[:pre] + lines + b[len(b) - suf:])
        assert rebuilt == after, f"{tid}: window does not reassemble"

        tasks.append({
            "id": tid,
            "family": family,
            "fixture": M,
            "instruction": instruction,
            "golden": {
                "first_changed": pre,
                "unchanged_tail": suf,
                "lines": lines,
            },
            "expect": {
                "section_delta": delta,
                "paths_present": present,
                "paths_absent": absent,
            },
            "ideal_calls": calls,
            "note": note,
        })
    return {
        "_comment": (
            "Three section tasks on a section that mixes CRLF and LF, built "
            "for F-remedy's line-endings refusal, which headroom.py priced "
            "UNTESTED at k = 0 for want of a fixture. Its own file rather "
            "than appended to sections.json, for the reason that file's "
            "siblings state: every recorded section pool was run over those "
            "fifteen tasks, and appending would change n and break "
            "comparability with every rate already published. Generated and "
            "regenerable by bench/make_mixed_endings_tasks.py, which explains "
            "why the two provoking tasks have a reachable golden at all -- "
            "the remedy the refusal names is performable, in two calls, by "
            "deleting the section and re-inserting it, and the price is "
            "retyping the body. The third task is the control: the same "
            "instruction on the section next door, whose endings are uniform."
        ),
        "tasks": tasks,
    }


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
