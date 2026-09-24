#!/usr/bin/env python3
"""Analyse the paired Ornith checkbox and section-level route experiment."""

import argparse
from collections import Counter
import json
from pathlib import Path
import statistics


HARMFUL = {"wrong", "destructive", "collateral:content", "collateral:formatting"}
EXPECTED = {
    "check-task-nested": (
        "list_set_checked_target",
        "list-set-checked-target",
        {
            "list": {"heading": "Task lists > Nested", "ordinal": 0},
            "match": "child pending",
            "checked": True,
        },
    ),
    "promote-api": (
        "section_set_level_target",
        "section-set-level-target",
        {
            "section": "Deep heading nesting > Reference > API",
            "level": 2,
            "subtree": True,
        },
    ),
}


def latest(path):
    rows = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            rows[(row["task_id"], row["trial"])] = row
    return rows


def metrics(keys, raw, graded):
    elapsed = [raw[key]["elapsed_s"] for key in keys
               if raw[key].get("elapsed_s") is not None]
    harmful = [key for key in keys if graded[key]["outcome"] in HARMFUL
               or graded[key].get("document_outcome") in HARMFUL]
    return {
        "observed": len(keys),
        "correct": sum(graded[key]["outcome"] == "correct" for key in keys),
        "harmful": len(harmful),
        "harmful_trials": [list(key) for key in harmful],
        "outcomes": dict(sorted(Counter(graded[key]["outcome"]
                                         for key in keys).items())),
        "mean_elapsed_s": round(statistics.mean(elapsed), 3),
        "median_elapsed_s": round(statistics.median(elapsed), 3),
        "max_elapsed_s": round(max(elapsed), 3),
    }


def successful_results(row, name):
    results = {result["tool_call_id"]: result
               for result in row.get("tool_results", [])}
    values = []
    for call in row.get("tool_calls", []):
        if call.get("function", {}).get("name") != name:
            continue
        result = results.get(call.get("id"))
        if result is not None and not result.get("is_error"):
            values.append((call, result))
    return values


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
    keys = sorted(treatment_graded)
    if set(keys) != set(control_graded) or set(keys) != set(treatment_raw):
        raise SystemExit("control and treatment keys differ")

    route_errors = []
    reasoning_leaks = []
    final_document_errors = []
    for key in keys:
        row = treatment_raw[key]
        grade = treatment_graded[key]
        if grade.get("document_outcome") != "correct":
            final_document_errors.append([*key, grade.get("document_outcome")])
        visible = "\n".join(
            [row.get("final_content") or ""]
            + [(call.get("function") or {}).get("arguments") or ""
               for call in row.get("tool_calls") or []]
        )
        if "<think>" in visible or "</think>" in visible:
            reasoning_leaks.append(list(key))
        if key[0] not in EXPECTED:
            continue
        tool, route, expected_args = EXPECTED[key[0]]
        first = (row.get("provider_requests") or [{}])[0]
        if first.get("tools") != [tool] or first.get("active_tools") != [tool]:
            route_errors.append([*key, "provider tools", first.get("active_tools"), first.get("tools")])
        successes = successful_results(row, tool)
        if len(successes) != 1:
            route_errors.append([*key, "successful calls", len(successes)])
            continue
        call, result = successes[0]
        details = result.get("details") or {}
        if json.loads((call.get("function") or {}).get("arguments") or "null") != {}:
            route_errors.append([*key, "supplied arguments"])
        if details.get("route") != route:
            route_errors.append([*key, "route", details.get("route")])
        if details.get("resolvedArguments") != expected_args:
            route_errors.append([*key, "resolved arguments", details.get("resolvedArguments")])

    control = metrics(keys, control_raw, control_graded)
    treatment = metrics(keys, treatment_raw, treatment_graded)
    target_keys = [key for key in keys if key[0] in EXPECTED]
    target_correct = sum(treatment_graded[key]["outcome"] == "correct"
                         for key in target_keys)
    troubleshooting_control = sum(
        control_graded[key]["outcome"] == "correct"
        for key in keys if key[0] == "insert-troubleshooting")
    troubleshooting_treatment = sum(
        treatment_graded[key]["outcome"] == "correct"
        for key in keys if key[0] == "insert-troubleshooting")
    gate_failures = []
    if target_correct != 20:
        gate_failures.append("target routes are not 20/20 correct")
    if treatment["correct"] != 30 or final_document_errors:
        gate_failures.append("not all final documents are correct")
    if treatment["harmful"]:
        gate_failures.append("harmful outcome")
    if any(treatment_graded[key]["outcome"] == "transport" for key in keys):
        gate_failures.append("transport outcome")
    if any(treatment_raw[key].get("framing_errors") for key in keys):
        gate_failures.append("provider framing error")
    if reasoning_leaks:
        gate_failures.append("reasoning leakage")
    if route_errors:
        gate_failures.append("route audit error")
    if troubleshooting_treatment < troubleshooting_control:
        gate_failures.append("troubleshooting control regressed")
    if treatment["mean_elapsed_s"] > 30:
        gate_failures.append("mean elapsed exceeds 30 seconds")
    if treatment["max_elapsed_s"] > 90:
        gate_failures.append("completed trial exceeds 90 seconds")

    report = {
        "status": "pass" if not gate_failures else "fail",
        "pairs": len(keys),
        "control": control,
        "treatment": treatment,
        "target_correct": target_correct,
        "troubleshooting": {
            "control_correct": troubleshooting_control,
            "treatment_correct": troubleshooting_treatment,
        },
        "final_document_errors": final_document_errors,
        "route_errors": route_errors,
        "reasoning_leaks": reasoning_leaks,
        "gate_failures": gate_failures,
    }
    output = Path(args.out)
    if output.exists():
        raise SystemExit(f"refusing to overwrite {output}")
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
