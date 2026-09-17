#!/usr/bin/env python3
"""Measure the harness ceiling before spending GPU time on a model arm.

Arm B is only interpretable if the mock's own ceiling is known. B1 established
this the hard way: twelve hand-written ideal tool calls had to grade `correct`
before any model trial was run, because without that a bug in the executor is
indistinguishable from a failure of the model, and the whole arm reads as a
capability result when it is a harness result.

That check was done by hand in B1. This makes it a script, so it can be re-run
after every schema or executor change instead of once at the start.

What it does, per task and per scheme:

  1. Take the task's `ideal_call` -- the op a perfect model would emit.
  2. Re-express it in that scheme's tool vocabulary, exactly as the model would
     have to (one tool per op vs. one tool with an `action` enum).
  3. Feed it through the arm's `grade_one` as a synthetic trial, so it travels
     the same normalize -> execute -> check_result path a real trial travels.

A ceiling below 100% is a bug in incise, the schema mapping or the grader, and
must be fixed before the arm is run. A ceiling of 100% is not a claim about the
model; it only says the ceiling is not what limits the number.

`--arm c` runs the same ideal calls through the real binary on real files
(`armc.grade_one`). The premise binds harder there than in Arm B: with a
subprocess and a filesystem in the loop there are more ways for the harness to
be what failed, and no more ways to tell from the rate alone.

Tasks with no `ideal_call` are skipped and named, not silently dropped.

  python3 bench/ceiling.py --tasks bench/tasks/lists.json \\
      --schemes list_naive,list_f
"""

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bench"))

import armb  # noqa: E402
import armc  # noqa: E402

# op name -> read tool name, the inverse of `armb.READS`. A read op is not in
# `OPS` and has no `action`, so neither of the two branches below it applies:
# without this, `table-get` would be expressed as `table_edit` with
# `action: "get"` and the ceiling would report the model's schema as broken when
# what failed was this mapping.
_READ_TOOLS = {v: k for k, v in armb.READS.items()}


def _ideal_calls(task):
    """The op sequence a perfect model would emit, always as a list.

    `ideal_calls` arrived with S6: making a section that contains a subsection
    is two calls in every vocabulary that keeps the level derived. Older task
    sets carry a single `ideal_call`, which is the one-element case.
    """
    if "ideal_calls" in task:
        return task["ideal_calls"]
    if "ideal_call" in task:
        return [task["ideal_call"]]
    return None


def as_tool_call(task, scheme, call):
    """Express one ideal op as a tool call in `scheme`'s vocabulary.

    The inverse of `armb.normalize`, and deliberately written separately: if the
    ceiling check reused normalize's own tables, a mapping bug would cancel out
    and the check would pass on a broken schema.
    """
    op = call["op"]
    args = dict(call["args"], path=task["fixture"])
    spec = {s["name"]: s for s in armb.SCHEMES[scheme]}
    tools = set(spec)

    if op in tools:                       # one tool per op (scheme_a)
        name = op
    elif op in _READ_TOOLS and _READ_TOOLS[op] in tools:
        name = _READ_TOOLS[op]            # a read tool, which has no action enum
    elif op.startswith("table-") and "table_edit" in tools:
        name, args = "table_edit", dict(args, action=op[len("table-"):])
    elif op.startswith("list-") and "list_edit" in tools:
        name, args = "list_edit", dict(args, action=op[len("list-"):])
    elif op == "section-insert" and "section_create" in tools:
        # F-narrow. A scheme publishing both routes to a new section has its
        # narrow one checked here, because that is the one the scheme exists to
        # introduce; `section_edit`'s insert is the adopted route and is
        # ceiling-checked under every other section scheme. `section_create`
        # takes no `action`, so unlike every branch around it nothing is added.
        name = "section_create"
    elif op.startswith("section-") and "section_edit" in tools:
        name, args = "section_edit", dict(args, action=op[len("section-"):])
    elif op.startswith("frontmatter-") and "frontmatter_edit" in tools:
        name, args = "frontmatter_edit", dict(
            args, action=op[len("frontmatter-"):])
    else:
        raise SystemExit(f"{task['id']}: op {op!r} has no home in {scheme}")

    # Some schemes rename a field (list_g: `item` -> `match`; section_p:
    # `heading` -> `new_heading`; section_g_file: `path` -> `file`;
    # table_read_naive: `filter` -> `where`). An ideal call is written in the
    # reference vocabulary, so it has to be translated, or the ceiling would
    # report a failure that only means "this scheme spells it differently". Only
    # renames the scheme actually declares are applied.
    props = spec[name]["parameters"]["properties"]
    for old, new in (("item", "match"), ("heading", "new_heading"),
                     ("path", "file"), ("filter", "where")):
        if old in args and old not in props and new in props:
            args[new] = args.pop(old)
    # The same, one level down: `section_g_hpath` spells the address `heading`.
    # Nested renames are checked against the nested sub-schema rather than the
    # top-level one, or `heading` at either depth would satisfy the other.
    sec_schema = props.get("section", {}).get("properties", {})
    if isinstance(args.get("section"), dict):
        args["section"] = {
            ("heading" if k == "path" and "path" not in sec_schema
             and "heading" in sec_schema else k): v
            for k, v in args["section"].items()
        }
        unknown_sec = [k for k in args["section"] if k not in sec_schema]
        if unknown_sec:
            return None, f"scheme cannot express section: {unknown_sec}"
    unknown = [k for k in args if k not in props]
    if unknown:
        # Reported per task rather than raised, because "this scheme cannot
        # express the correct call" is a finding about the scheme, not a bug in
        # the harness. It became one when the S2 guard made `overwrite` part of
        # a legitimate body replacement: `section_naive` and `section_p` have no
        # field for it, so under the guarded executor there is no call they can
        # make that grades `correct` on `replace-install-preamble`. Aborting the
        # whole run would have hidden that behind a stack trace.
        return None, f"scheme cannot express: {unknown}"
    return name, args


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default=os.path.join(ROOT, "bench/tasks/lists.json"))
    ap.add_argument("--schemes", default="list_naive,list_f")
    ap.add_argument("--arm", default="b", choices=("b", "c"),
                    help="which executor to check: b is `incise_ops.apply_op` "
                         "in-process, c is the real binary on real files")
    args = ap.parse_args()

    if args.arm == "b":
        grade_one = armb.grade_one
    else:
        binary = armc.find_binary()
        print(f"arm c: {binary}")
        grade_one = lambda task, trial: armc.grade_one(task, trial, binary)  # noqa: E731

    tasks = json.load(open(args.tasks))["tasks"]
    schemes = args.schemes.split(",")
    skipped = [t["id"] for t in tasks if _ideal_calls(t) is None]
    tasks = [t for t in tasks if _ideal_calls(t) is not None]

    failures = 0
    for scheme in schemes:
        if scheme not in armb.SCHEMES:
            raise SystemExit(f"unknown scheme {scheme!r}")
        print(f"\n=== {scheme}")
        for task in tasks:
            expressed = [as_tool_call(task, scheme, c) for c in _ideal_calls(task)]
            bad = next((d for n, d in expressed if n is None), None)
            if bad:
                failures += 1
                print(f"  FAIL {task['id']:28s} {bad}")
                continue
            # One synthetic trial carrying the whole sequence -- graded by the
            # same `grade_one` a real multi-turn trial goes through, so a
            # two-call task is checked end to end rather than call by call.
            trial = {"tool_calls": [
                {"function": {"name": n, "arguments": json.dumps(a)}}
                for n, a in expressed]}
            outcome, detail = grade_one(task, trial)
            mark = "ok " if outcome == "correct" else "FAIL"
            n_calls = f" ({len(expressed)} calls)" if len(expressed) > 1 else ""
            print(f"  {mark} {task['id']:28s} {outcome}{n_calls}")
            if outcome != "correct":
                failures += 1
                print(f"       {str(detail)[:200]}")

    n = len(tasks) * len(schemes)
    print(f"\nceiling: {n - failures}/{n} ideal calls grade correct")
    if skipped:
        print(f"skipped (no ideal_call): {', '.join(skipped)}")
    if failures:
        print("!! ceiling is below 100% -- fix the harness before running the arm")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
