#!/usr/bin/env python3
"""Analyze the preregistered MiniCPM Pi list-profile integration arm."""

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
TREATMENT_RAW = "bench/results/minicpm5_pi_list_profile_20260922_v2.jsonl"
TREATMENT_GRADED = "bench/results/minicpm5_pi_list_profile_20260922_v2_graded.jsonl"
OUT = "bench/results/minicpm5_pi_list_profile_analysis_20260922_v2.json"
TASKS = set(treatment.EXPECTED_ROUTE)


def rows(path):
    selected = {}
    with open(os.path.join(ROOT, path)) as handle:
        for line in handle:
            row = json.loads(line)
            if row["task_id"] in TASKS:
                selected[(row["task_id"], row["trial"])] = row
    return selected


def sha256(path):
    with open(os.path.join(ROOT, path), "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


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


def localize(raw, graded):
    if graded["outcome"] == "correct":
        return "correct"
    names = [call.get("function", {}).get("name") for call in raw.get("tool_calls", [])]
    if "list_select" not in names:
        return "tool_invocation"
    if raw.get("selection_validated") is not True:
        return "address_selection"
    if raw.get("route_correct") is not True:
        return "request_routing"
    if not any(name in {"list_append_item", "list_insert_after", "list_insert_between"}
               for name in names):
        return "content_invocation"
    if raw.get("content_validated") is not True:
        return "content_or_anchor_selection"
    return "execution_or_content_semantics"


def main():
    control = rows(CONTROL_GRADED)
    treated = rows(TREATMENT_GRADED)
    control_raw = rows(CONTROL_RAW)
    raw = rows(TREATMENT_RAW)
    expected = {(task, trial) for task in TASKS for trial in range(3)}
    if not all(set(data) == expected for data in (control, treated, control_raw, raw)):
        raise RuntimeError("control and treatment are not the fixed 21 pairs")

    cc = Counter(row["outcome"] for row in control.values())
    tc = Counter(row["outcome"] for row in treated.values())
    control_only = sum(
        control[key]["outcome"] == "correct"
        and treated[key]["outcome"] != "correct" for key in expected)
    treatment_only = sum(
        control[key]["outcome"] != "correct"
        and treated[key]["outcome"] == "correct" for key in expected)
    by_task = defaultdict(Counter)
    localization = Counter()
    for key in expected:
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
            for key in expected if treated[key]["outcome"] == "op_error"),
        "all_routes_match_preregistered_mapping": all(
            raw[key].get("route_correct") is True for key in expected),
        "executed_structure_was_validated": all(
            raw[key].get("selection_validated") is True
            and raw[key].get("content_validated") is True
            for key in expected if raw[key].get("successful_mutations", 0) > 0),
        "at_most_one_successful_mutation_per_turn": all(
            raw[key].get("successful_mutations", 0) <= 1 for key in expected),
    }
    gate["passed"] = all(gate.values())

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "preregistration_commit": "b53a9e9",
        "preflight_correction_commit": "9f213b0",
        "implementation_commit": "fd1776e",
        "model": "minicpm5-2b-q8",
        "pi_version": "0.85.1",
        "pairs": 21,
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
        "invocation": {
            "selection_calls": sum(
                any(call.get("function", {}).get("name") == "list_select"
                    for call in row.get("tool_calls", [])) for row in raw.values()),
            "validated_content_calls": sum(
                row.get("content_validated") is True for row in raw.values()),
            "successful_mutations": sum(
                row.get("successful_mutations", 0) for row in raw.values()),
        },
        "efficiency": {
            "control_mean_completion_tokens": mean(control_raw, "completion_tokens"),
            "treatment_mean_completion_tokens": mean(raw, "completion_tokens"),
            "treatment_mean_elapsed_s": mean(raw, "elapsed_s"),
            "treatment_mean_turns": mean(raw, "n_turns"),
        },
        "gate": gate,
        "source_sha256": {
            "extension": sorted({row.get("extension_sha256") for row in raw.values()}),
            "pipeline": sorted({row.get("pipeline_sha256") for row in raw.values()}),
            "worker": sorted({row.get("worker_sha256") for row in raw.values()}),
        },
        "artifacts": {
            path: sha256(path) for path in (
                CONTROL_RAW, CONTROL_GRADED, TREATMENT_RAW, TREATMENT_GRADED)
        },
    }
    with open(os.path.join(ROOT, OUT), "w") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
