#!/usr/bin/env python3
"""Run and analyse the full Gemma Pi safe-routed composition gate."""

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "bench"
sys.path.insert(0, str(BENCH))

import gemma_roadmap as roadmap  # noqa: E402
import gemma_safe_routed_profile as targeted  # noqa: E402
import pi_composition as pi_bench  # noqa: E402
from stats import mcnemar_exact  # noqa: E402


ROUTED_TABLE_TASKS = {
    "get-filter-one-column", "get-filter-two-columns",
    "get-filter-no-match", "get-escaped-cell",
}
ROUTED_TASKS = roadmap.SECTION_GUARD_TASKS | ROUTED_TABLE_TASKS
ROUTED_TOOLS = ["section_rename_target", "section_replace_target", "table_query"]
FULL_TOOLS = roadmap.BASELINE_TOOLS + ROUTED_TOOLS
DEFAULT_RAW = ROOT / "bench/results/gemma_safe_routed_full_20260922.jsonl"
DEFAULT_GRADED = ROOT / "bench/results/gemma_safe_routed_full_20260922_graded.jsonl"
DEFAULT_ANALYSIS = ROOT / "bench/results/gemma_safe_routed_full_20260922_analysis.json"
DEFAULT_SANDBOX = Path("/private/tmp/incise-gemma-safe-routed-full-20260922")


def call_worker(args, request):
    env = os.environ.copy()
    env["INCISE_BIN"] = str(Path(args.binary).resolve())
    env["INCISE_PROFILE"] = "safe-routed"
    env.pop("INCISE_MODEL_FAMILY", None)
    env.pop("INCISE_GEMMA_BENCH_CONFIG", None)
    process = subprocess.run(
        [args.node, str(Path(args.worker).resolve())],
        input=json.dumps(request), text=True, capture_output=True,
        timeout=args.timeout, env=env,
    )
    if process.returncode != 0:
        detail = process.stderr.strip() or process.stdout.strip()
        raise pi_bench.WorkerError(detail or f"worker exited {process.returncode}")
    matches = [line for line in process.stdout.splitlines()
               if line.startswith(pi_bench.RESULT_PREFIX)]
    if len(matches) != 1:
        raise pi_bench.WorkerError(
            f"worker returned {len(matches)} records: {process.stdout!r}")
    return json.loads(matches[0][len(pi_bench.RESULT_PREFIX):])


def grading_config(task, before):
    if task["id"] in roadmap.SECTION_GUARD_TASKS:
        return roadmap.config_for("section_guard", task, before)
    if task["id"] in ROUTED_TABLE_TASKS:
        ideal = task["ideal_call"]["args"]
        return {
            "path": task["fixture"],
            "kind": "table_query",
            "table": ideal["table"],
            "filterColumns": list(ideal["filter"]),
        }
    return None


def grade(task, row, before, after, config):
    if task["id"] in ROUTED_TABLE_TASKS:
        return roadmap.grade_treatment(
            task, "table_query", row, before, after, config)
    return pi_bench.grade_actual(task, row, before, after)


def run_one(args, task, trial):
    task = dict(task)
    task["_trial"] = trial
    sandbox = roadmap.reset_sandbox(args.sandbox, task)
    fixture = sandbox / task["fixture"]
    before = roadmap.read_text(ROOT / task["fixture"])
    config = grading_config(task, before)
    request = roadmap.worker_request(
        args, sandbox, roadmap.CURRENT_EXTENSION, FULL_TOOLS,
        task, pi_bench.prompt_for(task, before), 4,
    )
    try:
        result = call_worker(args, request)
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
        "condition": "safe-routed-full",
        "task_id": task["id"],
        "task_file": task["_task_file"],
        "family": roadmap.task_family(task),
        "trial": trial,
        "seed": trial,
        "max_turns": 4,
        "error": error,
        "initial_sha256": pi_bench.sha256_bytes(before.encode()),
        "final_sha256": pi_bench.sha256_bytes(after.encode()),
        "final_document": after,
        "routed": task["id"] in ROUTED_TASKS,
        "expected_tool": targeted.expected_tool(task) if task["id"] in ROUTED_TASKS else None,
        "grading_config": config,
    }
    outcome, detail = grade(task, row, before, after, config)
    graded = {
        "condition": "safe-routed-full",
        "task_id": task["id"],
        "family": roadmap.task_family(task),
        "trial": trial,
        "routed": task["id"] in ROUTED_TASKS,
        "outcome": outcome,
        "detail": detail,
    }
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
    print(f"{len(work)} full-profile trials to run", flush=True)
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


def first_request(row):
    requests = row.get("provider_requests") or []
    return requests[0] if requests else {}


def analyse(args):
    raw = roadmap.latest_rows(args.out)
    graded = roadmap.latest_rows(args.graded)
    baseline_raw = roadmap.latest_rows(args.baseline_raw)
    baseline = roadmap.latest_rows(args.baseline)
    keys = sorted(set(baseline) & set(graded))
    usable = [key for key in keys if baseline[key]["outcome"] != "transport"
              and graded[key]["outcome"] != "transport"]
    only_control = sum(
        baseline[key]["outcome"] == "correct" and graded[key]["outcome"] != "correct"
        for key in usable)
    only_treatment = sum(
        baseline[key]["outcome"] != "correct" and graded[key]["outcome"] == "correct"
        for key in usable)
    baseline_correct = sum(baseline[key]["outcome"] == "correct" for key in usable)
    treatment_correct = sum(graded[key]["outcome"] == "correct" for key in usable)
    harmful = {"wrong", "destructive", "collateral:content", "collateral:formatting"}
    baseline_harmful = sum(baseline[key]["outcome"] in harmful for key in usable)
    treatment_harmful = sum(graded[key]["outcome"] in harmful for key in usable)

    route_errors = []
    fallback_tool_drift = []
    fallback_regressions = []
    for key in usable:
        request = first_request(raw.get(key, {}))
        if key[0] in ROUTED_TASKS:
            expected = raw[key].get("expected_tool")
            if request.get("tools") != [expected] or request.get("active_tools") != [expected]:
                route_errors.append([*key, request.get("active_tools"), request.get("tools")])
        else:
            if request.get("tools") != roadmap.BASELINE_TOOLS or request.get("active_tools") != roadmap.BASELINE_TOOLS:
                fallback_tool_drift.append([*key, request.get("active_tools"), request.get("tools")])
            if baseline[key]["outcome"] == "correct" and graded[key]["outcome"] != "correct":
                fallback_regressions.append([*key, graded[key]["outcome"]])

    family_report = {}
    family_floors = {"table": 57, "list": 88, "section": 102, "frontmatter": 74, "table-read": 46}
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
    routed_forbidden = sum(
        graded[key]["outcome"] in harmful | {"unfiltered", "misreported"}
        for key in routed_keys)
    paired_p = mcnemar_exact(only_control, only_treatment)
    passes = (
        len(graded) == args.trials * 48
        and len(usable) == args.trials * 48
        and treatment_correct >= 400
        and treatment_correct > baseline_correct
        and paired_p <= 0.05
        and treatment_harmful <= baseline_harmful
        and routed_correct == args.trials * len(ROUTED_TASKS)
        and routed_forbidden == 0
        and not route_errors
        and not fallback_tool_drift
        and len(fallback_regressions) <= 5
        and family_pass
    )
    report = {
        "status": "pass" if passes else "fail",
        "expected": args.trials * 48,
        "observed": len(graded),
        "paired": len(usable),
        "overall": {
            "baseline_correct": baseline_correct,
            "treatment_correct": treatment_correct,
            "only_baseline": only_control,
            "only_treatment": only_treatment,
            "mcnemar_exact_p": paired_p,
            "baseline_harmful": baseline_harmful,
            "treatment_harmful": treatment_harmful,
            "outcomes": counts(graded[key] for key in usable),
        },
        "routed": {
            "n": len(routed_keys), "correct": routed_correct,
            "forbidden": routed_forbidden, "route_errors": route_errors,
        },
        "fallback": {
            "n": len(usable) - len(routed_keys),
            "baseline_correct_regressions": fallback_regressions,
            "tool_surface_drift": fallback_tool_drift,
        },
        "families": family_report,
        "baseline_raw_rows": len(baseline_raw),
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
    value.add_argument("--baseline", default=str(ROOT / "bench/results/gemma_roadmap_20260921_baseline_graded.jsonl"))
    value.add_argument("--baseline-raw", default=str(ROOT / "bench/results/gemma_roadmap_20260921_baseline.jsonl"))
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
