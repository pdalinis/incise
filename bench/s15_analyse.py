#!/usr/bin/env python3
"""S15: does renaming the colliding `path` argument fix S12's largest bucket?

`section_edit` spells the file `path` and the heading path `section.path` --
one word, two meanings, one call. S12 found the model putting the heading path
into the file argument in 6 of 15 unrecovered failures, and it was the only
failure that reproduced *identically* on the retry turn, which is what a name
collision looks like: a better error message does not move it.

Three arms, one factor each, `section_g` as the control:

  section_g        `path` = file, `section.path` = heading path   (control)
  section_g_file   `file` = file, `section.path`                  (rename the file arg)
  section_g_hpath  `path` = file, `section.heading`               (rename the address)

Every description string is byte-identical across the three; only the key
moves. Running both single-factor arms rather than the one that would ship
answers *which side* of the collision the model is confused about -- if only
`section_g_file` moves, the top-level name is pulling the value; if both move,
the collision itself was the problem and either disambiguation buys it.

A second comparison rides along free. This run is at `--result-shape delta`
(the S14 default) while S13's `section_g` ran the same 15 tasks and seeds at
`outline`, so pairing the control against that file is the full-arm answer to
caveat 13 -- whether the adopted result shape changes anything on a fresh run
rather than on the inherited prefixes S14 had to use.

  python3 bench/s15_analyse.py
"""

import argparse
import glob
import json
import os
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bench"))

import armb  # noqa: E402
from stats import mcnemar_exact, wilson  # noqa: E402

CONTROL = "section_g"
ARMS = ["section_g", "section_g_file", "section_g_hpath"]

# The three tasks that legitimately need more than one call (S13). Everything
# S15 measures is a first-call addressing question, but they are split out
# because pooling them hides a rename that helps one group and hurts the other.
MULTI = {"insert-release-at-top", "insert-nested-ratelimits",
         "insert-troubleshooting"}

# The first pass ran all 15 tasks x 10 trials and found the misfiling in 2 of
# 150 control trials -- all of them the same task, the same value, and nowhere
# near significance. That is S12's number read correctly: "6 of 15" was 6 of
# the fifteen *unrecovered failures*, not 6 of 150 trials, so the behaviour's
# base rate is ~1.3% overall and ~20% on the one task that provokes it.
#
# So the extra sampling goes there instead of spreading thin, exactly as S14
# spent its sampling only on the turn under test. The cost is that the arms are
# no longer balanced across tasks: `promote-api` has 60 trials and everything
# else has 10, and pooling them would let one task's result masquerade as the
# family's. The first two tables are therefore capped at the balanced prefix
# and the provoking task gets its own.
BALANCED = 10
PROVOKING = {"promote-api"}


def load(paths):
    """Last non-error row per (scheme, task, trial).

    `run()` retries errored trials on resume, which appends a second row for
    the same key; taking the last one keeps a retried trial from being counted
    twice. An all-error key is kept so it can be dropped from every arm at
    once rather than silently thinning one.

    Grading records are skipped, and the bug that makes this necessary is worth
    stating because it is the third of its kind. `--results` globs
    `armb_s15_*.jsonl`, which also matches
    `armb_s15_section_g_hpath_graded.jsonl` -- written later, for S16's
    control. A graded row carries the same `(scheme, task_id, trial)` key, has
    no `tool_calls`, and sorts *after* the raw file, so every `section_g_hpath`
    trial was being replaced by a stub with no calls in it. The arm then
    reported **0/150 correct** and a McNemar of `p = 1.2e-38` against the
    control -- which is how this was noticed, since a shipping schema scoring
    zero is not a result anyone believes.

    The test is a property of the row rather than of its file name, for the
    reason `bench/population.py` gives: a name-based skip is a blocklist, and
    the next file to land will not be called `_graded` either. A grading record
    is one that reports an `outcome` and contains no calls. An errored trial is
    not one -- it has no `outcome` -- so it still reaches the all-error path
    above and is dropped from every arm together.
    """
    rows = {}
    for path in paths:
        for line in open(path):
            line = line.strip()
            if not line:
                continue
            tr = json.loads(line)
            if "outcome" in tr and "tool_calls" not in tr:
                continue
            key = (tr["scheme"], tr["task_id"], tr["trial"])
            if key in rows and tr.get("error") and not rows[key].get("error"):
                continue
            rows[key] = tr
    return rows


def declared_file_arg(scheme):
    """What this scheme calls the file argument, read from the schema itself."""
    props = armb.SCHEMES[scheme][0]["parameters"]["properties"]
    return "file" if "file" in props else "path"


def first_args(tr):
    calls = tr.get("tool_calls") or []
    if not calls:
        return None
    try:
        return json.loads(calls[0].get("function", {}).get("arguments") or "{}")
    except json.JSONDecodeError:
        return None


def file_arg_of(tr, scheme):
    """What the trial's first call put in the file argument, or None.

    The whole point of S15, so it is read from the raw call rather than from
    anything `normalize` has already tidied up, and the key is taken from the
    scheme's own schema -- guessing `path` first would misread `section_g_file`
    whenever a model supplied the renamed field *and* a stray `path`.
    """
    a = first_args(tr)
    if a is None:
        return None
    want = declared_file_arg(scheme)
    if want in a:
        return a[want]
    # Fell back to the other spelling: itself a finding, since the schema does
    # not offer it. Reported rather than treated as absent.
    other = "path" if want == "file" else "file"
    return a.get(other)


def used_undeclared(tr, scheme):
    a = first_args(tr) or {}
    want = declared_file_arg(scheme)
    other = "path" if want == "file" else "file"
    return other in a and want not in a


def misfiled(tr, scheme, task):
    """True when the file argument holds something that is not the file.

    The S12 failure, detected positionally rather than by outcome: the model
    supplied a heading path where the filename goes. Checked against the task's
    own fixture instead of a heuristic about what a filename looks like, so a
    trial that named the wrong *file* counts too -- it is the same mistake.
    """
    got = file_arg_of(tr, scheme)
    if got is None:
        return False
    return str(got).strip() != task["fixture"]


def sent_ordinal(tr):
    """Did any call in this trial address a section with an `ordinal`?

    Any call, not the first: a model that addresses by name and then adds an
    ordinal on the retry has still reached for the disambiguator, which is the
    behaviour in question.
    """
    for c in tr.get("tool_calls") or []:
        fn = c.get("function") or {}
        try:
            a = json.loads(fn.get("arguments") or "{}")
        except json.JSONDecodeError:
            continue
        if isinstance(a, dict) and isinstance(a.get("section"), dict) \
                and "ordinal" in a["section"]:
            return True
    return False


def ordinal_use(rows, paired):
    """Spurious ordinal use per arm, paired, with the branch it feeds.

    A post-hoc endpoint on a pre-registered run, and labelled as one wherever
    it is quoted. It exists because the F-unique prefix pool contains no
    `section_g_hpath` row and the obvious reading -- that the arms producing
    ordinal refusals merely happened to run first -- is wrong. These three arms
    ran the same tasks, trials and result shape in one batch, so the comparison
    is paired by construction and costs nothing to recompute.

    `notes-second-ordinal` is excluded from the spurious count and reported
    beside it. Its own task note calls it *"the one case in the family where an
    ordinal is the answer rather than a longer path"*, so an ordinal there is
    correct and counting it as spurious would hide the thing worth checking:
    whether the renames suppress ordinals generally or only the wrong ones.
    """
    NEEDS = "notes-second-ordinal"
    spurious = [k for k in paired if k[0] != NEEDS]
    needs = [k for k in paired if k[0] == NEEDS]
    sent = {s: {k: sent_ordinal(rows[(s,) + k]) for k in paired} for s in ARMS}

    print("\n" + "=" * 74)
    print(f"SPURIOUS ORDINAL USE  (post-hoc endpoint; n={len(spurious)} paired, "
          f"{NEEDS!r} excluded)")
    print("=" * 74)
    for s in ARMS:
        n = sum(1 for k in spurious if sent[s][k])
        ok = sum(1 for k in needs if sent[s][k])
        print(f"  {s:<18} spurious {n:3d}/{len(spurious)}"
              f"   on {NEEDS}: {ok}/{len(needs)}")
    for s in ARMS:
        if s == CONTROL:
            continue
        b = sum(1 for k in spurious if sent[CONTROL][k] and not sent[s][k])
        c = sum(1 for k in spurious if sent[s][k] and not sent[CONTROL][k])
        print(f"  {s} vs {CONTROL}: discordant {b}-{c}, "
              f"p = {mcnemar_exact(b, c):.3g}")
    # Caveat 2: spread, not just count. A rate carried by one task is one
    # trajectory sampled repeatedly.
    by_task = Counter(k[0] for k in spurious if sent[CONTROL][k])
    print(f"  control's spurious trials span {len(by_task)} tasks: "
          + ", ".join(f"{t}={n}" for t, n in by_task.most_common()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", nargs="+",
                    default=sorted(glob.glob(os.path.join(
                        ROOT, "bench/results/armb_s15_*.jsonl"))))
    ap.add_argument("--outline", default=os.path.join(
        ROOT, "bench/results/s14_source_section_g.jsonl"),
        help="S13's section_g at --result-shape outline, for caveat 13")
    ap.add_argument("--tasks", default=os.path.join(
        ROOT, "bench/tasks/sections.json"))
    args = ap.parse_args()

    tasks = {t["id"]: t for t in json.load(open(args.tasks))["tasks"]}
    rows = load(args.results)

    # Pair by (task, trial): a trial missing from any arm is dropped from all
    # of them, or the arms would be compared on different samples.
    keys = defaultdict(set)
    for scheme, task_id, trial in rows:
        keys[(task_id, trial)].add(scheme)
    paired = sorted(k for k, v in keys.items() if set(ARMS) <= v)
    dropped = len(keys) - len(paired)
    print(f"{len(paired)} paired (task, trial) cells across {len(ARMS)} arms"
          + (f"  [dropped {dropped} incomplete]" if dropped else ""))

    graded = {}
    for scheme in ARMS:
        for task_id, trial in paired:
            tr = rows[(scheme, task_id, trial)]
            graded[(scheme, task_id, trial)] = armb.grade_one(tasks[task_id], tr)[0]

    def report(title, cells):
        print("\n" + "=" * 74)
        print(f"{title}  (n={len(cells)} per arm)")
        print("=" * 74)
        print(f"{'arm':<17}{'correct':>12}{'misfiled':>11}"
              f"{'op_error':>10}{'destructive':>13}")
        for scheme in ARMS:
            out = [graded[(scheme, t, n)] for t, n in cells]
            ok = sum(1 for o in out if o == "correct")
            lo, hi = wilson(ok, len(out))
            mis = sum(1 for t, n in cells
                      if misfiled(rows[(scheme, t, n)], scheme, tasks[t]))
            print(f"{scheme:<17}{ok:>4}/{len(out)} {100*ok/len(out):5.1f}%"
                  f"{mis:>11}{sum(1 for o in out if o == 'op_error'):>10}"
                  f"{sum(1 for o in out if o == 'destructive'):>13}"
                  f"   [{100*lo:.1f}-{100*hi:.1f}]")
        for scheme in ARMS:
            if scheme == CONTROL:
                continue
            for label, fn in (("correct", lambda s, c: graded[(s,) + c] == "correct"),
                              ("misfiled", lambda s, c: misfiled(rows[(s,) + c],
                                                                 s, tasks[c[0]]))):
                b = sum(1 for c in cells if fn(CONTROL, c) and not fn(scheme, c))
                d = sum(1 for c in cells if fn(scheme, c) and not fn(CONTROL, c))
                p = mcnemar_exact(b, d)
                print(f"  McNemar {label:<9}{CONTROL} -> {scheme:<16}"
                      f"only-control={b:>3} only-{'new':<4}={d:>3}  p = {p:.4g}")

    report("all section tasks", [c for c in paired if c[1] < BALANCED])
    report("single-call tasks",
           [c for c in paired if c[1] < BALANCED and c[0] not in MULTI])
    provoking = [c for c in paired if c[0] in PROVOKING]
    if provoking and len(provoking) > len(PROVOKING) * BALANCED:
        report("the task that provokes the collision (all trials)", provoking)

    ordinal_use(rows, paired)

    # Where the misfiling actually lives, per task and per arm.
    print("\n" + "=" * 74)
    print("misfiled file argument, by task (all trials, unbalanced)")
    print("=" * 74)
    per = {s: Counter() for s in ARMS}
    for scheme in ARMS:
        for t, n in paired:
            if misfiled(rows[(scheme, t, n)], scheme, tasks[t]):
                per[scheme][t] += 1
    shown = sorted({t for s in ARMS for t in per[s]})
    if not shown:
        print("  none in any arm")
    for t in shown:
        print(f"  {t:<28}" + "".join(f"{per[s][t]:>6}" for s in ARMS))
    print(f"  {'':<28}" + "".join(f"{s.split('_')[-1]:>6}" for s in ARMS))
    for scheme in ARMS:
        vals = sorted({str(file_arg_of(rows[(scheme, t, n)], scheme))
                       for t, n in paired
                       if misfiled(rows[(scheme, t, n)], scheme, tasks[t])})
        stray = sum(1 for t, n in paired
                    if used_undeclared(rows[(scheme, t, n)], scheme))
        if stray:
            print(f"\n  {scheme}: {stray} trials used the undeclared spelling")
        if vals:
            print(f"\n  {scheme} put these in the file argument:")
            for v in vals[:12]:
                print(f"    {v!r}")

    # Caveat 13: the control at `delta` against S13's same-tasks arm at
    # `outline`. Not a rename result at all -- it rides along because this run
    # is the first full arm at the adopted result shape.
    if os.path.exists(args.outline):
        old = load([args.outline])
        cells = [(t, n) for (t, n) in paired
                 if n < BALANCED and ("section_g", t, n) in old]
        if cells:
            print("\n" + "=" * 74)
            print(f"caveat 13: section_g at `delta` (this run) vs `outline` "
                  f"(S13)  (n={len(cells)})")
            print("=" * 74)
            for label, get in (("outline (S13)",
                                lambda c: armb.grade_one(tasks[c[0]],
                                                         old[("section_g",) + c])[0]),
                               ("delta (S15)",
                                lambda c: graded[("section_g",) + c])):
                out = [get(c) for c in cells]
                ok = sum(1 for o in out if o == "correct")
                lo, hi = wilson(ok, len(out))
                print(f"{label:<17}{ok:>4}/{len(out)} {100*ok/len(out):5.1f}%"
                      f"   destructive={sum(1 for o in out if o == 'destructive')}"
                      f"   [{100*lo:.1f}-{100*hi:.1f}]")
            b = sum(1 for c in cells
                    if armb.grade_one(tasks[c[0]], old[("section_g",) + c])[0] == "correct"
                    and graded[("section_g",) + c] != "correct")
            d = sum(1 for c in cells
                    if graded[("section_g",) + c] == "correct"
                    and armb.grade_one(tasks[c[0]], old[("section_g",) + c])[0] != "correct")
            print(f"  McNemar correct   outline -> delta   only-outline={b:>3} "
                  f"only-delta={d:>3}  p = {mcnemar_exact(b, d):.4g}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
