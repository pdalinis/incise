#!/usr/bin/env python3
"""Analyze the preregistered MiniCPM semantic-label planner arm."""

import hashlib
import json
import math
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bench"))
import minicpm_section_semantic_plan as semantic  # noqa: E402

CONTROL = "bench/results/minicpm5_section_pipeline_20260921.jsonl"
TREATMENT = "bench/results/minicpm5_section_semantic_plan_20260921.jsonl"
GRADED = "bench/results/minicpm5_section_semantic_plan_20260921_graded.jsonl"
ORIGINAL_GRADED = GRADED
GRADED = "bench/results/minicpm5_section_semantic_plan_20260921_regraded.jsonl"
OUT = "bench/results/minicpm5_section_semantic_plan_analysis_20260921.json"


def rows(path):
    result = {}
    with open(os.path.join(ROOT, path)) as fh:
        for line in fh:
            row = json.loads(line)
            result[(row["task_id"], row["trial"])] = row
    return result


def sha256(path):
    with open(os.path.join(ROOT, path), "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def exact_mcnemar(control_only, treatment_only):
    n = control_only + treatment_only
    if not n:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(min(control_only, treatment_only) + 1))
    return min(1.0, 2 * tail / (2 ** n))


def main():
    control, treatment, graded = rows(CONTROL), rows(TREATMENT), rows(GRADED)
    if set(control) != set(treatment) or set(graded) != set(treatment) or len(treatment) != 12:
        raise RuntimeError("control and treatment are not the fixed 12 pairs")
    control_only = sum(
        control[key].get("plan_exact") is True
        and treatment[key].get("plan_exact") is not True
        for key in treatment
    )
    treatment_only = sum(
        control[key].get("plan_exact") is not True
        and treatment[key].get("plan_exact") is True
        for key in treatment
    )
    exact = sum(row.get("plan_exact") is True for row in treatment.values())
    fields = {
        field: sum((row.get("field_matches") or {}).get(field) is True
                   for row in graded.values())
        for field in ("anchor", "relationship", "order", "content_shape")
    }
    by_task = defaultdict(Counter)
    for key, row in treatment.items():
        by_task[key[0]]["exact" if row.get("plan_exact") else "not_exact"] += 1
    outcomes = Counter(row["outcome"] for row in graded.values())
    gate = {
        "at_least_ten_exact_plans": exact >= 10,
        "relationship_order_shape_at_least_eleven": all(
            fields[field] >= 11
            for field in ("relationship", "order", "content_shape")),
        "every_task_exact_in_two_seeds": all(
            by_task[task]["exact"] >= 2 for task in semantic.prior.slots.TASK_IDS),
        "all_anchors_resolve_canonically": fields["anchor"] == 12,
        "no_edit_executor_called": not any(
            row.get("executor_called") for row in treatment.values()),
    }
    gate["passed"] = all(gate.values())

    def mean(field):
        values = [row[field] for row in treatment.values() if row.get(field) is not None]
        return round(sum(values) / len(values), 2)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "preregistration_commit": "e3ec099",
        "model": "minicpm5-2b-q8",
        "pairs": 12,
        "exact_plans": exact,
        "field_correct": fields,
        "outcomes": dict(sorted(outcomes.items())),
        "by_task": {
            task: dict(sorted(counts.items())) for task, counts in sorted(by_task.items())
        },
        "paired_vs_dynamic_planner": {
            "control_exact": sum(
                row.get("plan_exact") is True for row in control.values()),
            "treatment_exact": exact,
            "control_only": control_only,
            "treatment_only": treatment_only,
            "exact_mcnemar_p": exact_mcnemar(control_only, treatment_only),
        },
        "efficiency": {
            "mean_completion_tokens": mean("completion_tokens"),
            "mean_elapsed_s": mean("elapsed_s"),
        },
        "gate": gate,
        "sampling_harness_sha256": sorted({
            row.get("harness_sha256") for row in treatment.values()
        }),
        "grading_harness_sha256": sha256(
            "bench/minicpm_section_semantic_plan.py"),
        "schema_sha256": sorted({
            row.get("schema_sha256") for row in treatment.values()
        }),
        "artifacts": {
            path: sha256(path) for path in (
                CONTROL, TREATMENT, ORIGINAL_GRADED, GRADED)
        },
    }
    with open(os.path.join(ROOT, OUT), "w") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
