#!/usr/bin/env python3
"""Run and analyse the preregistered Gemma frontmatter route prompt."""

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

import gemma_frontmatter_force_v1 as v1  # noqa: E402
import gemma_roadmap as roadmap  # noqa: E402
import pi_composition as pi_bench  # noqa: E402
from stats import mcnemar_exact  # noqa: E402


EXTENSION = BENCH / "gemma_frontmatter_prompt_extension.ts"
DEFAULT_RAW = BENCH / "results" / "gemma_frontmatter_prompt_v2_20260922.jsonl"
DEFAULT_GRADED = BENCH / "results" / "gemma_frontmatter_prompt_v2_20260922_graded.jsonl"
DEFAULT_ANALYSIS = BENCH / "results" / "gemma_frontmatter_prompt_v2_20260922_analysis.json"


def instruction(tool):
    return (f"Incise inspected the frontmatter and activated {tool}. This custom tool is "
            "available even if the base tool summary says none. "
            f"Call {tool} exactly once to perform the requested edit; "
            "do not describe or simulate the call.")


def run(args):
    tasks = [task for task in roadmap.load_tasks()
             if task["id"] in roadmap.FRONTMATTER_TASKS]
    raw_path = Path(args.out)
    graded_path = Path(args.graded)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    done = {key for key, row in roadmap.latest_rows(raw_path).items()
            if not row.get("error")}
    work = [(task, trial) for task in tasks for trial in range(args.trials)
            if (task["id"], trial) not in done]
    roadmap.TREATMENT_EXTENSION = EXTENSION
    print(f"{len(work)} trials to run", flush=True)
    started = time.time()
    with open(raw_path, "a", encoding="utf-8", newline="\n") as raw_handle, \
            open(graded_path, "a", encoding="utf-8", newline="\n") as graded_handle:
        for index, (task, trial) in enumerate(work, 1):
            row, graded = roadmap.run_one(args, "frontmatter", task, trial)
            row["condition"] = "frontmatter-prompt-v2"
            graded["condition"] = "frontmatter-prompt-v2"
            roadmap.write_jsonl(raw_handle, row)
            roadmap.write_jsonl(graded_handle, graded)
            elapsed = time.time() - started
            eta = elapsed / index * (len(work) - index) / 60 if index else 0
            print(f"[{index:2d}/{len(work)}] {task['id']:18s} t{trial} "
                  f"{graded['outcome']:12s} eta {eta:.0f}m", flush=True)


def regrade(args):
    tasks = {task["id"]: task for task in roadmap.load_tasks()}
    with open(args.graded, "w", encoding="utf-8", newline="\n") as handle:
        for key, row in sorted(roadmap.latest_rows(args.out).items()):
            task = tasks[row["task_id"]]
            before = roadmap.read_text(ROOT / task["fixture"])
            after = row.get("final_document", before)
            outcome, detail = roadmap.grade_treatment(
                task, "frontmatter", row, before, after, row["bench_config"])
            roadmap.write_jsonl(handle, {
                "condition": "frontmatter-prompt-v2", "task_id": task["id"],
                "family": "frontmatter", "trial": row["trial"],
                "outcome": outcome, "detail": detail,
            })


def successful_calls(row):
    results = {item["tool_call_id"]: item for item in row.get("tool_results", [])}
    return [call for call in row.get("tool_calls", [])
            if call.get("id") in results and not results[call["id"]].get("is_error")]


def analyse(args):
    control = roadmap.latest_rows(v1.CONTROL_GRADED)
    control_raw = roadmap.latest_rows(v1.CONTROL_RAW)
    treatment = roadmap.latest_rows(args.graded)
    treatment_raw = roadmap.latest_rows(args.out)
    shared = sorted(set(control) & set(treatment))
    transport = [key for key in shared if treatment[key]["outcome"] == "transport"]
    usable = [key for key in shared if key not in set(transport)]
    only_control = [key for key in usable if control[key]["outcome"] == "correct"
                    and treatment[key]["outcome"] != "correct"]
    only_treatment = [key for key in usable if control[key]["outcome"] != "correct"
                      and treatment[key]["outcome"] == "correct"]
    request_errors = []
    call_errors = []
    config_errors = []
    for key in usable:
        task_id, trial = key
        expected_tool, expected_args = v1.CANONICAL[task_id]
        raw = treatment_raw[key]
        routed = [request for request in raw.get("provider_requests", [])
                  if expected_tool in request.get("tools", [])]
        if not routed:
            request_errors.append([task_id, trial, "no routed provider request"])
        for request in routed:
            if (request.get("tools") != [expected_tool]
                    or request.get("active_tools") != [expected_tool]
                    or request.get("tool_choice") is not None
                    or not request.get("system_prompt", "").endswith(
                        "\n\n" + instruction(expected_tool))):
                request_errors.append([task_id, trial, "provider request mismatch"])
        calls = successful_calls(raw)
        if len(calls) != 1:
            call_errors.append([task_id, trial, f"successful calls={len(calls)}"])
        else:
            call = calls[0].get("function", {})
            try:
                actual_args = json.loads(call.get("arguments") or "{}")
            except json.JSONDecodeError:
                actual_args = None
            if call.get("name") != expected_tool or actual_args != expected_args:
                call_errors.append([task_id, trial, call])
        if raw.get("bench_config") != control_raw[key].get("bench_config"):
            config_errors.append([task_id, trial])
    correct = sum(treatment[key]["outcome"] == "correct" for key in usable)
    harmful = sum(treatment[key]["outcome"] in v1.HARMFUL for key in usable)
    passed = (len(treatment) == 50 and len(usable) == 50 and correct == 50
              and harmful == 0 and not only_control and not request_errors
              and not call_errors and not config_errors)
    report = {
        "status": "pass" if passed else "fail",
        "expected": 50, "observed": len(treatment), "paired": len(usable),
        "transport_pairs": [list(key) for key in transport],
        "control_correct": sum(control[key]["outcome"] == "correct" for key in usable),
        "treatment_correct": correct,
        "only_control": [list(key) for key in only_control],
        "only_treatment": [list(key) for key in only_treatment],
        "mcnemar_exact_p": mcnemar_exact(len(only_control), len(only_treatment)),
        "treatment_outcomes": dict(sorted(Counter(
            row["outcome"] for row in treatment.values()).items())),
        "harmful": harmful, "request_errors": request_errors,
        "call_errors": call_errors, "config_errors": config_errors,
        "artifacts": {
            "raw": str(Path(args.out).resolve().relative_to(ROOT)),
            "raw_sha256": pi_bench.sha256_file(args.out),
            "graded": str(Path(args.graded).resolve().relative_to(ROOT)),
            "graded_sha256": pi_bench.sha256_file(args.graded),
        },
    }
    pi_bench.write_new_json(args.analysis, report)
    print(json.dumps(report, indent=2, sort_keys=True))


def preflight(args):
    if pi_bench.sha256_file(v1.CONTROL_RAW) != v1.CONTROL_SHA:
        raise RuntimeError("control raw pool hash changed")
    if pi_bench.sha256_file(v1.CONTROL_GRADED) != v1.CONTROL_GRADED_SHA:
        raise RuntimeError("control graded pool hash changed")
    subprocess.run([args.binary, "--version"], check=True)
    subprocess.run([args.node, "--experimental-strip-types", "--check", str(EXTENSION)], check=True)
    print("preflight passed")


def runtime(parser):
    roadmap.add_runtime(parser)
    parser.set_defaults(out=str(DEFAULT_RAW), graded=str(DEFAULT_GRADED))


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("preflight")
    runtime(check)
    check.set_defaults(func=preflight)
    execute = commands.add_parser("run")
    runtime(execute)
    execute.add_argument("--trials", type=int, default=10)
    execute.set_defaults(func=run)
    grade = commands.add_parser("regrade")
    grade.add_argument("--out", default=str(DEFAULT_RAW))
    grade.add_argument("--graded", default=str(DEFAULT_GRADED))
    grade.set_defaults(func=regrade)
    analysis = commands.add_parser("analyse")
    analysis.add_argument("--out", default=str(DEFAULT_RAW))
    analysis.add_argument("--graded", default=str(DEFAULT_GRADED))
    analysis.add_argument("--analysis", default=str(DEFAULT_ANALYSIS))
    analysis.set_defaults(func=analyse)
    args = parser.parse_args()
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
