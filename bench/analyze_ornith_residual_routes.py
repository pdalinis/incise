#!/usr/bin/env python3
"""Audit the preregistered Ornith residual-route treatment."""

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bench"))

import ornith_full as ornith  # noqa: E402
import pi_composition as pi_bench  # noqa: E402


TASKS = {"add-item-ordered-renumber", "delete-draft", "rename-setext"}
SPECS = {
    "add-item-ordered-renumber": {
        "tool": "list_append_target", "route": "list-append-target",
        "supplied": {},
        "resolved": {
            "list": {"heading": "Ordered list numbering > Sequential", "ordinal": 0},
            "text": "two and a half", "after": "second",
        },
    },
    "delete-draft": {
        "tool": "frontmatter_delete_target", "route": "frontmatter-delete",
        "supplied": {}, "resolved": {"key": "draft"},
    },
    "rename-setext": {
        "tool": "section_rename_target", "route": "section-rename",
        "supplied": {},
        "resolved": {
            "section": "Setext H1 Title > Setext H2",
            "heading": "Setext level two",
        },
    },
}
DEFAULT_RAW = ROOT / "bench/results/ornith_residual_routes_20260923.jsonl"
DEFAULT_GRADED = ROOT / "bench/results/ornith_residual_routes_20260923_graded.jsonl"
DEFAULT_CONTROL = ROOT / "bench/results/ornith_second_held_safe_routed_20260923_graded.jsonl"
DEFAULT_ANALYSIS = ROOT / "bench/results/ornith_residual_routes_20260923_analysis.json"


def successful_results(row, name):
    results = {item["tool_call_id"]: item for item in row.get("tool_results") or []}
    return [(call, results[call["id"]]) for call in row.get("tool_calls") or []
            if call.get("function", {}).get("name") == name
            and call.get("id") in results and not results[call["id"]].get("is_error")]


def main(args):
    raw = ornith.latest_rows(args.out)
    graded = ornith.latest_rows(args.graded)
    control = ornith.latest_rows(args.control)
    keys = sorted(set(raw) & set(graded))
    errors = []
    harmful = []
    elapsed = []
    for key in keys:
        row, grade, expected = raw[key], graded[key], SPECS[key[0]]
        elapsed.append(row.get("elapsed_s") or 0)
        requests = row.get("provider_requests") or []
        first = requests[0] if requests else {}
        if (first.get("tools") != [expected["tool"]]
                or first.get("active_tools") != [expected["tool"]]
                or first.get("parallel_tool_calls") is not False):
            errors.append([*key, "framing"])
        found = successful_results(row, expected["tool"])
        if len(found) != 1:
            errors.append([*key, "successful calls", len(found)])
            continue
        call, result = found[0]
        try:
            supplied = json.loads(call.get("function", {}).get("arguments") or "{}")
        except json.JSONDecodeError:
            supplied = "invalid-json"
        details = result.get("details") or {}
        if (supplied != expected["supplied"] or details.get("route") != expected["route"]
                or details.get("resolvedArguments") != expected["resolved"]
                or details.get("changed") is not True):
            errors.append([*key, "resolved call", supplied, details, expected])
        if (grade["outcome"] in ornith.HARMFUL
                or grade.get("document_outcome") in ornith.HARMFUL):
            harmful.append(list(key))
        if row.get("reasoning_characters") or "<think>" in (row.get("final_content") or ""):
            errors.append([*key, "reasoning leak"])

    outcomes = Counter(graded[key]["outcome"] for key in keys)
    correct = outcomes["correct"]
    control_keys = sorted(set(control) & {(task, seed) for task in TASKS
                                         for seed in range(20, 30)})
    control_correct = sum(control[key]["outcome"] == "correct" for key in control_keys)
    mean_elapsed = sum(elapsed) / len(elapsed) if elapsed else 0
    maximum = max(elapsed, default=0)
    passed = (len(keys) == 30 and correct == 30 and not harmful and not errors
              and mean_elapsed <= 20 and maximum <= 60)
    report = {
        "status": "pass" if passed else "fail", "observed": len(keys),
        "correct": correct, "control_correct": control_correct,
        "paired_gain": correct - control_correct,
        "outcomes": dict(sorted(outcomes.items())), "harmful_trials": harmful,
        "route_errors": errors, "mean_elapsed_s": round(mean_elapsed, 3),
        "max_elapsed_s": round(maximum, 3),
    }
    pi_bench.write_new_json(args.analysis, report)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(DEFAULT_RAW))
    parser.add_argument("--graded", default=str(DEFAULT_GRADED))
    parser.add_argument("--control", default=str(DEFAULT_CONTROL))
    parser.add_argument("--analysis", default=str(DEFAULT_ANALYSIS))
    main(parser.parse_args())
