#!/usr/bin/env python3
"""Audit exact safe-routed calls in the held Ornith evaluation."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "bench"
sys.path.insert(0, str(BENCH))

import gemma_frontmatter_create_route_v1 as front_create  # noqa: E402
import gemma_frontmatter_force_v1 as front_typed  # noqa: E402
import gemma_list_contains_route_v1 as list_contains  # noqa: E402
import gemma_list_remove_route_v1 as list_remove  # noqa: E402
import gemma_roadmap as roadmap  # noqa: E402
import gemma_section_append_route_v1 as section_append  # noqa: E402
import gemma_section_insert_route_v2 as section_insert  # noqa: E402
import analyze_ornith_fallback_routes as fallback_routes  # noqa: E402
import analyze_ornith_residual_routes as residual_routes  # noqa: E402
import analyze_ornith_preamble_route as preamble_route  # noqa: E402
import ornith_full as ornith  # noqa: E402
import pi_composition as pi_bench  # noqa: E402


DEFAULT_RAW = ROOT / "bench/results/ornith_held_safe_routed_20260923.jsonl"
DEFAULT_GRADED = ROOT / "bench/results/ornith_held_safe_routed_20260923_graded.jsonl"
DEFAULT_ANALYSIS = ROOT / "bench/results/ornith_held_routes_20260923_analysis.json"


def spec(tool, route, supplied, resolved):
    return {
        "tool": tool, "route": route,
        "supplied": supplied, "resolved": resolved,
    }


def expected_specs():
    tasks = {task["id"]: task for task in roadmap.load_tasks()}
    values = {
        "rename-closed-atx": spec(
            "section_rename_target", "section-rename",
            {},
            {
                "section": "Setext H1 Title > Setext H2 > Closed ATX level 3",
                "heading": "Closed ATX heading",
            },
        ),
        "replace-linux-body": spec(
            "section_replace_target", "section-replace-body",
            {"body": "See the platform notes."},
            {
                "section": "Deep heading nesting > Upgrade > Linux",
                "text": "See the platform notes.", "overwrite": True,
            },
        ),
        "check-task-nested": spec(
            "list_set_checked_target", "list-set-checked-target", {},
            {
                "list": {"heading": "Task lists > Nested", "ordinal": 0},
                "match": "child pending", "checked": True,
            },
        ),
        "promote-api": spec(
            "section_set_level_target", "section-set-level-target", {},
            {
                "section": "Deep heading nesting > Reference > API",
                "level": 2, "subtree": True,
            },
        ),
    }
    table_addresses = {
        "get-filter-one-column": (
            {"heading": "Sortable table > Packages", "ordinal": 0},
            {"Priority": "high"},
        ),
        "get-filter-two-columns": (
            {"heading": "Sortable table > Packages", "ordinal": 0},
            {"Priority": "low", "Version": "2.0.0"},
        ),
        "get-filter-no-match": (
            {"heading": "Sortable table > Packages", "ordinal": 0},
            {"Priority": "urgent"},
        ),
        "get-escaped-cell": (
            {"heading": "Table cell edge cases > Hazardous cells", "ordinal": 0},
            {"Case": "escaped pipe"},
        ),
    }
    for task_id, (table, query_filter) in table_addresses.items():
        values[task_id] = spec(
            "table_query", "table-query", {},
            {"table": table, "filter": query_filter},
        )
    for task_id in roadmap.SECTION_INSERT_TASKS:
        values[task_id] = spec(
            "section_insert_target", "section-insert", {},
            section_insert.canonical_arguments(tasks[task_id]),
        )
    for task_id, (tool, supplied) in front_typed.CANONICAL.items():
        resolved = {**supplied, "must_exist": True}
        if tool == "frontmatter_clear":
            resolved["value"] = None
        values[task_id] = spec(tool, "frontmatter-typed", supplied, resolved)
    for task_id, resolved in list_remove.EXPECTED.items():
        values[task_id] = spec(
            "list_remove_target", "list-remove-target", {}, resolved)
    values["add-build-cache"] = spec(
        "frontmatter_create_target", "frontmatter-create", {},
        front_create.EXPECTED,
    )
    values["append-after-fence"] = spec(
        "section_append_target", "section-append", {}, section_append.EXPECTED)
    values["add-item-mixed-markers"] = spec(
        "list_append_target", "list-append-target", {}, list_contains.EXPECTED)
    values.update(fallback_routes.SPECS)
    values.update(residual_routes.SPECS)
    values.update(preamble_route.SPECS)
    return values


def successful_results(row, name):
    results = {result["tool_call_id"]: result
               for result in row.get("tool_results") or []}
    found = []
    for call in row.get("tool_calls") or []:
        if call.get("function", {}).get("name") != name:
            continue
        result = results.get(call.get("id"))
        if result is not None and not result.get("is_error"):
            found.append((call, result))
    return found


def analyse(args):
    raw = ornith.latest_rows(args.out)
    graded = ornith.latest_rows(args.graded)
    keys = sorted(set(raw) & set(graded))
    specs = expected_specs()
    routed = [key for key in keys if key[0] in specs]
    fallback = [key for key in keys if key[0] not in specs]
    errors = []

    for key in routed:
        row = raw[key]
        expected = specs[key[0]]
        requests = row.get("provider_requests") or []
        first = requests[0] if requests else {}
        if (first.get("tools") != [expected["tool"]]
                or first.get("active_tools") != [expected["tool"]]
                or first.get("tool_choice") is not None):
            errors.append([*key, "provider framing", first.get("tools"),
                           first.get("active_tools"), first.get("tool_choice")])
        call_names = [call.get("function", {}).get("name")
                      for call in row.get("tool_calls") or []]
        if any(name != expected["tool"] for name in call_names):
            errors.append([*key, "unexpected tool calls", call_names])
        successes = successful_results(row, expected["tool"])
        if len(successes) != 1:
            errors.append([*key, "successful calls", len(successes)])
            continue
        call, result = successes[0]
        try:
            supplied = json.loads(call.get("function", {}).get("arguments") or "{}")
        except json.JSONDecodeError:
            supplied = "invalid-json"
        details = result.get("details") or {}
        changed = bool(details.get("changed"))
        expected_changed = expected["tool"] != "table_query"
        if (supplied != expected["supplied"]
                or details.get("route") != expected["route"]
                or details.get("resolvedArguments") != expected["resolved"]
                or changed != expected_changed):
            errors.append([
                *key, "resolved call", supplied, details.get("route"),
                details.get("resolvedArguments"), changed, expected,
            ])

    for key in fallback:
        requests = raw[key].get("provider_requests") or []
        first = requests[0] if requests else {}
        if (first.get("tools") != ornith.STANDARD_TOOLS
                or first.get("active_tools") != ornith.STANDARD_TOOLS):
            errors.append([*key, "fallback tool surface", first.get("tools"),
                           first.get("active_tools")])

    routed_correct = sum(graded[key]["outcome"] == "correct" for key in routed)
    passed = (
        len(keys) == args.trials * 48
        and len(routed) == args.trials * len(specs)
        and routed_correct == len(routed)
        and not errors
    )
    report = {
        "status": "pass" if passed else "fail",
        "observed": len(keys),
        "expected_routed_tasks": sorted(specs),
        "routed": len(routed),
        "routed_correct": routed_correct,
        "fallback": len(fallback),
        "errors": errors,
    }
    pi_bench.write_new_json(args.analysis, report)
    print(json.dumps(report, indent=2, sort_keys=True))


def parser():
    value = argparse.ArgumentParser()
    value.add_argument("--trials", type=int, default=10)
    value.add_argument("--out", default=str(DEFAULT_RAW))
    value.add_argument("--graded", default=str(DEFAULT_GRADED))
    value.add_argument("--analysis", default=str(DEFAULT_ANALYSIS))
    return value


if __name__ == "__main__":
    analyse(parser().parse_args())
