#!/usr/bin/env python3
"""Run and analyse Gemma compatibility for the shared Ornith routes."""

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
import ornith_full as ornith  # noqa: E402
import pi_composition as pi_bench  # noqa: E402


TASKS = {"check-task-nested", "promote-api"}
EXPECTED = {
    "check-task-nested": {
        "tool": "list_set_checked_target",
        "route": "list-set-checked-target",
        "arguments": {
            "list": {"heading": "Task lists > Nested", "ordinal": 0},
            "match": "child pending",
            "checked": True,
        },
    },
    "promote-api": {
        "tool": "section_set_level_target",
        "route": "section-set-level-target",
        "arguments": {
            "section": "Deep heading nesting > Reference > API",
            "level": 2,
            "subtree": True,
        },
    },
}
HARMFUL = {"wrong", "destructive", "collateral:content", "collateral:formatting"}
DEFAULT_RAW = ROOT / "bench/results/gemma_ornith_routes_20260923.jsonl"
DEFAULT_GRADED = ROOT / "bench/results/gemma_ornith_routes_20260923_graded.jsonl"
DEFAULT_ANALYSIS = ROOT / "bench/results/gemma_ornith_routes_20260923_analysis.json"
DEFAULT_SANDBOX = Path("/private/tmp/incise-gemma-ornith-routes-20260923")


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


def run_one(args, source, trial):
    task = {**source, "_trial": trial}
    sandbox = roadmap.reset_sandbox(args.sandbox, task)
    fixture = sandbox / task["fixture"]
    before = roadmap.read_text(ROOT / task["fixture"])
    request = roadmap.worker_request(
        args, sandbox, roadmap.CURRENT_EXTENSION, ornith.ALL_TOOLS,
        task, pi_bench.prompt_for(task, before), 4,
    )
    try:
        result = call_worker(args, request)
        error = result.get("error")
    except (pi_bench.WorkerError, subprocess.TimeoutExpired) as exc:
        result = {
            "elapsed_s": None, "completion_tokens": 0, "n_turns": 0,
            "turns": [], "tool_calls": [], "tool_results": [],
            "final_content": "", "capped": False, "active_tools": [],
            "provider_requests": [],
        }
        error = f"{type(exc).__name__}: {exc}"
    after = roadmap.read_text(fixture)
    row = {
        **result,
        "condition": "gemma-ornith-routes",
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
        "expected": EXPECTED[task["id"]],
    }
    outcome, detail = pi_bench.grade_actual(task, row, before, after)
    document_outcome = None
    document_detail = None
    if after != before:
        document_outcome, document_detail = pi_bench.check_result(
            task, before, after, None)
    graded = {
        "condition": "gemma-ornith-routes",
        "task_id": task["id"],
        "family": roadmap.task_family(task),
        "trial": trial,
        "outcome": outcome,
        "detail": detail,
        "document_outcome": document_outcome,
        "document_detail": document_detail,
    }
    return row, graded


def run(args):
    tasks = [task for task in roadmap.load_tasks() if task["id"] in TASKS]
    raw_path, graded_path = Path(args.out), Path(args.graded)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    done = {key for key, row in roadmap.latest_rows(raw_path).items()
            if not row.get("error")}
    work = [(task, trial) for task in tasks for trial in range(args.trials)
            if (task["id"], trial) not in done]
    print(f"{len(work)} Gemma shared-route trials to run", flush=True)
    started = time.time()
    with open(raw_path, "a", encoding="utf-8", newline="\n") as raw_handle, \
            open(graded_path, "a", encoding="utf-8", newline="\n") as graded_handle:
        for index, (task, trial) in enumerate(work, 1):
            row, graded = run_one(args, task, trial)
            roadmap.write_jsonl(raw_handle, row)
            roadmap.write_jsonl(graded_handle, graded)
            eta = (time.time() - started) / index * (len(work) - index) / 60
            print(
                f"[{index:2d}/{len(work)}] {task['id']:20s} s{trial:<2d} "
                f"{(row.get('elapsed_s') or 0):6.1f}s {graded['outcome']:18s} "
                f"eta {eta:.0f}m",
                flush=True,
            )


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
    raw = roadmap.latest_rows(args.out)
    graded = roadmap.latest_rows(args.graded)
    keys = sorted(set(raw) & set(graded))
    errors = []
    harmful = []
    for key in keys:
        row = raw[key]
        grade = graded[key]
        expected = EXPECTED[key[0]]
        if (grade["outcome"] in HARMFUL
                or grade.get("document_outcome") in HARMFUL):
            harmful.append(list(key))
        requests = row.get("provider_requests") or []
        first = requests[0] if requests else {}
        if (first.get("tools") != [expected["tool"]]
                or first.get("active_tools") != [expected["tool"]]
                or first.get("tool_choice") is not None):
            errors.append([*key, "provider framing", first.get("tools"),
                           first.get("active_tools"), first.get("tool_choice")])
        if any(request.get("parallel_tool_calls") is not None for request in requests):
            errors.append([*key, "Ornith-only parallel_tool_calls setting"])
        successes = successful_results(row, expected["tool"])
        changed = [pair for pair in successes
                   if (pair[1].get("details") or {}).get("changed")]
        if len(successes) != 1 or len(changed) != 1:
            errors.append([*key, "successful mutations", len(successes), len(changed)])
            continue
        call, result = successes[0]
        try:
            supplied = json.loads(call.get("function", {}).get("arguments") or "{}")
        except json.JSONDecodeError:
            supplied = "invalid-json"
        details = result.get("details") or {}
        if (supplied != expected.get("supplied", {})
                or details.get("route") != expected["route"]
                or details.get("resolvedArguments") != expected["arguments"]):
            errors.append([
                *key, "resolved call", supplied, details.get("route"),
                details.get("resolvedArguments"), expected,
            ])

    outcomes = Counter(graded[key]["outcome"] for key in keys)
    correct = outcomes["correct"]
    passed = (
        len(keys) == args.trials * len(TASKS)
        and correct == len(keys)
        and not harmful
        and not errors
        and not any(graded[key]["outcome"] in {"transport", "malformed"}
                    for key in keys)
    )
    report = {
        "status": "pass" if passed else "fail",
        "expected": args.trials * len(TASKS),
        "observed": len(keys),
        "correct": correct,
        "outcomes": dict(sorted(outcomes.items())),
        "harmful_trials": harmful,
        "route_errors": errors,
        "mean_elapsed_s": round(
            sum(raw[key].get("elapsed_s") or 0 for key in keys) / len(keys), 3
        ) if keys else 0,
    }
    pi_bench.write_new_json(args.analysis, report)
    print(json.dumps(report, indent=2, sort_keys=True))


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
