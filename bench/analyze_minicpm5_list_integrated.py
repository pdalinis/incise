#!/usr/bin/env python3
"""Analyze the preregistered integrated MiniCPM routed-list arm."""

import hashlib
import json
import math
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bench"))
import minicpm_list_integrated as treatment  # noqa: E402

CONTROL_RAW = "bench/results/minicpm5_routed_lists_20260921.jsonl"
CONTROL_GRADED = "bench/results/minicpm5_routed_lists_20260921_graded.jsonl"
TREATMENT_RAW = "bench/results/minicpm5_list_integrated_20260922.jsonl"
TREATMENT_GRADED = "bench/results/minicpm5_list_integrated_20260922_graded.jsonl"
OUT = "bench/results/minicpm5_list_integrated_analysis_20260922.json"
TASKS = set(treatment.EXPECTED_ROUTE)


def rows(path):
    selected = {}
    with open(os.path.join(ROOT, path)) as fh:
        for line in fh:
            row = json.loads(line)
            if row["task_id"] in TASKS:
                selected[(row["task_id"], row["trial"])] = row
    return selected


def sha256(path):
    with open(os.path.join(ROOT, path), "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def exact_mcnemar(control_only, treatment_only):
    n = control_only + treatment_only
    if not n:
        return 1.0
    tail = sum(
        math.comb(n, k) for k in range(min(control_only, treatment_only) + 1))
    return min(1.0, 2 * tail / (2 ** n))


def mean(data, field):
    values = [row[field] for row in data.values() if row.get(field) is not None]
    return round(sum(values) / len(values), 2) if values else None


def localize(raw_row, graded_row):
    if graded_row["outcome"] == "correct":
        return "correct"
    if raw_row.get("address_correct") is not True:
        return "address_selection"
    if raw_row.get("route_correct") is not True:
        return "request_routing"
    if raw_row.get("composed_operation") is None:
        if raw_row.get("host_route") in {"after", "between"}:
            return "content_or_anchor_selection"
        return "content_selection"
    if raw_row.get("execution_error"):
        return "execution"
    return "content_semantics"


def main():
    control = rows(CONTROL_GRADED)
    treated = rows(TREATMENT_GRADED)
    control_raw = rows(CONTROL_RAW)
    raw = rows(TREATMENT_RAW)
    expected_keys = {(task, trial) for task in TASKS for trial in range(3)}
    if not all(set(data) == expected_keys for data in (
            control, treated, control_raw, raw)):
        raise RuntimeError("control and treatment are not the fixed 21 pairs")

    cc = Counter(row["outcome"] for row in control.values())
    tc = Counter(row["outcome"] for row in treated.values())
    control_only = sum(
        control[key]["outcome"] == "correct"
        and treated[key]["outcome"] != "correct" for key in expected_keys)
    treatment_only = sum(
        control[key]["outcome"] != "correct"
        and treated[key]["outcome"] == "correct" for key in expected_keys)
    by_task = defaultdict(Counter)
    localization = Counter()
    for key in expected_keys:
        by_task[key[0]][treated[key]["outcome"]] += 1
        localization[localize(raw[key], treated[key])] += 1

    unsafe = {"destructive", "collateral:content", "collateral:formatting"}
    gate = {
        "at_least_nineteen_correct": tc["correct"] >= 19,
        "each_task_correct_in_two_seeds": all(
            by_task[task]["correct"] >= 2 for task in TASKS),
        "no_control_correct_regressed": control_only == 0,
        "no_destructive_or_collateral": not any(tc[name] for name in unsafe),
        "refusals_left_fixture_unchanged": all(
            not raw[key].get("document_changed")
            for key in expected_keys if raw[key].get("phase_error") is not None),
        "all_routes_match_preregistered_mapping": all(
            raw[key].get("route_correct") is True for key in expected_keys),
        "executed_structure_was_validated": all(
            raw[key].get("structure_validated") is True
            for key in expected_keys
            if raw[key].get("composed_operation") is not None),
    }
    gate["passed"] = all(gate.values())

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "preregistration_commit": "9564eee",
        "pre_sampling_amendment_commit": "ab0e487",
        "model": "minicpm5-2b-q8",
        "pairs": 21,
        "address_selection": {
            "correct": sum(
                row.get("address_correct") is True for row in raw.values()),
            "total": 21,
        },
        "request_routing": {
            "correct": sum(
                row.get("route_correct") is True for row in raw.values()),
            "total": 21,
            "mapping": dict(sorted(treatment.EXPECTED_ROUTE.items())),
        },
        "control_outcomes": dict(sorted(cc.items())),
        "treatment_outcomes": dict(sorted(tc.items())),
        "treatment_by_task": {
            task: dict(sorted(counts.items()))
            for task, counts in sorted(by_task.items())
        },
        "failure_localization": dict(sorted(localization.items())),
        "paired_correct": {
            "control": cc["correct"],
            "treatment": tc["correct"],
            "control_only": control_only,
            "treatment_only": treatment_only,
            "exact_mcnemar_p": exact_mcnemar(control_only, treatment_only),
        },
        "efficiency": {
            "control_mean_completion_tokens": mean(
                control_raw, "completion_tokens"),
            "treatment_mean_completion_tokens": mean(raw, "completion_tokens"),
            "select_mean_completion_tokens": mean(
                raw, "select_completion_tokens"),
            "content_mean_completion_tokens": mean(
                raw, "content_completion_tokens"),
            "treatment_mean_elapsed_s": mean(raw, "elapsed_s"),
        },
        "gate": gate,
        "sampling_harness_sha256": sorted({
            row.get("harness_sha256") for row in raw.values()}),
        "schema_sha256": {
            "selection": sorted({
                row.get("selection_schema_sha256") for row in raw.values()}),
            "content": sorted({
                row.get("content_schema_sha256") for row in raw.values()}),
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
