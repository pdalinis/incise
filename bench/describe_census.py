#!/usr/bin/env python3
"""Two censuses over the success line, for the open `describe_change` item.

    $ python3 bench/describe_census.py

The item asks two questions and both have been argued rather than counted:

  1. **Should `describe_frontmatter_change` fold into `describe_change`?**
     They are siblings dispatched on the op name (`armb.py:1818`,
     `incise-cli/src/main.rs:451`). The reason given for keeping them apart --
     the Rust had no frontmatter parser -- expired when F-frontport ported
     `describe_frontmatter_change` into `ops/frontmatter.rs`. What survives is
     the hazard the dispatch comment names: `describe_change` is derived from
     the two documents and not from the op, so a fold *re-describes calls that
     are not frontmatter calls*. Prepending text to a file that opens with
     `---` moves the delimiter off line 0, `find_frontmatter` stops finding a
     block, and the change reads as the block having been **removed**.

  2. **`table-realign`'s success line.** F-mirror recorded it reporting
     "Applied: changed text outside any heading. (+3 lines, -3 lines.)" -- on
     the one op that changes no cell text and exists to change nothing but
     padding.

Neither is a question a `regrade_snapshot --compare` can answer:
`regrade_snapshot` hashes the resulting document and the error string, and the
success line is in neither. This module is that snapshot's missing half. It
borrows `regrade_snapshot.disposition` rather than keeping a fourth copy of the
rules for what a recorded call executes.

**The fold is a candidate, not a proposal.** "Which calls would move" is not
answerable without a concrete `folded()`, so one is written below in the
smallest shape that could be correct, and the census is over *that*. A
different fold moves a different set; what the census establishes is the shape
and the size of the set, and whether any of it is wrong rather than merely
different.
"""

import collections
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bench"))

import incise_ops as F  # noqa: E402
import mdfront  # noqa: E402
import regrade_snapshot as RS  # noqa: E402


def fixtures():
    """The corpus and the synthetic fixtures, the population `replay_all` uses.

    Same list and same reason: the synthetic files are the documents the
    recorded trials actually ran against, and a census over the corpus alone is
    silent about every finding that needed a fixture the corpus does not have.
    """
    paths = sorted(
        glob.glob(os.path.join(ROOT, "corpus", "**", "*.md"), recursive=True)
        + glob.glob(os.path.join(ROOT, "bench", "synthetic", "*.md")))
    return [(os.path.relpath(p, ROOT), open(p, newline="").read())
            for p in paths]


# --------------------------------------------------------------------------
# The candidate fold.

def folded(before, after, path=""):
    """One function for both families, derived from the documents as before.

    Two changes from the shipped pair, and no third:

      * the frontmatter block's notes are computed for **every** op, not only
        for `frontmatter-*`. `_front_notes` already returns `([], False)` when
        the block's text is unchanged, so this is inert on a document without
        one and on an edit that leaves one alone.
      * the heading notes are computed on the body with the block removed, so
        a block that grows or shrinks cannot be reported a second time as a
        change to the text before the first heading.

    The notes are reassembled from `describe_change`'s own output rather than
    by duplicating its loop. That is string surgery and it is deliberate:
    `incise_ops.describe_change` is the graded executor for four thousand
    trials and `difftest.py`'s oracle for the Rust, and a census is not a
    reason to reshape it. A real fold would refactor; this one only has to
    predict what a real fold would say.
    """
    if before == after:
        return "Applied, but the document is unchanged."
    fnotes, ftally = F._front_notes(before, after)

    body_b, body_a = F._strip_front(before), F._strip_front(after)
    notes = []
    tally_wanted = bool(ftally)
    if body_b != body_a:
        said = F.describe_change(body_b, body_a, path)
        head = said[len("Applied: "):]
        if head.endswith(".)"):                     # "... . (+1 line.)"
            head = head[:head.rindex(" (")]
            tally_wanted = True
        notes = head.rstrip(".").split("; ")

    notes = fnotes + notes
    if not notes:
        notes.append("changed text outside any heading")
        tally_wanted = True

    tally = []
    if tally_wanted:
        added, removed = F._line_counts(before, after)
        if added:
            tally.append(f"+{F._plural(added, 'line')}")
        if removed:
            tally.append(f"-{F._plural(removed, 'line')}")
    out = "Applied: " + "; ".join(notes) + "."
    return out + (f" ({', '.join(tally)}.)" if tally else "")


def shipped(op, before, after, path=""):
    """What the product says today: dispatched on the op name."""
    if op.startswith("frontmatter-"):
        return F.describe_frontmatter_change(before, after)
    return F.describe_change(before, after, path)


def block_text(doc):
    """The frontmatter block's own bytes, or None when there is no block."""
    fm = mdfront.find_frontmatter(doc)
    if not fm.present:
        return None
    return "\n".join(doc.split("\n")[fm.start:fm.end + 1])


def verdict(before, after, said):
    """Is a moved sentence true of the two documents, or displaced-block noise?

    The one failure mode the dispatch comment predicts is a block that did not
    change and only *moved*: `find_frontmatter` anchors at line 0, so text
    prepended above a block makes it invisible and the fold reports a removal
    that did not happen. That is checkable without reading the sentence -- the
    block's bytes are still in the document, somewhere -- so it is checked
    rather than eyeballed.
    """
    b, a = block_text(before), block_text(after)
    if b is not None and a is None and b in after:
        return "FALSE: block still present, reported as removed"
    if b is None and a is not None and a in before:
        return "FALSE: block was already present, reported as added"
    return "true"


# --------------------------------------------------------------------------
# Census 1: the fold, over every recorded call against every fixture.

def census_fold():
    calls = collections.Counter()      # (op, args-json) -> recorded call count
    files = sorted(glob.glob(os.path.join(ROOT, "bench", "results", "*.jsonl")))
    for f in files:
        for ln in open(f):
            ln = ln.strip()
            if not ln:
                continue
            try:
                rec = json.loads(ln)
            except ValueError:
                continue
            for call in (rec.get("tool_calls") or []):
                fn = call.get("function") or {}
                d = RS.disposition(fn.get("name"), fn.get("arguments"))
                if d["route"] != "edit":
                    continue            # a read writes no document to describe
                calls[(d["op"], json.dumps(d["op_args"], sort_keys=True,
                                           default=str))] += 1

    fx = fixtures()
    applied = moved = 0
    by_op = collections.Counter()
    kinds = collections.Counter()
    examples = {}
    for (op, argj), n in calls.items():
        args = json.loads(argj)
        for rel, content in fx:
            try:
                after, err = F.apply_op(content, op, args)
            except Exception:           # noqa: BLE001 -- censusing, not fixing
                continue
            if err is not None or after == content:
                continue
            applied += 1
            was = shipped(op, content, after, rel)
            now = folded(content, after, rel)
            if was == now:
                continue
            moved += 1
            by_op[op] += n
            v = verdict(content, after, now)
            kinds[v] += 1
            examples.setdefault((op, v), (rel, args, was, now))

    print("=" * 74)
    print("census 1 -- the fold")
    print(f"  {len(calls)} distinct edit calls recorded, over {len(fx)} "
          f"fixtures")
    print(f"  {applied} (call, fixture) pairs apply and change the document")
    print(f"  {moved} would be described differently by the candidate fold")
    if moved:
        print("\n  by op (weighted by recorded calls):")
        for op, n in by_op.most_common():
            print(f"    {op:<24} {n}")
        print("\n  is the moved sentence true of the two documents?")
        for k, n in kinds.most_common():
            print(f"    {n:>6}  {k}")
        print("\n  one example per (op, verdict):")
        for (op, v), (rel, args, was, now) in sorted(examples.items()):
            print(f"\n    {op} {json.dumps(args, default=str)}  on {rel}")
            print(f"      [{v}]")
            print(f"      now:    {was}")
            print(f"      folded: {now}")
    return moved, kinds


# --------------------------------------------------------------------------
# Census 2: what `table-realign` actually says.

def census_realign():
    fx = fixtures()
    said = collections.Counter()
    refused = collections.Counter()
    examples = {}
    total = aligned = 0
    for rel, content in fx:
        entries = F.list_tables(content, rel)
        for e in entries:
            # The address is read back out of `list_tables`, which is the only
            # form guaranteed to resolve: `_locate_table` requires a heading
            # and treats `ordinal` as a tiebreak *within* it, so a bare ordinal
            # is refused as "table address required" on any multi-table file.
            # Censusing with one -- which this did first -- silently reduces the
            # population to files holding a single table, and the three it
            # found were not three tables, they were three files.
            addr = {"heading": e["heading"], "ordinal": e["ordinal"]}
            if not e["heading"]:
                if len(entries) > 1:
                    continue
                addr = None
            try:
                after, err = F.apply_op(content, "table-realign",
                                        {"table": addr} if addr else {})
            except Exception:           # noqa: BLE001
                continue
            if err is not None:
                refused[err.split("\n")[0][:46]] += 1
                continue
            if after == content:
                aligned += 1
                continue
            total += 1
            line = F.describe_change(content, after, rel)
            # The clause is what matters, not the line counts.
            clause = line[len("Applied: "):].split(" (")[0].rstrip(".")
            kind = ("outside any heading"
                    if clause == "changed text outside any heading"
                    else "named the section")
            said[kind] += 1
            examples.setdefault(kind, (rel, e["heading"] or "(none)", line))

    print()
    print("=" * 74)
    print("census 2 -- what `table-realign` says when it succeeds")
    print(f"  {total} tables across {len(fx)} fixtures realign to a changed "
          f"document; {aligned} are already aligned and describe as no-ops")
    for k, n in said.most_common():
        rel, heading, line = examples[k]
        print(f"    {n:>4}  {k}")
        print(f'          e.g. "{heading}" in {rel}')
        print(f"          {line}")
    if refused:
        print("  refused:")
        for msg, n in refused.most_common():
            print(f"    {n:>4}  {msg}")
    return said


def probe_displacement():
    """The hazard the dispatch comment predicts, asked of the product directly.

    Census 1 counts what the *recorded* calls would do, and a branch no
    recorded call reaches is exactly what `headroom.py` spends its time
    distinguishing from a branch that is safe. So the displaced block gets its
    own probe, in two parts, because the two answers are different:

      * **Can the function be made to lie?** Displace a block by hand -- this is
        not an op, it is a document pair -- and ask.
      * **Can an op produce that pair?** `section-insert` with
        `position: "before"` against the document's first heading is the only
        published call that writes above every heading, so it is the only route
        to text above line 0. Every frontmatter fixture, every first heading.

    A fold is safe to take if the second answer is no, and needs a guard if it
    is yes. The first answer alone decides nothing and is printed so the second
    is not mistaken for the function being incapable of the fault.
    """
    fx = fixtures()
    withfm = [(rel, c) for rel, c in fx if block_text(c) is not None]

    print()
    print("=" * 74)
    print("probe -- the displaced block")
    print(f"  {len(withfm)} of {len(fx)} fixtures open with a frontmatter block")

    rel, content = withfm[0]
    hand = "Prepended.\n\n" + content
    print(f"\n  by hand, on {rel} (a document pair, not an op):")
    print(f"    now:    {shipped('section-insert', content, hand, rel)}")
    print(f"    folded: {folded(content, hand, rel)}")
    print(f"    [{verdict(content, hand, folded(content, hand, rel))}]")

    reached = []
    for rel, content in withfm:
        outline = F.section_outline(content)
        if not outline:
            continue
        args = {"section": outline[0]["path"], "position": "before",
                "heading": "Prepended", "body": "Prepended."}
        try:
            after, err = F.apply_op(content, "section-insert", args)
        except Exception:               # noqa: BLE001
            continue
        if err is not None or after == content:
            continue
        if block_text(after) is None:
            reached.append((rel, folded(content, after, rel)))

    print(f"\n  by op: `section-insert position=before` against the first "
          f"heading of each")
    if reached:
        print(f"    {len(reached)} displace the block. A fold needs a guard.")
        for rel, line in reached[:3]:
            print(f"      {rel}: {line}")
    else:
        print("    0 displace the block -- the block is above every heading, "
              "so inserting before the first one still lands below it.")
    return reached


def main():
    moved, kinds = census_fold()
    census_realign()
    reached = probe_displacement()
    print()
    print("=" * 74)
    bad = sum(n for k, n in kinds.items() if k.startswith("FALSE"))
    if bad or reached:
        print(f"{bad} of {moved} moved sentences are false of the documents "
              f"they describe; {len(reached)} ops reach the displaced block.")
    else:
        print(f"no moved sentence is false of the documents it describes "
              f"({moved} moved), and no published op displaces a block.")


if __name__ == "__main__":
    main()
