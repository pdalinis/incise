#!/usr/bin/env python3
"""Analyse Ornith's parallel-tool-call protocol treatment."""

import argparse
import json
from pathlib import Path
import statistics


HARMFUL = {"wrong", "destructive", "collateral:content", "collateral:formatting"}
TASK = "insert-troubleshooting"


def latest(path):
    rows = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            rows[(row["task_id"], row["trial"])] = row
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--control-raw", required=True)
    parser.add_argument("--control-graded", required=True)
    parser.add_argument("--treatment-raw", required=True)
    parser.add_argument("--treatment-graded", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    control_raw, control_graded = latest(args.control_raw), latest(args.control_graded)
    treatment_raw = latest(args.treatment_raw)
    treatment_graded = latest(args.treatment_graded)
    keys = sorted(key for key in treatment_graded if key[0] == TASK)
    if len(keys) != 10 or any(key not in control_graded for key in keys):
        raise SystemExit("expected ten paired troubleshooting rows")

    audit_errors = []
    harmful = []
    reasoning_leaks = []
    for key in keys:
        row = treatment_raw[key]
        graded = treatment_graded[key]
        if graded["outcome"] in HARMFUL or graded.get("document_outcome") in HARMFUL:
            harmful.append(list(key))
        requests = row.get("provider_requests") or []
        if not requests or any(request.get("parallel_tool_calls") is not False
                               for request in requests):
            audit_errors.append([*key, "parallel_tool_calls was not always false"])
        calls = row.get("tool_calls") or []
        results = row.get("tool_results") or []
        successful = [result for result in results
                      if not result.get("is_error")
                      and (result.get("details") or {}).get("changed")]
        rejected = [result for result in results if result.get("is_error")]
        if len(calls) != 1 or len(successful) != 1 or rejected:
            audit_errors.append([
                *key, "call cardinality", len(calls), len(successful), len(rejected),
            ])
        visible = "\n".join(
            [row.get("final_content") or ""]
            + [(call.get("function") or {}).get("arguments") or "" for call in calls]
        )
        if "<think>" in visible or "</think>" in visible:
            reasoning_leaks.append(list(key))

    control_times = [control_raw[key]["elapsed_s"] for key in keys]
    treatment_times = [treatment_raw[key]["elapsed_s"] for key in keys]
    control_correct = sum(control_graded[key]["outcome"] == "correct" for key in keys)
    treatment_correct = sum(treatment_graded[key]["outcome"] == "correct" for key in keys)
    transports = [list(key) for key in keys
                  if treatment_graded[key]["outcome"] == "transport"]
    framing_errors = [list(key) for key in keys
                      if treatment_raw[key].get("framing_errors")]
    mean_elapsed = statistics.mean(treatment_times)
    max_elapsed = max(treatment_times)
    gate_failures = []
    if treatment_correct != 10:
        gate_failures.append("treatment is not 10/10 correct")
    if harmful:
        gate_failures.append("harmful outcome")
    if transports:
        gate_failures.append("transport outcome")
    if framing_errors:
        gate_failures.append("framing error")
    if reasoning_leaks:
        gate_failures.append("reasoning leak")
    if audit_errors:
        gate_failures.append("single-call audit error")
    if mean_elapsed > 20:
        gate_failures.append("mean elapsed exceeds 20 seconds")
    if max_elapsed > 45:
        gate_failures.append("maximum elapsed exceeds 45 seconds")
    if treatment_correct < control_correct:
        gate_failures.append("paired correctness regression")

    report = {
        "status": "pass" if not gate_failures else "fail",
        "pairs": len(keys),
        "control": {
            "correct": control_correct,
            "mean_elapsed_s": round(statistics.mean(control_times), 3),
            "max_elapsed_s": round(max(control_times), 3),
        },
        "treatment": {
            "correct": treatment_correct,
            "mean_elapsed_s": round(mean_elapsed, 3),
            "median_elapsed_s": round(statistics.median(treatment_times), 3),
            "max_elapsed_s": round(max_elapsed, 3),
        },
        "seed_1_elapsed_s": {
            "control": control_raw[(TASK, 1)]["elapsed_s"],
            "treatment": treatment_raw[(TASK, 1)]["elapsed_s"],
        },
        "harmful_trials": harmful,
        "transports": transports,
        "framing_errors": framing_errors,
        "reasoning_leaks": reasoning_leaks,
        "audit_errors": audit_errors,
        "gate_failures": gate_failures,
    }
    output = Path(args.out)
    if output.exists():
        raise SystemExit(f"refusing to overwrite {output}")
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
