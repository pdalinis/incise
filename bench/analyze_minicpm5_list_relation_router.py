#!/usr/bin/env python3
"""Analyze the preregistered MiniCPM list-relation router arm."""

import hashlib
import json
import math
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TASKS = {"add-item-nested-asterisk", "add-item-ordered-renumber"}
GENERIC_GRADED = "bench/results/minicpm5_routed_lists_20260921_graded.jsonl"
AFTER_GRADED = "bench/results/minicpm5_list_required_after_20260922_graded.jsonl"
BETWEEN_GRADED = "bench/results/minicpm5_list_between_20260922_graded.jsonl"
TREATMENT_RAW = "bench/results/minicpm5_list_relation_router_20260922.jsonl"
TREATMENT_GRADED = "bench/results/minicpm5_list_relation_router_20260922_graded.jsonl"
OUT = "bench/results/minicpm5_list_relation_router_analysis_20260922.json"


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
    tail = sum(math.comb(n, k) for k in range(min(control_only, treatment_only) + 1))
    return min(1.0, 2 * tail / (2 ** n))


def paired(control, treated):
    control_only = sum(
        control[key]["outcome"] == "correct"
        and treated[key]["outcome"] != "correct" for key in treated)
    treatment_only = sum(
        control[key]["outcome"] != "correct"
        and treated[key]["outcome"] == "correct" for key in treated)
    return {
        "control_correct": sum(
            row["outcome"] == "correct" for row in control.values()),
        "treatment_correct": sum(
            row["outcome"] == "correct" for row in treated.values()),
        "control_only": control_only,
        "treatment_only": treatment_only,
        "exact_mcnemar_p": exact_mcnemar(control_only, treatment_only),
    }


def main():
    generic = rows(GENERIC_GRADED)
    after = rows(AFTER_GRADED)
    between = rows(BETWEEN_GRADED)
    treated = rows(TREATMENT_GRADED)
    raw = rows(TREATMENT_RAW)
    ceiling = {
        key: (after[key] if key[0] == "add-item-nested-asterisk" else between[key])
        for key in treated
    }
    if (len(treated) != 6 or set(generic) != set(treated)
            or set(ceiling) != set(treated) or set(raw) != set(treated)):
        raise RuntimeError("references and treatment are not the fixed six pairs")
    outcomes = Counter(row["outcome"] for row in treated.values())
    relation_correct = sum(
        row.get("relation_correct") is True for row in treated.values())
    by_task = defaultdict(Counter)
    for key, row in treated.items():
        by_task[key[0]][row["outcome"]] += 1
    unsafe = {"destructive", "collateral:content", "collateral:formatting"}
    gate = {
        "at_least_five_correct_relations": relation_correct >= 5,
        "at_least_five_correct_documents": outcomes["correct"] >= 5,
        "each_task_correct_in_two_seeds": all(
            by_task[task]["correct"] >= 2 for task in TASKS),
        "no_destructive_or_collateral": not any(outcomes[name] for name in unsafe),
        "refusals_left_fixture_unchanged": all(
            not raw[key].get("document_changed")
            for key in treated if treated[key]["outcome"] == "op_error"),
        "executed_calls_passed_validation": all(
            row.get("validation_passed") is True
            for row in raw.values() if row.get("composed_operation") is not None),
    }
    gate["passed"] = all(gate.values())

    def mean(field):
        values = [row[field] for row in raw.values() if row.get(field) is not None]
        return round(sum(values) / len(values), 2)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "preregistration_commit": "e105bb4",
        "model": "minicpm5-2b-q8",
        "pairs": 6,
        "relation_selection": {
            "correct": relation_correct,
            "total": 6,
            "by_task": {
                task: sum(
                    row.get("relation_correct") is True
                    for key, row in treated.items() if key[0] == task)
                for task in sorted(TASKS)
            },
        },
        "treatment_outcomes": dict(sorted(outcomes.items())),
        "treatment_by_task": {
            task: dict(sorted(counts.items())) for task, counts in sorted(by_task.items())
        },
        "paired_vs_generic": paired(generic, treated),
        "paired_vs_oracle_ceiling": paired(ceiling, treated),
        "efficiency": {
            "mean_completion_tokens": mean("completion_tokens"),
            "read_mean_completion_tokens": mean("read_completion_tokens"),
            "route_mean_completion_tokens": mean("route_completion_tokens"),
            "mean_elapsed_s": mean("elapsed_s"),
        },
        "gate": gate,
        "sampling_harness_sha256": sorted({
            row.get("harness_sha256") for row in raw.values()}),
        "schema_sha256": {
            "list_get": sorted({
                row.get("list_get_schema_sha256") for row in raw.values()}),
            "relation_tools": sorted({
                row.get("relation_schemas_sha256") for row in raw.values()}),
        },
        "artifacts": {
            path: sha256(path) for path in (
                GENERIC_GRADED, AFTER_GRADED, BETWEEN_GRADED,
                TREATMENT_RAW, TREATMENT_GRADED)
        },
    }
    with open(os.path.join(ROOT, OUT), "w") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
