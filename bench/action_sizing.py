#!/usr/bin/env python3
"""How many recorded calls the F-action condition would change, and which.

`armb.CHECK_ACTION` (the `--check-action` flag) was built and never run. Before
spending GPU time on it, the question F-framing taught this project to ask
first: how many calls does it even reach? Its docstring answered that once, in
prose, from a scan nobody kept -- "across 6678 edit-tool calls" -- and by the
time it was re-run the directory held considerably more. A number written into
a comment and never recomputed is exactly how F-framing's population figure
went wrong twice, so this is the command.

It replays every edit-tool call in `bench/results/` through `_action_of` and
sorts the outcome into the four messages that function can raise, plus the two
non-outcomes (the call was fine; the arguments were not JSON at all). The four
shapes matter separately because they are different refusals with different
repairs, and a condition whose messages mostly have no caller cannot be sized
on this data whatever the total says.

    python3 bench/action_sizing.py
"""

import collections
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bench"))

import armb  # noqa: E402
import population  # noqa: E402

# Which message a refusal is, by the shape of its first line. Keyed on text
# because `_action_of` raises one exception type for all four -- deliberately,
# since the model sees a sentence and not a class -- and this file must not
# become a second implementation of the branch structure it is measuring.
SHAPES = (
    ("unknown action name", lambda s: s.startswith("no action ")),
    ("fused key", lambda s: "arrived as one JSON key" in s),
    ("missing action", lambda s: s.startswith("`action` is required")),
    ("action not a string", lambda s: s.startswith("`action` must be one of")),
)


def shape_of(text):
    for label, pred in SHAPES:
        if pred(text):
            return label
    return "UNCLASSIFIED: " + text.split("\n")[0]


def calls():
    """(file, task_id, scheme, trial, tool name, parsed args) per edit call.

    Over `population.recorded_rows()`, not the directory. A replay re-executes
    a prefix's first call verbatim, so its rows would inflate the denominator
    with calls already counted -- the same defect that published a 206 for
    `ordinal_sizing.py` and a 353 for `refusal_pool.py`. Note `.rsplit(":", 1)`
    below: this file already knew replay rows carry compound schemes, and
    folded them onto their base scheme rather than dropping them.
    """
    for path, r in population.recorded_rows():
        for c in r.get("tool_calls") or []:
            fn = c.get("function") or {}
            if fn.get("name") not in armb.ACTIONS:
                continue
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                args = None
            yield (os.path.basename(path), r.get("task_id"),
                   (r.get("scheme") or "?").rsplit(":", 1)[0],
                   r.get("trial"), fn["name"], args)


def main():
    counts = collections.Counter()
    where = collections.defaultdict(collections.Counter)
    texts = collections.defaultdict(set)
    per_scheme = collections.Counter()
    fused_scheme = collections.Counter()
    fused_seed = collections.Counter()
    total = 0
    for fname, task, scheme, trial, name, args in calls():
        total += 1
        per_scheme[scheme] += 1
        if not isinstance(args, dict):
            # These never reached `normalize` in the trial either:
            # `armb.run_trial` decodes inside the same `try`, so the model was
            # answered with the decode error and no op ran. Counted apart from
            # the four messages rather than as a fifth -- the check cannot see
            # them, so they are not a population it could serve.
            counts["arguments are not a JSON object"] += 1
            continue
        try:
            armb._action_of(name, args)
            counts["valid -- the check is a no-op"] += 1
        except armb.ArgError as e:
            label = shape_of(str(e))
            counts[label] += 1
            where[label][f"{fname} {task}"] += 1
            texts[label].add(str(e))
            fused_scheme[scheme] += 1
            fused_seed[(scheme.split("_")[0], trial)] += 1

    print(f"edit-tool calls in bench/results/: {total}")
    for label, n in counts.most_common():
        print(f"  {n:5d}  {label}")
    for label, _pred in SHAPES:
        if not counts[label]:
            print(f"\n{label.upper()}: no caller in any recorded trial.")
            continue
        print(f"\n{label.upper()}: {counts[label]} calls, "
              f"{len(texts[label])} distinct message(s)")
        for k, n in where[label].most_common():
            print(f"  {n:5d}  {k}")
        for t in sorted(texts[label]):
            print("  ---")
            for ln in t.split("\n"):
                print(f"  | {ln}")

    # The load-bearing part of the sizing, and the reason the raw count is
    # misleading: which schemes and which seeds these came from. A fault that
    # only one seed produces is one trajectory sampled repeatedly, not N events
    # (caveat 2, arriving from the wrong-answer side).
    print("\nBY SCHEME (schemes with a fault, and the same family's others)")
    families = {s.split("_")[0] for s in fused_scheme}
    for s in sorted(per_scheme, key=lambda s: -per_scheme[s]):
        if s.split("_")[0] in families:
            print(f"  {s:20s} {per_scheme[s]:5d} calls   fused {fused_scheme[s]}")
    print("\nBY (family, seed)")
    for k, n in sorted(fused_seed.items()):
        print(f"  {k}  {n}")


if __name__ == "__main__":
    main()
