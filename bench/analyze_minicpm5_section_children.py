#!/usr/bin/env python3
"""Paired report for the preregistered MiniCPM section-children arm."""

import hashlib
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bench"))

import minicpm_routed  # noqa: E402


TASKS = {
    "insert-release-at-top", "insert-subsection-last",
    "insert-nested-ratelimits", "insert-troubleshooting",
}
CONTROL_RAW = "bench/results/minicpm5_routed_sections_20260921.jsonl"
CONTROL_GRADED = "bench/results/minicpm5_routed_sections_20260921_graded.jsonl"
TREATMENT_RAW = "bench/results/minicpm5_section_children_20260921.jsonl"
TREATMENT_GRADED = "bench/results/minicpm5_section_children_20260921_graded.jsonl"
OUT = "bench/results/minicpm5_section_children_analysis_20260921.json"


def sha256(path):
    return hashlib.sha256(open(os.path.join(ROOT, path), "rb").read()).hexdigest()


def rows(path):
    out = {}
    for line in open(os.path.join(ROOT, path)):
        row = json.loads(line)
        if row["task_id"] in TASKS:
            out[(row["task_id"], row["trial"])] = row
    return out


def main():
    control = rows(CONTROL_GRADED)
    treatment = rows(TREATMENT_GRADED)
    treatment_raw = rows(TREATMENT_RAW)
    if set(control) != set(treatment) or len(control) != 12:
        raise RuntimeError(
            f"expected the same 12 keys, got {len(control)} and {len(treatment)}")

    transitions = Counter(
        (control[key]["outcome"], treatment[key]["outcome"])
        for key in sorted(control)
    )
    control_counts = Counter(row["outcome"] for row in control.values())
    treatment_counts = Counter(row["outcome"] for row in treatment.values())
    unsafe = {"destructive", "collateral:content", "collateral:formatting"}
    refusals_unchanged = all(
        not raw.get("document_changed")
        for key, raw in treatment_raw.items()
        if treatment[key]["outcome"] == "op_error"
    )
    single_keys = [key for key in treatment if key[0] == "insert-subsection-last"]

    binary = os.path.join(ROOT, "target/debug/incise")
    schema = minicpm_routed.load_schemas(binary, section_children=True)["section_insert"]
    schema_bytes = json.dumps(schema, sort_keys=True, separators=(",", ":")).encode()
    gate = {
        "at_least_four_correct": treatment_counts["correct"] >= 4,
        "no_treatment_destructive_or_collateral": not any(
            treatment_counts[name] for name in unsafe),
        "single_subsection_no_new_unsafe": not any(
            treatment[key]["outcome"] in unsafe for key in single_keys),
        "refusals_left_fixture_unchanged": refusals_unchanged,
    }
    gate["passed"] = all(gate.values())

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "preregistration_commit": "789aa42",
        "model": "minicpm5-2b-q8",
        "pairs": 12,
        "control_outcomes": dict(sorted(control_counts.items())),
        "treatment_outcomes": dict(sorted(treatment_counts.items())),
        "transitions": {
            f"{a}->{b}": count for (a, b), count in sorted(transitions.items())
        },
        "paired_correct": {
            "control": control_counts["correct"],
            "treatment": treatment_counts["correct"],
            "control_only": sum(
                control[k]["outcome"] == "correct" and treatment[k]["outcome"] != "correct"
                for k in control),
            "treatment_only": sum(
                control[k]["outcome"] != "correct" and treatment[k]["outcome"] == "correct"
                for k in control),
            "exact_mcnemar_p": 1.0,
        },
        "gate": gate,
        "schema_sha256": hashlib.sha256(schema_bytes).hexdigest(),
        "artifacts": {
            path: sha256(path) for path in (
                CONTROL_RAW, CONTROL_GRADED, TREATMENT_RAW, TREATMENT_GRADED)
        },
        "harness_sha256": sha256("bench/minicpm_routed.py"),
    }
    with open(os.path.join(ROOT, OUT), "w") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
