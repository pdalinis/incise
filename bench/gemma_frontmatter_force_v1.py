#!/usr/bin/env python3
"""Run and analyse the preregistered forced Gemma frontmatter route."""

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
import pi_composition as pi_bench  # noqa: E402
from stats import mcnemar_exact  # noqa: E402


CONTROL_RAW = BENCH / "results" / "gemma_roadmap_20260921_frontmatter.jsonl"
CONTROL_GRADED = BENCH / "results" / "gemma_roadmap_20260921_frontmatter_graded.jsonl"
EXTENSION = BENCH / "gemma_frontmatter_force_extension.ts"
DEFAULT_RAW = BENCH / "results" / "gemma_frontmatter_force_v1_20260922.jsonl"
DEFAULT_GRADED = BENCH / "results" / "gemma_frontmatter_force_v1_20260922_graded.jsonl"
DEFAULT_ANALYSIS = BENCH / "results" / "gemma_frontmatter_force_v1_20260922_analysis.json"
CONTROL_SHA = "ee50a36105747d70e6d17a8db53495f39d4fb29f0e6b3372415dfcbeddfc246b"
CONTROL_GRADED_SHA = "c3825e775a5853b762507ed916644729cf77780273c76487329605f1cbf8e0d2"
CANONICAL = {
    "set-build-jobs": ("frontmatter_set_integer", {"key": "build.jobs", "value": 8}),
    "set-build-target": ("frontmatter_set_string", {"key": "build.target", "value": "debug"}),
    "set-dana-role": ("frontmatter_set_string", {"key": "authors[1].role", "value": "maintainer"}),
    "clear-title": ("frontmatter_clear", {"key": "title"}),
    "set-draft-true": ("frontmatter_set_boolean", {"key": "draft", "value": True}),
}
HARMFUL = {"destructive", "collateral:content", "collateral:formatting"}


def rows(path):
    return roadmap.latest_rows(path)


def count_outcomes(values):
    return dict(sorted(Counter(row["outcome"] for row in values).items()))


def successful_calls(row):
    results = {item["tool_call_id"]: item for item in row.get("tool_results", [])}
    return [call for call in row.get("tool_calls", [])
            if call.get("id") in results and not results[call["id"]].get("is_error")]


def run(args):
    tasks = [task for task in roadmap.load_tasks()
             if task["id"] in roadmap.FRONTMATTER_TASKS]
    raw_path = Path(args.out)
    graded_path = Path(args.graded)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    done = {key for key, row in rows(raw_path).items() if not row.get("error")}
    work = [(task, trial) for task in tasks for trial in range(args.trials)
            if (task["id"], trial) not in done]
    roadmap.TREATMENT_EXTENSION = EXTENSION
    print(f"{len(work)} trials to run", flush=True)
    started = time.time()
    with open(raw_path, "a", encoding="utf-8", newline="\n") as raw_handle, \
            open(graded_path, "a", encoding="utf-8", newline="\n") as graded_handle:
        for index, (task, trial) in enumerate(work, 1):
            row, graded = roadmap.run_one(args, "frontmatter", task, trial)
            row["condition"] = "frontmatter-force-v1"
            graded["condition"] = "frontmatter-force-v1"
            roadmap.write_jsonl(raw_handle, row)
            roadmap.write_jsonl(graded_handle, graded)
            elapsed = time.time() - started
            eta = elapsed / index * (len(work) - index) / 60 if index else 0
            print(f"[{index:2d}/{len(work)}] {task['id']:18s} t{trial} "
                  f"{graded['outcome']:12s} eta {eta:.0f}m", flush=True)


def regrade(args):
    tasks = {task["id"]: task for task in roadmap.load_tasks()}
    with open(args.graded, "w", encoding="utf-8", newline="\n") as handle:
        for key, row in sorted(rows(args.out).items()):
            task = tasks[row["task_id"]]
            before = roadmap.read_text(ROOT / task["fixture"])
            after = row.get("final_document", before)
            outcome, detail = roadmap.grade_treatment(
                task, "frontmatter", row, before, after, row["bench_config"])
            roadmap.write_jsonl(handle, {
                "condition": "frontmatter-force-v1", "task_id": task["id"],
                "family": "frontmatter", "trial": row["trial"],
                "outcome": outcome, "detail": detail,
            })


def analyse(args):
    control = rows(CONTROL_GRADED)
    control_raw = rows(CONTROL_RAW)
    treatment = rows(args.graded)
    treatment_raw = rows(args.out)
    shared = sorted(set(control) & set(treatment))
    transport = [key for key in shared if treatment[key]["outcome"] == "transport"]
    usable = [key for key in shared if key not in set(transport)]
    only_control = [key for key in usable
                    if control[key]["outcome"] == "correct"
                    and treatment[key]["outcome"] != "correct"]
    only_treatment = [key for key in usable
                      if control[key]["outcome"] != "correct"
                      and treatment[key]["outcome"] == "correct"]
    request_errors = []
    call_errors = []
    config_errors = []
    for key in usable:
        task_id, trial = key
        expected_tool, expected_args = CANONICAL[task_id]
        raw = treatment_raw[key]
        routed_requests = [request for request in raw.get("provider_requests", [])
                           if expected_tool in request.get("tools", [])]
        choice = {"type": "function", "function": {"name": expected_tool}}
        if not routed_requests:
            request_errors.append([task_id, trial, "no routed provider request"])
        for request in routed_requests:
            if (request.get("tools") != [expected_tool]
                    or request.get("active_tools") != [expected_tool]
                    or request.get("tool_choice") != choice):
                request_errors.append([task_id, trial, request])
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
    treatment_correct = sum(treatment[key]["outcome"] == "correct" for key in usable)
    harmful = sum(treatment[key]["outcome"] in HARMFUL for key in usable)
    passed = (
        len(treatment) == 50 and len(usable) == 50 and treatment_correct == 50
        and harmful == 0 and not only_control and not request_errors
        and not call_errors and not config_errors
    )
    report = {
        "status": "pass" if passed else "fail",
        "expected": 50,
        "observed": len(treatment),
        "paired": len(usable),
        "transport_pairs": [list(key) for key in transport],
        "control_correct": sum(control[key]["outcome"] == "correct" for key in usable),
        "treatment_correct": treatment_correct,
        "only_control": [list(key) for key in only_control],
        "only_treatment": [list(key) for key in only_treatment],
        "mcnemar_exact_p": mcnemar_exact(len(only_control), len(only_treatment)),
        "treatment_outcomes": count_outcomes(treatment.values()),
        "harmful": harmful,
        "request_errors": request_errors,
        "call_errors": call_errors,
        "config_errors": config_errors,
        "artifacts": {
            "raw": str(Path(args.out).relative_to(ROOT)),
            "raw_sha256": pi_bench.sha256_file(args.out),
            "graded": str(Path(args.graded).relative_to(ROOT)),
            "graded_sha256": pi_bench.sha256_file(args.graded),
        },
    }
    pi_bench.write_new_json(args.analysis, report)
    print(json.dumps(report, indent=2, sort_keys=True))


def preflight(args):
    if pi_bench.sha256_file(CONTROL_RAW) != CONTROL_SHA:
        raise RuntimeError("control raw pool hash changed")
    if pi_bench.sha256_file(CONTROL_GRADED) != CONTROL_GRADED_SHA:
        raise RuntimeError("control graded pool hash changed")
    if len(rows(CONTROL_RAW)) != 50 or len(rows(CONTROL_GRADED)) != 50:
        raise RuntimeError("control pool is not 50 complete pairs")
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
