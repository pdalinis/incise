#!/usr/bin/env python3
"""Confirm the production safe-routed frontmatter route on its measured scope."""

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

import gemma_frontmatter_force_v1 as v1  # noqa: E402
import gemma_frontmatter_prompt_v2 as v2  # noqa: E402
import gemma_roadmap as roadmap  # noqa: E402
import pi_composition as pi_bench  # noqa: E402


TARGETS = roadmap.FRONTMATTER_TASKS
PROFILE_TOOLS = sorted({tool for tool, _args in v1.CANONICAL.values()})
DEFAULT_RAW = BENCH / "results" / "gemma_frontmatter_profile_v3_20260922.jsonl"
DEFAULT_GRADED = BENCH / "results" / "gemma_frontmatter_profile_v3_20260922_graded.jsonl"
DEFAULT_ANALYSIS = BENCH / "results" / "gemma_frontmatter_profile_v3_20260922_analysis.json"
DEFAULT_SANDBOX = Path("/private/tmp/incise-gemma-frontmatter-profile-v3-20260922")


def latest(path):
    return roadmap.latest_rows(path)


def call_worker(args, request):
    env = os.environ.copy()
    env["INCISE_BIN"] = str(Path(args.binary).resolve())
    env["INCISE_PROFILE"] = "safe-routed"
    env.pop("INCISE_MODEL_FAMILY", None)
    env.pop("INCISE_GEMMA_BENCH_CONFIG", None)
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
    config = roadmap.config_for("frontmatter", task, before)
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
        **result, "condition": "frontmatter-profile-v3",
        "task_id": task["id"], "task_file": task["_task_file"],
        "family": "frontmatter", "trial": trial, "seed": trial,
        "max_turns": 2, "error": error,
        "initial_sha256": pi_bench.sha256_bytes(before.encode()),
        "final_sha256": pi_bench.sha256_bytes(after.encode()),
        "final_document": after, "grading_config": config,
    }
    outcome, detail = roadmap.grade_treatment(
        task, "frontmatter", row, before, after, config)
    graded = {"condition": "frontmatter-profile-v3", "task_id": task["id"],
              "family": "frontmatter", "trial": trial,
              "outcome": outcome, "detail": detail}
    return row, graded


def run(args):
    tasks = [task for task in roadmap.load_tasks() if task["id"] in TARGETS]
    done = {key for key, row in latest(args.out).items() if not row.get("error")}
    work = [(task, trial) for task in tasks for trial in range(args.trials)
            if (task["id"], trial) not in done]
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    print(f"{len(work)} production-profile trials to run", flush=True)
    started = time.time()
    with open(args.out, "a", encoding="utf-8", newline="\n") as raw_handle, \
            open(args.graded, "a", encoding="utf-8", newline="\n") as graded_handle:
        for index, (task, trial) in enumerate(work, 1):
            row, graded = run_one(args, task, trial)
            roadmap.write_jsonl(raw_handle, row)
            roadmap.write_jsonl(graded_handle, graded)
            eta = (time.time() - started) / index * (len(work) - index) / 60
            print(f"[{index:2d}/{len(work)}] {task['id']:18s} t{trial} "
                  f"{graded['outcome']:12s} eta {eta:.0f}m", flush=True)


def regrade(args):
    tasks = {task["id"]: task for task in roadmap.load_tasks()}
    with open(args.graded, "w", encoding="utf-8", newline="\n") as handle:
        for key, row in sorted(latest(args.out).items()):
            task = tasks[row["task_id"]]
            before = roadmap.read_text(ROOT / task["fixture"])
            outcome, detail = roadmap.grade_treatment(
                task, "frontmatter", row, before,
                row.get("final_document", before), row["grading_config"])
            roadmap.write_jsonl(handle, {
                "condition": "frontmatter-profile-v3", "task_id": task["id"],
                "family": "frontmatter", "trial": row["trial"],
                "outcome": outcome, "detail": detail})


def analyse(args):
    raw = latest(args.out)
    graded = latest(args.graded)
    errors = []
    for key in sorted(graded):
        task_id, trial = key
        expected_tool, expected_args = v1.CANONICAL[task_id]
        row = raw[key]
        first = (row.get("provider_requests") or [{}])[0]
        if (first.get("tools") != [expected_tool]
                or first.get("active_tools") != [expected_tool]
                or first.get("tool_choice") is not None
                or v2.instruction(expected_tool) not in first.get("system_prompt", "")):
            errors.append([task_id, trial, "provider route"])
        results = {item["tool_call_id"]: item for item in row.get("tool_results", [])}
        calls = [call for call in row.get("tool_calls", [])
                 if call.get("id") in results and not results[call["id"]].get("is_error")]
        if len(calls) != 1:
            errors.append([task_id, trial, f"successful calls={len(calls)}"])
            continue
        call = calls[0].get("function", {})
        try:
            model_args = json.loads(call.get("arguments") or "{}")
        except json.JSONDecodeError:
            model_args = None
        if call.get("name") != expected_tool or model_args != expected_args:
            errors.append([task_id, trial, "model arguments", call])
        details = results[calls[0]["id"]].get("details") or {}
        resolved = {**expected_args, "must_exist": True}
        if expected_tool == "frontmatter_clear":
            resolved["value"] = None
        if (details.get("route") != "frontmatter-typed"
                or details.get("resolvedArguments") != resolved):
            errors.append([task_id, trial, "resolved arguments", details])
    correct = sum(row["outcome"] == "correct" for row in graded.values())
    harmful = sum(row["outcome"] in v1.HARMFUL for row in graded.values())
    passed = len(graded) == 50 and correct == 50 and harmful == 0 and not errors
    report = {
        "status": "pass" if passed else "fail", "expected": 50,
        "observed": len(graded), "correct": correct, "harmful": harmful,
        "outcomes": dict(sorted(Counter(row["outcome"] for row in graded.values()).items())),
        "audit_errors": errors,
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
