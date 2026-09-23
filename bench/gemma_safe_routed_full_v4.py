#!/usr/bin/env python3
"""Run and analyse the fourth full Gemma Pi safe-routed composition gate."""

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "bench"
sys.path.insert(0, str(BENCH))

import gemma_frontmatter_force_v1 as front_v1  # noqa: E402
import gemma_frontmatter_prompt_v2 as front_v2  # noqa: E402
import gemma_roadmap as roadmap  # noqa: E402
import gemma_safe_routed_full_v2 as full_v2  # noqa: E402
import gemma_safe_routed_full_v3 as full_v3  # noqa: E402
import gemma_section_insert_route_v1 as insert_v1  # noqa: E402
import gemma_section_insert_route_v2 as insert_v2  # noqa: E402
from stats import mcnemar_exact  # noqa: E402


FRONTMATTER_TASKS = roadmap.FRONTMATTER_TASKS
ROUTED_TASKS = full_v3.ROUTED_TASKS | FRONTMATTER_TASKS
FULL_TOOLS = full_v3.FULL_TOOLS + sorted({tool for tool, _args in front_v1.CANONICAL.values()})
DEFAULT_RAW = ROOT / "bench/results/gemma_safe_routed_full_v4_20260922.jsonl"
DEFAULT_GRADED = ROOT / "bench/results/gemma_safe_routed_full_v4_20260922_graded.jsonl"
DEFAULT_ANALYSIS = ROOT / "bench/results/gemma_safe_routed_full_v4_20260922_analysis.json"
DEFAULT_BASELINE = ROOT / "bench/results/gemma_safe_routed_full_v3_20260922_graded.jsonl"
DEFAULT_SANDBOX = Path("/private/tmp/incise-gemma-safe-routed-full-v4-20260922")


_previous_expected_tool = full_v3.expected_tool


def expected_tool(task):
    if task["id"] in FRONTMATTER_TASKS:
        return front_v1.CANONICAL[task["id"]][0]
    return _previous_expected_tool(task)


full_v3.ROUTED_TASKS = ROUTED_TASKS
full_v3.FULL_TOOLS = FULL_TOOLS
full_v2.ROUTED_TASKS = ROUTED_TASKS
full_v2.FULL_TOOLS = FULL_TOOLS
full_v2.full_v1.targeted.expected_tool = expected_tool


def run_one(args, task, trial):
    row, graded = full_v3.run_one(args, task, trial)
    row["condition"] = "safe-routed-full-v4"
    graded["condition"] = "safe-routed-full-v4"
    if task["id"] in FRONTMATTER_TASKS:
        tool, model_args = front_v1.CANONICAL[task["id"]]
        resolved = {**model_args, "must_exist": True}
        if tool == "frontmatter_clear":
            resolved["value"] = None
        row["expected_frontmatter_model_arguments"] = model_args
        row["expected_frontmatter_resolved_arguments"] = resolved
    return row, graded


def run(args):
    tasks = roadmap.load_tasks()
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    done = {key for key, row in roadmap.latest_rows(args.out).items()
            if not row.get("error")}
    work = [(task, trial) for task in tasks for trial in range(args.trials)
            if (task["id"], trial) not in done]
    print(f"{len(work)} full-profile-v4 trials to run", flush=True)
    started = time.time()
    with open(args.out, "a", encoding="utf-8", newline="\n") as raw_handle, \
            open(args.graded, "a", encoding="utf-8", newline="\n") as graded_handle:
        for index, (task, trial) in enumerate(work, 1):
            row, graded = run_one(args, task, trial)
            roadmap.write_jsonl(raw_handle, row)
            roadmap.write_jsonl(graded_handle, graded)
            eta = (time.time() - started) / index * (len(work) - index) / 60
            print(f"[{index:3d}/{len(work)}] {task['id']:27s} t{trial:<2d} "
                  f"{(row.get('elapsed_s') or 0):6.1f}s {graded['outcome']:18s} "
                  f"eta {eta:.0f}m", flush=True)


def counts(rows):
    return dict(sorted(Counter(row["outcome"] for row in rows).items()))


def successful_results(row, name):
    results = {item["tool_call_id"]: item for item in row.get("tool_results", [])}
    return [(call, results[call["id"]]) for call in row.get("tool_calls", [])
            if call.get("function", {}).get("name") == name
            and call.get("id") in results and not results[call["id"]].get("is_error")]


def analyse(args):
    raw = roadmap.latest_rows(args.out)
    graded = roadmap.latest_rows(args.graded)
    baseline = roadmap.latest_rows(args.baseline)
    keys = sorted(set(baseline) & set(graded))
    transports = [key for key in keys if baseline[key]["outcome"] == "transport"
                  or graded[key]["outcome"] == "transport"]
    usable = [key for key in keys if key not in set(transports)]
    only_control = sum(baseline[key]["outcome"] == "correct"
                       and graded[key]["outcome"] != "correct" for key in usable)
    only_treatment = sum(baseline[key]["outcome"] != "correct"
                         and graded[key]["outcome"] == "correct" for key in usable)
    baseline_correct = sum(baseline[key]["outcome"] == "correct" for key in usable)
    treatment_correct = sum(graded[key]["outcome"] == "correct" for key in usable)
    harmful_set = {"wrong", "destructive", "collateral:content", "collateral:formatting"}
    baseline_harmful = sum(baseline[key]["outcome"] in harmful_set for key in usable)
    treatment_harmful = sum(graded[key]["outcome"] in harmful_set for key in usable)

    route_errors = []
    filter_errors = []
    insertion_errors = []
    frontmatter_errors = []
    multiple_mutations = []
    fallback_drift = []
    for key in usable:
        row = raw[key]
        request = full_v2.first_request(row)
        if key[0] in ROUTED_TASKS:
            expected = row.get("expected_tool")
            if request.get("tools") != [expected] or request.get("active_tools") != [expected]:
                route_errors.append([*key, request.get("active_tools"), request.get("tools")])
            if key[0] in full_v3.ROUTED_TABLE_TASKS:
                _call, result = full_v2.table_v2.successful_result(row, "table_query")
                resolved = ((result or {}).get("details") or {}).get("resolvedArguments", {}).get("filter")
                if resolved != row.get("expected_filter"):
                    filter_errors.append([*key, row.get("expected_filter"), resolved])
            if key[0] in full_v3.INSERT_TASKS:
                successes = insert_v1.successful_results(row, insert_v1.TOOL)
                if len(successes) > 1:
                    multiple_mutations.append([*key, len(successes)])
                if successes:
                    call, result = successes[0]
                    try:
                        supplied = json.loads(call.get("function", {}).get("arguments") or "{}")
                    except json.JSONDecodeError:
                        supplied = "invalid-json"
                    resolved = (result.get("details") or {}).get("resolvedArguments")
                    if supplied != {} or resolved != row.get("expected_arguments"):
                        insertion_errors.append([*key, supplied, row.get("expected_arguments"), resolved])
            if key[0] in FRONTMATTER_TASKS:
                if (request.get("tool_choice") is not None
                        or front_v2.instruction(expected) not in request.get("system_prompt", "")):
                    frontmatter_errors.append([*key, "provider framing"])
                successes = successful_results(row, expected)
                if len(successes) > 1:
                    multiple_mutations.append([*key, len(successes)])
                if len(successes) != 1:
                    frontmatter_errors.append([*key, f"successful calls={len(successes)}"])
                else:
                    call, result = successes[0]
                    try:
                        supplied = json.loads(call.get("function", {}).get("arguments") or "{}")
                    except json.JSONDecodeError:
                        supplied = "invalid-json"
                    resolved = (result.get("details") or {}).get("resolvedArguments")
                    if (supplied != row.get("expected_frontmatter_model_arguments")
                            or resolved != row.get("expected_frontmatter_resolved_arguments")):
                        frontmatter_errors.append([
                            *key, supplied, row.get("expected_frontmatter_model_arguments"),
                            resolved, row.get("expected_frontmatter_resolved_arguments")])
        elif (request.get("tools") != roadmap.BASELINE_TOOLS
              or request.get("active_tools") != roadmap.BASELINE_TOOLS):
            fallback_drift.append([*key, request.get("active_tools"), request.get("tools")])

    floors = {"table": 57, "list": 88, "section": 135,
              "frontmatter": 95, "table-read": 57}
    families = {}
    family_pass = True
    for family, floor in floors.items():
        selected = [graded[key] for key in usable if graded[key]["family"] == family]
        correct = sum(row["outcome"] == "correct" for row in selected)
        passed = correct >= floor
        family_pass &= passed
        families[family] = {"n": len(selected), "correct": correct, "floor": floor,
                            "status": "pass" if passed else "fail",
                            "outcomes": counts(selected)}

    routed = [key for key in usable if key[0] in ROUTED_TASKS]
    routed_correct = sum(graded[key]["outcome"] == "correct" for key in routed)
    paired_p = mcnemar_exact(only_control, only_treatment)
    passed = (
        len(graded) == args.trials * 48 and len(usable) >= args.trials * 48 - 2
        and len(transports) <= 2 and treatment_correct >= 455
        and treatment_correct > baseline_correct and paired_p <= 0.05
        and treatment_harmful <= baseline_harmful
        and len(routed) == args.trials * len(ROUTED_TASKS)
        and routed_correct == len(routed) and not route_errors and not filter_errors
        and not insertion_errors and not frontmatter_errors and not multiple_mutations
        and not fallback_drift and family_pass)
    report = {
        "status": "pass" if passed else "fail", "expected": args.trials * 48,
        "observed": len(graded), "paired": len(usable),
        "transport_pairs": [list(key) for key in transports],
        "overall": {"baseline_correct": baseline_correct,
                    "treatment_correct": treatment_correct,
                    "only_baseline": only_control, "only_treatment": only_treatment,
                    "mcnemar_exact_p": paired_p,
                    "baseline_harmful": baseline_harmful,
                    "treatment_harmful": treatment_harmful,
                    "outcomes": counts(graded[key] for key in usable)},
        "routed": {"n": len(routed), "correct": routed_correct,
                   "route_errors": route_errors, "filter_errors": filter_errors,
                   "insertion_argument_errors": insertion_errors,
                   "frontmatter_errors": frontmatter_errors,
                   "multiple_mutations": multiple_mutations},
        "fallback": {"n": len(usable) - len(routed),
                     "tool_surface_drift": fallback_drift},
        "families": families,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    Path(args.analysis).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")


def parser():
    value = argparse.ArgumentParser()
    value.add_argument("command", choices=("run", "analyse"))
    value.add_argument("--trials", type=int, default=10)
    value.add_argument("--out", default=str(DEFAULT_RAW))
    value.add_argument("--graded", default=str(DEFAULT_GRADED))
    value.add_argument("--analysis", default=str(DEFAULT_ANALYSIS))
    value.add_argument("--baseline", default=str(DEFAULT_BASELINE))
    value.add_argument("--sandbox", type=Path, default=DEFAULT_SANDBOX)
    value.add_argument("--binary", default=str(roadmap.DEFAULT_BINARY))
    value.add_argument("--worker", default=str(full_v2.pi_bench.DEFAULT_WORKER))
    value.add_argument("--pi-sdk", default=str(full_v2.pi_bench.DEFAULT_PI_SDK))
    value.add_argument("--node", default="node")
    value.add_argument("--endpoint", default="http://127.0.0.1:8081/v1")
    value.add_argument("--timeout", type=int, default=240)
    return value


if __name__ == "__main__":
    parsed = parser().parse_args()
    run(parsed) if parsed.command == "run" else analyse(parsed)
