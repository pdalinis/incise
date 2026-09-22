#!/usr/bin/env python3
"""Confirm predicate parsing and host-owned values for Gemma table reads."""

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
from grade import check_result  # noqa: E402


TABLE_TASKS = {
    "get-whole-table", "get-filter-one-column", "get-filter-two-columns",
    "get-filter-no-match", "get-ordinal-table", "get-escaped-cell",
}
ROUTED_TASKS = {
    "get-filter-one-column", "get-filter-two-columns",
    "get-filter-no-match", "get-escaped-cell",
}
FULL_TOOLS = roadmap.BASELINE_TOOLS + [
    "section_rename_target", "section_replace_target", "table_query",
]
DEFAULT_RAW = ROOT / "bench/results/gemma_table_route_v2_20260922.jsonl"
DEFAULT_GRADED = ROOT / "bench/results/gemma_table_route_v2_20260922_graded.jsonl"
DEFAULT_ANALYSIS = ROOT / "bench/results/gemma_table_route_v2_20260922_analysis.json"
DEFAULT_SANDBOX = Path("/private/tmp/incise-gemma-table-route-v2-20260922")


def call_worker(args, request):
    env = os.environ.copy()
    env["INCISE_BIN"] = str(Path(args.binary).resolve())
    env["INCISE_PROFILE"] = "safe-routed"
    env.pop("INCISE_MODEL_FAMILY", None)
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


def successful_result(row, name):
    results = {result["tool_call_id"]: result for result in row.get("tool_results", [])}
    for call in row.get("tool_calls", []):
        if call.get("function", {}).get("name") != name:
            continue
        result = results.get(call.get("id"))
        if result is not None and not result.get("is_error"):
            return call, result
    return None, None


def grade(task, row, before, after):
    if task["id"] not in ROUTED_TASKS:
        return pi_bench.grade_actual(task, row, before, after)
    if row.get("error"):
        return ("transport" if pi_bench.is_transport(row["error"]) else "malformed",
                row["error"])
    call, result = successful_result(row, "table_query")
    if call is None:
        errors = [item.get("content", "tool failed") for item in row.get("tool_results", [])
                  if item.get("is_error")]
        return ("op_error", errors[-1]) if errors else ("malformed", "no successful table_query")
    report = (result.get("details") or {}).get("rows")
    return check_result(task, before, after, report)


def run_one(args, task, trial):
    task = dict(task)
    task["_trial"] = trial
    sandbox = roadmap.reset_sandbox(args.sandbox, task)
    fixture = sandbox / task["fixture"]
    before = roadmap.read_text(ROOT / task["fixture"])
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
        "condition": "table-route-v2",
        "task_id": task["id"],
        "task_file": task["_task_file"],
        "family": "table-read",
        "trial": trial,
        "seed": trial,
        "max_turns": 4,
        "error": error,
        "initial_sha256": pi_bench.sha256_bytes(before.encode()),
        "final_sha256": pi_bench.sha256_bytes(after.encode()),
        "final_document": after,
        "expected_route": task["id"] in ROUTED_TASKS,
        "expected_filter": task.get("ideal_call", {}).get("args", {}).get("filter"),
    }
    outcome, detail = grade(task, row, before, after)
    graded = {
        "condition": "table-route-v2", "task_id": task["id"],
        "family": "table-read", "trial": trial,
        "routed": task["id"] in ROUTED_TASKS,
        "outcome": outcome, "detail": detail,
    }
    return row, graded


def run(args):
    tasks = [task for task in roadmap.load_tasks() if task["id"] in TABLE_TASKS]
    raw_path = Path(args.out)
    graded_path = Path(args.graded)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    graded_path.parent.mkdir(parents=True, exist_ok=True)
    done = {key for key, row in roadmap.latest_rows(raw_path).items()
            if not row.get("error")}
    work = [(task, trial) for task in tasks for trial in range(args.trials)
            if (task["id"], trial) not in done]
    print(f"{len(work)} table-route-v2 trials to run", flush=True)
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
    raw = roadmap.latest_rows(args.out)
    graded = roadmap.latest_rows(args.graded)
    route_errors = []
    filter_errors = []
    outcomes = Counter()
    per_task = {}
    for task_id in sorted(TABLE_TASKS):
        keys = sorted(key for key in graded if key[0] == task_id)
        task_rows = [graded[key] for key in keys]
        outcomes.update(row["outcome"] for row in task_rows)
        per_task[task_id] = dict(sorted(Counter(row["outcome"] for row in task_rows).items()))
        for key in keys:
            row = raw[key]
            first = (row.get("provider_requests") or [{}])[0]
            expected_tools = ["table_query"] if task_id in ROUTED_TASKS else roadmap.BASELINE_TOOLS
            if first.get("tools") != expected_tools or first.get("active_tools") != expected_tools:
                route_errors.append([*key, first.get("active_tools"), first.get("tools")])
            if task_id in ROUTED_TASKS:
                _call, result = successful_result(row, "table_query")
                resolved = ((result or {}).get("details") or {}).get("resolvedArguments", {}).get("filter")
                if resolved != row.get("expected_filter"):
                    filter_errors.append([*key, row.get("expected_filter"), resolved])
    correct = outcomes["correct"]
    passes = (
        len(graded) == args.trials * len(TABLE_TASKS)
        and correct == args.trials * len(TABLE_TASKS)
        and not route_errors
        and not filter_errors
    )
    report = {
        "status": "pass" if passes else "fail",
        "expected": args.trials * len(TABLE_TASKS), "observed": len(graded),
        "correct": correct, "outcomes": dict(sorted(outcomes.items())),
        "per_task": per_task, "route_errors": route_errors,
        "filter_errors": filter_errors,
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
