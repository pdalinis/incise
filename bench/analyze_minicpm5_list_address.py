#!/usr/bin/env python3
"""Analyze the preregistered MiniCPM required structured list-address arm."""

import hashlib
import json
import math
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TASKS = {"add-item-loose", "add-item-mixed-markers"}
CONTROL_RAW = "bench/results/minicpm5_routed_lists_20260921.jsonl"
CONTROL_GRADED = "bench/results/minicpm5_routed_lists_20260921_graded.jsonl"
HANDLE_GRADED = "bench/results/minicpm5_list_handle_20260922_graded.jsonl"
TREATMENT_RAW = "bench/results/minicpm5_list_address_20260922.jsonl"
TREATMENT_GRADED = "bench/results/minicpm5_list_address_20260922_graded.jsonl"
OUT = "bench/results/minicpm5_list_address_analysis_20260922.json"


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


def exact_mcnemar(a, b):
    n = a + b
    if not n:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(min(a, b) + 1))
    return min(1.0, 2 * tail / (2 ** n))


def paired(control, treated):
    a = sum(control[k]["outcome"] == "correct" and treated[k]["outcome"] != "correct"
            for k in treated)
    b = sum(control[k]["outcome"] != "correct" and treated[k]["outcome"] == "correct"
            for k in treated)
    return {
        "control_correct": sum(r["outcome"] == "correct" for r in control.values()),
        "treatment_correct": sum(r["outcome"] == "correct" for r in treated.values()),
        "control_only": a, "treatment_only": b, "exact_mcnemar_p": exact_mcnemar(a, b),
    }


def main():
    control, handles = rows(CONTROL_GRADED), rows(HANDLE_GRADED)
    treated, raw = rows(TREATMENT_GRADED), rows(TREATMENT_RAW)
    control_raw = rows(CONTROL_RAW)
    if (len(treated) != 6 or set(control) != set(treated)
            or set(handles) != set(treated) or set(raw) != set(treated)):
        raise RuntimeError("references and treatment are not the fixed six pairs")
    outcomes = Counter(r["outcome"] for r in treated.values())
    addresses = sum(r.get("address_correct") is True for r in raw.values())
    by_task = defaultdict(Counter)
    for key, row in treated.items():
        by_task[key[0]][row["outcome"]] += 1
    generic_pair = paired(control, treated)
    unsafe = {"destructive", "collateral:content", "collateral:formatting"}
    gate = {
        "at_least_five_correct_addresses": addresses >= 5,
        "at_least_five_correct_documents": outcomes["correct"] >= 5,
        "each_task_correct_in_two_seeds": all(
            by_task[t]["correct"] >= 2 for t in TASKS),
        "no_generic_control_correct_regressed": generic_pair["control_only"] == 0,
        "no_destructive_or_collateral": not any(outcomes[x] for x in unsafe),
        "refusals_left_fixture_unchanged": all(
            not raw[k].get("document_changed")
            for k in treated if treated[k]["outcome"] == "op_error"),
        "executed_addresses_from_entries": all(
            r.get("address_from_entries") is True for r in raw.values()),
    }
    gate["passed"] = all(gate.values())

    def mean(data, field):
        vals = [r[field] for r in data.values() if r.get(field) is not None]
        return round(sum(vals) / len(vals), 2)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "preregistration_commit": "ba0016e",
        "model": "minicpm5-2b-q8", "pairs": 6,
        "address_selection": {"correct": addresses, "total": 6},
        "treatment_outcomes": dict(sorted(outcomes.items())),
        "treatment_by_task": {
            t: dict(sorted(c.items())) for t, c in sorted(by_task.items())},
        "paired_vs_generic": generic_pair,
        "paired_vs_composite_handle": paired(handles, treated),
        "efficiency": {
            "generic_mean_completion_tokens": mean(control_raw, "completion_tokens"),
            "treatment_mean_completion_tokens": mean(raw, "completion_tokens"),
            "select_mean_completion_tokens": mean(raw, "select_completion_tokens"),
            "content_mean_completion_tokens": mean(raw, "content_completion_tokens"),
            "treatment_mean_elapsed_s": mean(raw, "elapsed_s"),
        },
        "gate": gate,
        "sampling_harness_sha256": sorted({r.get("harness_sha256") for r in raw.values()}),
        "artifacts": {p: sha256(p) for p in (
            CONTROL_RAW, CONTROL_GRADED, HANDLE_GRADED, TREATMENT_RAW, TREATMENT_GRADED)},
    }
    with open(os.path.join(ROOT, OUT), "w") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
