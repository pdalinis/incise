#!/usr/bin/env python3
"""Audit the preregistered Ornith qualified-preamble route."""

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bench"))

import ornith_full as ornith  # noqa: E402
import pi_composition as pi_bench  # noqa: E402


TASKS = {"replace-install-preamble"}
SPECS = {
    "replace-install-preamble": {
        "tool": "section_replace_target", "route": "section-replace-body",
        "supplied": {},
        "resolved": {
            "section": "Deep heading nesting > Install",
            "text": "Choose your platform below.", "overwrite": True,
        },
    },
}


def successful_results(row, name):
    results = {item["tool_call_id"]: item for item in row.get("tool_results") or []}
    return [(call, results[call["id"]]) for call in row.get("tool_calls") or []
            if call.get("function", {}).get("name") == name
            and call.get("id") in results and not results[call["id"]].get("is_error")]


def main(args):
    raw = ornith.latest_rows(args.out)
    graded = ornith.latest_rows(args.graded)
    keys = sorted(set(raw) & set(graded))
    errors = []
    harmful = []
    for key in keys:
        row, grade, expected = raw[key], graded[key], SPECS[key[0]]
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
    passed = len(keys) == 10 and outcomes["correct"] == 10 and not harmful and not errors
    report = {
        "status": "pass" if passed else "fail", "observed": len(keys),
        "correct": outcomes["correct"], "outcomes": dict(sorted(outcomes.items())),
        "harmful_trials": harmful, "route_errors": errors,
        "mean_elapsed_s": round(sum(raw[key].get("elapsed_s") or 0 for key in keys) / len(keys), 3) if keys else 0,
        "max_elapsed_s": round(max((raw[key].get("elapsed_s") or 0 for key in keys), default=0), 3),
    }
    pi_bench.write_new_json(args.analysis, report)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "bench/results/ornith_preamble_route_20260923.jsonl"))
    parser.add_argument("--graded", default=str(ROOT / "bench/results/ornith_preamble_route_20260923_graded.jsonl"))
    parser.add_argument("--analysis", default=str(ROOT / "bench/results/ornith_preamble_route_20260923_analysis.json"))
    main(parser.parse_args())
