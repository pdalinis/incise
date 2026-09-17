#!/usr/bin/env python3
"""Count the refusals `bench/results/` actually contains, by arm.

F-framing published a population figure — "726 refusals, one over the host's
2048-character cap" — that was wrong, and this file exists because of how it was
wrong. **`bench/results/` is not one population.** It holds every arm this
project has run, and re-executing a row's first tool call through the release
binary asks the binary a question the row was never asked:

  - **Arm A** rows (`trials.jsonl`, `trials_lists.jsonl`, `arma_sections.jsonl`)
    call `patch`, the string-replacement baseline. The binary has no such op.
  - **Frontmatter** rows call `frontmatter-set` / `-delete`, which
    `bench/incise_ops.py` implements and the Rust core does not — the port is
    deliberately still open (`PLAN.md` workstream 3a stops at Arm B).
  - **Read** rows call `table_get` / `frontmatter_get`, which are off `apply_op`
    by design and are not reachable through `armc.execute` at all.

All three answer `unknown operation "X"`. None of them is a refusal any model
was ever shown; each is a measurement of the harness pointing at the wrong
executor. 1380 of 1727 exit-1 first calls in this directory are one of those
three, which is why a raw count is off by a factor of five.

The rule, and the only part worth remembering:

    an unknown-operation result is an artifact exactly when the executor that
    produced the row implemented the op and the release binary does not.

That is checkable rather than a file-name blocklist, and it keeps the case the
blocklist gets wrong: `unknown operation "list-None"` is implemented by
*nobody*, so it is a genuine refusal an Arm B model really read — it is the
missing-`action` failure §2.3 of the plan is about, and dropping it would delete
the only rows that measure it.

One thing this count is not. The string recorded here is the one the **release
binary** produces today, which enumerates fifteen op names. When this paragraph
was written it enumerated thirteen and the oracle knew fifteen, so a handful of
these sentences were not byte-identical to what the model in that row actually
read; F-frontport closed that gap by porting the two frontmatter ops, and
`bench/difftest.py` asserts the two lists agree. The caveat that survives is
narrower and still worth stating: the sentence is regenerated from today's
binary rather than replayed from the row, so it is the right population for a
question about the shipping front end — which is what F-framing asks — and the
wrong one for a question about what any particular arm's model saw.

    python3 bench/refusal_pool.py [--list]
"""

import collections
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bench"))

import armb  # noqa: E402
import armc  # noqa: E402
import incise_ops  # noqa: E402
import population  # noqa: E402
from schematest import find_binary  # noqa: E402

CAP = 2048

# Ops whose `unknown operation` answer is the harness, not a refusal: Arm A's
# tool, everything the reference implements and the core does not, and the reads
# that are off `apply_op` by design.
ARM_A_TOOL = "patch"
READ_OPS = {"table_get", "frontmatter_get"}
FAMILY = {"table_edit": "tables", "list_edit": "lists", "section_edit": "sections",
          "frontmatter_edit": "frontmatter",
          # scheme_a published one tool per op rather than one per family
          "table-add-row": "tables", "table-update-cell": "tables",
          "table-delete-row": "tables", "table-realign": "tables"}

# Replay outputs are not new refusals. `armc.replay` selects prefixes *from* this
# pool and re-executes their first call under each framing, so every row in a
# replay's output is a copy of a row already counted — including the one
# over-cap refusal, which would otherwise appear three times and turn n = 1 into
# n = 3.
#
# This used to be `base.startswith("armc_framing_")`, under a comment claiming
# the rule was general — *"not as a blocklist of arms: the same applies to any
# future replay output."* It was a blocklist, and the next two replays were
# named `armc_replay_path*` and `armc_ordinal*`, so both slipped through and
# took the published 353 to 525. The rule now lives in `bench/population.py`
# and keys on the row's own `tag` field, which is a property of the row rather
# than of the name someone gave its file.


def fixtures():
    """task_id -> fixture, read off the task files rather than off the rows.

    A row whose call names a path that does not exist is still a real refusal —
    the binary answers it — so the sandbox is built from the *task's* fixture,
    which is what a live run does, instead of skipping the row.
    """
    out = {}
    for tf in sorted(glob.glob(os.path.join(ROOT, "bench/tasks/*.json"))):
        for t in json.load(open(tf))["tasks"]:
            out[t["id"]] = t["fixture"]
    return out


def first_calls():
    fix = fixtures()
    for path, row in population.recorded_rows():
        base = os.path.basename(path)
        calls = row.get("tool_calls") or []
        if not calls:
            continue
        fn = calls[0].get("function", {})
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except ValueError:
            args = {}
        f = fix.get(row.get("task_id"))
        if f and isinstance(args, dict):
            yield base, row.get("task_id"), fn.get("name"), args, f


def is_artifact(op, err):
    if not err.startswith("unknown operation"):
        return False
    return op == ARM_A_TOOL or op in READ_OPS or op in incise_ops.OPS


def collect(binary):
    real, artifacts = [], []
    for base, tid, name, args, fixture in first_calls():
        op, op_args = armb.normalize(name, args)
        with armc.Sandbox({"fixture": fixture}) as sb:
            _desc, err, code = armc.execute(binary, sb, op, op_args)
        if code != 1:
            continue
        rec = (base, tid, name, op, err or "")
        (artifacts if is_artifact(op, err or "") else real).append(rec)
    return real, artifacts


def main():
    binary = find_binary()
    real, artifacts = collect(binary)
    total = len(real) + len(artifacts)

    print(f"exit-1 first calls in bench/results/: {total}")
    print(f"  harness artifacts : {len(artifacts)}")
    print("    by op:", dict(collections.Counter(o for _, _, _, o, _ in artifacts)))
    print(f"  real refusals     : {len(real)}"
          f"   distinct strings: {len(set(e for *_, e in real))}")
    fam = collections.Counter(FAMILY.get(n, n) for _, _, n, _, _ in real)
    print("    by family:", dict(fam))

    n = len(real)
    ml = sum(1 for *_, e in real if "\n" in e)
    qt = sum(1 for *_, e in real if '"' in e)
    both = sum(1 for *_, e in real if "\n" in e and '"' in e)
    neither = sum(1 for *_, e in real if "\n" not in e and '"' not in e)
    print("\n  what the JSON framing transforms:")
    for label, v in (("multi-line", ml), ("quoted name", qt),
                     ("both", both), ("neither", neither)):
        print(f"    {label:12s}: {v:4d} = {100 * v / n:.1f}%")

    over = [(b, t, len(e), len(e) - CAP) for b, t, _, _, e in real if len(e) > CAP]
    print(f"\n  over the {CAP}-character cap: {len(over)}")
    for b, t, size, delta in over:
        print(f"    {b} {t}: {size} chars, {delta} over")

    if "--list" in sys.argv:
        print("\n  distinct refusal strings:")
        for s in sorted(set(e for *_, e in real)):
            print(f"    [{len(s):4d}] {s.splitlines()[0]}")


if __name__ == "__main__":
    main()
