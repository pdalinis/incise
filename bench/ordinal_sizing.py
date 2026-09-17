#!/usr/bin/env python3
"""Who reaches the section ordinal refusal, and what its advice does if taken.

F-address rewrote this message. The rewrite's whole content was a *split*: when
the sections a path matches have **different** paths an ordinal cannot tell them
apart, so the repair is a longer path; when they share one path the ordinal is
the right tool and the message names the ordinals that exist. That split was
correct, and the first draft without it offered twenty-one zeroes against
`api-reference.md` -- advice that cannot be taken.

This is the question that was not asked: *which branch do the recorded callers
land in, and if one of them did exactly what its branch says, what would happen
to the document?* Both halves are computable offline, so neither needs an arm.

It replays every recorded tool call in `bench/results/` in trial order --
sequentially, so a retry is graded against the document its own trial had
reached -- and collects every call the section resolver refuses on an ordinal.
Then, for the first calls only (where the document is the pristine fixture and
`grade.check_result` therefore means what it means everywhere else in this
project), it takes each repair the message offers, applies it, and grades the
result.

"Follow the advice" is not a paraphrase. The offered ordinals are parsed back
out of the message's own text rather than recomputed from the resolver, for the
reason `action_sizing.py` keys on first lines: this file must not become a
second implementation of the branch it is measuring. If the parse ever falls
behind the message -- either parsing nothing, or parsing only some of what the
message offers -- the run stops rather than reporting a smaller population. The
second half of that guard was added after the first half failed open.

The population it counts over is `population.recorded_rows()`, not the
directory: a replay's rows are copies of calls already counted, and counting
them published a 206 that is really 140.

    python3 bench/ordinal_sizing.py
"""

import collections
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bench"))

import armb  # noqa: E402
import incise_ops  # noqa: E402
import grade  # noqa: E402
import population  # noqa: E402
from incise_ops import apply_op  # noqa: E402

# The branches, keyed on their text. `MARK` is what makes a refusal one of
# ours at all: every ordinal refusal in the section family quotes the ordinal
# back in its first line, and no other refusal does.
MARK = re.compile(r'^no section ".*" with ordinal ')
BRANCHES = (
    ("shared path -> send one of these ordinals",
     "Ordinals count sections that share a heading path"),
    ("tied paths differ -> use a longer path",
     "sections have different paths, so an ordinal does not tell them"),
    # Keyed on the clause that does not interpolate. The unique branch now
    # quotes the caller's own key -- "Only one section matches
    # `section.heading`" -- so the sentence's opening is not a constant, and
    # keying on it classified all 385 rows UNCLASSIFIED without failing.
    ("path is unique -> drop it, or go deeper",
     "Sending an ordinal says you expected several"),
)
OFFER_ORDINALS = re.compile(r"Send ordinal ((?:\d+(?: or )?)+), or drop it\.")
OFFER_DROP = "without an ordinal"
# The third alternative is the unique branch's offer, and it is written out
# rather than loosened to `.*: ` because a regex broad enough to match any
# introduction would also match the first line's `no section "X" with ordinal`.
OFFER_PATHS = re.compile(
    r"(?:longer path|Candidates|send one of these as `[^`]+`): (.*)$", re.M)
QUOTED = re.compile(r'"([^"]+)"')


def branch_of(text):
    for label, mark in BRANCHES:
        if mark in text:
            return label
    return "UNCLASSIFIED: " + text.split("\n")[1].strip()


def repairs(text):
    """Every repair the message offers, as (kind, mutation).

    A mutation takes the `section` object the caller sent and returns the one
    the message is telling it to send instead. Parsed back out of the message's
    own text rather than recomputed from the resolver, for the reason
    `action_sizing.py` keys on first lines: this file must not become a second
    implementation of the branch it is measuring. If a message ever offers
    nothing this can parse, the run stops rather than reporting a smaller
    population -- which is how the rewrite below was caught changing it.
    """
    out = []
    m = OFFER_ORDINALS.search(text)
    if m:
        for n in m.group(1).split(" or "):
            out.append((m.start(), f"ordinal {n}",
                        lambda s, n=int(n): {**s, "ordinal": n}))
        out.append((m.start(), "drop", lambda s: {k: v for k, v in s.items()
                                                  if k != "ordinal"}))
    d = text.find(OFFER_DROP)
    if d >= 0 and not m:
        out.append((d, "drop", lambda s: {k: v for k, v in s.items()
                                          if k != "ordinal"}))
    p = OFFER_PATHS.search(text)
    if p:
        for q in QUOTED.findall(p.group(1)):
            out.append((p.start(), "longer path", lambda s, q=q: {"path": q}))
    if not out:
        raise SystemExit("ordinal_sizing: could not parse any repair out of "
                         "this message, so it cannot be followed:\n" + text)
    # And the stronger form of the same check, which is the one that was
    # missing. "Did anything parse" fails open: when the unique branch was
    # reworded to quote the caller's key -- `send one of these as
    # `section.path`: "..."` -- `OFFER_PATHS` stopped matching it, every
    # longer-path repair silently vanished, and the run did not stop, because
    # `drop` still parsed. So it reported a *smaller* population by exactly the
    # mechanism the docstring promises it will not.
    #
    # Every address these messages quote below the first line is an address
    # they are offering; the first line is excluded because it quotes the
    # caller's own failed address back at it. If one is quoted and no repair
    # sends it, this file has fallen behind the message again.
    offered = {f({}).get("path") for _i, k, f in out if k == "longer path"}
    for q in QUOTED.findall(text.split("\n", 1)[1] if "\n" in text else ""):
        if q not in offered:
            raise SystemExit(
                f"ordinal_sizing: the message quotes {q!r} as an address and no "
                "parsed repair sends it, so the repairs read off this message "
                "are incomplete:\n" + text)
    # In the order the sentence offers them, not the order this function
    # happens to look for them. `main` reports what a model that takes the
    # *first* thing offered gets, so if the message moves a repair the
    # measurement has to move with it -- which is the whole point of reading
    # the offers back off the text.
    out.sort(key=lambda x: x[0])
    return [(k, f) for _i, k, f in out]


def tasks():
    out = {}
    for path in sorted(glob.glob(os.path.join(ROOT, "bench/tasks/*.json"))):
        for t in json.load(open(path))["tasks"]:
            out[t["id"]] = t
    return out


def refusals(all_tasks):
    """Every ordinal refusal in `bench/results/`, in trial order.

    The document is carried forward across a trial's calls: a fourth-turn retry
    is refused (or not) by the document its own trial had already produced, and
    replaying it against the pristine fixture would be a different experiment.

    Selects on arm before it counts, which F-framing had to learn the hard way
    and this file then repeated: `results/` is not one population. The replays
    this file *emits* the prefixes for write their own rows back into the same
    directory, and their first call is pinned -- it is the prefix, replayed --
    so every one of them is a call already counted. Counting them turned a
    published 206 into 385, three commits after the lesson was written down.
    The rule now lives in `bench/population.py`, which is also where the two
    ways of getting it wrong are written down.
    """
    for path, r in population.recorded_rows():
        task = all_tasks.get(r.get("task_id"))
        if not task:
            continue
        try:
            doc = open(os.path.join(ROOT, task["fixture"]),
                       newline="").read()
        except OSError:
            continue
        for i, c in enumerate(r.get("tool_calls") or []):
            fn = c.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                continue
            if not isinstance(args, dict):
                continue
            try:
                op, op_args = armb.normalize(fn.get("name"), args)
                nxt, err = apply_op(doc, op, op_args)
            except Exception as e:  # noqa: BLE001
                nxt, err = None, str(e)
            if err and MARK.match(err):
                yield (os.path.basename(path), r.get("scheme"), task,
                       r.get("trial"), i, args, err, doc, r)
            if nxt:
                doc = nxt


def followed(task, args, mutate):
    """Grade the document one offered repair produces, from the fixture."""
    before = open(os.path.join(ROOT, task["fixture"]), newline="").read()
    try:
        sec = mutate(dict(args.get("section") or {}))
        op, op_args = armb.normalize("section_edit", {**args, "section": sec})
        after, err = apply_op(before, op, op_args)
    except Exception as e:  # noqa: BLE001
        after, err = None, str(e)
    if err:
        return "refused again"
    return grade.check_result(task, before, after)[0]


def names_the_target(task, doc, text):
    """Does the refusal quote a path that resolves to the task's own target?

    The task's `ideal_calls` carry the address a correct call uses, so "the
    section the caller should have addressed" is on record and does not have to
    be inferred. Both sides go through `resolve_section` rather than being
    compared as strings, because the ideal address is often a bare leaf
    (`"Closed ATX level 3"`) and the message quotes the full path.

    A refusal that offers the right address is not the same as a model taking
    it -- that needs an arm. It is the precondition, and the old message could
    not meet it, because it quoted no paths at all.
    """
    ideal = (task.get("ideal_calls") or [{}])[0].get("args", {})
    want = ideal.get("section") or ideal.get("heading")
    if not isinstance(want, str):
        return None
    try:
        target = incise_ops.resolve_section(doc, {"path": want})
    except Exception:  # noqa: BLE001
        return None
    for q in QUOTED.findall(text.split("\n", 1)[1] if "\n" in text else ""):
        try:
            # `==`, not `is`: `resolve_section` re-parses the document on every
            # call, so the two answers are equal dataclasses and never the same
            # object. `is` is therefore *always* false here -- not usually, but
            # by construction -- so the bug could only ever under-report, which
            # is why it was silent. On the population as `bench/population.py`
            # now defines it this predicate is true for 62 of 140 refusals, and
            # every one of those 62 is an answer `is` would have thrown away.
            # (The figure this comment used to carry, "201 times out of 206",
            # is not recoverable: 206 was the pre-`population.py` count that
            # included replay copies, and no quantity over it reproduces that
            # ratio. Recomputed rather than rescaled.)
            if incise_ops.resolve_section(doc, {"path": q}) == target:
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def emit_prefixes(rows, out):
    """Write the trials whose FIRST call lands in this branch, for `armc.replay`.

    The one thing this file cannot answer is which reading of the message a
    model takes, and the instrument for that is `armc.replay --select refusal`
    run against two `--binary`s. But `--select refusal` selects *every* exit-1
    refusal, and the two builds emit the same sentence for almost all of them.
    Pairs that cannot differ are not evidence of a null; they are dilution, and
    caveat 18 is about exactly this -- an arm showing no discordant pairs may
    not have exercised the change.

    So the sample is chosen here, by the instrument that already knows which
    calls reach the branch, and handed to `armc.replay` as its `--replay`
    source. First calls only: a replay pins the first turn and samples what
    follows, so a prefix whose refusal happened on turn three has already had
    two turns of history this cannot reconstruct. `refusals` has already dropped
    the replays' own rows; the extra check here is a different question with a
    different answer -- not *did a model answer this freshly* but *can
    `build_payload` rebuild the prompt* -- and `section_g:delta` fails the
    second while passing the first.
    """
    seen, n, dropped = set(), 0, collections.Counter()
    with open(out, "w") as fh:
        for _f, _s, task, trial, i, args, _err, _d, rec in rows:
            if i != 0:
                continue
            scheme = rec.get("scheme")
            if scheme not in armb.SCHEMES:
                dropped[f"no prompt can be built: {scheme}"] += 1
                continue
            # Keyed on the call *and the seed*, not on the file it was found
            # in. `build_payload` takes the trial index, so the same first call
            # at two trial indices is two independent samples of the recovery
            # under test, which is the thing being measured -- not a duplicate.
            # A duplicate is the same scheme, task, seed and call found in two
            # results files, which happens because separate runs write separate
            # files, and replaying both would report one sample as two.
            key = (scheme, task["id"], trial, json.dumps(args, sort_keys=True))
            if key in seen:
                dropped["same scheme, task, seed and first call"] += 1
                continue
            seen.add(key)
            fh.write(json.dumps(rec) + "\n")
            n += 1
    by_scheme = collections.Counter(k[0] for k in seen)
    distinct = len({(k[0], k[1], k[3]) for k in seen})
    print(f"{n} prefixes -> {out}")
    print(f"  over {distinct} distinct (scheme, task, first call) situations -- "
          f"the effective width of the sample, which is not {n}")
    for s, c in by_scheme.most_common():
        print(f"  {c:5d}  {s}")
    for s, c in dropped.most_common():
        print(f"  dropped {c:5d}  {s}")


def main():
    all_tasks = tasks()
    rows = list(refusals(all_tasks))
    if len(sys.argv) > 2 and sys.argv[1] == "--emit-prefixes":
        return emit_prefixes(rows, sys.argv[2]) or 0
    by_branch = collections.Counter()
    by_pos = collections.Counter()
    by_task = collections.Counter()
    first_lines = collections.Counter()
    sample = {}

    for _f, _s, task, _t, i, _a, err, _d, _r in rows:
        b = branch_of(err)
        by_branch[b] += 1
        by_pos["first call" if i == 0 else f"retry (call {i + 1})"] += 1
        by_task[task["id"]] += 1
        first_lines[err.split("\n")[0]] += 1
        sample.setdefault(b, err)

    print(f"{len(rows)} ordinal refusals in bench/results/\n")
    print("  by branch")
    for b, n in by_branch.most_common():
        print(f"    {n:5d}  {b}")
    print("\n  by turn")
    for p, n in sorted(by_pos.items()):
        print(f"    {n:5d}  {p}")
    print("\n  by task")
    for t, n in by_task.most_common():
        print(f"    {n:5d}  {t}")
    print(f"\n  {len(first_lines)} distinct first lines; the five commonest:")
    for ln, n in first_lines.most_common(5):
        print(f"    {n:5d}  {ln}")

    # How many repairs of each kind the messages offer. Under the old text
    # `ordinal N` appeared once per call and was always `ordinal 0`, which is
    # the resolver's own statement -- read back off the sentence rather than
    # recomputed -- that the path matched exactly one section. That is the
    # finding: a message whose subject is how to tell tied sections apart, sent
    # to 206 callers who never had a tie.
    kinds = collections.Counter(k for *_x, e, _d, _r in rows
                               for k, _m in repairs(e))
    print("\n  repairs offered, by kind")
    for k, n in kinds.most_common():
        print(f"    {n:5d}  {k}")

    # The point of the file. Only first calls: `check_result` grades against a
    # whole-document golden that starts from the fixture, so a mid-trial retry
    # has no golden to be graded against and would silently score `wrong` for
    # edits its own trial had already made.
    print("\n  IF THE ADVICE IS TAKEN  (first calls only, from the fixture)")
    outcomes = collections.Counter()
    worst = collections.defaultdict(collections.Counter)
    best = collections.Counter()
    for _f, _s, task, _t, i, args, err, _d, _r in rows:
        if i != 0:
            continue
        graded = [(k, followed(task, args, m)) for k, m in repairs(err)]
        for k, o in graded:
            outcomes[(k, o)] += 1
        # Two summaries per *call*, not per repair, because a message offering
        # several repairs is not several messages. `worst` is what a model that
        # takes the first thing offered gets; `best` is the ceiling -- whether
        # the right answer was anywhere in the sentence at all.
        #
        # `worst` is an upper bound on damage, not a prediction, and the gap
        # between the two is the honest width of what this file can say. A
        # message that offers several longer paths is offering a *menu*, and
        # scoring it by taking the first item treats the menu as an imperative.
        # The old message genuinely was one (`Send ordinal 0, or drop it.`), so
        # for it the two readings coincided; for a message whose lines are
        # conditionals they do not, and `worst` gets worse while `best` gets
        # better. Report both. Which item a model picks is not computable here
        # and needs `armc.replay --select refusal` across two `--binary`s.
        worst[graded[0][1]][task["id"]] += 1
        best["correct" if any(o == "correct" for _k, o in graded)
             else "no offered repair is correct"] += 1
    n_first = by_pos.get("first call", 0)
    print(f"    {n_first} first calls, each offered repair applied and graded")
    for (kind, o), n in sorted(outcomes.items()):
        print(f"      {n:5d}  {kind:12s} -> {o}")
    print("\n    taking the first repair offered (upper bound on damage; a"
          " menu read as an order)")
    for o, tasks_ in sorted(worst.items(), key=lambda x: -sum(x[1].values())):
        print(f"      {sum(tasks_.values()):5d}  {o:22s} "
              + ", ".join(f"{t} x{n}" for t, n in tasks_.most_common(3)))
    print("\n    is a correct repair offered anywhere in the message")
    for o, n in best.most_common():
        print(f"      {n:5d}  {o}")

    print("\n  DOES THE REFUSAL QUOTE THE ADDRESS THE TASK WANTED")
    named = collections.Counter()
    by_outcome = collections.defaultdict(collections.Counter)
    for _f, _s, task, _t, i, args, err, doc, _r in rows:
        got = names_the_target(task, doc, err)
        named[got] += 1
        if i == 0:
            by_outcome[followed(task, args, repairs(err)[0][1])][got] += 1
    lab = {True: "yes", False: "no", None: "task has no single-string address"}
    for k, n in sorted(named.items(), key=lambda x: str(x[0])):
        print(f"    {n:5d}  {lab[k]}")
    print("    by what taking the first offered repair does (first calls):")
    for o, c in sorted(by_outcome.items()):
        print(f"      {o:22s} " + ", ".join(f"{lab[k]} x{n}"
                                            for k, n in c.most_common()))

    # The claim the F-unique section actually makes, printed rather than
    # assembled by hand from the tables above. "The old advice" is `drop`,
    # which is exactly what the pre-rewrite message said -- `Send ordinal 0,
    # or drop it.` offered one repair under two names -- and it is still one of
    # the repairs offered here, so the cut is computable from the same rows.
    # It was previously read off a coincidence: the count of first calls the
    # old advice destroyed and the count the *new* first repair destroys were
    # both 64, and the second table was quoted for the first claim.
    hit = collections.Counter()
    for _f, _s, task, _t, i, args, err, doc, _r in rows:
        if i != 0:
            continue
        drops = [m for k, m in repairs(err) if k == "drop"]
        if not drops or followed(task, args, drops[0]) != "destructive":
            continue
        hit[names_the_target(task, doc, err)] += 1
    print("\n    of the first calls the OLD advice destroyed, does the new "
          "message quote the address the task wanted")
    for k, n in sorted(hit.items(), key=lambda x: str(x[0])):
        print(f"      {n:5d}  {lab[k]}")

    for b, err in sorted(sample.items()):
        print(f"\n  --- {b} ---\n" + "\n".join("  " + x for x in err.split("\n")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
