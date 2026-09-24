#!/usr/bin/env python3
"""Analyse the preregistered Ornith fallback-route treatment."""

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bench"))

import ornith_full as ornith  # noqa: E402
import pi_composition as pi_bench  # noqa: E402


TASKS = {
    "add-item-nested-asterisk", "add-item-ordered-all-ones",
    "add-item-paren-delimiter", "rename-setext", "notes-second-ordinal",
    "append-atx-line", "append-macos-note", "delete-build", "release-bump",
    "create-on-absent", "fill-empty",
}
DEFAULT_RAW = ROOT / "bench/results/ornith_fallback_routes_20260923.jsonl"
DEFAULT_GRADED = ROOT / "bench/results/ornith_fallback_routes_20260923_graded.jsonl"
DEFAULT_CONTROL = ROOT / "bench/results/ornith_held_safe_routed_20260923_graded.jsonl"
DEFAULT_ANALYSIS = ROOT / "bench/results/ornith_fallback_routes_20260923_analysis.json"


def spec(tool, route, resolved, supplied=None):
    return {"tool": tool, "route": route, "supplied": supplied or {},
            "resolved": resolved}


SPECS = {
    "add-item-nested-asterisk": spec(
        "list_append_target", "list-append-target",
        {"list": {"heading": "Nested and mixed lists > Asterisk markers, four-space indent",
                  "ordinal": 0}, "text": "beta-three", "after": "beta-two"}),
    "add-item-ordered-all-ones": spec(
        "list_append_target", "list-append-target",
        {"list": {"heading": "Ordered list numbering > All ones", "ordinal": 0},
         "text": "fourth", "position": "end"}),
    "add-item-paren-delimiter": spec(
        "list_append_target", "list-append-target",
        {"list": {"heading": "Ordered list numbering > Paren delimiter", "ordinal": 0},
         "text": "fourth", "position": "end"}),
    "rename-setext": spec(
        "section_rename_target", "section-rename",
        {"section": "Setext H1 Title > Setext H2", "heading": "Setext level two"}),
    "notes-second-ordinal": spec(
        "section_append_target", "section-append",
        {"section": {"path": "Notes", "ordinal": 1}, "text": "Superseded."}),
    "append-atx-line": spec(
        "section_append_target", "section-append",
        {"section": "Setext H1 Title > Setext H2 > ATX level 3",
         "text": "The same is true of the closed form."}),
    "append-macos-note": spec(
        "section_append_target", "section-append",
        {"section": "Deep heading nesting > Install > macOS",
         "text": "Requires macOS 13 or later."}),
    "delete-build": spec(
        "frontmatter_delete_target", "frontmatter-delete", {"key": "build"}),
    "release-bump": spec(
        "frontmatter_release_target", "frontmatter-release",
        {"updates": [
            {"key": "version", "value": "0.5.0", "must_exist": True},
            {"key": "released", "value": "2026-09-12", "must_absent": True},
        ]}),
    "create-on-absent": spec(
        "frontmatter_create_target", "frontmatter-create",
        {"key": "title", "value": "Absent frontmatter", "must_absent": True}),
    "fill-empty": spec(
        "frontmatter_create_target", "frontmatter-create",
        {"key": "draft", "value": True, "must_absent": True}),
}


def successes(row, name):
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
        found = successes(row, expected["tool"])
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
                                         for seed in range(10, 20)})
    control_correct = sum(control[key]["outcome"] == "correct" for key in control_keys)
    mean_elapsed = sum(elapsed) / len(elapsed) if elapsed else 0
    maximum = max(elapsed, default=0)
    passed = (len(keys) == 110 and correct == 110 and not harmful and not errors
              and mean_elapsed <= 20 and maximum <= 60)
    report = {
        "status": "pass" if passed else "fail", "observed": len(keys),
        "correct": correct, "control_correct": control_correct,
        "paired_gain": correct - control_correct,
        "outcomes": dict(sorted(outcomes.items())), "harmful_trials": harmful,
        "route_errors": errors,
        "mean_elapsed_s": round(mean_elapsed, 3), "max_elapsed_s": round(maximum, 3),
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
