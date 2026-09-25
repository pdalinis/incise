#!/usr/bin/env python3
"""Replay routed MiniCPM frontmatter calls with host existence guards."""

import copy
import hashlib
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bench"))

import armb  # noqa: E402
from incise_ops import apply_op  # noqa: E402


RAW = os.path.join(
    ROOT, "bench/results/minicpm5_routed_frontmatter_20260921.jsonl")
GRADED = os.path.join(
    ROOT, "bench/results/minicpm5_routed_frontmatter_20260921_graded.jsonl")
OUT = os.path.join(
    ROOT, "bench/results/minicpm5_frontmatter_guard_replay_20260921.jsonl")
ANALYSIS = os.path.join(
    ROOT, "bench/results/minicpm5_frontmatter_guard_analysis_20260921.json")
TASKS = os.path.join(ROOT, "bench/tasks/frontmatter.json")

CREATE_TASKS = {"add-build-cache", "create-on-absent", "fill-empty"}
UPDATE_TASKS = {
    "set-build-jobs", "set-build-target", "set-dana-role", "clear-title",
    "set-draft-true", "release-bump",
}


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_last(path):
    rows = {}
    with open(path) as fh:
        for line in fh:
            row = json.loads(line)
            rows[(row["task_id"], row["trial"])] = row
    return rows


def precondition(task_id):
    if task_id in CREATE_TASKS:
        return {"must_absent": True}
    if task_id in UPDATE_TASKS:
        return {"must_exist": True}
    raise ValueError(f"no preregistered existence intent for {task_id}")


def guarded_trial(row):
    """Copy a recorded trial and add one host-owned mutation precondition."""
    guarded = copy.deepcopy(row)
    changed = 0
    for call in guarded.get("tool_calls") or []:
        fn = call.get("function", {})
        if fn.get("name") in armb.READS:
            continue
        args = json.loads(fn.get("arguments") or "{}")
        args.update(precondition(row["task_id"]))
        fn["arguments"] = json.dumps(args, separators=(",", ":"))
        changed += 1
    if changed > 1:
        raise ValueError(
            f"{row['task_id']} trial {row['trial']} has {changed} mutation calls")
    guarded["host_preconditions"] = (
        precondition(row["task_id"]) if changed else None)
    return guarded


def execute(task, row):
    with open(os.path.join(ROOT, task["fixture"]), newline="") as fh:
        before = fh.read()
    doc = before
    errors = []
    for call in row.get("tool_calls") or []:
        fn = call.get("function", {})
        if fn.get("name") in armb.READS:
            continue
        args = json.loads(fn.get("arguments") or "{}")
        op, args = armb.normalize(fn.get("name"), args)
        after, error = apply_op(doc, op, args)
        if error:
            errors.append(error)
        else:
            doc = after
    return before, doc, errors


def main():
    tasks = {
        task["id"]: task
        for task in json.load(open(TASKS))["tasks"]
        if task["id"] in CREATE_TASKS | UPDATE_TASKS
    }
    source = read_last(RAW)
    recorded = read_last(GRADED)
    if len(source) != 27 or len(recorded) != 27:
        raise RuntimeError(
            f"expected 27 paired rows, got raw={len(source)} graded={len(recorded)}")

    transitions = Counter()
    control_counts = Counter()
    treatment_counts = Counter()
    results = []
    all_control_grades_match = True
    all_prior_correct_identical = True
    all_refusals_unchanged = True

    for key in sorted(source):
        row = source[key]
        task = tasks[row["task_id"]]
        control_outcome, control_detail = armb.grade_one(task, row)
        recorded_outcome = recorded[key]["outcome"]
        control_grade_matches = control_outcome == recorded_outcome
        all_control_grades_match &= control_grade_matches

        treatment = guarded_trial(row)
        treatment_outcome, treatment_detail = armb.grade_one(task, treatment)
        before, control_doc, control_errors = execute(task, row)
        _, treatment_doc, treatment_errors = execute(task, treatment)

        correct_identical = control_outcome != "correct" or treatment_doc == control_doc
        refused_unchanged = not treatment_errors or treatment_doc == before
        all_prior_correct_identical &= correct_identical
        all_refusals_unchanged &= refused_unchanged

        control_counts[control_outcome] += 1
        treatment_counts[treatment_outcome] += 1
        transitions[(control_outcome, treatment_outcome)] += 1
        results.append({
            "task_id": row["task_id"],
            "trial": row["trial"],
            "precondition": precondition(row["task_id"]),
            "control_outcome": control_outcome,
            "control_detail": control_detail,
            "recorded_control_outcome": recorded_outcome,
            "control_grade_matches": control_grade_matches,
            "treatment_outcome": treatment_outcome,
            "treatment_detail": treatment_detail,
            "control_errors": control_errors,
            "treatment_errors": treatment_errors,
            "previously_correct_result_identical": correct_identical,
            "refusal_left_document_unchanged": refused_unchanged,
        })

    with open(OUT, "w") as fh:
        for result in results:
            fh.write(json.dumps(result, sort_keys=True) + "\n")

    unsafe = {"destructive", "collateral:content", "collateral:formatting"}
    destructive_eliminated = (
        control_counts["destructive"] == 2
        and treatment_counts["destructive"] == 0
    )
    no_treatment_unsafe = not any(treatment_counts[name] for name in unsafe)
    gate = {
        "destructive_calls_became_loud_refusals": (
            transitions[("destructive", "op_error")] == 2
            and destructive_eliminated
            and all_refusals_unchanged
        ),
        "previously_correct_results_byte_identical": all_prior_correct_identical,
        "no_treatment_destructive_or_collateral": no_treatment_unsafe,
        "control_grades_match_recorded": all_control_grades_match,
    }
    gate["passed"] = all(gate.values())

    analysis = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "preregistration_commit": "657daa4",
        "source": {
            "raw": os.path.relpath(RAW, ROOT),
            "raw_sha256": sha256(RAW),
            "graded": os.path.relpath(GRADED, ROOT),
            "graded_sha256": sha256(GRADED),
            "tasks_sha256": sha256(TASKS),
        },
        "implementation": {
            path: sha256(os.path.join(ROOT, path))
            for path in (
                "bench/incise_ops.py",
                "bench/replay_minicpm5_frontmatter_guard.py",
                "crates/incise-core/src/ops/frontmatter.rs",
                "crates/incise-core/src/ops/dispatch.rs",
                "crates/incise-core/src/error.rs",
            )
        },
        "pairs": len(results),
        "control_outcomes": dict(sorted(control_counts.items())),
        "treatment_outcomes": dict(sorted(treatment_counts.items())),
        "transitions": {
            f"{before}->{after}": count
            for (before, after), count in sorted(transitions.items())
        },
        "gate": gate,
    }
    with open(ANALYSIS, "w") as fh:
        json.dump(analysis, fh, indent=2, sort_keys=True)
        fh.write("\n")

    print(json.dumps(analysis, indent=2, sort_keys=True))
    return 0 if gate["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
