#!/usr/bin/env python3
"""Analyze the preregistered MiniCPM required exact-list-anchor arm."""

import hashlib
import json
import math
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bench"))
import minicpm_list_required_after as treatment  # noqa: E402

CONTROL_RAW = "bench/results/minicpm5_routed_lists_20260921.jsonl"
CONTROL_GRADED = "bench/results/minicpm5_routed_lists_20260921_graded.jsonl"
TREATMENT_RAW = "bench/results/minicpm5_list_required_after_20260922.jsonl"
TREATMENT_GRADED = "bench/results/minicpm5_list_required_after_20260922_graded.jsonl"
OUT = "bench/results/minicpm5_list_required_after_analysis_20260922.json"


def rows(path):
    selected = {}
    with open(os.path.join(ROOT, path)) as fh:
        for line in fh:
            row = json.loads(line)
            if row["task_id"] in treatment.TASK_IDS:
                selected[(row["task_id"], row["trial"])] = row
    return selected


def sha256(path):
    with open(os.path.join(ROOT, path), "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def exact_mcnemar(control_only, treatment_only):
    n = control_only + treatment_only
    if not n:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(min(control_only, treatment_only) + 1))
    return min(1.0, 2 * tail / (2 ** n))


def mean(data, field):
    values = [row[field] for row in data.values() if row.get(field) is not None]
    return round(sum(values) / len(values), 2)


def main():
    control = rows(CONTROL_GRADED)
    treated = rows(TREATMENT_GRADED)
    control_raw = rows(CONTROL_RAW)
    treated_raw = rows(TREATMENT_RAW)
    if set(control) != set(treated) or len(treated) != 6:
        raise RuntimeError("control and treatment are not the fixed six pairs")
    cc = Counter(row["outcome"] for row in control.values())
    tc = Counter(row["outcome"] for row in treated.values())
    control_only = sum(
        control[key]["outcome"] == "correct"
        and treated[key]["outcome"] != "correct" for key in treated)
    treatment_only = sum(
        control[key]["outcome"] != "correct"
        and treated[key]["outcome"] == "correct" for key in treated)
    by_task = defaultdict(Counter)
    for key, row in treated.items():
        by_task[key[0]][row["outcome"]] += 1
    unsafe = {"destructive", "collateral:content", "collateral:formatting"}
    gate = {
        "at_least_five_correct": tc["correct"] >= 5,
        "each_task_correct_in_two_seeds": all(
            by_task[task]["correct"] >= 2 for task in treatment.TASK_IDS),
        "no_control_correct_regressed": control_only == 0,
        "no_destructive_or_collateral": not any(tc[name] for name in unsafe),
        "refusals_left_fixture_unchanged": all(
            not treated_raw[key].get("document_changed")
            for key in treated if treated[key]["outcome"] == "op_error"),
        "every_executed_after_from_read": all(
            row.get("after_from_read") is True for row in treated_raw.values()),
    }
    gate["passed"] = all(gate.values())
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "preregistration_commit": "f12ab5d",
        "model": "minicpm5-2b-q8",
        "pairs": 6,
        "control_outcomes": dict(sorted(cc.items())),
        "treatment_outcomes": dict(sorted(tc.items())),
        "treatment_by_task": {
            task: dict(sorted(counts.items())) for task, counts in sorted(by_task.items())
        },
        "paired_correct": {
            "control": cc["correct"], "treatment": tc["correct"],
            "control_only": control_only, "treatment_only": treatment_only,
            "exact_mcnemar_p": exact_mcnemar(control_only, treatment_only),
        },
        "efficiency": {
            "control_mean_completion_tokens": mean(control_raw, "completion_tokens"),
            "treatment_mean_completion_tokens": mean(
                treated_raw, "completion_tokens"),
            "read_mean_completion_tokens": mean(
                treated_raw, "read_completion_tokens"),
            "edit_mean_completion_tokens": mean(
                treated_raw, "edit_completion_tokens"),
            "treatment_mean_elapsed_s": mean(treated_raw, "elapsed_s"),
        },
        "gate": gate,
        "sampling_harness_sha256": sorted({
            row.get("harness_sha256") for row in treated_raw.values()}),
        "schema_sha256": {
            "list_get": sorted({
                row.get("list_get_schema_sha256") for row in treated_raw.values()}),
            "dynamic_edit": sorted({
                row.get("edit_schema_sha256") for row in treated_raw.values()}),
        },
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
