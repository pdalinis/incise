#!/usr/bin/env python3
"""Replay every recorded tool call through the executor and hash the outcome.

Written to answer one question with evidence instead of argument: **can the
argument layer in `incise_ops.py` be fixed without disturbing a single recorded
grade?**

The ill-typed-argument survey (FINDINGS F-args) found paths that crash the
executor outright and paths that silently default -- `position: "0"` appends at
the end and reports success. Those are bugs worth fixing, but `incise_ops.py` is
the graded executor for 4009 trials, and changing a graded executor is how a
result quietly becomes a different result.

So: snapshot every recorded call's outcome before the change, snapshot after,
and require them to be identical. If they are, the fix touched only paths no
trial ever took, and every number in FINDINGS still stands. If they are not, the
diff says exactly which trials moved and the change has to be argued rather than
assumed.

  python3 bench/regrade_snapshot.py before.json
  # ...make the change...
  python3 bench/regrade_snapshot.py after.json --compare before.json

Both snapshots must come from the same version of *this* script. A digest is a
hash over a fixed fixture vector, so widening the fixture list or changing how a
call is executed moves every digest at once and a cross-version `--compare` is
noise. The 2026-09-17 commit did both, which is why F-remedy re-took its
"before" snapshot rather than reusing one from that morning.

They must also be taken with no arm running. `moved` is computed over the
*union* of the two key sets, so a trial appended to `bench/results/` between the
two snapshots is reported as a changed call reading `was None`. F-agree's
verification hit this: 24 of 13422 "CHANGED", all of them rows the live
F-realign gate wrote while the pair was being taken, and every key present in
both sides identical. Read the `was` column before reading the count.

A moved digest says only *that* a call's behaviour changed. The standing rule is
that each one is confirmed, never argued from the shape of the change, so there
is a second pass that replays just those calls and keeps the strings:

  python3 bench/regrade_snapshot.py after.json --compare before.json \
      --moved-out moved.txt
  git stash push -- bench/incise_ops.py
  python3 bench/regrade_snapshot.py vec_before.json --keys moved.txt --vectors
  git stash pop
  python3 bench/regrade_snapshot.py vec_after.json --keys moved.txt --vectors
  python3 bench/regrade_snapshot.py /dev/null --explain vec_before.json vec_after.json
"""

import argparse
import collections
import glob
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bench"))

import armb  # noqa: E402
import incise_ops as F  # noqa: E402


def digest(s):
    return hashlib.sha256(s.encode("utf-8", "surrogatepass")).hexdigest()[:16]


def disposition(name, raw_args):
    """What `replay_all` does with one recorded call, as a decision on its own.

    `{"route": "read"|"edit", "op":…, "args":…, "op_args":…}`, or
    `{"route": "skip", "reason": …}` where the reason is **the exact string
    this script records for that call**. Split out of `replay_all`'s loop
    unchanged, so `replaycheck.py` can ask this module what it executes instead
    of keeping a third copy of the rules; the reasons stay byte-identical
    because they are hashed into snapshots and a reworded one would move every
    such key in a `--compare`.
    """
    try:
        cargs = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
    except ValueError:
        # Arguments that do not parse never reached `normalize` in the trial:
        # `armb.run_trial` calls `json.loads` inside the same `try`, so the
        # model was answered with the decode error and no op ran. Replaying
        # them as `{}` -- which is what this did -- hashed what `section-None`
        # does to 26 files, a vector belonging to no real call, and made these
        # keys move for any change in how a missing field is handled. Three of
        # them are truncated argument blobs (35783 characters in one case)
        # where `action` was present and valid and the model simply ran out of
        # tokens.
        return {"route": "skip", "reason": "arguments-did-not-parse"}
    try:
        op, oargs = armb.normalize(name, cargs)
    except Exception as e:  # noqa: BLE001 -- recording, not handling
        return {"route": "skip", "reason": f"normalize-raised {type(e).__name__}"}
    # Keyed on the tool name, where `headroom.disposition` keys on the op.
    # Equivalent only while `normalize` returns the tool name unchanged for a
    # read; `replaycheck.py` asserts it.
    return {"route": "read" if name in armb.READS else "edit",
            "op": op, "args": cargs, "op_args": oargs}


def replay_all(keys=None, vectors=False):
    """Every tool call in every results file, through normalize + apply_op.

    `keys` restricts the replay to a named set — the moved keys from an earlier
    `--compare` — and `vectors` keeps each call's raw per-corpus-file result
    instead of hashing it. Together they are `--explain`: a digest that moved
    says only *that* something changed, and the standing rule for a moved digest
    (F-dupcol, `FINDINGS:2318-2330`) is that every one is confirmed rather than
    argued from the shape of the change. Confirming it needs the strings back.

    Deliberately executor-level rather than grade-level. `grade_one` needs the
    task definition and only some results files have one; the executor needs
    only the call, so this covers every recorded call including the replay and
    rename arms. It also isolates the thing under test: a grade can move for
    reasons that have nothing to do with the argument layer.

    **It also reads `bench/results/` whole, on purpose, and must not be routed
    through `bench/population.py`.** That module exists because a census of
    what models did was counting replay rows twice, and it now guards
    `ordinal_sizing`, `refusal_pool` and `action_sizing`. This is not a census.
    The question here is whether any *recorded call's* behaviour moves, which
    makes the directory a regression corpus: a replay's re-execution of a call
    is a recorded call, its behaviour moves too, and dropping it would shrink
    coverage to no benefit. Duplicates cost this script runtime, not validity.
    The two kinds of count are expected to disagree where they meet -- F-action
    reaches 21 fused keys here and 11 through `population.py`, differing by
    exactly the ten `armc_framing_lists` copies (`FINDINGS:4701`) -- and that
    reconciliation is the cross-check, not a defect to flatten.

    One consequence worth stating: the call count is dated. It was 5674, then
    7294, then 9455, and is **10072 across 45 files** as of 2026-09-15, because
    every arm appends. A figure quoted from a run is an as-of number. What a
    `--compare` row asserts is unaffected by that -- both sides are the same
    snapshot -- so growth changes the denominator and not the claim.
    """
    out = {}
    fixtures = {}

    def fixture(path):
        if path not in fixtures:
            p = os.path.join(ROOT, path)
            fixtures[path] = open(p, newline="").read() if os.path.exists(p) else None
        return fixtures[path]

    # `corpus/` **and** `bench/synthetic/`. The corpus is frozen and holds no
    # table with a repeated header -- that absence is why the differential suite
    # could not see F-dupcol -- so a replay over the corpus alone cannot reach
    # the branch that refuses one, and reported "no recorded call changed
    # behaviour" for a change that rewrites exactly that refusal (F-remedy).
    # The synthetic fixtures are the documents those trials actually ran
    # against; leaving them out made the vector silent about every finding that
    # needed a fixture the corpus does not contain.
    corpus = sorted(glob.glob(os.path.join(ROOT, "corpus", "**", "*.md"),
                              recursive=True)
                    + glob.glob(os.path.join(ROOT, "bench", "synthetic", "*.md")))

    for f in sorted(glob.glob(os.path.join(ROOT, "bench", "results", "*.jsonl"))):
        rel = os.path.relpath(f, ROOT)
        for lineno, ln in enumerate(open(f)):
            ln = ln.strip()
            if not ln:
                continue
            try:
                rec = json.loads(ln)
            except ValueError:
                continue
            calls = rec.get("tool_calls") or []
            for ci, call in enumerate(calls):
                fn = call.get("function") or {}
                name = fn.get("name")
                raw = fn.get("arguments")
                key = f"{rel}:{lineno}:{ci}"
                if keys is not None and key not in keys:
                    continue
                d = disposition(name, raw)
                if d["route"] == "skip":
                    out[key] = d["reason"]
                    continue
                op, oargs, cargs = d["op"], d["op_args"], d["args"]
                # The fixture the trial actually ran against is not always in
                # the record, so replay against every corpus file and hash the
                # whole vector. A behaviour change anywhere shows up.
                #
                # A read is not an `apply_op` entry (§6.1), and routing one
                # through it hashed the *same* "unknown operation" vector for
                # every recorded `table_get` call -- so this script reported
                # "no recorded call changed behaviour" for a change to the read
                # path that it structurally could not see. Found while checking
                # F-remedy's blast radius, where the answer should have been ten
                # `get-repeated-name` calls and was zero. Reads reach the model
                # the same way an edit's refusal does, so they belong in the
                # snapshot; `armb.read_call` is the same entry point the trials
                # took, and the report is hashed beside the error because a read
                # that changes what it *returns* moves a grade too.
                is_read = d["route"] == "read"
                sig = []
                for c in corpus:
                    content = fixture(os.path.relpath(c, ROOT))
                    try:
                        if is_read:
                            report, _, err = armb.read_call(content, name, cargs)
                            doc = None if err is not None else json.dumps(
                                report, sort_keys=True, default=str)
                        else:
                            doc, err = F.apply_op(content, op, oargs)
                    except Exception as e:  # noqa: BLE001
                        sig.append(f"CRASH {type(e).__name__}: {e}")
                        continue
                    sig.append(f"ERR {err}" if err is not None else f"OK {digest(doc)}")
                out[key] = sig if vectors else digest("\n".join(sig))
    return out


def explain(before, after):
    """Print, per moved call, every corpus file whose result differs.

    The claim a moved digest usually has to support is "a refusal writes no
    document, so no grade can move." That is only checkable one file at a time:
    `OK <digest>` on either side of a difference is a real edit and has to be
    argued for, `ERR` on both sides is a sentence that moved. So the summary
    counts the four transitions and the body prints the strings, and a reviewer
    reads the counts first.
    """
    keys = sorted(set(before) | set(after))
    kinds = collections.Counter()
    for k in keys:
        b, a = before.get(k) or [], after.get(k) or []
        for i, (x, y) in enumerate(zip(b, a)):
            if x == y:
                continue
            kinds[(x.split(" ", 1)[0], y.split(" ", 1)[0])] += 1
    print(f"{len(keys)} calls, differing corpus results by transition:")
    for (x, y), n in sorted(kinds.items()):
        flag = "" if x == "ERR" == y else "   <-- NOT a refusal on both sides"
        print(f"  {n:6d}  {x} -> {y}{flag}")
    for k in keys:
        b, a = before.get(k) or [], after.get(k) or []
        diffs = [(x, y) for x, y in zip(b, a) if x != y]
        if not diffs:
            continue
        print(f"\n{k}  ({len(diffs)} of {len(b)} corpus files differ)")
        for x, y in diffs[:2]:
            print("  was " + x.replace("\n", "\n      "))
            print("  now " + y.replace("\n", "\n      "))
        if len(diffs) > 2:
            print(f"  ... and {len(diffs) - 2} more, same shape")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--compare", help="an earlier snapshot to diff against")
    ap.add_argument("--moved-out", help="write the moved keys, one per line, "
                                        "for a later --keys run")
    ap.add_argument("--keys", help="replay only the keys listed in this file")
    ap.add_argument("--vectors", action="store_true",
                    help="store each call's raw per-corpus-file results "
                         "instead of a digest, for --explain")
    ap.add_argument("--explain", nargs=2, metavar=("BEFORE", "AFTER"),
                    help="diff two --vectors files and exit")
    args = ap.parse_args()

    if args.explain:
        return explain(json.load(open(args.explain[0])),
                       json.load(open(args.explain[1])))

    keys = None
    if args.keys:
        keys = {ln.strip() for ln in open(args.keys) if ln.strip()}
    snap = replay_all(keys=keys, vectors=args.vectors)
    print(f"{len(snap)} recorded tool calls replayed")
    with open(args.out, "w") as fh:
        json.dump(snap, fh, indent=0, sort_keys=True)

    if not args.compare:
        return 0
    old = json.load(open(args.compare))
    moved = [k for k in sorted(set(old) | set(snap)) if old.get(k) != snap.get(k)]
    if args.moved_out:
        with open(args.moved_out, "w") as fh:
            fh.write("".join(k + "\n" for k in moved))
    if not moved:
        print(f"identical to {args.compare}: no recorded call changed behaviour")
        return 0
    print(f"\n{len(moved)} of {len(snap)} calls CHANGED behaviour:")
    for k in moved[:20]:
        print(f"  {k}\n    was {old.get(k)}\n    now {snap.get(k)}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
