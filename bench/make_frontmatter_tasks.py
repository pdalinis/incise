#!/usr/bin/env python3
"""Generate bench/tasks/frontmatter.json, goldens included.

`make_section_tasks.py`'s mechanism, unchanged: the golden is the **minimal
changed window**, and grading reassembles

    before[:first_changed] + golden_lines + before[len - unchanged_tail:]

and demands byte-equality. That choice is not a preference here, it is the only
form that can express what this family is for. `corpus/frontmatter/rich.md:37-43`
requires key order, a leading comment, an inline comment on a sibling, two block
scalar styles and one quoted key to be byte-identical after a single set. A
scoped golden -- "the block looks like this" -- would restate the block and
therefore restate whatever the generator's own serializer did to it, which is
exactly the failure the fixture exists to catch. Pinning every byte outside a
one-line window says the same thing without anyone having to write the block out
twice.

The two honesty conditions carry over unchanged:

  1. Every task's `key_delta` / `keys_present` / `keys_absent` / `state` are
     written by hand against the fixture, and `build()` asserts the reference
     implementation agrees. They are not read back off the output. A task whose
     hand-written expectation is wrong fails to generate rather than quietly
     redefining correct.
  2. `test_incise_ops.py` asserts the reference still reproduces every golden,
     so an executor regression is a test failure, not a re-baselined benchmark.

**What the instructions may not say.** The section family's rule is that an
instruction never names a heading level, because deriving it is the thing under
test. The equivalent here is that an instruction never writes a key as a dotted
path. `build.jobs` in an instruction hands over the answer to the one question
Arm B is asking -- whether a model reaches a nested key by path at all, or sends
`jobs` and gets a refusal. So instructions name keys the way a person would:
"the number of parallel jobs the build uses". The paths are all in the injected
summary, which is where the model is supposed to find them.

  python3 bench/make_frontmatter_tasks.py > bench/tasks/frontmatter.json
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bench"))

import mdfront  # noqa: E402
from incise_ops import apply_op  # noqa: E402

R = "corpus/frontmatter/rich.md"
E = "corpus/frontmatter/empty.md"
A = "corpus/frontmatter/absent.md"

# (id, family, fixture, instruction, op, args, key_delta, state,
#  keys_present, keys_absent, note)
#
# `keys_present` maps a path to the value text expected on its line -- "" for a
# key set to null, and the value *as written*, so a task cannot assert a
# quoting the executor does not produce.
SPECS = [
    (
        "set-build-jobs", "frontmatter-set", R,
        "The build should run with 8 parallel jobs instead of 4.",
        "frontmatter-set", {"key": "build.jobs", "value": 8},
        0, "present", {"build.jobs": "8"}, [],
        "`corpus/frontmatter/rich.md:37` names this exact edit as the file's "
        "reason for existing, so it is the family's first task. Two ways to "
        "get it wrong and they fail differently. `jobs` alone is a refusal -- "
        "loud, costs a turn -- and it is the failure worth measuring, because "
        "nothing in the instruction says the key is nested and the only place "
        "that is written down is the injected summary. Rewriting the block "
        "with a YAML library is the quiet one: it produces `jobs: 8` in a "
        "document that has lost the leading comment, the inline comment on "
        "`build.target`, and the quoting of `quoted_key`, and the whole-"
        "document golden is what makes that visible rather than merely true.",
    ),
    (
        "set-build-target", "frontmatter-set", R,
        "Switch the build from a release build to a debug one.",
        "frontmatter-set", {"key": "build.target", "value": "debug"},
        0, "present", {"build.target": "debug"}, [],
        "The sibling edit `rich.md:38` asks about: `target` carries an inline "
        "comment eight spaces out, and the golden pins the comment, the "
        "padding and the column. An edit that rewrites the line from parsed "
        "pieces keeps the value and loses the sentence next to it, which is a "
        "loss no key-level check can see.",
    ),
    (
        "set-dana-role", "frontmatter-set", R,
        "Dana has taken over as a maintainer. Update her entry in the authors "
        "list to say so.",
        "frontmatter-set", {"key": "authors[1].role", "value": "maintainer"},
        0, "present", {"authors[1].role": "maintainer"}, [],
        "The only task that needs an index, and `rich.md:50` names index "
        "addressing as one of the file's cases. Two failures: not finding the "
        "bracket syntax at all, and finding it but editing `authors[0]`, who "
        "is already the maintainer -- so an off-by-one here produces a "
        "document with two maintainers and no contributor, and Peter's role "
        "silently changes. The instruction says `Dana` and never says 1; the "
        "mapping from the name to the index is only in the document.\n\n"
        "That last sentence is the whole task, and F-frontmatter found out the "
        "hard way what it costs: `render_frontmatter` omits scalar values by "
        "design, so a scheme offering only `frontmatter_edit` gives the model "
        "`authors[0].name` and `authors[1].name` and no way whatever to learn "
        "which is Dana. The two arms guessed 3/10 and 7/10 in mirror image and "
        "that one task was the difference between p = 0.0156 and p = 0.25 for "
        "the whole arm. The task is **not** reworded -- it is the correct "
        "task, and it was the schemes that were incomplete. It is the "
        "discriminating task for `front_r`, which publishes the read op the "
        "family has had since it was built.",
    ),
    (
        "add-build-cache", "frontmatter-set", R,
        "Turn on caching for the build.",
        "frontmatter-set", {"key": "build.cache", "value": True},
        1, "present", {"build.cache": "true"}, [],
        "A key that does not exist yet, under a parent that does. The new line "
        "has to land inside `build` at its siblings' indent and above "
        "`authors`; appending it at the top level gives a document where "
        "`cache` is a peer of `build` and the build does not see it. The "
        "indent is not in the instruction and not in the schema -- it is read "
        "off the siblings, which is `bench/synthetic/front-shapes.md`'s "
        "four-space section asking the same question of the executor.",
    ),
    (
        "clear-title", "frontmatter-set", R,
        "Blank out the title, but leave the key itself in the frontmatter.",
        "frontmatter-set", {"key": "title", "value": None},
        0, "present", {"title": ""}, [],
        "`rich.md:52` says null is distinct from absent and from the empty "
        "string, and this is the task that makes the distinction cost "
        "something. Deleting the key is the obvious wrong answer and the "
        "instruction rules it out in as many words. Writing `title: \"\"` is "
        "the subtle one: it renders the same in most tooling and is a "
        "different value, which is why the golden compares bytes.",
    ),
    (
        "delete-draft", "frontmatter-delete", R,
        "This file is no longer a draft. Take the draft flag out of the "
        "frontmatter completely.",
        "frontmatter-delete", {"key": "draft"},
        -1, "present", {}, ["draft"],
        "Half of the family's verb pair. The instruction says the flag should "
        "be gone, not false, and `draft: false` is a document that still "
        "carries a draft flag. Paired with `set-draft-true` below, which asks "
        "for the opposite on the same key in the same file -- one task cannot "
        "tell a verb confusion from a coin flip, which is FINDINGS caveat 6.",
    ),
    (
        "delete-build", "frontmatter-delete", R,
        "Drop the whole build configuration from the frontmatter.",
        "frontmatter-delete", {"key": "build"},
        -6, "present", {}, ["build", "build.target", "build.jobs",
                           "build.features"],
        "One delete of a container, not three deletes of its leaves. Removing "
        "`target`, `features` and `jobs` one at a time leaves `build:` behind "
        "as a key with nothing under it, which is a different document and a "
        "different meaning. Six entries go, because the two items under "
        "`features` go with it -- the delta is what catches a delete that "
        "took the key and orphaned its children, the failure "
        "`bench/synthetic/front-shapes.md` exists to make reachable.",
    ),
    (
        "set-draft-true", "frontmatter-set", R,
        "This file has gone back to being a draft. Say so in the frontmatter.",
        "frontmatter-set", {"key": "draft", "value": True},
        0, "present", {"draft": "true"}, [],
        "The other half of the verb pair: the same `draft` key as "
        "`delete-draft`, in the same file, wanted the other way. One task "
        "cannot tell a verb confusion from a coin flip, which is FINDINGS "
        "caveat 6, and the two directions are what make a preference for "
        "`delete` visible as a preference. The key currently holds `false`, so "
        "an edit that merely reasserts the current state is not available "
        "here -- a wrong verb produces a document with no draft flag at all.",
    ),
    (
        "release-bump", "frontmatter-set", R,
        "Update the version to 0.5.0, and set `released` to 2026-09-12.",
        "frontmatter-set",
        [{"op": "frontmatter-set", "args": {"key": "version", "value": "0.5.0"}},
         {"op": "frontmatter-set", "args": {"key": "released",
                                            "value": "2026-09-12"}}],
        1, "present", {"version": "0.5.0", "released": "2026-09-12"}, [],
        "Two calls, one changing a key and one adding a top-level key that has "
        "no obvious neighbour. Both values are quoted in the instruction and "
        "must be written bare: `0.5.0` is not a number, and a serializer that "
        "decides quoting from the JSON type the value arrived as writes "
        "`\"0.5.0\"`, which is a different value to every tool that reads it. "
        "The date is the same trap with a different shape -- YAML would read it "
        "as a date either way, and quoting it changes that.\n\n"
        "This task has been wrong twice, in two different ways, and both are "
        "kept here because the failures are more instructive than the task.\n\n"
        "It opened `Cut version 0.5.0, ...`, and measured the verb rather than "
        "the edit: 10/10 trials in *both* F-frontmatter arms read that as "
        "`action=delete` on `version` -- a release-engineering idiom colliding "
        "with an `action` enum -- and destroyed the key. That is the clearest "
        "evidence in the project that an instruction verb colliding with a "
        "destructive action name is a data-loss route no argument-level guard "
        "can see, since every argument in that call is well-formed. `Update` "
        "removed it: 20 destroyed documents became 0.\n\n"
        "What that was masking was a wrong *expectation*. The instruction said "
        "`record 2026-09-12 as the release date` and this note used to say the "
        "key it becomes is the model's choice -- while `keys_present` demanded "
        "`released` and the golden pinned its line. Both cannot be true, and "
        "the expectation is the half with teeth: all 30 trials across the three "
        "F-frontread schemes made both calls, wrote both values bare, and chose "
        "`release_date`, so the task scored 0/30 for obeying an instruction that "
        "never named a key. Naming it is the fix, and it is chosen over "
        "loosening the expectation because the whole-document golden is this "
        "family's entire point -- a task that accepts two different documents "
        "cannot pin the bytes `rich.md:37-43` exists to protect.",
    ),
    (
        "create-on-absent", "frontmatter-set", A,
        'Give this file a frontmatter block with a title of "Absent '
        'frontmatter".',
        "frontmatter-set", {"key": "title", "value": "Absent frontmatter"},
        1, "present", {"title": "Absent frontmatter"}, [],
        "The one task where the block does not exist yet, and the only one "
        "where the edit inserts above every byte of the document. The summary "
        "the model is given says the file has no frontmatter, so this measures "
        "whether it reads that as 'nothing to edit' and refuses -- which is "
        "the failure to watch for, since every other family's tools can only "
        "change what is already there. `corpus/frontmatter/absent.md:5` names "
        "the blank line between the new block and `# No frontmatter` as part "
        "of what must be right, and the whole-document golden pins it.",
    ),
    (
        "fill-empty", "frontmatter-set", E,
        "Mark this file as a draft by adding a draft flag set to true.",
        "frontmatter-set", {"key": "draft", "value": True},
        1, "present", {"draft": "true"}, [],
        "The state `create-on-absent` is not: delimiters present, no keys. "
        "`corpus/frontmatter/empty.md:9-11` requires the key to fill the "
        "existing block rather than open a second one above it, and a second "
        "`---` block would leave the file's real frontmatter being the new one "
        "and the old pair being a thematic break and a heading. Together with "
        "`create-on-absent` this is the pair that makes absent and empty "
        "different states rather than two spellings of falsy.",
    ),
]


def _window(before, after):
    """The minimal changed line window: (first_changed, unchanged_tail, lines).

    Identical to `make_section_tasks._window`, deliberately: the two families
    share a grader rung and a task shape, and two copies of this that drifted
    would put the same golden in two different places.
    """
    b, a = before.split("\n"), after.split("\n")
    pre = 0
    while pre < min(len(b), len(a)) and b[pre] == a[pre]:
        pre += 1
    suf = 0
    while suf < min(len(b), len(a)) - pre and b[-1 - suf] == a[-1 - suf]:
        suf += 1
    return pre, suf, a[pre: len(a) - suf]


def _state(content):
    fm = mdfront.find_frontmatter(content)
    if not fm.present:
        return "absent"
    return "empty" if not fm.entries else "present"


def build():
    tasks = []
    for (tid, family, fixture, instruction, op, args, delta, state,
         present, absent, note) in SPECS:
        path = os.path.join(ROOT, fixture)
        before = open(path, newline="").read()
        calls = args if isinstance(args, list) else [{"op": op, "args": args}]
        after = before
        for i, c in enumerate(calls):
            after, err = apply_op(after, c["op"], c["args"])
            if err:
                raise SystemExit(
                    f"{tid}: reference implementation refused call {i + 1}: {err}")
        if after == before:
            raise SystemExit(f"{tid}: reference implementation changed nothing")

        # The hand-written expectations are checked here, against the reference,
        # rather than read off it. A wrong expectation stops the build.
        fm_after = mdfront.find_frontmatter(after)
        by = {mdfront.format_path(e.path): e for e in fm_after.entries}
        got = len(fm_after.entries) - len(
            mdfront.find_frontmatter(before).entries)
        if got != delta:
            raise SystemExit(
                f"{tid}: expected key delta {delta:+d}, reference gives {got:+d}")
        if _state(after) != state:
            raise SystemExit(
                f"{tid}: expected state {state!r}, reference gives "
                f"{_state(after)!r}")
        for k, v in present.items():
            if k not in by:
                raise SystemExit(f"{tid}: expected key {k!r} in the result; "
                                 f"reference produced {sorted(by)}")
            if by[k].value != v:
                raise SystemExit(f"{tid}: expected {k!r} to hold {v!r}, "
                                 f"reference wrote {by[k].value!r}")
        for k in absent:
            if k in by:
                raise SystemExit(f"{tid}: key {k!r} should be gone, it is not")
        # Nothing outside the block may move. Every task here edits frontmatter
        # and only frontmatter, so this is an assertion about the *task*, not
        # about the model: a spec whose ideal calls disturb the body is a spec
        # that cannot be graded by a frontmatter-shaped expectation.
        b_body = before.split("\n")[
            mdfront.find_frontmatter(before).end + 1:]
        a_body = after.split("\n")[fm_after.end + 1:]
        if _state(before) != "absent" and b_body != a_body:
            raise SystemExit(f"{tid}: ideal calls changed the document body")

        pre, suf, lines = _window(before, after)
        b = before.split("\n")
        rebuilt = "\n".join(b[:pre] + lines + b[len(b) - suf:])
        assert rebuilt == after, f"{tid}: window does not reassemble"

        tasks.append({
            "id": tid,
            "family": family,
            "fixture": fixture,
            "instruction": instruction,
            "golden": {
                "first_changed": pre,
                "unchanged_tail": suf,
                "lines": lines,
            },
            "expect": {
                "key_delta": delta,
                "state": state,
                "keys_present": present,
                "keys_absent": absent,
            },
            "ideal_calls": calls,
            "note": note,
        })
    return {
        "_comment": (
            "Eleven frontmatter tasks, graded against whole-document goldens "
            "stored as a minimal changed window: rebuild with "
            "before[:first_changed] + lines + before[len - unchanged_tail:] "
            "and compare bytes. Generated and regenerable by "
            "bench/make_frontmatter_tasks.py, which explains why this family "
            "pins the whole document. Instructions are phrased as a user would "
            "phrase them and never write a key as a dotted path -- reaching a "
            "nested key by path is the thing under test, and the paths are in "
            "the injected summary."
        ),
        "tasks": tasks,
    }


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
