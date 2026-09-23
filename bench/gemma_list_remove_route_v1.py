#!/usr/bin/env python3
"""Confirm the production exact list-removal route on its measured scope."""

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


TARGETS = {"remove-item-non-sequential", "remove-item-mixed"}
TOOL = "list_remove_target"
EXPECTED = {
    "remove-item-non-sequential": {
        "list": {"heading": "Ordered list numbering > Non-sequential", "ordinal": 0},
        "match": "third",
    },
    "remove-item-mixed": {
        "list": {"heading": "Task lists > Mixed with plain items", "ordinal": 0},
        "match": "not a task, just an item",
    },
}
CONTROL = BENCH / "results" / "gemma_safe_routed_full_v4_20260922_graded.jsonl"
DEFAULT_RAW = BENCH / "results" / "gemma_list_remove_route_v1_20260922.jsonl"
DEFAULT_GRADED = BENCH / "results" / "gemma_list_remove_route_v1_20260922_graded.jsonl"
DEFAULT_ANALYSIS = BENCH / "results" / "gemma_list_remove_route_v1_20260922_analysis.json"
DEFAULT_SANDBOX = Path("/private/tmp/incise-gemma-list-remove-route-v1-20260922")
PROFILE_TOOLS = [TOOL]


def latest(path):
    return roadmap.latest_rows(path)


def call_worker(args, request):
    env = os.environ.copy()
    env["INCISE_BIN"] = str(Path(args.binary).resolve())
    env["INCISE_PROFILE"] = "safe-routed"
    env.pop("INCISE_MODEL_FAMILY", None)
    process = subprocess.run(
        [args.node, str(Path(args.worker).resolve())], input=json.dumps(request),
        text=True, capture_output=True, timeout=args.timeout, env=env)
    if process.returncode != 0:
        detail = process.stderr.strip() or process.stdout.strip()
        raise pi_bench.WorkerError(detail or f"worker exited {process.returncode}")
    matches = [line for line in process.stdout.splitlines()
               if line.startswith(pi_bench.RESULT_PREFIX)]
    if len(matches) != 1:
        raise pi_bench.WorkerError(
            f"worker returned {len(matches)} records: {process.stdout!r}")
    return json.loads(matches[0][len(pi_bench.RESULT_PREFIX):])


def run_one(args, task, trial):
    task = dict(task)
    task["_trial"] = trial
    sandbox = roadmap.reset_sandbox(args.sandbox, task)
    fixture = sandbox / task["fixture"]
    before = roadmap.read_text(ROOT / task["fixture"])
    request = roadmap.worker_request(
        args, sandbox, roadmap.CURRENT_EXTENSION, PROFILE_TOOLS,
        task, pi_bench.prompt_for(task, before), 2)
    try:
        result = call_worker(args, request)
        error = result.get("error")
    except (pi_bench.WorkerError, subprocess.TimeoutExpired) as exc:
        result = {"elapsed_s": None, "completion_tokens": 0, "n_turns": 0,
                  "turns": [], "tool_calls": [], "tool_results": [],
                  "final_content": "", "capped": False}
        error = f"{type(exc).__name__}: {exc}"
    after = roadmap.read_text(fixture)
    row = {
        **result, "condition": "list-remove-route-v1", "task_id": task["id"],
        "task_file": task["_task_file"], "family": "list", "trial": trial,
        "seed": trial, "max_turns": 2, "error": error,
        "initial_sha256": pi_bench.sha256_bytes(before.encode()),
        "final_sha256": pi_bench.sha256_bytes(after.encode()),
        "final_document": after, "expected_arguments": EXPECTED[task["id"]],
    }
    outcome, detail = pi_bench.grade_actual(task, row, before, after)
    graded = {"condition": "list-remove-route-v1", "task_id": task["id"],
              "family": "list", "trial": trial,
              "outcome": outcome, "detail": detail}
    return row, graded


def run(args):
    tasks = [task for task in roadmap.load_tasks() if task["id"] in TARGETS]
    done = {key for key, row in latest(args.out).items() if not row.get("error")}
    work = [(task, trial) for task in tasks for trial in range(args.trials)
            if (task["id"], trial) not in done]
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    print(f"{len(work)} list-removal trials to run", flush=True)
    started = time.time()
    with open(args.out, "a", encoding="utf-8", newline="\n") as raw_handle, \
            open(args.graded, "a", encoding="utf-8", newline="\n") as graded_handle:
        for index, (task, trial) in enumerate(work, 1):
            row, graded = run_one(args, task, trial)
            roadmap.write_jsonl(raw_handle, row)
            roadmap.write_jsonl(graded_handle, graded)
            eta = (time.time() - started) / index * (len(work) - index) / 60
            print(f"[{index:2d}/{len(work)}] {task['id']:28s} t{trial} "
                  f"{graded['outcome']:12s} eta {eta:.0f}m", flush=True)


def regrade(args):
    tasks = {task["id"]: task for task in roadmap.load_tasks()}
    with open(args.graded, "w", encoding="utf-8", newline="\n") as handle:
        for key, row in sorted(latest(args.out).items()):
            task = tasks[row["task_id"]]
            before = roadmap.read_text(ROOT / task["fixture"])
            outcome, detail = pi_bench.grade_actual(
                task, row, before, row.get("final_document", before))
            roadmap.write_jsonl(handle, {
                "condition": "list-remove-route-v1", "task_id": task["id"],
                "family": "list", "trial": row["trial"],
                "outcome": outcome, "detail": detail})


def analyse(args):
    raw = latest(args.out)
    graded = latest(args.graded)
    control = latest(CONTROL)
    usable = sorted(set(control) & set(graded))
    regressions = []
    audit_errors = []
    for key in usable:
        if control[key]["outcome"] == "correct" and graded[key]["outcome"] != "correct":
            regressions.append(list(key))
        row = raw[key]
        first = (row.get("provider_requests") or [{}])[0]
        if first.get("tools") != [TOOL] or first.get("active_tools") != [TOOL]:
            audit_errors.append([*key, "provider route"])
        results = {item["tool_call_id"]: item for item in row.get("tool_results", [])}
        calls = [(call, results[call["id"]]) for call in row.get("tool_calls", [])
                 if call.get("function", {}).get("name") == TOOL
                 and call.get("id") in results and not results[call["id"]].get("is_error")]
        if len(calls) != 1:
            audit_errors.append([*key, f"successful calls={len(calls)}"])
            continue
        call, result = calls[0]
        try:
            supplied = json.loads(call.get("function", {}).get("arguments") or "{}")
        except json.JSONDecodeError:
            supplied = "invalid-json"
        resolved = (result.get("details") or {}).get("resolvedArguments")
        if supplied != {} or resolved != EXPECTED[key[0]]:
            audit_errors.append([*key, supplied, resolved])
    correct = sum(graded[key]["outcome"] == "correct" for key in usable)
    harmful_set = {"wrong", "destructive", "collateral:content", "collateral:formatting"}
    harmful = sum(graded[key]["outcome"] in harmful_set for key in usable)
    passed = (len(graded) == 20 and len(usable) == 20 and correct == 20
              and harmful == 0 and not regressions and not audit_errors)
    report = {
        "status": "pass" if passed else "fail", "expected": 20,
        "observed": len(graded), "paired": len(usable),
        "control_correct": sum(control[key]["outcome"] == "correct" for key in usable),
        "treatment_correct": correct, "harmful": harmful,
        "regressions": regressions, "audit_errors": audit_errors,
        "outcomes": dict(sorted(Counter(graded[key]["outcome"] for key in usable).items())),
        "artifacts": {
            "raw": str(Path(args.out).resolve().relative_to(ROOT)),
            "raw_sha256": pi_bench.sha256_file(args.out),
            "graded": str(Path(args.graded).resolve().relative_to(ROOT)),
            "graded_sha256": pi_bench.sha256_file(args.graded),
        },
    }
    pi_bench.write_new_json(args.analysis, report)
    print(json.dumps(report, indent=2, sort_keys=True))


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    for name, function in (("run", run), ("regrade", regrade), ("analyse", analyse)):
        command = commands.add_parser(name)
        command.add_argument("--out", default=str(DEFAULT_RAW))
        command.add_argument("--graded", default=str(DEFAULT_GRADED))
        command.set_defaults(func=function)
        if name == "run":
            roadmap.add_runtime(command)
            command.add_argument("--trials", type=int, default=10)
            command.set_defaults(sandbox=DEFAULT_SANDBOX)
        if name == "analyse":
            command.add_argument("--analysis", default=str(DEFAULT_ANALYSIS))
    args = parser.parse_args()
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
