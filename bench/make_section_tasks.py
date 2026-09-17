#!/usr/bin/env python3
"""Generate bench/tasks/sections.json, goldens included.

Same honesty conditions as `make_list_tasks.py`, one different mechanism.

The list family scoped each golden to the target list's own lines, because a
list edit cannot reach past the list. A section edit can and routinely does:
`section-delete` on `Install` in `deep-nesting.md` removes thirty-two lines and
six subsections, and `section-set-level` rewrites every heading in a subtree. A
scoped golden would have to be scoped to most of the file, which is not a scope.

So the golden here is the **minimal changed window**: the common prefix and
common suffix are trimmed off and only the lines that actually differ are
stored, together with how many lines of each were trimmed. Grading reassembles

    before[:first_changed] + golden_lines + before[len - unchanged_tail:]

and demands byte-equality with the model's output. That is whole-document
exactness -- strictly stronger than the list family's scoped golden, since
nothing outside the window is merely unchecked, it is *pinned* -- while staying
readable, because the window is exactly the diff a reviewer would look at.

The two honesty conditions carry over unchanged:

  1. Every task's `paths_present` / `paths_absent` / `section_delta` are written
     by hand against the fixture, and `build()` asserts the reference
     implementation agrees. They are not read back off the output. A task whose
     hand-written expectation is wrong fails to generate rather than quietly
     redefining correct.
  2. `test_incise_ops.py` asserts the reference still reproduces every golden,
     so an executor regression is a test failure, not a re-baselined benchmark.

Arm A is graded against these same goldens. Both arms, one definition.

  python3 bench/make_section_tasks.py > bench/tasks/sections.json
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bench"))

from incise_ops import apply_op, section_outline  # noqa: E402

C = "corpus/documents/changelog.md"
D = "corpus/sections/deep-nesting.md"
S = "corpus/sections/setext-and-atx.md"
U = "corpus/sections/duplicate-siblings.md"
F = "corpus/hazards/code-fences.md"

# (id, family, fixture, instruction, op, args, section_delta,
#  paths_present, paths_absent, note)
SPECS = [
    (
        "insert-release-at-top", "section-insert", C,
        "Add a new release section for version 1.5.0, dated 2026-09-06, "
        "immediately above the [1.4.2] release. Give it an Added subsection "
        'containing the line "- `plan --explain` flag."',
        "section-insert",
        [{"op": "section-insert",
          "args": {"section": "[1.4.2] - 2026-08-14", "position": "before",
                   "heading": "[1.5.0] - 2026-09-06"}},
         {"op": "section-insert",
          "args": {"section": "Changelog > [1.5.0] - 2026-09-06",
                   "position": "last-child", "heading": "Added",
                   "body": "- `plan --explain` flag."}}],
        2,
        ["Changelog > [1.5.0] - 2026-09-06",
         "Changelog > [1.5.0] - 2026-09-06 > Added"],
        [],
        "The single most common changelog edit there is, and the one the file "
        "was added to the corpus for. Three ways to get it wrong: put it below "
        "[1.4.2] instead of above, give it the wrong level, or land it between "
        "[Unreleased] and its `### Added` child. The level is not in the "
        "instruction and must be derived from the anchor.\n"
        "Re-specified as two calls after S6: the one-call form needed "
        "`### Added` written by hand into `body`, which the executor now "
        "refuses. The golden document is byte-identical either way -- what "
        "changed is which vocabulary can reach it.\n"
        "The instruction was later made to quote the body line verbatim. It "
        "originally paraphrased ('listing a new `plan --explain` flag'), which "
        "was the only paraphrased payload in the family -- every other task "
        "quotes its text. Under a multi-turn harness that stopped being "
        "harmless: trials that derived the level correctly still graded wrong "
        "because they wrote `* New \\`plan --explain\\` flag` against a golden "
        "that says `- \\`plan --explain\\` flag.` A whole-document golden "
        "cannot express 'any bullet to this effect', so the instruction has to "
        "be the thing that is specific. The golden is unchanged; only its "
        "reachability is.",
    ),
    (
        "insert-subsection-last", "section-insert", D,
        "Under Install, add a FreeBSD subsection after the existing ones, "
        'saying "Use pkg."',
        "section-insert",
        {"section": "Install", "position": "last-child", "heading": "FreeBSD",
         "body": "Use pkg."},
        1,
        ["Deep heading nesting > Install > FreeBSD"],
        [],
        "`last-child` means after the anchor's whole subtree, so this lands "
        "below `### Windows` and above `## Upgrade`. Appending to Install's own "
        "body instead would put FreeBSD above macOS. The level is 3, derived "
        "from the anchor -- a hand editor that counts the nearest heading above "
        "the insertion point writes `####`, because the nearest heading above "
        "is `### Windows`'s body.",
    ),
    (
        "append-hotfix-note", "section-append", C,
        "Add a sentence to the [1.4.2] release itself -- not to any of its "
        'subsections -- saying "This release is a hotfix."',
        "section-append",
        {"section": "[1.4.2] - 2026-08-14", "text": "This release is a hotfix."},
        0, [], [],
        "`## [1.4.2]` has no prose of its own and two subsections, so its own "
        "body is empty and the sentence goes between the heading and "
        "`### Fixed`. 'Append to the section' read as 'append to the end of the "
        "section' puts it under `### Changed`, which attributes it to the wrong "
        "subsection.",
    ),
    (
        "rename-setext", "section-rename", S,
        'Rename the "Setext H2" heading to "Setext level two".',
        "section-rename",
        {"section": "Setext H2", "heading": "Setext level two"},
        0,
        ["Setext H1 Title > Setext level two"],
        ["Setext H1 Title > Setext H2"],
        "The heading is underlined, not marked with hashes. Rewriting it as "
        "`## Setext level two` addresses identically and is still wrong: it "
        "changes the document's syntax. The underline must also be re-run to "
        "the new width -- leaving nine dashes under a sixteen-character title "
        "is the kind of damage that renders fine and reads as sloppy forever.",
    ),
    (
        "rename-closed-atx", "section-rename", S,
        'Rename "Closed ATX level 3" to "Closed ATX heading".',
        "section-rename",
        {"section": "Closed ATX level 3", "heading": "Closed ATX heading"},
        0,
        ["Setext H1 Title > Setext H2 > Closed ATX heading"],
        ["Setext H1 Title > Setext H2 > Closed ATX level 3"],
        "The trailing `###` is decoration and is not part of the address, so a "
        "model that reads the address off the outline sees no hashes to "
        "preserve. They must survive anyway.",
    ),
    (
        "delete-install-macos", "section-delete", D,
        "Delete the macOS section under Install, including everything in it.",
        "section-delete",
        {"section": "Install > macOS"},
        -3,
        ["Deep heading nesting > Install > Linux",
         "Deep heading nesting > Upgrade > macOS",
         "Deep heading nesting > Uninstall > macOS"],
        ["Deep heading nesting > Install > macOS",
         "Deep heading nesting > Install > macOS > Apple Silicon",
         "Deep heading nesting > Install > macOS > Intel"],
        "Two failure modes in opposite directions. Deleting the heading and its "
        "paragraph but not `#### Apple Silicon` and `#### Intel` orphans them "
        "under Install. Matching `macOS` by name instead of by path hits the "
        "wrong one of three -- and the two under Upgrade and Uninstall must "
        "still be there afterwards, which is what makes that detectable.",
    ),
    (
        "promote-api", "section-set-level", D,
        "Promote the API heading under Reference to a second-level heading, "
        "moving its subsections with it.",
        "section-set-level",
        {"section": "Reference > API", "level": 2},
        0,
        ["Deep heading nesting > API",
         "Deep heading nesting > API > Endpoints",
         "Deep heading nesting > API > Endpoints > Authentication"],
        ["Deep heading nesting > Reference > API"],
        "Three headings change, not one. `##### Authentication` is four levels "
        "down and has to come up with the rest; leaving it behind produces a "
        "document where a level-5 heading follows a level-2 one with nothing "
        "in between. Section count is unchanged -- only the shape is.",
    ),
    (
        "replace-install-preamble", "section-replace-body", D,
        "Replace the introductory paragraph under Install -- the one before the "
        'macOS subsection -- with "Choose your platform below."',
        "section-replace-body",
        {"section": "Install", "text": "Choose your platform below.",
         "overwrite": True},
        0,
        ["Deep heading nesting > Install > macOS"],
        [],
        "The inverse of `append-hotfix-note` and the same boundary: 'the text "
        "under Install' is its own body, which stops at `### macOS`. Reading it "
        "as the whole subtree replaces six subsections with one sentence, which "
        "is the most destructive single outcome available in this family.\n"
        "`overwrite` is required because Install's body is not empty: FINDINGS "
        "S2 made an unacknowledged overwrite an `op_error`, so the ideal call "
        "has to acknowledge it. This is the one task where the destructive "
        "action is the correct one, and it exists so a fix for S2 cannot be "
        "'remove replace-body' -- something has to still be able to do this.",
    ),
    (
        "notes-second-ordinal", "section-append", U,
        'Add the line "Superseded." to the second of the three Notes sections.',
        "section-append",
        {"section": {"path": "Notes", "ordinal": 1}, "text": "Superseded."},
        0, [], [],
        "Three sections share the path `Notes` and nothing but position "
        "distinguishes them, so this is the one case in the family where an "
        "ordinal is the answer rather than a longer path. Silently editing the "
        "first is the outcome the fixture exists to catch.",
    ),
    (
        "append-after-fence", "section-append", F,
        'Add a sentence to the "Fenced headings and lists" section saying '
        '"None of the above is parsed as markdown."',
        "section-append",
        {"section": "Fenced headings and lists",
         "text": "None of the above is parsed as markdown."},
        0, [], [],
        "The section's body is a fenced block containing `# Not a real heading` "
        "and `## Also not real`. Anything that finds the end of the section by "
        "scanning forward for the next `#` stops inside the fence and writes "
        "the sentence into the code block, where it is not prose and not "
        "visible as an edit.",
    ),

    # --- the append / replace-body pair -------------------------------------
    # Added after the first section arm. FINDINGS caveat 6: exactly one task
    # (`notes-second-ordinal`) could tell the two verbs apart, and it produced
    # every destructive trial in the family. One task is not enough evidence for
    # the most severe finding here, so the pair now has four tasks pulling in
    # both directions -- two where `append` is right and overwriting loses
    # prose, two where replacing is right and appending is merely wrong.
    (
        "append-atx-line", "section-append", S,
        'Add the sentence "The same is true of the closed form." to the '
        '"ATX level 3" section.',
        "section-append",
        {"section": "ATX level 3",
         "text": "The same is true of the closed form."},
        0, [], [],
        "The cleanest possible append/overwrite discriminator: one addressable "
        "section, no duplicate paths, no subsections, and a one-line body "
        "(`Normal.`) that an overwrite destroys and an append keeps. Nothing "
        "about addressing is at stake, so a failure here is a failure to "
        "choose the verb.",
    ),
    (
        "append-macos-note", "section-append", D,
        'Add "Requires macOS 13 or later." to the macOS section under Install.',
        "section-append",
        {"section": "Install > macOS",
         "text": "Requires macOS 13 or later."},
        0, [], [],
        "The same choice with both of the family's other traps present: "
        "`macOS` appears under three parents so the path must be full, and the "
        "section has two subsections, so the sentence belongs after "
        "`Use Homebrew.` and before `#### Apple Silicon` -- own body, not "
        "subtree.",
    ),
    (
        "replace-linux-body", "section-replace-body", D,
        'Replace the text under Upgrade > Linux with "See the platform notes."',
        "section-replace-body",
        {"section": "Upgrade > Linux", "text": "See the platform notes.",
         "overwrite": True},
        0, [], [],
        "The other direction, and the reason the pair needs four tasks rather "
        "than two more appends: an instruction that says *replace* must still "
        "reach the destructive op. A schema change that fixes S2 by making "
        "overwriting unreachable would score 0 here, which is the point.",
    ),
    # The two below were added for S6, before the arm that measures it was run.
    # `insert-release-at-top` was the family's only task that needs a section
    # *and* a subsection, and it is also the only task no scheme ever solved --
    # one task carrying a whole design question, which is caveat 6's mistake a
    # second time. These put the same mechanism on a different fixture, at
    # deeper levels, and at a call count of three.
    (
        "insert-nested-ratelimits", "section-insert", D,
        "Under the API section, add a Rate limits section, and give it a "
        'Headers subsection saying "Every response carries `X-RateLimit-*`."',
        "section-insert",
        [{"op": "section-insert",
          "args": {"section": "Reference > API", "position": "last-child",
                   "heading": "Rate limits"}},
         {"op": "section-insert",
          "args": {"section": "Reference > API > Rate limits",
                   "position": "last-child", "heading": "Headers",
                   "body": "Every response carries `X-RateLimit-*`."}}],
        2,
        ["Deep heading nesting > Reference > API > Rate limits",
         "Deep heading nesting > Reference > API > Rate limits > Headers"],
        [],
        "The changelog task's mechanism at depth: `API` is level 3, so the two "
        "new headings are 4 and 5. Neither number is in the instruction and "
        "neither is expressible in the schema, so both must come from the "
        "anchor. `Endpoints` is already a level-4 child of `API`, which makes "
        "a wrong level land the new section inside it rather than beside it.",
    ),
    (
        "insert-troubleshooting", "section-insert", D,
        "At the end of Deep heading nesting, add a Troubleshooting section "
        'with two subsections: Logs, saying "Written to `~/.incise/log`.", and '
        'Common errors, saying "See the FAQ."',
        "section-insert",
        [{"op": "section-insert",
          "args": {"section": "Deep heading nesting", "position": "last-child",
                   "heading": "Troubleshooting"}},
         {"op": "section-insert",
          "args": {"section": "Deep heading nesting > Troubleshooting",
                   "position": "last-child", "heading": "Logs",
                   "body": "Written to `~/.incise/log`."}},
         {"op": "section-insert",
          "args": {"section": "Deep heading nesting > Troubleshooting",
                   "position": "last-child", "heading": "Common errors",
                   "body": "See the FAQ."}}],
        3,
        ["Deep heading nesting > Troubleshooting",
         "Deep heading nesting > Troubleshooting > Logs",
         "Deep heading nesting > Troubleshooting > Common errors"],
        [],
        "Three calls, and the first one has to go past a seventeen-section "
        "subtree: the end of `Deep heading nesting` is the end of the file, "
        "not the line under its heading. Also the only task where a scheme "
        "with a structured payload could legitimately finish in one call, "
        "which is what makes it worth measuring against a scheme that "
        "cannot.\n"
        "First written with the anchor left implicit -- 'at the end of the "
        "document' -- and an ideal call that made Troubleshooting a *sibling* "
        "of the H1. All 30 trials across the three S6 schemes chose "
        "`last-child` of the H1 instead. They were right and the task was "
        "wrong: 'the end of the document' names an insertion point and not a "
        "level, both readings put the bytes in the same place, and the level "
        "is the only difference. This was the family's one insert task that "
        "did not name its anchor, and an anchor-relative op cannot be graded "
        "on an unstated anchor. Naming it is the fix; the level is still "
        "derived and still not in the instruction.",
    ),
]


def _window(before, after):
    """The minimal changed line window: (first_changed, unchanged_tail, lines).

    Trimming both ends is what keeps a 29,000-byte fixture's golden readable
    without weakening it -- the trimmed lines are still asserted, they are just
    asserted by reference to the input instead of being copied.
    """
    b, a = before.split("\n"), after.split("\n")
    pre = 0
    while pre < min(len(b), len(a)) and b[pre] == a[pre]:
        pre += 1
    suf = 0
    while suf < min(len(b), len(a)) - pre and b[-1 - suf] == a[-1 - suf]:
        suf += 1
    return pre, suf, a[pre: len(a) - suf]


def build():
    tasks = []
    for (tid, family, fixture, instruction, op, args, delta,
         present, absent, note) in SPECS:
        path = os.path.join(ROOT, fixture)
        before = open(path, newline="").read()
        # A spec's call slot is either one op's args or an explicit list of
        # `{op, args}`. S6 forced the second form: making a section that
        # contains a subsection is two calls, because the one-call form put
        # raw `### Added` in `body` and the executor now refuses that. The
        # golden is a document, not a call count, so a task that needs two
        # calls is graded exactly like a task that needs one.
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
        paths_before = [e["path"] for e in section_outline(before)]
        paths_after = [e["path"] for e in section_outline(after)]
        got = len(paths_after) - len(paths_before)
        if got != delta:
            raise SystemExit(
                f"{tid}: expected section delta {delta:+d}, reference gives {got:+d}")
        for p in present:
            if p not in paths_after:
                raise SystemExit(f"{tid}: expected path {p!r} in the result; "
                                 f"reference produced {paths_after}")
        for p in absent:
            if p in paths_after:
                raise SystemExit(f"{tid}: path {p!r} should be gone, it is not")

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
                "section_delta": delta,
                "paths_present": present,
                "paths_absent": absent,
            },
            "ideal_calls": calls,
            "note": note,
        })
    return {
        "_comment": (
            "Fifteen section tasks, graded against whole-document goldens stored "
            "as "
            "a minimal changed window: rebuild with "
            "before[:first_changed] + lines + before[len - unchanged_tail:] and "
            "compare bytes. Generated and regenerable by "
            "bench/make_section_tasks.py, which explains why this family pins "
            "the whole document where the list family scoped to one list. "
            "Instructions are phrased as a user would phrase them and avoid "
            "incise's op vocabulary -- in particular they never name a heading "
            "level, because deriving it is the thing under test."
        ),
        "tasks": tasks,
    }


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
