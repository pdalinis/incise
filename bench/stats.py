#!/usr/bin/env python3
"""Confidence intervals and paired tests over graded trials.

The arithmetic here was done by hand for every result up to B7, which is fine
once and a liability by the fourth op family. Two things it exists to stop:

  * **Reporting a proportion without an interval.** 60/60 and 6/6 are both
    "100%"; their Wilson intervals are 94.0-100 and 61.0-100. The point estimate
    alone invites a claim the sample cannot support.
  * **Comparing two schemes with two independent intervals.** The schemes are
    run on the *same* tasks with the *same* seeds, so the trials are paired and
    the question is whether the disagreements are lopsided. That is McNemar's
    test, and overlapping intervals do not answer it.

Exact binomial tail sums are used rather than a chi-square approximation, since
the discordant counts here are routinely single digits.

  python3 bench/stats.py --graded bench/results/armb_lists_graded.jsonl \\
      --key scheme --compare list_naive,list_f

Cross-arm, where the two files name the arm field differently:

  python3 bench/stats.py --compare armA,armB \\
      --graded armA=bench/results/graded_lists.jsonl \\
               armB=bench/results/armb_lists_graded.jsonl
"""

import argparse
import json
import math
import os
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def wilson(k, n, z=1.96):
    """Wilson score interval. Degrades sanely at k==0 and k==n, unlike Wald."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, centre - half), min(1.0, centre + half))


def mcnemar_exact(b, c):
    """Two-sided exact McNemar p-value for discordant counts (b, c).

    Under the null the b+c discordant pairs split 50/50, so this is a two-sided
    binomial test at p=0.5. Concordant pairs carry no information about which
    scheme is better and are correctly ignored.
    """
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


# (arm, task_id, trial) -> the exception string, for `transport` rows only.
TRANSPORT_DETAIL = {}


def load(path, key, label=None):
    """(arm -> {(task_id, trial): outcome}).

    `key` names the field separating arms within one file (`scheme` for Arm B,
    `condition` for Arm A). `label` overrides it, which is what makes the two
    arms comparable at all: they use different field names for the same idea,
    and both key the trial on (task_id, trial) with the same seeds, so they pair
    cleanly once the arms are given names that do not collide.
    """
    by = defaultdict(dict)
    for line in open(path):
        if not line.strip():
            continue
        r = json.loads(line)
        arm = label
        if arm is None:
            # Arm A files carry `condition`, Arm B files carry `scheme`. Trying
            # each candidate in turn lets one command span both without a
            # relabel that would collapse several schemes onto one trial key.
            for k in key.split(","):
                if k in r:
                    arm = r[k]
                    break
            else:
                raise SystemExit(f"{path}: no field among {key} in a trial row")
        by[arm][(r["task_id"], r["trial"])] = r["outcome"]
        if r["outcome"] == "transport":
            # Kept beside the outcome rather than in it, so `Counter` still
            # sees one class while the printout can name what failed. A 4xx
            # here would be a fault in this harness rather than in the server,
            # and the difference must not be absorbed into a count.
            TRANSPORT_DETAIL[(arm, r["task_id"], r["trial"])] = r.get("detail", "")
    return by


def report(name, outcomes):
    # A transport failure is not an outcome this benchmark measures: the request
    # never produced a completion, so it is out of the denominator as well as
    # out of the pairing. Counted and printed rather than dropped, because the
    # ten that were found were found by grepping. See `armb.grade_one`.
    gone = [k for k, v in outcomes.items() if v == "transport"]
    outcomes = {k: v for k, v in outcomes.items() if v != "transport"}
    n = len(outcomes)
    counts = Counter(outcomes.values())
    k = counts["correct"]
    lo, hi = wilson(k, n)
    print(f"\n{name}   n={n}")
    if gone:
        seen = sorted({TRANSPORT_DETAIL.get((name,) + g, "") for g in gone})
        print(f"  transport failures {len(gone)} excluded from n"
              f"   ({'; '.join(s for s in seen if s)})")
    print(f"  correct            {k}/{n} = {100*k/n:5.1f}%   "
          f"95% CI {100*lo:.1f}-{100*hi:.1f}")
    # Silent corruption is the number this project exists to move: the document
    # was changed, wrongly, with nothing raised. `op_error` is excluded because
    # it is loud -- it costs a turn, not a document.
    silent = sum(v for kk, v in counts.items()
                 if kk in ("destructive", "wrong",
                           "collateral:formatting", "collateral:content"))
    slo, shi = wilson(silent, n)
    print(f"  silent corruption  {silent}/{n} = {100*silent/n:5.1f}%   "
          f"95% CI {100*slo:.1f}-{100*shi:.1f}")
    for kk, v in counts.most_common():
        print(f"    {kk:24s} {v:4d}")


def compare(a_name, a, b_name, b):
    """Paired comparison over the trials the two arms actually share."""
    shared = sorted(set(a) & set(b))
    only_a, only_b = len(set(a) - set(b)), len(set(b) - set(a))
    # A transport failure in *either* arm drops the pair from *both*. The
    # trial produced no completion on one side, so the pair carries no
    # information about the change under test -- and leaving it in charges a
    # server fault to whichever arm happened to hit it, which is exactly how
    # F-compose's sections row came to read 14-1 instead of 13-1. Reported
    # rather than silently excluded.
    dropped = [k for k in shared
               if a[k] == "transport" or b[k] == "transport"]
    shared = [k for k in shared if k not in set(dropped)]
    if not shared:
        print(f"\n{a_name} vs {b_name}: no shared (task, trial) pairs -- "
              "not comparable as paired data")
        return
    aw = [a[k] == "correct" for k in shared]
    bw = [b[k] == "correct" for k in shared]
    both = sum(1 for x, y in zip(aw, bw) if x and y)
    neither = sum(1 for x, y in zip(aw, bw) if not x and not y)
    only_a_win = sum(1 for x, y in zip(aw, bw) if x and not y)
    only_b_win = sum(1 for x, y in zip(aw, bw) if y and not x)
    p = mcnemar_exact(only_a_win, only_b_win)

    print(f"\n{'='*70}\nPAIRED: {a_name} vs {b_name}   ({len(shared)} shared trials)")
    if dropped:
        print(f"  note: {len(dropped)} pair(s) dropped for a transport failure "
              f"in one arm or the other: "
              + ", ".join(f"{t}/t{tr}" for t, tr in dropped))
    if only_a or only_b:
        print(f"  note: {only_a} trials only in {a_name}, {only_b} only in "
              f"{b_name} -- excluded from the pairing")
    print(f"  both correct        {both}")
    print(f"  neither correct     {neither}")
    print(f"  only {a_name:14s} {only_a_win}")
    print(f"  only {b_name:14s} {only_b_win}")
    print(f"  McNemar exact p = {p:.4g}"
          + ("" if p < 0.05 else "   (not significant at 0.05)"))
    if only_a_win + only_b_win == 0:
        print("  the two arms were trial-for-trial identical: the change moved "
              "nothing, and n is irrelevant to that")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--graded", required=True, nargs="+",
                    help="graded .jsonl files, each optionally `label=path` to "
                         "name the arm explicitly instead of reading --key")
    ap.add_argument("--key", default="scheme,condition",
                    help="comma-separated candidate fields naming the arm; the "
                         "first present in each row wins (`scheme`, `condition`)")
    ap.add_argument("--compare", default="",
                    help="two arm names, comma separated, for a paired test")
    args = ap.parse_args()

    by = defaultdict(dict)
    for spec in args.graded:
        label, _, path = spec.rpartition("=")
        for k, v in load(path, args.key, label or None).items():
            by[k].update(v)

    for name in sorted(by):
        report(name, by[name])

    if args.compare:
        a_name, b_name = args.compare.split(",")
        missing = [n for n in (a_name, b_name) if n not in by]
        if missing:
            raise SystemExit(f"not in the data: {', '.join(missing)}; "
                             f"have {', '.join(sorted(by))}")
        compare(a_name, by[a_name], b_name, by[b_name])
    return 0


if __name__ == "__main__":
    sys.exit(main())
