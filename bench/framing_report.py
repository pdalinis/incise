#!/usr/bin/env python3
"""Every number F-framing publishes, recomputed from the trial files.

This exists because of how F-framing's population figure went wrong: it was
computed once, written into prose, and then nothing ever recomputed it. Two
successive corrections later, the rule adopted was that a number this project
publishes has to be regenerable by a command. `bench/refusal_pool.py` does that
for the refusal population; this does it for the experiment.

Three analyses, all over the same 202 paired prefixes:

  **primary / secondary** -- graded `correct` at four turns, and whether the
  next call after the refusal succeeded. Paired per prefix, so McNemar.

  **mechanism** -- the secondary endpoint stratified by what the JSON framing
  actually does to *that* refusal (escapes a newline, escapes a quote, both,
  neither). The pre-registered prediction was that the effect lives where the
  escaping is; it does not.

  **single turn** -- what the framing costs a host that gives a tool one
  attempt. This needs no new trials, which was not obvious and is worth stating:
  `--turns N` counts the whole trial and the prefix's refused call is turn 1, so
  a single-turn caller's only attempt is the trial's *second* call. The turn
  budget never reaches the model -- nothing in the payload mentions it -- so that
  call is byte-identical to the one the four-turn run recorded. Grading
  `tool_calls[:2]` is the single-turn experiment rather than an estimate of it,
  and grading the untruncated list reproduces the four-turn column, which is the
  check that the reconstruction is sound.

    python3 bench/framing_report.py
"""

import collections
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bench"))

import armb  # noqa: E402
import armc  # noqa: E402
import incise_ops  # noqa: E402
from stats import mcnemar_exact, wilson  # noqa: E402

FAMILIES = {
    "lists": ("armc_framing_lists", "bench/tasks/lists.json"),
    "sections": ("armc_framing_sections", "bench/tasks/sections.json"),
    "tables": ("armc_framing_tables", "bench/tasks/tables.json"),
}


def load(binary):
    """{(family, scheme, task, trial): {framing: record}} for complete pairs."""
    pool = {}
    for family, (stem, taskfile) in FAMILIES.items():
        tasks = {t["id"]: t
                 for t in json.load(open(os.path.join(ROOT, taskfile)))["tasks"]}
        path = os.path.join(ROOT, "bench/results", stem + ".jsonl")
        for line in open(path, newline=""):
            if not line.strip():
                continue
            r = json.loads(line)
            task = tasks[r["task_id"]]

            # The single-turn trial: the same prefix, the same next call, graded
            # after it. `final_hash` is dropped because it belongs to the full
            # run and would otherwise register as a mismatch.
            one = dict(r)
            one["tool_calls"] = (r.get("tool_calls") or [])[:2]
            one.pop("final_hash", None)

            key = (family, r["scheme"].rsplit(":", 1)[0], r["task_id"], r["trial"])
            pool.setdefault(key, {})[r["framing"]] = {
                "codes": r.get("exit_codes") or [],
                "calls": r.get("tool_calls") or [],
                "fixture": task["fixture"],
                "four": armc.grade_one(task, r, binary)[0],
                "one": armc.grade_one(task, one, binary)[0],
            }
    return {k: v for k, v in pool.items() if "plain" in v and "json" in v}


def mcnemar(pairs, label):
    plain_only = sum(1 for p, j in pairs if p and not j)
    json_only = sum(1 for p, j in pairs if j and not p)
    n = len(pairs)
    np_ = sum(1 for p, _ in pairs if p)
    nj = sum(1 for _, j in pairs if j)
    lo, hi = wilson(np_, n)
    jlo, jhi = wilson(nj, n)
    print(f"  {label:22s} n={n:4d}"
          f"   plain {np_:4d} ({100 * np_ / n:5.1f}%, {100 * lo:.1f}-{100 * hi:.1f})"
          f"   json {nj:4d} ({100 * nj / n:5.1f}%, {100 * jlo:.1f}-{100 * jhi:.1f})"
          f"   {plain_only}-{json_only}  p={mcnemar_exact(plain_only, json_only):.3f}")


def recovered_in_one_turn(rec):
    """The refusal, then a call that worked. §5.3's one-turn rate."""
    c = rec["codes"]
    return len(c) >= 2 and c[0] == 1 and c[1] == 0


def endpoints(sub, title):
    print(f"\n{title}")
    mcnemar([(v["plain"]["four"] == "correct", v["json"]["four"] == "correct")
             for v in sub], "four turns, correct")
    mcnemar([(recovered_in_one_turn(v["plain"]), recovered_in_one_turn(v["json"]))
             for v in sub], "recovered in 1 turn")
    mcnemar([(v["plain"]["one"] == "correct", v["json"]["one"] == "correct")
             for v in sub], "ONE turn, correct")
    for framing in ("plain", "json"):
        calls = [len(v[framing]["calls"]) for v in sub]
        print(f"      mean calls {framing:5s}: {sum(calls) / len(calls):.2f}")


def mechanism(pool, binary):
    """The secondary endpoint, split by what `json` does to each refusal."""
    strata = collections.defaultdict(list)
    for v in pool.values():
        rec = v["plain"]
        fn = (rec["calls"] or [{}])[0].get("function", {})
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except ValueError:
            args = {}
        op, op_args = armb.normalize(fn.get("name"),
                                     args if isinstance(args, dict) else {})
        with armc.Sandbox({"fixture": rec["fixture"]}) as sb:
            _d, err, _c = armc.execute(binary, sb, op, op_args)
        err = err or ""
        newline, quote = "\n" in err, '"' in err
        label = ('newline and quote escaped' if newline and quote else
                 'newline only' if newline else
                 'quote only' if quote else
                 'nothing but the {"error": ...} wrapper')
        strata[label].append((recovered_in_one_turn(v["plain"]),
                              recovered_in_one_turn(v["json"])))
    print("\nMECHANISM (secondary endpoint, by what the framing changes)")
    for label, pairs in sorted(strata.items(), key=lambda kv: -len(kv[1])):
        mcnemar(pairs, label)


def turns_are_free(pool):
    """What turns 2-4 buy, and what they cost. The S14 question, restated.

    Reported because the answer is not S14's. S14 found an extra call on a task
    that did not need one destroyed the document 36% of the time. These are
    prefixes whose first call was *refused*, so a later turn is a repair rather
    than a gratuitous second edit -- a different population, and it behaves
    differently enough to be worth keeping separate.
    """
    print("\nWHAT TURNS 2-4 ARE WORTH")
    for framing in ("plain", "json"):
        sub = [v[framing] for v in pool.values()]
        one = sum(1 for r in sub if r["one"] == "correct")
        four = sum(1 for r in sub if r["four"] == "correct")
        fixed = sum(1 for r in sub if r["one"] != "correct" and r["four"] == "correct")
        broke = sum(1 for r in sub if r["one"] == "correct" and r["four"] != "correct")
        print(f"  {framing:5s}: one turn {one:3d} -> four turns {four:3d}"
              f"   later turns repaired {fixed}, destroyed {broke}")


def first_refusal(rec, binary):
    """Re-execute this prefix's first call and return the refusal it got."""
    fn = (rec["calls"] or [{}])[0].get("function", {})
    try:
        args = json.loads(fn.get("arguments") or "{}")
    except ValueError:
        args = {}
    op, op_args = armb.normalize(fn.get("name"),
                                 args if isinstance(args, dict) else {})
    with armc.Sandbox({"fixture": rec["fixture"]}) as sb:
        _d, err, _c = armc.execute(binary, sb, op, op_args)
    return err or ""


def oracle_accepts(rec):
    """Did this prefix's first call actually *work* under Arm B's executor?

    It should be impossible for a selected prefix to say yes here: `armc.replay`
    keeps only prefixes whose first call failed. It says yes 38 times, and
    finding that is what corrected this experiment's tables result.

    The cause is that `replay` selects by re-executing against `--binary`
    (`armc.py:497`, deliberately -- the single-turn arms record no exit codes,
    and the current binary's code is the one the replay will send). For a
    *retired* scheme that is a category error: `scheme_d` declares `row`, the
    shipping schema does not, so a `scheme_d` model using its own argument
    correctly is refused by a binary that never implemented its tool. Those
    prefixes are failures of the harness, not of the model, and they belong in
    no recovery rate.

    Paired endpoints are untouched -- the executor is identical on both sides of
    every pair, so a prefix wrongly refused is wrongly refused in both framings.
    Only absolute rates move, which is what `armc.replay`'s own docstring warns
    about when it says a replay's rate "is not comparable to a list or table
    rate in FINDINGS, only to its own pair."
    """
    fn = (rec["calls"] or [{}])[0].get("function", {})
    try:
        args = json.loads(fn.get("arguments") or "{}")
    except ValueError:
        return False
    op, op_args = armb.normalize(fn.get("name"),
                                 args if isinstance(args, dict) else {})
    content = open(os.path.join(ROOT, rec["fixture"]), newline="").read()
    after, err = incise_ops.apply_op(content, op, op_args)
    return err is None and after != content


def phantom_prefixes(pool):
    """Prefixes the binary refused but the arm's executor accepted.

    Published in FINDINGS as the correction to the tables gap, so it is
    regenerable here rather than asserted there.
    """
    print("\nPREFIXES THE BINARY REFUSED BUT THE ORACLE ACCEPTS")
    for family in FAMILIES:
        rows = [(k, v["plain"]) for k, v in pool.items() if k[0] == family]
        if not rows:
            continue
        real = [r for k, r in rows if not oracle_accepts(r)]
        bad = [k for k, r in rows if oracle_accepts(r)]
        got = sum(recovered_in_one_turn(r) for r in real)
        print(f"  {family}: {len(bad)} of {len(rows)} phantom"
              + (f"  schemes={dict(collections.Counter(k[1] for k in bad))}"
                 if bad else "")
              + f"\n    one-turn recovery over the {len(real)} genuine: "
                f"{got}/{len(real)} = {100 * got / max(len(real), 1):.1f}%")


def by_message(pool, binary):
    """One-turn recovery per refusal sentence, which is where tables' gap is.

    The pooled tables figure is 59.0% against §5.3's 100%, and the obvious
    reading -- that selecting on "was refused" conditions on hard cases -- is
    wrong. Split by the sentence the model actually read and the family is not
    uniformly worse at all: every tables refusal recovers at 100% except one,
    which recovers at 34.2% and is two thirds of the pool. A rate pooled over
    messages is not a property of the family; it is a property of the mix.

    That much held up. The reading of the low stratum did not, twice over, and
    both corrections are printed here rather than left to the reader.

    `phantom=` is the tables case: run `phantom_prefixes` and the low stratum is
    *exactly* the 38 whose first call the oracle accepts, so the models in it
    neither failed nor failed to recover.

    `schemes=` is the lists case, which `phantom=` cannot catch. Lists' `` `text`
    is required `` sits at 16/37 and every one of the 37 is `list_f` or
    `list_naive`; the adopted `list_g` draws that refusal 0 times in 400 calls,
    because L3 renamed the selector `item` -> `match` and the collision that
    produced it stopped existing. Those refusals are real -- the models genuinely
    failed -- so nothing about the execution is contradictory. Only the scheme
    label says the rate describes a retired schema. **A prefix pool inherits the
    schema its trials were run under**, and a stratum is unreadable without it.

    Kept as a standing cut because the same arithmetic applies to any family
    whose pooled recovery looks mediocre.
    """
    print("\nONE-TURN RECOVERY BY REFUSAL SENTENCE (plain framing)")
    for family in FAMILIES:
        rows = [(k[1].split(":")[0], v["plain"])
                for k, v in pool.items() if k[0] == family]
        if not rows:
            continue
        strata = collections.defaultdict(list)
        phantom = collections.Counter()
        schemes = collections.defaultdict(collections.Counter)
        for scheme, rec in rows:
            first = first_refusal(rec, binary).split("\n")[0]
            strata[first].append(recovered_in_one_turn(rec))
            phantom[first] += oracle_accepts(rec)
            schemes[first][scheme] += 1
        got = sum(sum(v) for v in strata.values())
        print(f"  {family}: {got}/{len(rows)} = {100 * got / len(rows):.1f}% pooled")
        for sentence, hits in sorted(strata.items(), key=lambda kv: -len(kv[1])):
            mix = ",".join(f"{s}:{n}" for s, n in schemes[sentence].most_common(3))
            print(f"    {sum(hits):3d}/{len(hits):3d}  "
                  f"{100 * sum(hits) / len(hits):5.1f}%  "
                  f"phantom={phantom[sentence]:<3d} {sentence[:52]:52s} {mix}")


def main():
    binary = armc.find_binary()
    pool = load(binary)
    print("paired prefixes:", len(pool),
          dict(collections.Counter(k[0] for k in pool)))
    endpoints(list(pool.values()), "POOLED (three families)")
    for family in FAMILIES:
        endpoints([v for k, v in pool.items() if k[0] == family], family.upper())
    mechanism(pool, binary)
    by_message(pool, binary)
    phantom_prefixes(pool)
    turns_are_free(pool)


if __name__ == "__main__":
    main()
