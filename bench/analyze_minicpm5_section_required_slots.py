#!/usr/bin/env python3
"""Paired report for MiniCPM cardinality-routed required section slots."""

import hashlib
import json
import math
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bench"))
import minicpm_section_slots as slots  # noqa: E402

CONTROL_RAW = "bench/results/minicpm5_section_slots_20260921.jsonl"
CONTROL_GRADED = "bench/results/minicpm5_section_slots_20260921_graded.jsonl"
TREATMENT_RAW = "bench/results/minicpm5_section_required_slots_20260921.jsonl"
TREATMENT_GRADED = "bench/results/minicpm5_section_required_slots_20260921_graded.jsonl"
OUT = "bench/results/minicpm5_section_required_slots_analysis_20260921.json"


def sha256(path):
    with open(os.path.join(ROOT, path), "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def rows(path):
    out = {}
    with open(os.path.join(ROOT, path)) as fh:
        for line in fh:
            row = json.loads(line)
            out[(row["task_id"], row["trial"])] = row
    return out


def exact_mcnemar(a, b):
    n = a + b
    if not n:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(min(a, b) + 1))
    return min(1.0, 2 * tail / (2 ** n))


def main():
    control, treatment = rows(CONTROL_GRADED), rows(TREATMENT_GRADED)
    control_raw, treatment_raw = rows(CONTROL_RAW), rows(TREATMENT_RAW)
    if set(control) != set(treatment) or len(control) != 12:
        raise RuntimeError("control and treatment are not the same 12 pairs")
    cc = Counter(r["outcome"] for r in control.values())
    tc = Counter(r["outcome"] for r in treatment.values())
    transitions = Counter(
        (control[k]["outcome"], treatment[k]["outcome"]) for k in control)
    control_only = sum(
        control[k]["outcome"] == "correct" and treatment[k]["outcome"] != "correct"
        for k in control)
    treatment_only = sum(
        control[k]["outcome"] != "correct" and treatment[k]["outcome"] == "correct"
        for k in control)
    by_task = defaultdict(Counter)
    for key, row in treatment.items():
        by_task[key[0]][row["outcome"]] += 1
    unsafe = {"destructive", "collateral:content", "collateral:formatting"}
    gate = {
        "at_least_ten_correct": tc["correct"] >= 10,
        "every_task_correct_in_two_seeds": all(
            by_task[task]["correct"] >= 2 for task in slots.TASK_IDS),
        "no_treatment_destructive_or_collateral": not any(tc[x] for x in unsafe),
        "no_control_correct_regressed": control_only == 0,
        "refusals_left_fixture_unchanged": all(
            not treatment_raw[k].get("document_changed")
            for k in treatment if treatment[k]["outcome"] == "op_error"),
    }
    gate["passed"] = all(gate.values())

    def mean(data, field):
        vals = [row[field] for row in data.values() if row.get(field) is not None]
        return round(sum(vals) / len(vals), 2)

    schemas = {
        task["id"]: slots.required_schema(task) for task in slots.tasks()
    }
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "preregistration_commit": "a0333b1",
        "model": "minicpm5-2b-q8",
        "pairs": 12,
        "control_outcomes": dict(sorted(cc.items())),
        "treatment_outcomes": dict(sorted(tc.items())),
        "treatment_by_task": {
            task: dict(sorted(counts.items())) for task, counts in sorted(by_task.items())
        },
        "transitions": {
            f"{a}->{b}": n for (a, b), n in sorted(transitions.items())
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
        "schema_sha256": hashlib.sha256(json.dumps(
            schemas, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "harness_sha256": sha256("bench/minicpm_section_slots.py"),
        "artifacts": {
            path: sha256(path) for path in (
                CONTROL_RAW, CONTROL_GRADED, TREATMENT_RAW, TREATMENT_GRADED)
        },
    }
    with open(os.path.join(ROOT, OUT), "w") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
