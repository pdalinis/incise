#!/usr/bin/env python3
"""Confirm the production safe-routed Pi profile on its measured Gemma scope."""

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
import pi_composition as pi_bench  # noqa: E402


TARGETS = roadmap.SECTION_GUARD_TASKS | roadmap.TABLE_QUERY_TASKS
PROFILE_TOOLS = ["section_rename_target", "section_replace_target", "table_query"]
DEFAULT_RAW = ROOT / "bench/results/gemma_safe_routed_profile_20260922.jsonl"
DEFAULT_GRADED = ROOT / "bench/results/gemma_safe_routed_profile_20260922_graded.jsonl"
DEFAULT_SANDBOX = Path("/private/tmp/incise-gemma-safe-routed-profile-20260922")


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


def expected_tool(task):
    if task["id"] == "rename-closed-atx":
        return "section_rename_target"
    if task["id"] == "replace-linux-body":
        return "section_replace_target"
    return "table_query"


def arm_for(task):
    return "section_guard" if task["id"] in roadmap.SECTION_GUARD_TASKS else "table_query"


def run_one(args, task, trial):
    task = dict(task)
    task["_trial"] = trial
    sandbox = roadmap.reset_sandbox(args.sandbox, task)
    fixture = sandbox / task["fixture"]
    before = roadmap.read_text(ROOT / task["fixture"])
    arm = arm_for(task)
    config = roadmap.config_for(arm, task, before)
    prompt = roadmap.treatment_prompt(task, before, arm)
    request = roadmap.worker_request(
        args, sandbox, roadmap.CURRENT_EXTENSION, PROFILE_TOOLS,
        task, prompt, 2,
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
        "condition": "safe-routed-profile",
        "arm": arm,
        "task_id": task["id"],
        "task_file": task["_task_file"],
        "family": roadmap.task_family(task),
        "trial": trial,
        "seed": trial,
        "max_turns": 2,
        "error": error,
        "initial_sha256": pi_bench.sha256_bytes(before.encode()),
        "final_sha256": pi_bench.sha256_bytes(after.encode()),
        "final_document": after,
        "expected_tool": expected_tool(task),
        "grading_config": config,
    }
    outcome, detail = roadmap.grade_treatment(task, arm, row, before, after, config)
    graded = {
        "condition": "safe-routed-profile",
        "arm": arm,
        "task_id": task["id"],
        "family": roadmap.task_family(task),
        "trial": trial,
        "outcome": outcome,
        "detail": detail,
    }
    return row, graded


def latest(path):
    return roadmap.latest_rows(path)


def run(args):
    tasks = [task for task in roadmap.load_tasks() if task["id"] in TARGETS]
    raw_path = Path(args.out)
    graded_path = Path(args.graded)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    graded_path.parent.mkdir(parents=True, exist_ok=True)
    done = {key for key, row in latest(raw_path).items() if not row.get("error")}
    work = [(task, trial) for task in tasks for trial in range(args.trials)
            if (task["id"], trial) not in done]
    print(f"{len(work)} production-profile trials to run", flush=True)
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
                f"[{index:2d}/{len(work)}] {task['id']:24s} t{trial:<2d} "
                f"{(row.get('elapsed_s') or 0):6.1f}s {graded['outcome']:14s} eta {eta:.0f}m",
                flush=True,
            )


def analyse(args):
    raw = latest(args.out)
    graded = latest(args.graded)
    baseline = latest(args.baseline)
    forbidden = {"destructive", "collateral:content", "collateral:formatting",
                 "unfiltered", "misreported"}
    report = {"status": "pass", "expected": args.trials * len(TARGETS), "observed": len(graded), "arms": {}}
    if len(graded) != report["expected"]:
        report["status"] = "fail"
    for arm, ids in (("section_guard", roadmap.SECTION_GUARD_TASKS),
                     ("table_query", roadmap.TABLE_QUERY_TASKS)):
        keys = sorted(key for key in graded if key[0] in ids)
        correct = sum(graded[key]["outcome"] == "correct" for key in keys)
        bad = sum(graded[key]["outcome"] in forbidden for key in keys)
        regressions = sum(
            baseline.get(key, {}).get("outcome") == "correct"
            and graded[key]["outcome"] != "correct" for key in keys)
        expected = args.trials * len(ids)
        passes = len(keys) == expected and correct >= 18 and bad == 0 and regressions == 0
        if not passes:
            report["status"] = "fail"
        report["arms"][arm] = {
            "status": "pass" if passes else "fail",
            "expected": expected,
            "observed": len(keys),
            "correct": correct,
            "outcomes": dict(sorted(Counter(graded[key]["outcome"] for key in keys).items())),
            "forbidden": bad,
            "baseline_correct_regressions": regressions,
        }
    route_errors = []
    for key, row in raw.items():
        expected = row.get("expected_tool")
        first = (row.get("provider_requests") or [{}])[0]
        if first.get("tools") != [expected] or first.get("active_tools") != [expected]:
            route_errors.append([*key, first.get("active_tools"), first.get("tools")])
    report["route_errors"] = route_errors
    if route_errors:
        report["status"] = "fail"
    print(json.dumps(report, indent=2, sort_keys=True))
    if args.analysis:
        Path(args.analysis).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")


def parser():
    value = argparse.ArgumentParser()
    value.add_argument("command", choices=("run", "analyse"))
    value.add_argument("--trials", type=int, default=10)
    value.add_argument("--out", default=str(DEFAULT_RAW))
    value.add_argument("--graded", default=str(DEFAULT_GRADED))
    value.add_argument("--analysis", default=str(ROOT / "bench/results/gemma_safe_routed_profile_20260922_analysis.json"))
    value.add_argument("--baseline", default=str(ROOT / "bench/results/gemma_roadmap_20260921_baseline_graded.jsonl"))
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
