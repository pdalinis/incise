#!/usr/bin/env python3
"""S14: does a tool result that names the change stop the redundant turn?

Reads a `--replay` output file, where every prefix -- a task, a seed, and one
already-successful first call -- was re-sampled under each result shape. The
comparison is paired by prefix, so the test is McNemar's rather than Fisher's,
and the concordant prefixes (the ~96% that stop under every shape) correctly
carry no weight.

Two endpoints, and they are not the same question:

  continued     did the model make another call after being told the first one
                worked? This is the behaviour S13 found, measured directly.
  outcome       what did the document end up as? A shape that suppresses the
                redundant turn is only a win if it does not also suppress the
                *needed* second call, which is why the three multi-call tasks
                are reported separately rather than pooled away.

  python3 bench/s14_analyse.py --replay bench/results/armb_s14_2call.jsonl
"""

import argparse
import json
import os
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bench"))

from armb import grade_one  # noqa: E402
from stats import mcnemar_exact, wilson  # noqa: E402

# The three tasks whose answer key is more than one call. Everywhere else a
# second call is by definition redundant; here it is required, and a shape that
# stops it is worse, not better. Kept explicit rather than derived so that the
# split is visible in the output next to the numbers it governs.
MULTI = {"insert-release-at-top", "insert-nested-ratelimits",
         "insert-troubleshooting"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--replay", required=True, nargs="+")
    ap.add_argument("--tasks", default=os.path.join(ROOT, "bench/tasks/sections.json"))
    ap.add_argument("--baseline", default="outline")
    args = ap.parse_args()

    tasks = {t["id"]: t for t in json.load(open(args.tasks))["tasks"]}
    rows = [json.loads(l) for f in args.replay for l in open(f) if l.strip()]

    # (scheme, task, trial) -> shape -> row. The key is the prefix; the shape
    # is the treatment. Several schemes pool here and that is sound, because
    # every comparison is within a prefix -- the scheme is a blocking factor,
    # not a second treatment. A prefix missing any shape is dropped, since an
    # unpaired observation in a paired test silently unbalances it.
    cells = defaultdict(dict)
    shapes = []
    for r in rows:
        sh = r.get("shape")
        if sh and sh not in shapes:
            shapes.append(sh)
        base = (r.get("scheme") or "").rsplit(":", 1)[0]
        cells[(base, r["task_id"], r["trial"])][sh] = r
    complete = {k: v for k, v in cells.items() if len(v) == len(shapes)}
    dropped = len(cells) - len(complete)
    print(f"{len(complete)} complete prefixes x {len(shapes)} shapes"
          + (f"  ({dropped} incomplete, dropped)" if dropped else ""))
    by_scheme = Counter(k[0] for k in complete)
    print("  prefixes per source scheme: "
          + ", ".join(f"{k}={v}" for k, v in sorted(by_scheme.items())))
    if args.baseline not in shapes:
        print(f"baseline {args.baseline!r} not in {shapes}")
        return 1

    graded = {}
    for k, byshape in complete.items():
        for sh, r in byshape.items():
            graded[(k, sh)] = grade_one(tasks[r["task_id"]], r)[0]

    # Whether the *first* call alone already produced the right document.
    # S13 counted a prefix as "already succeeded" when the call applied without
    # an error, which is what an executor can see -- but a call can apply
    # cleanly and still rename the wrong section, and a model that then keeps
    # going is not being redundant, it is being right. Both populations are
    # reported. The looser one is primary because it is the one S13 measured
    # and narrowing it after the fact would be choosing the definition that
    # flatters the result.
    first_ok = {}
    for k, byshape in complete.items():
        r = next(iter(byshape.values()))
        stub = dict(r, tool_calls=(r.get("tool_calls") or [])[:1])
        first_ok[k] = grade_one(tasks[r["task_id"]], stub)[0] == "correct"

    for label, keys in (
            ("single-call tasks (a second call is redundant)",
             [k for k in complete if k[1] not in MULTI]),
            ("single-call tasks where the first call was already right",
             [k for k in complete if k[1] not in MULTI and first_ok[k]]),
            ("multi-call tasks (a second call is required)",
             [k for k in complete if k[1] in MULTI]),
            ("all tasks", list(complete))):
        print(f"\n{'='*74}\n{label}  (n={len(keys)} prefixes)\n{'='*74}")
        print(f"{'shape':10s} {'continued':>12s}  {'correct':>10s} "
              f"{'destructive':>12s} {'other':>8s}")
        for sh in shapes:
            cont = sum(1 for k in keys if complete[k][sh].get("continued"))
            out = Counter(graded[(k, sh)] for k in keys)
            lo, hi = wilson(cont, len(keys)) if keys else (0, 0)
            print(f"{sh:10s} {cont:4d}/{len(keys):<4d} "
                  f"{100*cont/max(1,len(keys)):5.1f}%  {out['correct']:10d} "
                  f"{out['destructive']:12d} "
                  f"{len(keys)-out['correct']-out['destructive']:8d}"
                  f"   [{100*lo:.1f}-{100*hi:.1f}]")

        for sh in shapes:
            if sh == args.baseline:
                continue
            for metric, fn in (("continued",
                                lambda k, s: bool(complete[k][s].get("continued"))),
                               ("correct",
                                lambda k, s: graded[(k, s)] == "correct")):
                b = sum(1 for k in keys
                        if fn(k, args.baseline) and not fn(k, sh))
                c = sum(1 for k in keys
                        if not fn(k, args.baseline) and fn(k, sh))
                p = mcnemar_exact(b, c)
                arrow = "->" if metric == "continued" else "->"
                print(f"  McNemar {metric:9s} {args.baseline} {arrow} {sh:8s} "
                      f"only-{args.baseline}={b:3d} only-{sh}={c:3d}  "
                      f"p = {p:.4g}")

    # What the redundant turns actually did. The 4/11 destructive rate is the
    # reason this experiment exists, so the same slice is printed here rather
    # than left to be recomputed from the raw file.
    print(f"\n{'='*74}\nwhat happened when the model continued anyway "
          f"(single-call tasks)\n{'='*74}")
    for sh in shapes:
        keys = [k for k in complete
                if k[1] not in MULTI and complete[k][sh].get("continued")]
        out = Counter(graded[(k, sh)] for k in keys)
        print(f"  {sh:10s} n={len(keys):<4d} {dict(out) or '-'}")
        for k in keys:
            calls = complete[k][sh].get("tool_calls") or []
            extra = [json.loads(c["function"].get("arguments") or "{}")
                     for c in calls[1:]]
            acts = ", ".join(str(e.get("action") or e.get("op") or "?")
                             for e in extra)
            print(f"      {k[0]:14s} {k[1]:26s} t{k[2]:<2d} "
                  f"{graded[(k, sh)]:12s} +{acts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
