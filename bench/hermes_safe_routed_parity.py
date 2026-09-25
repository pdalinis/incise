#!/usr/bin/env python3
"""Audit Hermes route decisions against the final measured Pi route pool."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "bench"
sys.path.insert(0, str(BENCH))

import pi_composition  # noqa: E402


def load_hermes_plugin():
    here = ROOT / "plugins" / "hermes"
    spec = importlib.util.spec_from_file_location(
        "incise", here / "__init__.py", submodule_search_locations=[str(here)]
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["incise"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def expected_rows(path: Path):
    rows = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            rows.setdefault(row["task_id"], row)
    return rows


def routed_expectation(row):
    results = {result["tool_call_id"]: result for result in row.get("tool_results", [])}
    for call in row.get("tool_calls", []):
        result = results.get(call.get("id"))
        details = (result or {}).get("details") or {}
        if details.get("route"):
            raw = call.get("function", {}).get("arguments", "{}")
            params = json.loads(raw) if isinstance(raw, str) else raw
            return {
                "name": call["function"]["name"],
                "kind": details["route"],
                "params": params,
                "resolved": details.get("resolvedArguments"),
            }
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--pi-raw",
        default=BENCH / "results" / "ornith_final_v2_safe_routed_20260923.jsonl",
        type=Path,
    )
    parser.add_argument(
        "--out",
        default=BENCH / "results" / "hermes_safe_routed_parity_20260924.json",
        type=Path,
    )
    parser.add_argument("--baseline-pi-raw", type=Path)
    args = parser.parse_args()

    plugin = load_hermes_plugin()
    expected = expected_rows(args.pi_raw)
    baseline = expected_rows(args.baseline_pi_raw) if args.baseline_pi_raw else None
    errors = []
    baseline_errors = []
    expanded_tasks = []
    observed = []
    routed = fallback = 0
    tasks = pi_composition.load_tasks()

    with tempfile.TemporaryDirectory(prefix="incise-hermes-route-parity-") as root:
        sandbox = Path(root)
        for task in tasks:
            source = ROOT / task["fixture"]
            destination = sandbox / task["fixture"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            before = source.read_text(encoding="utf-8")
            prompt = pi_composition.prompt_for(task, before).replace(
                task["fixture"], str(destination)
            )
            spec = plugin.safe_routed.route_for_prompt(prompt, str(sandbox))
            wanted = routed_expectation(expected[task["id"]])
            previous = routed_expectation(baseline[task["id"]]) if baseline else None
            if previous is None and wanted is not None:
                expanded_tasks.append(task["id"])
            elif previous is not None and wanted is not None:
                for field in ("name", "kind", "resolved"):
                    if previous[field] != wanted[field]:
                        baseline_errors.append({
                            "task_id": task["id"],
                            "field": field,
                            "baseline": previous[field],
                            "current": wanted[field],
                        })
            elif previous is not None and wanted is None:
                baseline_errors.append({
                    "task_id": task["id"],
                    "field": "route",
                    "baseline": previous["name"],
                    "current": "standard",
                })
            item = {
                "task_id": task["id"],
                "expected": wanted["name"] if wanted else "standard",
                "actual": spec.schema["name"] if spec else "standard",
            }
            if wanted is None:
                fallback += 1
                if spec is not None:
                    errors.append({**item, "error": "unexpected route"})
            else:
                routed += 1
                if spec is None:
                    errors.append({**item, "error": "missing route"})
                else:
                    params = wanted["params"]
                    resolved = (
                        spec.resolved_arguments(params)
                        if spec.resolved_arguments
                        else spec.arguments(params)
                    )
                    item.update({
                        "kind": spec.kind,
                        "resolved": resolved,
                    })
                    if spec.schema["name"] != wanted["name"]:
                        errors.append({**item, "error": "tool mismatch"})
                    if spec.kind != wanted["kind"]:
                        errors.append({**item, "error": "kind mismatch"})
                    if resolved != wanted["resolved"]:
                        errors.append({
                            **item,
                            "error": "resolved arguments mismatch",
                            "expected_resolved": wanted["resolved"],
                        })
            observed.append(item)

    analysis = {
        "status": "pass" if not errors and not baseline_errors and len(observed) == 48 and routed + fallback == 48 else "fail",
        "observed_tasks": len(observed),
        "routed_tasks": routed,
        "fallback_tasks": fallback,
        "expected_trial_projection": {"routed": routed * 10, "fallback": fallback * 10},
        "errors": errors,
        "baseline_reference": str(args.baseline_pi_raw) if args.baseline_pi_raw else None,
        "baseline_errors": baseline_errors,
        "expanded_tasks": expanded_tasks,
        "routes": observed,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(analysis, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in analysis.items() if key != "routes"}, indent=2))
    return 0 if analysis["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
