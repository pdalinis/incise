#!/usr/bin/env python3
"""Analyze the preregistered MiniCPM two-phase section pipeline arm."""

import hashlib
import json
import math
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bench"))
import minicpm_section_pipeline as pipeline  # noqa: E402


CEILING_RAW = "bench/results/minicpm5_section_required_slots_20260921.jsonl"
CEILING_GRADED = "bench/results/minicpm5_section_required_slots_20260921_graded.jsonl"
ORIGINAL_RAW = "bench/results/minicpm5_routed_sections_20260921.jsonl"
ORIGINAL_GRADED = "bench/results/minicpm5_routed_sections_20260921_graded.jsonl"
TREATMENT_RAW = "bench/results/minicpm5_section_pipeline_20260921.jsonl"
TREATMENT_GRADED = "bench/results/minicpm5_section_pipeline_20260921_graded.jsonl"
OUT = "bench/results/minicpm5_section_pipeline_analysis_20260921.json"


def sha256(path):
    with open(os.path.join(ROOT, path), "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def rows(path):
    selected = {}
    with open(os.path.join(ROOT, path)) as fh:
        for line in fh:
            row = json.loads(line)
            if row["task_id"] in pipeline.slots.TASK_IDS:
                selected[(row["task_id"], row["trial"])] = row
    return selected


def exact_mcnemar(control_only, treatment_only):
    n = control_only + treatment_only
    if not n:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(min(control_only, treatment_only) + 1))
    return min(1.0, 2 * tail / (2 ** n))


def paired(control, treatment):
    control_only = sum(
        control[key]["outcome"] == "correct"
        and treatment[key]["outcome"] != "correct"
        for key in control
    )
    treatment_only = sum(
        control[key]["outcome"] != "correct"
        and treatment[key]["outcome"] == "correct"
        for key in control
    )
    return {
        "control_correct": sum(row["outcome"] == "correct" for row in control.values()),
        "treatment_correct": sum(
            row["outcome"] == "correct" for row in treatment.values()),
        "control_only": control_only,
        "treatment_only": treatment_only,
        "exact_mcnemar_p": exact_mcnemar(control_only, treatment_only),
    }


def mean(data, field):
    values = [row.get(field) for row in data.values() if row.get(field) is not None]
    return round(sum(values) / len(values), 2)


def main():
    ceiling = rows(CEILING_GRADED)
    original = rows(ORIGINAL_GRADED)
    treatment = rows(TREATMENT_GRADED)
    ceiling_raw = rows(CEILING_RAW)
    original_raw = rows(ORIGINAL_RAW)
    treatment_raw = rows(TREATMENT_RAW)
    expected_keys = set(treatment)
    if len(expected_keys) != 12 or set(ceiling) != expected_keys or set(original) != expected_keys:
        raise RuntimeError("reference and treatment arms are not the same 12 pairs")

    outcomes = Counter(row["outcome"] for row in treatment.values())
    by_task = defaultdict(Counter)
    for key, row in treatment.items():
        by_task[key[0]][row["outcome"]] += 1
    exact_plans = sum(row.get("plan_exact") is True for row in treatment.values())
    plan_fields = Counter()
    for row in treatment.values():
        expected = row.get("expected_plan") or {}
        received = row.get("received_plan") or {}
        for field in ("anchor", "position", "child_count"):
            if received.get(field) != expected.get(field):
                plan_fields[field] += 1
    failure_stages = Counter(
        row["failure_stage"] for row in treatment.values()
        if row.get("failure_stage")
    )
    unsafe = {"destructive", "collateral:content", "collateral:formatting"}
    gate = {
        "at_least_eleven_exact_plans": exact_plans >= 11,
        "at_least_ten_correct_final_documents": outcomes["correct"] >= 10,
        "every_task_correct_in_two_seeds": all(
            by_task[task]["correct"] >= 2 for task in pipeline.slots.TASK_IDS),
        "no_destructive_or_collateral": not any(outcomes[name] for name in unsafe),
        "refusals_left_fixture_unchanged": all(
            not treatment_raw[key].get("document_changed")
            for key in treatment
            if treatment[key]["outcome"] == "op_error"
        ),
    }
    gate["passed"] = all(gate.values())

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "preregistration_commit": "72f5ec0",
        "model": "minicpm5-2b-q8",
        "pairs": 12,
        "plan_accuracy": {
            "exact": exact_plans,
            "total": len(treatment),
            "field_mismatches": dict(sorted(plan_fields.items())),
        },
        "treatment_outcomes": dict(sorted(outcomes.items())),
        "treatment_by_task": {
            task: dict(sorted(counts.items())) for task, counts in sorted(by_task.items())
        },
        "failure_stages": dict(sorted(failure_stages.items())),
        "paired_vs_required_slot_ceiling": paired(ceiling, treatment),
        "paired_vs_original_routed": paired(original, treatment),
        "efficiency": {
            "pipeline_mean_completion_tokens": mean(treatment_raw, "completion_tokens"),
            "pipeline_mean_elapsed_s": mean(treatment_raw, "elapsed_s"),
            "plan_mean_completion_tokens": mean(
                treatment_raw, "plan_completion_tokens"),
            "plan_mean_elapsed_s": mean(treatment_raw, "plan_elapsed_s"),
            "content_mean_completion_tokens": mean(
                treatment_raw, "content_completion_tokens"),
            "content_mean_elapsed_s": mean(treatment_raw, "content_elapsed_s"),
            "required_slot_mean_completion_tokens": mean(
                ceiling_raw, "completion_tokens"),
            "original_routed_mean_completion_tokens": mean(
                original_raw, "completion_tokens"),
        },
        "gate": gate,
        "schema_sha256": {
            "plan": hashlib.sha256(json.dumps(
                {task["id"]: pipeline.plan_schema(
                    open(os.path.join(ROOT, task["fixture"]), newline="").read())
                 for task in pipeline.slots.tasks()},
                sort_keys=True, separators=(",", ":"),
            ).encode()).hexdigest(),
            "content": hashlib.sha256(json.dumps(
                {count: pipeline.slots.schema_for_child_count(count)
                 for count in (0, 1, 2)},
                sort_keys=True, separators=(",", ":"),
            ).encode()).hexdigest(),
        },
        "harness_sha256": sha256("bench/minicpm_section_pipeline.py"),
        "artifacts": {
            path: sha256(path) for path in (
                CEILING_RAW, CEILING_GRADED, ORIGINAL_RAW, ORIGINAL_GRADED,
                TREATMENT_RAW, TREATMENT_GRADED)
        },
    }
    with open(os.path.join(ROOT, OUT), "w") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
