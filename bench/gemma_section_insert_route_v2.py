#!/usr/bin/env python3
"""Run and analyse host-owned section insertion literals for Gemma/Pi."""

import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "bench"
sys.path.insert(0, str(BENCH))

import gemma_roadmap as roadmap  # noqa: E402
import gemma_section_insert_route_v1 as v1  # noqa: E402
import pi_composition as pi_bench  # noqa: E402
from stats import mcnemar_exact  # noqa: E402


TASKS = roadmap.SECTION_INSERT_TASKS
TOOL = v1.TOOL
FULL_TOOLS = v1.FULL_TOOLS
DEFAULT_RAW = ROOT / "bench/results/gemma_section_insert_route_v2_20260922.jsonl"
DEFAULT_GRADED = ROOT / "bench/results/gemma_section_insert_route_v2_20260922_graded.jsonl"
DEFAULT_ANALYSIS = ROOT / "bench/results/gemma_section_insert_route_v2_20260922_analysis.json"
DEFAULT_CONTROL = ROOT / "bench/results/gemma_section_insert_route_v1_20260922_graded.jsonl"
DEFAULT_PRODUCT_BASELINE = ROOT / "bench/results/gemma_safe_routed_full_v2_20260922_graded.jsonl"
DEFAULT_SANDBOX = Path("/private/tmp/incise-gemma-section-insert-route-v2-20260922")


def canonical_arguments(task):
    calls = task["ideal_calls"]
    first = calls[0]["args"]
    result = {
        "section": v1.EXPECTED_ANCHORS[task["id"]],
        "position": first["position"],
        "heading": first["heading"],
    }
    if "body" in first:
        result["body"] = first["body"]
    if len(calls) > 1:
        result["children"] = [
            {"heading": call["args"]["heading"], "body": call["args"]["body"]}
            for call in calls[1:]
        ]
    return result


def run_one(args, task, trial):
    task = dict(task)
    task["_trial"] = trial
    sandbox = roadmap.reset_sandbox(args.sandbox, task)
    fixture = sandbox / task["fixture"]
    before = roadmap.read_text(ROOT / task["fixture"])
    request = roadmap.worker_request(
        args, sandbox, roadmap.CURRENT_EXTENSION, FULL_TOOLS,
        task, pi_bench.prompt_for(task, before), 2,
    )
    try:
        result = v1.call_worker(args, request)
        error = result.get("error")
    except (pi_bench.WorkerError, subprocess.TimeoutExpired) as exc:
        result = {
            "elapsed_s": None, "completion_tokens": 0, "n_turns": 0,
            "turns": [], "tool_calls": [], "tool_results": [],
            "final_content": "", "capped": False,
        }
        error = f"{type(exc).__name__}: {exc}"
    after = roadmap.read_text(fixture)
    row = {
        **result,
        "condition": "section-insert-route-v2",
        "task_id": task["id"],
        "task_file": task["_task_file"],
        "family": "section",
        "trial": trial,
        "seed": trial,
        "max_turns": 2,
        "error": error,
        "initial_sha256": pi_bench.sha256_bytes(before.encode()),
        "final_sha256": pi_bench.sha256_bytes(after.encode()),
        "final_document": after,
        "expected_arguments": canonical_arguments(task),
    }
    outcome, detail = pi_bench.grade_actual(task, row, before, after)
    graded = {
        "condition": "section-insert-route-v2",
        "task_id": task["id"],
        "family": "section",
        "trial": trial,
        "outcome": outcome,
        "detail": detail,
    }
    return row, graded


def run(args):
    tasks = [task for task in roadmap.load_tasks() if task["id"] in TASKS]
    raw_path = Path(args.out)
    graded_path = Path(args.graded)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    graded_path.parent.mkdir(parents=True, exist_ok=True)
    done = {key for key, row in roadmap.latest_rows(raw_path).items()
            if not row.get("error")}
    work = [(task, trial) for task in tasks for trial in range(args.trials)
            if (task["id"], trial) not in done]
    print(f"{len(work)} section-insert-route-v2 trials to run", flush=True)
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
                f"[{index:2d}/{len(work)}] {task['id']:27s} t{trial:<2d} "
                f"{(row.get('elapsed_s') or 0):6.1f}s {graded['outcome']:18s} eta {eta:.0f}m",
                flush=True,
            )


def counts(rows):
    return dict(sorted(Counter(row["outcome"] for row in rows).items()))


def analyse(args):
    raw = roadmap.latest_rows(args.out)
    graded = roadmap.latest_rows(args.graded)
    control = roadmap.latest_rows(args.control)
    product = roadmap.latest_rows(args.product_baseline)
    keys = sorted(set(control) & set(graded))
    transports = [key for key in keys if control[key]["outcome"] == "transport"
                  or graded[key]["outcome"] == "transport"]
    usable = [key for key in keys if key not in set(transports)]
    route_errors = []
    model_argument_errors = []
    resolved_argument_errors = []
    multiple_mutations = []
    for key in usable:
        row = raw[key]
        first = (row.get("provider_requests") or [{}])[0]
        if first.get("tools") != [TOOL] or first.get("active_tools") != [TOOL]:
            route_errors.append([*key, first.get("active_tools"), first.get("tools")])
        successes = v1.successful_results(row, TOOL)
        if len(successes) > 1:
            multiple_mutations.append([*key, len(successes)])
        if successes:
            call, result = successes[0]
            try:
                supplied = json.loads(call.get("function", {}).get("arguments") or "{}")
            except json.JSONDecodeError:
                supplied = "invalid-json"
            if supplied != {}:
                model_argument_errors.append([*key, supplied])
            resolved = (result.get("details") or {}).get("resolvedArguments")
            if resolved != row.get("expected_arguments"):
                resolved_argument_errors.append(
                    [*key, row.get("expected_arguments"), resolved])

    treatment_correct = sum(graded[key]["outcome"] == "correct" for key in usable)
    control_correct = sum(control[key]["outcome"] == "correct" for key in usable)
    product_correct = sum(product.get(key, {}).get("outcome") == "correct" for key in usable)
    only_control = sum(control[key]["outcome"] == "correct"
                       and graded[key]["outcome"] != "correct" for key in usable)
    only_treatment = sum(control[key]["outcome"] != "correct"
                         and graded[key]["outcome"] == "correct" for key in usable)
    harmful = {"destructive", "collateral:content", "collateral:formatting"}
    harmful_count = sum(graded[key]["outcome"] in harmful for key in usable)
    per_task = {}
    task_floors_pass = True
    for task_id in sorted(TASKS):
        task_keys = [key for key in usable if key[0] == task_id]
        correct = sum(graded[key]["outcome"] == "correct" for key in task_keys)
        passed = len(task_keys) >= args.trials - 1 and correct >= 9
        task_floors_pass &= passed
        per_task[task_id] = {
            "n": len(task_keys), "correct": correct,
            "outcomes": counts(graded[key] for key in task_keys),
            "status": "pass" if passed else "fail",
        }
    passes = (
        len(graded) == args.trials * len(TASKS)
        and len(usable) >= args.trials * len(TASKS) - 1
        and len(transports) <= 1
        and treatment_correct >= 38
        and treatment_correct > control_correct
        and harmful_count == 0
        and only_control <= 1
        and task_floors_pass
        and not route_errors
        and not model_argument_errors
        and not resolved_argument_errors
        and not multiple_mutations
    )
    report = {
        "status": "pass" if passes else "fail",
        "expected": args.trials * len(TASKS),
        "observed": len(graded),
        "paired": len(usable),
        "transport_pairs": [list(key) for key in transports],
        "product_baseline_correct": product_correct,
        "v1_control_correct": control_correct,
        "treatment_correct": treatment_correct,
        "discordant_vs_v1": {
            "only_control": only_control,
            "only_treatment": only_treatment,
            "mcnemar_exact_p": mcnemar_exact(only_control, only_treatment),
        },
        "outcomes": counts(graded[key] for key in usable),
        "harmful": harmful_count,
        "per_task": per_task,
        "route_errors": route_errors,
        "model_argument_errors": model_argument_errors,
        "resolved_argument_errors": resolved_argument_errors,
        "multiple_mutations": multiple_mutations,
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
    value.add_argument("--control", default=str(DEFAULT_CONTROL))
    value.add_argument("--product-baseline", default=str(DEFAULT_PRODUCT_BASELINE))
    value.add_argument("--sandbox", type=Path, default=DEFAULT_SANDBOX)
    value.add_argument("--binary", default=str(roadmap.DEFAULT_BINARY))
    value.add_argument("--worker", default=str(pi_bench.DEFAULT_WORKER))
    value.add_argument("--pi-sdk", default=str(pi_bench.DEFAULT_PI_SDK))
    value.add_argument("--node", default="node")
    value.add_argument("--endpoint", default="http://127.0.0.1:8081/v1")
    value.add_argument("--timeout", type=int, default=240)
    return value


if __name__ == "__main__":
    parsed = parser().parse_args()
    run(parsed) if parsed.command == "run" else analyse(parsed)
