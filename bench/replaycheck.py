#!/usr/bin/env python3
"""Do the two replays agree about which recorded calls are executable?

There are two independent replays of the same recorded tool calls:

  * `headroom.py` replays them to count how many trials *reach* a branch, so a
    pending re-measurement can be priced before any GPU is spent.
  * `regrade_snapshot.py` replays them to hash each call's outcome, so a change
    to the executor can be shown to disturb no recorded grade.

They were written months apart for different questions, and until this module
existed nothing compared them. That is not a hypothetical worry — it is the
defect this project has already paid for twice, in the same release:

  **Both had the identical read-blindness bug, and it was fixed in one and left
  in the other.** `armb.READS` are off `apply_op` on purpose, so routing a read
  through it yields `unknown operation "table_get"` — a sentence no model was
  ever shown. `headroom.py` had it fixed during F-remedy's *control* arm (its
  survey had reported the candidate UNTESTED at k=0 with ten reaching calls
  already on disk). `regrade_snapshot.py` still had it a week later, where it
  answered "no recorded call changed behaviour" for a change that rewrites
  exactly the refusal ten recorded calls draw — inverting a pre-registered void
  condition. One replay knew; the other did not; nothing asked.

So this asks. Each module exposes a `disposition(name, raw_args)` — its own
rules, in its own file, not a shared implementation, because two copies that
call one function cannot drift and therefore cannot demonstrate agreement
either. This walks every recorded call, asks both, and fails on any
disagreement that is not on the named list below.

What it deliberately does not check: the two modules execute against different
documents (a task's fixture, in sequence, versus every corpus and synthetic file
from pristine), and that difference is by design in both docstrings. The claim
here is narrower and is the one that was violated: **for a given recorded call,
both modules agree on whether it is executable and by which route.**

    python3 bench/replaycheck.py

Exit 1 on any unlisted disagreement.
"""

import collections
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bench"))

import armb  # noqa: E402
import headroom  # noqa: E402
import regrade_snapshot as RS  # noqa: E402


# One-sided skips that are correct and reasoned, keyed by the module that skips
# and the reason it gives. Anything not here is a failure, so adding an entry is
# a deliberate act with a sentence attached.
EXPECTED_ONE_SIDED = {
    ("headroom", "tool no scheme publishes"):
        "Arm A's `patch` is executed by `arma.py` and never goes near "
        "`apply_op`; replaying it manufactures `unknown operation \"patch\"` "
        "380 times, a sentence no model in that arm was shown. `headroom.py` "
        "counts a population and must not invent one. `regrade_snapshot.py` is "
        "a regression corpus over calls, not a census, and hashing what the "
        "executor does with an unknown name is a real regression signal.",
    ("headroom", "arguments are not an object"):
        "`armb.run_trial` decodes inside the `try` that wraps the call, so a "
        "non-object payload was answered with the decode error and no op ran. "
        "`headroom.py` refuses to invent a `section-None`; `regrade_snapshot.py` "
        "hashes whatever `normalize` does with it, which is a behaviour worth "
        "pinning even though no model saw it.",
}


def recorded_calls():
    """Every call in every results file: (key, tool name, raw arguments).

    Enumerated `regrade_snapshot.py`'s way — the whole directory, replays
    included — because a per-call routing rule does not depend on which trial
    the call came from, and the superset is what makes a divergence findable.
    `headroom.py` visits a deduped subset via `population.recorded_rows()`; that
    is a census decision, and applying it here would hide a disagreement on
    exactly the rows it drops.
    """
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
            for ci, call in enumerate(rec.get("tool_calls") or []):
                fn = call.get("function") or {}
                yield f"{rel}:{lineno}:{ci}", fn.get("name"), fn.get("arguments")


def check_reads_keying():
    """The assumption both modules rest on, asserted instead of trusted.

    `headroom.disposition` tests `op in armb.READS`; `RS.disposition` tests
    `name in armb.READS`. Those are the same test only because `armb.READS` is
    keyed by *tool* name and `normalize` returns the tool name unchanged for a
    read. The day a read gets an op name of its own, the two modules disagree
    silently on every read call — the exact failure this file exists for — so
    the dependency is checked here rather than left in two comments.
    """
    bad = []
    for name in armb.READS:
        try:
            op, _ = armb.normalize(name, {})
        except Exception as e:  # noqa: BLE001
            bad.append(f"{name}: normalize raised {type(e).__name__}: {e}")
            continue
        if op != name:
            bad.append(f"{name}: normalize returns {op!r}, so `op in READS` and "
                       f"`name in READS` are no longer the same test")
    return bad


def classify(d):
    return d["route"], d.get("reason")


def main():
    problems = []
    for msg in check_reads_keying():
        problems.append(("READS keying", msg))

    cross = collections.Counter()
    examples = {}
    n = 0
    for key, name, raw in recorded_calls():
        n += 1
        try:
            h = headroom.disposition(name, raw)
        except Exception as e:  # noqa: BLE001
            # `headroom.replay` does not guard `normalize`, so this is a crash
            # in the survey, not a skip. Reported as a disagreement because
            # `regrade_snapshot.py` records the same exception and continues.
            h = {"route": "crash", "reason": f"{type(e).__name__}: {e}"}
        try:
            r = RS.disposition(name, raw)
        except Exception as e:  # noqa: BLE001
            r = {"route": "crash", "reason": f"{type(e).__name__}: {e}"}

        hr, rr = h["route"], r["route"]
        cross[(hr, rr)] += 1
        examples.setdefault((hr, rr), (key, name))

        if hr == rr:
            if hr == "crash":
                problems.append(("both crash", f"{key} {name}: {h['reason']}"))
            continue
        if "crash" in (hr, rr):
            problems.append((
                f"{hr} vs {rr}",
                f"{key} {name}: headroom={hr}({h.get('reason')}) "
                f"regrade={rr}({r.get('reason')})"))
            continue
        if {hr, rr} == {"read", "edit"}:
            problems.append((
                "read vs edit",
                f"{key} {name}: headroom routes it {hr}, regrade routes it {rr} "
                f"-- this is the read-blindness class, and one of the two is "
                f"showing the model a sentence it never saw"))
            continue
        # One executes, one skips.
        who, reason = ("headroom", h.get("reason")) if hr == "skip" \
            else ("regrade", r.get("reason"))
        if (who, reason) not in EXPECTED_ONE_SIDED:
            problems.append((
                "unlisted one-sided skip",
                f"{key} {name}: {who} skips with reason {reason!r}, the other "
                f"executes it. Either the rule is wrong or it belongs in "
                f"EXPECTED_ONE_SIDED with a sentence saying why."))

    print(f"{n} recorded tool calls, both replays asked about each\n")
    print(f"  {'headroom':28s} {'regrade_snapshot':28s} {'calls':>7s}")
    for (hr, rr), c in sorted(cross.items(), key=lambda kv: (-kv[1], kv[0])):
        mark = "" if hr == rr else "   <-- one-sided"
        print(f"  {hr:28s} {rr:28s} {c:7d}{mark}")
        if hr != rr:
            k, nm = examples[(hr, rr)]
            print(f"  {'':28s} {'':28s}   e.g. {k} {nm}")

    if EXPECTED_ONE_SIDED:
        print("\nasymmetries on the list, and why each is correct:")
        for (who, reason), why in sorted(EXPECTED_ONE_SIDED.items()):
            print(f"  {who} skips {reason!r}\n    {why}")

    if not problems:
        print("\nOK: the two replays agree about every recorded call, or "
              "disagree only where the list says they should.")
        return 0
    print(f"\n{len(problems)} DISAGREEMENT(S):")
    seen = collections.Counter()
    for kind, msg in problems:
        seen[kind] += 1
        if seen[kind] <= 5:
            print(f"  [{kind}] {msg}")
    for kind, c in seen.items():
        if c > 5:
            print(f"  [{kind}] ... and {c - 5} more")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
