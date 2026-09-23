#!/usr/bin/env python3
"""Run and analyse the third full Gemma Pi safe-routed composition gate."""

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "bench"
sys.path.insert(0, str(BENCH))

import gemma_roadmap as roadmap  # noqa: E402
import gemma_safe_routed_full_v2 as full_v2  # noqa: E402
import gemma_section_insert_route_v1 as insert_v1  # noqa: E402
import gemma_section_insert_route_v2 as insert_v2  # noqa: E402
from stats import mcnemar_exact  # noqa: E402


INSERT_TASKS = roadmap.SECTION_INSERT_TASKS
ROUTED_TABLE_TASKS = full_v2.ROUTED_TABLE_TASKS
ROUTED_TASKS = full_v2.ROUTED_TASKS | INSERT_TASKS
FULL_TOOLS = full_v2.FULL_TOOLS + [insert_v1.TOOL]
DEFAULT_RAW = ROOT / "bench/results/gemma_safe_routed_full_v3_20260922.jsonl"
DEFAULT_GRADED = ROOT / "bench/results/gemma_safe_routed_full_v3_20260922_graded.jsonl"
DEFAULT_ANALYSIS = ROOT / "bench/results/gemma_safe_routed_full_v3_20260922_analysis.json"
DEFAULT_BASELINE = ROOT / "bench/results/gemma_safe_routed_full_v2_20260922_graded.jsonl"
DEFAULT_SANDBOX = Path("/private/tmp/incise-gemma-safe-routed-full-v3-20260922")


_previous_expected_tool = full_v2.full_v1.targeted.expected_tool


def expected_tool(task):
    if task["id"] in INSERT_TASKS:
        return insert_v1.TOOL
    return _previous_expected_tool(task)


full_v2.ROUTED_TASKS = ROUTED_TASKS
full_v2.FULL_TOOLS = FULL_TOOLS
full_v2.full_v1.targeted.expected_tool = expected_tool


def run_one(args, task, trial):
    row, graded = full_v2.run_one(args, task, trial)
    row["condition"] = "safe-routed-full-v3"
    graded["condition"] = "safe-routed-full-v3"
    if task["id"] in INSERT_TASKS:
        row["expected_arguments"] = insert_v2.canonical_arguments(task)
    return row, graded


def run(args):
    tasks = roadmap.load_tasks()
    raw_path = Path(args.out)
    graded_path = Path(args.graded)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    graded_path.parent.mkdir(parents=True, exist_ok=True)
    done = {key for key, row in roadmap.latest_rows(raw_path).items()
            if not row.get("error")}
    work = [(task, trial) for task in tasks for trial in range(args.trials)
            if (task["id"], trial) not in done]
    print(f"{len(work)} full-profile-v3 trials to run", flush=True)
    started = time.time()
    with open(raw_path, "a", encoding="utf-8", newline="\n") as raw_handle, \
            open(graded_path, "a", encoding="utf-8", newline="\n") as graded_handle:
        for index, (task, trial) in enumerate(work, 1):
            row, graded = run_one(args, task, trial)
            roadmap.write_jsonl(raw_handle, row)
            roadmap.write_jsonl(graded_handle, graded)
            elapsed = time.time() - started
            eta = elapsed / index * (len(work) - index) / 60
            print(
                f"[{index:3d}/{len(work)}] {task['id']:27s} t{trial:<2d} "
                f"{(row.get('elapsed_s') or 0):6.1f}s {graded['outcome']:18s} eta {eta:.0f}m",
                flush=True,
            )


def counts(rows):
    return dict(sorted(Counter(row["outcome"] for row in rows).items()))


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
    harmful = {"wrong", "destructive", "collateral:content", "collateral:formatting"}
    baseline_harmful = sum(baseline[key]["outcome"] in harmful for key in usable)
    treatment_harmful = sum(graded[key]["outcome"] in harmful for key in usable)

    route_errors = []
    filter_errors = []
    insertion_argument_errors = []
    fallback_tool_drift = []
    multiple_mutations = []
    for key in usable:
        row = raw[key]
        request = full_v2.first_request(row)
        if key[0] in ROUTED_TASKS:
            expected = row.get("expected_tool")
            if request.get("tools") != [expected] or request.get("active_tools") != [expected]:
                route_errors.append([*key, request.get("active_tools"), request.get("tools")])
            if key[0] in ROUTED_TABLE_TASKS:
                _call, result = full_v2.table_v2.successful_result(row, "table_query")
                resolved = ((result or {}).get("details") or {}).get("resolvedArguments", {}).get("filter")
                if resolved != row.get("expected_filter"):
                    filter_errors.append([*key, row.get("expected_filter"), resolved])
            if key[0] in INSERT_TASKS:
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
                        insertion_argument_errors.append(
                            [*key, supplied, row.get("expected_arguments"), resolved])
        elif request.get("tools") != roadmap.BASELINE_TOOLS or request.get("active_tools") != roadmap.BASELINE_TOOLS:
            fallback_tool_drift.append([*key, request.get("active_tools"), request.get("tools")])

    family_floors = {
        "table": 57, "list": 88, "section": 135,
        "frontmatter": 74, "table-read": 57,
    }
    family_report = {}
    family_pass = True
    for family, floor in family_floors.items():
        family_rows = [graded[key] for key in usable if graded[key]["family"] == family]
        correct = sum(row["outcome"] == "correct" for row in family_rows)
        passed = correct >= floor
        family_pass &= passed
        family_report[family] = {
            "n": len(family_rows), "correct": correct, "floor": floor,
            "status": "pass" if passed else "fail", "outcomes": counts(family_rows),
        }

    routed_keys = [key for key in usable if key[0] in ROUTED_TASKS]
    routed_correct = sum(graded[key]["outcome"] == "correct" for key in routed_keys)
    paired_p = mcnemar_exact(only_control, only_treatment)
    passes = (
        len(graded) == args.trials * 48
        and len(usable) >= args.trials * 48 - 2
        and len(transports) <= 2
        and treatment_correct >= 430
        and treatment_correct > baseline_correct
        and paired_p <= 0.05
        and treatment_harmful <= baseline_harmful
        and len(routed_keys) == args.trials * len(ROUTED_TASKS)
        and routed_correct == len(routed_keys)
        and not route_errors
        and not filter_errors
        and not insertion_argument_errors
        and not multiple_mutations
        and not fallback_tool_drift
        and family_pass
    )
    report = {
        "status": "pass" if passes else "fail",
        "expected": args.trials * 48, "observed": len(graded),
        "paired": len(usable), "transport_pairs": [list(key) for key in transports],
        "overall": {
            "baseline_correct": baseline_correct, "treatment_correct": treatment_correct,
            "only_baseline": only_control, "only_treatment": only_treatment,
            "mcnemar_exact_p": paired_p,
            "baseline_harmful": baseline_harmful,
            "treatment_harmful": treatment_harmful,
            "outcomes": counts(graded[key] for key in usable),
        },
        "routed": {
            "n": len(routed_keys), "correct": routed_correct,
            "route_errors": route_errors, "filter_errors": filter_errors,
            "insertion_argument_errors": insertion_argument_errors,
            "multiple_mutations": multiple_mutations,
        },
        "fallback": {
            "n": len(usable) - len(routed_keys),
            "tool_surface_drift": fallback_tool_drift,
        },
        "families": family_report,
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
