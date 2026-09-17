#!/usr/bin/env python3
"""Does the model name the file, and can Arm B tell?

F-nofile left one thing open: the section family supplies a file on only 9-26%
of repair turns under every message tested, against 83-96% for lists, and that
was recorded as "an S15-shaped problem -- the schema, not the sentence". This
locates it, from the trials already on disk, before any new ones are run.

Two questions, in the order that matters:

  **can the harness see it?** `armb.run_trial` opens `task["fixture"]` itself
  and passes the *content* to `apply_op`. The model's `path` rides along in
  `op_args` and the core ignores it. So Arm B grades a call that names no file,
  or names the wrong one, exactly as it grades a correct one. `check()` below
  demonstrates that rather than asserting it -- the same op, three ways, one
  result.

  **where did it go?** Every recorded first tool call, split by action. It is
  not a family effect and not an era effect: `section-insert` omits the file on
  ~92% of calls under the adopted `section_g` family and ~10% under its untuned
  predecessors, while every *other* section action got better across the same
  transition. The two are paired by (task, trial), which is S15's design.

The join of the two is the finding: the schema that omits the file was selected
by an arm that could not score the omission.

`arm_c()` is the third question, and it is the one that puts a price on the
first two. Arm C runs the real binary, which *does* read `path`, so it is the
only arm on disk that ever scored this argument. It scored it as the whole
difference: of 149 section trials, the 114 whose opening call named a file
finished `correct` 112 times, and the 35 that did not finished `correct` 8
times, four turns of recovery included. That split is **observational** -- the
model chose, nobody assigned -- so `within_task()` re-runs it holding the task
fixed, and the p is exact stratified rather than paired, because these are not
pairs.

    python3 bench/file_argument.py
"""

import collections
import glob
import json
import os
import sys
from math import comb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bench"))

import armb  # noqa: E402
from incise_ops import apply_op  # noqa: E402
from stats import mcnemar_exact, wilson  # noqa: E402

# The untuned section schemes, against everything downstream of `section_g`.
# `section_naive` and `section_p` differ from each other on the rename key
# (`heading` vs `new_heading`) and agree here, which is what makes the split
# readable: the thing that moved is not that key.
EARLY = {"section_naive", "section_p"}


def _rows(relpath):
    """Every JSON object in a results file. `newline=""` is not optional here:
    plain `open()` rewrites CRLF, and these files record byte-exact documents."""
    out = []
    for line in open(os.path.join(ROOT, relpath), newline=""):
        if line.strip():
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def has_file(args):
    return isinstance(args.get("path"), str) and bool(args["path"])


def first_calls():
    """(task, trial, scheme, tool, args) for every trial's opening call."""
    for path in sorted(glob.glob(os.path.join(ROOT, "bench/results/*.jsonl"))):
        if path.endswith("_graded.jsonl"):
            continue
        for line in open(path, newline=""):
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            made = r.get("tool_calls") or []
            if not made:
                continue
            fn = made[0].get("function") or {}
            if fn.get("name") not in armb.ACTIONS:
                continue
            try:
                a = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                continue
            if isinstance(a, dict):
                yield (r.get("task_id"), r.get("trial"),
                       (r.get("scheme") or "?").rsplit(":", 1)[0],
                       fn["name"], a)


def can_arm_b_see_it():
    """The same insert, three ways. If all three agree, `path` is not graded."""
    task = [t for t in json.load(
        open(os.path.join(ROOT, "bench/tasks/sections.json")))["tasks"]
        if t["id"] == "insert-subsection-last"][0]
    doc = open(os.path.join(ROOT, task["fixture"]), newline="").read()
    base = {"action": "insert", "new_heading": "FreeBSD",
            "position": "last-child", "body": "Use pkg.",
            "section": {"heading": "Deep heading nesting > Install"}}
    out = {}
    for label, extra in (("no `path` at all", {}),
                         ("the right file", {"path": task["fixture"]}),
                         ("a file that does not exist",
                          {"path": "/nowhere/absent.md"})):
        op, op_args = armb.normalize("section_edit", dict(base, **extra))
        after, err = apply_op(doc, op, op_args)
        out[label] = (err, None if after is None else hash(after))
    print("CAN ARM B SEE THE FILE ARGUMENT?")
    for label, (err, h) in out.items():
        print(f"  {label:28s} error={err!r:6s} result={h}")
    same = len({v for v in out.values()}) == 1
    print(f"  -> all three identical: {same}."
          + ("  Arm B cannot score this argument." if same else ""))
    return same


def by_action():
    tot = collections.Counter()
    miss = collections.Counter()
    for _task, _trial, _scheme, tool, a in first_calls():
        act = a.get("action")
        key = (tool, act if isinstance(act, str) else "?")
        tot[key] += 1
        if not has_file(a):
            miss[key] += 1
    print("\nFIRST CALLS THAT NAME NO FILE, by action")
    print(f"  {'tool/action':32s} {'calls':>7s} {'no file':>9s} {'rate':>7s}")
    for k in sorted(tot, key=lambda k: -tot[k]):
        if tot[k] < 10:
            continue
        print(f"  {k[0] + '/' + str(k[1]):32s} {tot[k]:7d} {miss[k]:9d}"
              f" {100 * miss[k] / tot[k]:6.1f}%")


def by_era():
    """Every section action, untuned schemes against the adopted family."""
    per = collections.defaultdict(lambda: [0, 0])
    for _task, _trial, scheme, tool, a in first_calls():
        if tool != "section_edit":
            continue
        act = a.get("action")
        era = "early" if scheme in EARLY else "g-family"
        key = (era, act if isinstance(act, str) else "?")
        per[key][0] += 1
        if not has_file(a):
            per[key][1] += 1
    print("\nSECTION ACTIONS: untuned schemes vs the adopted family")
    print(f"  {'action':14s} {'section_naive/_p':>20s} {'section_g family':>20s}")
    for act in sorted({k[1] for k in per}):
        cells = []
        for era in ("early", "g-family"):
            n, m = per.get((era, act), [0, 0])
            cells.append(f"{m}/{n} ({100 * m / n:.1f}%)" if n else "-")
        print(f"  {act:14s} {cells[0]:>20s} {cells[1]:>20s}")


def paired():
    """`section_p` vs `section_g` on insert, paired by (task, trial).

    S15's design: same task, same seed, one factor. The endpoint is whether the
    opening call named a file -- not the grade, because the grade cannot see it.
    """
    arms = {}
    for task, trial, scheme, tool, a in first_calls():
        if tool != "section_edit" or a.get("action") != "insert":
            continue
        if scheme in ("section_p", "section_g"):
            arms.setdefault(scheme, {})[(task, trial)] = has_file(a)
    p, g = arms.get("section_p", {}), arms.get("section_g", {})
    shared = sorted(set(p) & set(g))
    only_p = sum(1 for k in shared if p[k] and not g[k])
    only_g = sum(1 for k in shared if g[k] and not p[k])
    print(f"\nPAIRED on insert: section_p vs section_g "
          f"({len(shared)} shared (task, trial))")
    print(f"  named a file under section_p only: {only_p}")
    print(f"  named a file under section_g only: {only_g}")
    if shared:
        print(f"  McNemar exact p = {mcnemar_exact(only_p, only_g):.4g}")
    print("  tasks:", sorted({k[0] for k in shared}))


def cmh_exact(strata):
    """One-sided exact stratified test. `strata` is [(n, m, k, x), ...].

    Per stratum: n trials, m of which named a file, k of which finished
    `correct`, x of those correct ones among the file-namers. Under the null
    that naming a file is unrelated to the outcome, x is hypergeometric with
    the margins held -- so the null distribution of `sum(x)` is the convolution
    of the per-stratum hypergeometrics, and p is its upper tail at the observed
    sum. This is the exact form of Cochran-Mantel-Haenszel.

    McNemar is not the test here and `stats.mcnemar_exact` is deliberately not
    reused: every paired comparison in this project assigned the thing under
    test, and nothing assigned this one. The model decided whether to name a
    file. Holding the task fixed is the most this data supports, and a
    stratified test is what that design is.
    """
    dist = {0: 1.0}
    for n, m, k, _x in strata:
        lo, hi = max(0, m + k - n), min(m, k)
        cell = {}
        for i in range(lo, hi + 1):
            cell[i] = (comb(m, i) * comb(n - m, k - i)) / comb(n, k)
        nxt = collections.defaultdict(float)
        for s, ps in dist.items():
            for i, pi in cell.items():
                nxt[s + i] += ps * pi
        dist = nxt
    obs = sum(s[3] for s in strata)
    return sum(p for s, p in dist.items() if s >= obs)


def arm_c(family="sections"):
    """The arm that can score `path`, and what it scored.

    Arm C drives the real binary through `incise-cli`, so a missing `path` is a
    real failure with a real exit code rather than an argument the grader never
    looks at. Two tables: the outcome split, and the same split with the task
    held fixed, since `insert` is both the action that omits the file and a
    plausibly harder action.
    """
    raw = {(r["task_id"], r["trial"]): r
           for r in _rows(f"bench/results/armc_{family}.jsonl")}
    graded = {(r["task_id"], r["trial"]): r.get("outcome")
              for r in _rows(f"bench/results/armc_{family}_graded.jsonl")}

    seen = {}
    for key, r in raw.items():
        calls = r.get("tool_calls") or []
        if not calls:
            continue
        fn = calls[0].get("function") or {}
        try:
            a = json.loads(fn.get("arguments") or "{}")
        except ValueError:
            continue
        if not isinstance(a, dict) or key not in graded:
            continue
        seen[key] = (has_file(a), a.get("action"), graded[key],
                     (r.get("exit_codes") or [None])[0])

    print(f"\nARM C ({family}): THE ARM THAT CAN SEE `path`")
    codes = collections.Counter((v[0], v[3]) for v in seen.values())
    for (hasp, code) in sorted(codes, key=lambda k: (not k[0], str(k[1]))):
        print(f"  first call named a file={hasp!s:5s}  first exit="
              f"{code!s:5s}  {codes[(hasp, code)]:4d}")

    print(f"\n  FINAL OUTCOME, {raw and len(seen)} trials, four turns to recover")
    for hasp in (True, False):
        sub = collections.Counter(v[2] for v in seen.values() if v[0] == hasp)
        tot = sum(sub.values())
        if not tot:
            continue
        ok = sub.get("correct", 0)
        lo, hi = wilson(ok, tot)
        print(f"    named a file={hasp!s:5s} n={tot:4d}   correct {ok:4d} "
              f"= {100 * ok / tot:5.1f}%   95% CI {100*lo:.1f}-{100*hi:.1f}")
        for o in sorted(sub, key=lambda o: -sub[o]):
            print(f"        {o:20s} {sub[o]:4d}")
    omit = collections.Counter(v[1] for v in seen.values() if not v[0])
    print("    actions among the omitters:", dict(omit))
    within_task(seen)


def within_task(seen):
    """The same split with the task held fixed.

    `insert` is the action that omits the file, so the unconditional split
    confounds the argument with the action. This removes that: only tasks where
    both happened contribute, which is also why n collapses -- the omission is
    so near-total on insert that there is barely any contrast left to look at.
    That thinness is reported rather than smoothed over.
    """
    per = collections.defaultdict(lambda: {True: [0, 0], False: [0, 0]})
    for (task, _trial), (hasp, act, out, _code) in seen.items():
        cell = per[(task, act)][hasp]
        cell[0] += 1
        cell[1] += (out == "correct")

    print("\n  WITH THE TASK HELD FIXED (only tasks where both happened)")
    print(f"    {'task / action':42s} {'named a file':>14s} {'named none':>14s}")
    strata, tot = [], {True: [0, 0], False: [0, 0]}
    for key in sorted(per):
        y, n = per[key][True], per[key][False]
        if not (y[0] and n[0]):
            continue
        strata.append((y[0] + n[0], y[0], y[1] + n[1], y[1]))
        for hasp, cell in ((True, y), (False, n)):
            tot[hasp][0] += cell[0]
            tot[hasp][1] += cell[1]
        print(f"    {key[0] + '/' + str(key[1]):42s} "
              f"{f'{y[1]}/{y[0]}':>14s} {f'{n[1]}/{n[0]}':>14s}")
    if not strata:
        print("    no task saw both -- the split cannot be deconfounded here")
        return
    y, n = tot[True], tot[False]
    print(f"    {'TOTAL':42s} {f'{y[1]}/{y[0]}':>14s} {f'{n[1]}/{n[0]}':>14s}")
    print(f"    {'':42s} {100 * y[1] / y[0]:13.1f}% {100 * n[1] / n[0]:13.1f}%")
    print(f"    exact stratified (CMH) p = {cmh_exact(strata):.4g}"
          f"   over {len(strata)} task strata")


# S15's three arms, and which key each one calls the file. Every description
# string is byte-identical across the three; only the key moves. That is what
# makes re-reading them on a new endpoint legitimate -- the arms were assigned
# and paired by (task, trial), so this is not the observational split `arm_c`
# reports, it is the experiment, asked a question nobody asked it at the time.
S15_ARMS = {"section_g": "path",        # control
            "section_g_file": "file",   # the top-level name moved
            "section_g_hpath": "path"}  # the address name moved instead
S15_ACTIONS = ("append", "delete", "insert", "rename",
               "replace-body", "set-level")


def _s15_first_calls(arm):
    out = {}
    for r in _rows(f"bench/results/armb_s15_{arm}.jsonl"):
        calls = r.get("tool_calls") or []
        if not calls:
            continue
        fn = calls[0].get("function") or {}
        try:
            a = json.loads(fn.get("arguments") or "{}")
        except ValueError:
            continue
        if isinstance(a, dict):
            out[(r["task_id"], r["trial"])] = a
    return out


def s15_reread():
    """S15's rows, on the endpoint S15's arm could not grade.

    S15 asked whether `path` meaning two things -- the file, and the heading
    path inside it -- made the model misfile the heading. It renamed each side
    in turn and found the two disambiguations *identical*: 9 misfilings to 0,
    same cells, same discordant pairs. It concluded that the collision itself
    was the problem and either fix removes it.

    That is correct on its endpoint. But the arm could not see whether the model
    named a file at all (see `can_arm_b_see_it`), so S15 never checked, and on
    that endpoint the two arms are **not** identical. S15 wrote the inference
    rule down in advance -- *"if only `section_g_file` moves, the top-level name
    is pulling the value"* -- and it is applied here unchanged, to data it was
    written for.

    Multiplicity is real and is reported: this is 6 actions x 2 arms = 12
    post-hoc comparisons on an endpoint chosen after seeing `arm_c`. Bonferroni
    at 12 is the honest bar and the column below says which cells clear it.
    """
    arms = {a: _s15_first_calls(a) for a in S15_ARMS}
    ctrl = "section_g"

    print("\nS15 RE-READ: the assigned experiment, on the endpoint it could not"
          " grade")
    print("  (endpoint: did the opening call name a file -- not whether it"
          " graded correct)")
    for arm, key in S15_ARMS.items():
        d = arms[arm]
        n = sum(1 for a in d.values() if _named(a, key))
        print(f"    {arm:18s} key=`{key}`  {n:3d}/{len(d)} opening calls named"
              " a file")

    tasks = {t["id"]: t["fixture"] for t in json.load(
        open(os.path.join(ROOT, "bench/tasks/sections.json")))["tasks"]}
    print("\n  AND WAS IT THE RIGHT FILE? (insert only, where the gap is)")
    for arm, key in S15_ARMS.items():
        ks = [k for k, a in arms[arm].items() if a.get("action") == "insert"]
        named = [k for k in ks if _named(arms[arm][k], key)]
        right = [k for k in named if arms[arm][k][key] == tasks.get(k[0])]
        print(f"    {arm:18s} named {len(named):3d}/{len(ks):3d}, and "
              f"{len(right)} of those were the task's own fixture")

    for arm in ("section_g_file", "section_g_hpath"):
        print(f"\n  PAIRED: {ctrl} vs {arm}, by (task, trial)")
        _paired_table(arms[ctrl], S15_ARMS[ctrl], arms[arm], S15_ARMS[arm],
                      correction=12)


def _paired_table(ctrl, ctrl_key, arm, arm_key, correction=1):
    """Discordant pairs per action, on the file endpoint. Returns per-action.

    `correction` is the number of comparisons the table is one of, printed as a
    column rather than applied silently, so a reader can see both the raw p and
    the bar it is being held to. A pre-registered single endpoint takes 1; a
    post-hoc sweep takes the size of the sweep.
    """
    head = f"Bonf. {correction}" if correction > 1 else "p<0.05"
    print(f"    {'action':14s} {'n':>4s} {'ctrl-only':>10s}"
          f" {'arm-only':>9s} {'p':>10s}  {head:>9s}")
    tot, rows = [0, 0], {}
    for act in S15_ACTIONS:
        shared = [k for k in set(ctrl) & set(arm)
                  if ctrl[k].get("action") == act and arm[k].get("action") == act]
        if not shared:
            continue
        b = sum(1 for k in shared if _named(ctrl[k], ctrl_key)
                and not _named(arm[k], arm_key))
        c = sum(1 for k in shared if _named(arm[k], arm_key)
                and not _named(ctrl[k], ctrl_key))
        tot[0] += b
        tot[1] += c
        p = mcnemar_exact(b, c)
        rows[act] = (len(shared), b, c, p)
        print(f"    {act:14s} {len(shared):4d} {b:10d} {c:9d} {p:10.3g}"
              f"  {'yes' if p * correction < 0.05 else 'no':>9s}")
    print(f"    {'POOLED':14s} {'':4s} {tot[0]:10d} {tot[1]:9d}"
          f" {mcnemar_exact(*tot):10.4g}")
    return rows


S16_RUN = "bench/results/armb_s16_section_g_both.jsonl"
S16_N = 150   # 15 section tasks x 10 trials, the registered size


def s16():
    """The pre-registered combination arm, against S15's stored control.

    Registration is in FINDINGS under "S16 -- pre-registration", committed
    before the arm ran. Reported in that order and not reordered by what the
    numbers turned out to be:

      primary  insert, does the opening call name a file, paired McNemar;
      harm     rename, where `section_g_file` was 10-1 backwards;
      then     the pooled table and the graded outcome, the latter with the
               standing caveat that the grade cannot see this argument at all.
    """
    if not os.path.exists(os.path.join(ROOT, S16_RUN)):
        print("\nS16: not run yet -- no", S16_RUN)
        return
    ctrl = _s15_first_calls("section_g_hpath")
    arm = {}
    for r in _rows(S16_RUN):
        calls = r.get("tool_calls") or []
        if not calls:
            continue
        fn = calls[0].get("function") or {}
        try:
            a = json.loads(fn.get("arguments") or "{}")
        except ValueError:
            continue
        if isinstance(a, dict):
            arm[(r["task_id"], r["trial"])] = a

    print("\nS16: section_g_hpath (control, adopted) vs section_g_both")
    print(f"  control {len(ctrl)} trials, arm {len(arm)} trials, "
          f"{len(set(ctrl) & set(arm))} shared (task, trial)")

    # A partial run is the one state where this function can do real damage:
    # the tasks are emitted in file order, so the first rows are all `insert`,
    # and reading the registration off them would announce a verdict on the
    # arm's best-covered action before any other action has been sampled at
    # all. S16_N is the run's size; below it, the tables print and the verdict
    # does not.
    complete = len(arm) >= S16_N
    if not complete:
        print(f"  ** INCOMPLETE: {len(arm)} of {S16_N} trials. Tables below are"
              " interim and the\n  ** registration is NOT evaluated -- the task"
              " order front-loads `insert`.")

    tasks = {t["id"]: t["fixture"] for t in json.load(
        open(os.path.join(ROOT, "bench/tasks/sections.json")))["tasks"]}
    print("\n  PRIMARY: insert, did the opening call name a file")
    for label, d, key in (("section_g_hpath", ctrl, "path"),
                          ("section_g_both", arm, "file")):
        ks = [k for k, a in d.items() if a.get("action") == "insert"]
        named = [k for k in ks if _named(d[k], key)]
        right = [k for k in named if d[k][key] == tasks.get(k[0])]
        pct = f"{100 * len(named) / len(ks):.0f}%" if ks else "-"
        print(f"    {label:18s} {len(named):3d}/{len(ks):<3d} ({pct})"
              f"   of those, {len(right)} were the task's own fixture")

    print("\n  PAIRED by (task, trial), endpoint = opening call named a file")
    rows = _paired_table(ctrl, "path", arm, "file", correction=1)
    if not complete:
        return
    ins, ren = rows.get("insert"), rows.get("rename")
    print("\n  AGAINST THE REGISTRATION")
    if ins:
        n, b, c, p = ins
        met = c > b and p < 0.05
        print(f"    primary (insert)  {b}-{c}, p={p:.4g}  -> "
              + ("prediction held" if met else
                 "PREDICTION NOT MET -- the falsifier named in advance"))
    if ren:
        n, b, c, p = ren
        print(f"    harm (rename)     {b}-{c}, p={p:.4g}  -> "
              + ("no harm detected" if c >= b else
                 f"HARM PRESENT: {b} trials lost the file under the arm"))
    _s16_graded(set(ctrl) & set(arm))


def _s16_graded(shared):
    """The registered secondary, reported with the reason it proves little.

    The grade cannot see the file argument (`can_arm_b_see_it`), so this is not
    the endpoint and is not evidence about it. It is here because it was
    registered, and because an arm that traded the endpoint for a large drop in
    correctness would be worth knowing about even though the grade is blind to
    the mechanism.
    """
    ctrl_f = "bench/results/armb_s15_section_g_hpath_graded.jsonl"
    arm_f = "bench/results/armb_s16_section_g_both_graded.jsonl"
    for f in (ctrl_f, arm_f):
        if not os.path.exists(os.path.join(ROOT, f)):
            print(f"\n  SECONDARY: not graded yet -- no {f}")
            return
    out = {}
    for label, f in (("section_g_hpath", ctrl_f), ("section_g_both", arm_f)):
        out[label] = {(r["task_id"], r["trial"]): r["outcome"]
                      for r in _rows(f)}
    keys = sorted(shared & set(out["section_g_hpath"]) & set(out["section_g_both"]))
    print(f"\n  SECONDARY (registered): graded outcome, {len(keys)} shared trials")
    print("    the grade cannot see `file`; this is not the endpoint")
    for label in ("section_g_hpath", "section_g_both"):
        sub = collections.Counter(out[label][k] for k in keys)
        ok = sub.get("correct", 0)
        lo, hi = wilson(ok, len(keys))
        print(f"    {label:18s} correct {ok:3d}/{len(keys)} = "
              f"{100 * ok / len(keys):5.1f}%   95% CI {100*lo:.1f}-{100*hi:.1f}")
    b = sum(1 for k in keys if out["section_g_hpath"][k] == "correct"
            and out["section_g_both"][k] != "correct")
    c = sum(1 for k in keys if out["section_g_both"][k] == "correct"
            and out["section_g_hpath"][k] != "correct")
    print(f"    discordant {b}-{c}, McNemar exact p = {mcnemar_exact(b, c):.4g}")


def _named(args, key):
    v = args.get(key)
    return isinstance(v, str) and bool(v)


def _check_cmh():
    """`cmh_exact` verifies itself every time a number is regenerated from it.

    Neither `stats.mcnemar_exact` nor `stats.wilson` has a test anywhere in the
    tree -- they are used by five analysis scripts on trust. That is tolerable
    for a function whose output has been read a hundred times; it is not
    tolerable for one written this week that a p-value in FINDINGS rests on. The
    three anchors below are hand-computable, so a wrong convolution cannot pass:

      * one stratum is Fisher's exact test, one-sided, and nothing else;
      * a stratum where no trial succeeded carries no information, so p is 1;
      * duplicating a stratum must tighten p, never loosen it.
    """
    one = comb(5, 5) * comb(5, 0) / comb(10, 5)
    two = one + comb(5, 4) * comb(5, 1) / comb(10, 5)
    for got, want, what in (
            (cmh_exact([(10, 5, 5, 5)]), one, "one stratum is Fisher, 5 of 5"),
            (cmh_exact([(10, 5, 5, 4)]), two, "one stratum is Fisher, 4 of 5"),
            (cmh_exact([(10, 5, 0, 0)]), 1.0, "no successes carries no signal")):
        if abs(got - want) > 1e-12:
            raise SystemExit(f"cmh_exact is wrong: {what} -> {got}, not {want}")
    if not cmh_exact([(10, 5, 5, 5)] * 2) < cmh_exact([(10, 5, 5, 5)]):
        raise SystemExit("cmh_exact is wrong: replication did not tighten p")


def main():
    _check_cmh()
    can_arm_b_see_it()
    by_action()
    by_era()
    paired()
    arm_c()
    s15_reread()
    s16()


if __name__ == "__main__":
    main()
