#!/usr/bin/env python3
"""Paired report for the preregistered MiniCPM flat section-slots arm."""

import hashlib
import json
import math
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TASKS = {
    "insert-release-at-top", "insert-subsection-last",
    "insert-nested-ratelimits", "insert-troubleshooting",
}
MULTI = {
    "insert-release-at-top", "insert-nested-ratelimits", "insert-troubleshooting",
}
CONTROL_RAW = "bench/results/minicpm5_routed_sections_20260921.jsonl"
CONTROL_GRADED = "bench/results/minicpm5_routed_sections_20260921_graded.jsonl"
TREATMENT_RAW = "bench/results/minicpm5_section_slots_20260921.jsonl"
TREATMENT_GRADED = "bench/results/minicpm5_section_slots_20260921_graded.jsonl"
OUT = "bench/results/minicpm5_section_slots_analysis_20260921.json"


def sha256(path):
    with open(os.path.join(ROOT, path), "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def rows(path):
    out = {}
    with open(os.path.join(ROOT, path)) as fh:
        for line in fh:
            row = json.loads(line)
            if row["task_id"] in TASKS:
                out[(row["task_id"], row["trial"])] = row
    return out


def exact_mcnemar(control_only, treatment_only):
    n = control_only + treatment_only
    if not n:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(min(control_only, treatment_only) + 1))
    return min(1.0, 2 * tail / (2 ** n))


def main():
    control = rows(CONTROL_GRADED)
    treatment = rows(TREATMENT_GRADED)
    control_raw = rows(CONTROL_RAW)
    treatment_raw = rows(TREATMENT_RAW)
    if set(control) != set(treatment) or len(control) != 12:
        raise RuntimeError("control and treatment are not the preregistered 12 pairs")

    transitions = Counter(
        (control[key]["outcome"], treatment[key]["outcome"])
        for key in sorted(control)
    )
    cc = Counter(row["outcome"] for row in control.values())
    tc = Counter(row["outcome"] for row in treatment.values())
    control_only = sum(
        control[k]["outcome"] == "correct" and treatment[k]["outcome"] != "correct"
        for k in control)
    treatment_only = sum(
        control[k]["outcome"] != "correct" and treatment[k]["outcome"] == "correct"
        for k in control)
    by_task = defaultdict(Counter)
    for key, row in treatment.items():
        by_task[key[0]][row["outcome"]] += 1
    qualifying_multi = sum(by_task[task]["correct"] >= 2 for task in MULTI)
    unsafe = {"destructive", "collateral:content", "collateral:formatting"}
    refusals_unchanged = all(
        not treatment_raw[key].get("document_changed")
        for key in treatment
        if treatment[key]["outcome"] == "op_error"
    )
    gate = {
        "at_least_eight_correct": tc["correct"] >= 8,
        "two_multi_section_types_succeed_in_two_seeds": qualifying_multi >= 2,
        "no_treatment_destructive_or_collateral": not any(tc[name] for name in unsafe),
        "refusals_left_fixture_unchanged": refusals_unchanged,
    }
    gate["passed"] = all(gate.values())

    def mean(rows_by_key, field):
        values = [row.get(field) for row in rows_by_key.values() if row.get(field) is not None]
        return round(sum(values) / len(values), 2)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "preregistration_commit": "159e54a",
        "model": "minicpm5-2b-q8",
        "pairs": 12,
        "control_outcomes": dict(sorted(cc.items())),
        "treatment_outcomes": dict(sorted(tc.items())),
        "treatment_by_task": {
            task: dict(sorted(counts.items())) for task, counts in sorted(by_task.items())
        },
        "transitions": {
            f"{a}->{b}": count for (a, b), count in sorted(transitions.items())
        },
        "paired_correct": {
            "control": cc["correct"], "treatment": tc["correct"],
            "control_only": control_only, "treatment_only": treatment_only,
            "exact_mcnemar_p": exact_mcnemar(control_only, treatment_only),
        },
        "efficiency": {
            "control_mean_completion_tokens": mean(control_raw, "completion_tokens"),
            "treatment_mean_completion_tokens": mean(treatment_raw, "completion_tokens"),
            "control_mean_elapsed_s": mean(control_raw, "elapsed_s"),
            "treatment_mean_elapsed_s": mean(treatment_raw, "elapsed_s"),
        },
        "gate": gate,
        "artifacts": {
            path: sha256(path) for path in (
                CONTROL_RAW, CONTROL_GRADED, TREATMENT_RAW, TREATMENT_GRADED)
        },
        "schema_sha256": hashlib.sha256(json.dumps(
            __import__("minicpm_section_slots").SCHEMA,
            sort_keys=True, separators=(",", ":"),
        ).encode()).hexdigest(),
        "harness_sha256": sha256("bench/minicpm_section_slots.py"),
    }
    with open(os.path.join(ROOT, OUT), "w") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
