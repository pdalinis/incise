#!/usr/bin/env python3
"""Analyze the preregistered MiniCPM5 routed treatment against its fixed control."""

import argparse
import hashlib
import json
import math
import os
from collections import Counter
from datetime import datetime, timezone

import minicpm_routed as routed


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(ROOT, "bench", "results")


def read_last(path):
    rows = {}
    with open(path) as fh:
        for line in fh:
            row = json.loads(line)
            rows[(row["task_id"], row["trial"])] = row
    return rows


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def exact_mcnemar(control_only, treatment_only):
    n = control_only + treatment_only
    if not n:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(min(control_only, treatment_only) + 1))
    return min(1.0, 2 * tail / (2**n))


def paths(family, treatment=False):
    if treatment:
        stem = f"minicpm5_routed_{family}_20260921"
    else:
        stem = f"minicpm5_roadmap_{family}_compose_5_20260921"
    return (os.path.join(RESULTS, stem + ".jsonl"),
            os.path.join(RESULTS, stem + "_graded.jsonl"))


def metrics(raw, grades):
    outcomes = Counter(row["outcome"] for row in grades.values())
    n = len(grades)
    silent = sum(count for outcome, count in outcomes.items()
                 if outcome in {"wrong", "destructive"}
                 or outcome.startswith("collateral:"))
    return {
        "trials": n,
        "outcomes": dict(sorted(outcomes.items())),
        "correct": outcomes["correct"],
        "silent_corruption": silent,
        "data_loss": outcomes["destructive"],
        "mean_completion_tokens": round(
            sum(row.get("completion_tokens") or 0 for row in raw.values()) / n, 2),
        "mean_elapsed_s": round(
            sum(row.get("elapsed_s") or 0 for row in raw.values()) / n, 2),
        "mean_executed_tool_calls": round(
            sum(len(row.get("tool_calls") or []) for row in raw.values()) / n, 2),
        "mean_emitted_tool_calls": round(
            sum(len(row.get("emitted_tool_calls", row.get("tool_calls")) or [])
                for row in raw.values()) / n, 2),
        "phase_errors": sum(bool(row.get("phase_error")) for row in raw.values()),
        "runaway_over_1000_tokens": sum(
            (row.get("completion_tokens") or 0) > 1000 for row in raw.values()),
    }


def attempt_counts(path):
    attempts = 0
    transport = 0
    with open(path) as fh:
        for line in fh:
            attempts += 1
            row = json.loads(line)
            kind = (row.get("error") or "").split(":", 1)[0]
            transport += int(kind in armb_transport_errors())
    return {"attempt_rows": attempts, "transport_rows": transport}


def armb_transport_errors():
    # Kept behind a function so importing this analysis remains cheap and the
    # source of truth stays in the grader that classifies these rows.
    import armb
    return armb.TRANSPORT_ERRORS


def family_report(family):
    control_raw_path, control_grade_path = paths(family)
    treatment_raw_path, treatment_grade_path = paths(family, treatment=True)
    allowed = routed.PRIMARY[family]
    control_raw = {key: row for key, row in read_last(control_raw_path).items()
                   if key[0] in allowed}
    control_grade = {key: row for key, row in read_last(control_grade_path).items()
                     if key[0] in allowed}
    treatment_raw = read_last(treatment_raw_path)
    treatment_grade = read_last(treatment_grade_path)
    keys = {(task, trial) for task in allowed for trial in range(3)}
    for label, rows in (("control raw", control_raw),
                        ("control grades", control_grade),
                        ("treatment raw", treatment_raw),
                        ("treatment grades", treatment_grade)):
        if set(rows) != keys:
            raise RuntimeError(f"{family} {label} keys differ from preregistration")
    control_only = sum(control_grade[key]["outcome"] == "correct"
                       and treatment_grade[key]["outcome"] != "correct" for key in keys)
    treatment_only = sum(control_grade[key]["outcome"] != "correct"
                         and treatment_grade[key]["outcome"] == "correct" for key in keys)
    return {
        "control": metrics(control_raw, control_grade),
        "treatment": metrics(treatment_raw, treatment_grade),
        "treatment_attempts": attempt_counts(treatment_raw_path),
        "paired": {
            "control_only_correct": control_only,
            "treatment_only_correct": treatment_only,
            "discordant": control_only + treatment_only,
            "exact_mcnemar_p": exact_mcnemar(control_only, treatment_only),
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out")
    parser.add_argument("--binary", default=os.path.join(ROOT, "target", "debug", "incise"))
    args = parser.parse_args()
    families = {family: family_report(family) for family in routed.PRIMARY}
    control_only = sum(item["paired"]["control_only_correct"] for item in families.values())
    treatment_only = sum(item["paired"]["treatment_only_correct"] for item in families.values())
    control_outcomes = Counter()
    treatment_outcomes = Counter()
    for item in families.values():
        control_outcomes.update(item["control"]["outcomes"])
        treatment_outcomes.update(item["treatment"]["outcomes"])

    gate = {
        "pooled_significant_improvement": (
            treatment_outcomes["correct"] > control_outcomes["correct"]
            and exact_mcnemar(control_only, treatment_only) < 0.05
        ),
        "no_family_loses_more_than_one_correct": all(
            item["treatment"]["correct"] >= item["control"]["correct"] - 1
            for item in families.values()
        ),
        "zero_treatment_data_loss": all(
            item["treatment"]["data_loss"] == 0 for item in families.values()
        ),
        "silent_corruption_not_increased": all(
            item["treatment"]["silent_corruption"]
            <= item["control"]["silent_corruption"]
            for item in families.values()
        ),
    }
    gate["passed"] = all(gate.values())

    artifacts = []
    for family in routed.PRIMARY:
        for treatment in (False, True):
            for path in paths(family, treatment=treatment):
                artifacts.append({"path": os.path.relpath(path, ROOT), "sha256": sha256(path)})
    schemas = routed.load_schemas(args.binary)
    schema_bytes = json.dumps(schemas, sort_keys=True, separators=(",", ":")).encode()
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": "minicpm5-2b-q8",
        "preregistration_commit": "cc97711",
        "primary_pairs": 90,
        "families": families,
        "pooled": {
            "control_outcomes": dict(sorted(control_outcomes.items())),
            "treatment_outcomes": dict(sorted(treatment_outcomes.items())),
            "control_correct": control_outcomes["correct"],
            "treatment_correct": treatment_outcomes["correct"],
            "control_only_correct": control_only,
            "treatment_only_correct": treatment_only,
            "exact_mcnemar_p": exact_mcnemar(control_only, treatment_only),
        },
        "gate": gate,
        "inputs": {
            "executor_sha256": sha256(args.binary),
            "harness_sha256": sha256(os.path.join(ROOT, "bench", "minicpm_routed.py")),
            "routed_schema_sha256": hashlib.sha256(schema_bytes).hexdigest(),
            "tasks": {
                family: sha256(os.path.join(ROOT, "bench", "tasks", routed.TASK_FILE[family]))
                for family in routed.PRIMARY
            },
        },
        "artifacts": artifacts,
    }
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(rendered)
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
