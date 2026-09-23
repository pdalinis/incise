#!/usr/bin/env python3
"""Run and analyse the sixth full Gemma Pi safe-routed composition gate."""

import argparse
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "bench"
sys.path.insert(0, str(BENCH))

import gemma_frontmatter_create_route_v1 as create_v1  # noqa: E402
import gemma_roadmap as roadmap  # noqa: E402
import gemma_safe_routed_full_v5 as full_v5  # noqa: E402


CREATE_TASKS = {create_v1.TARGET}
ROUTED_TASKS = full_v5.ROUTED_TASKS | CREATE_TASKS
FULL_TOOLS = full_v5.FULL_TOOLS + [create_v1.TOOL]
DEFAULT_RAW = ROOT / "bench/results/gemma_safe_routed_full_v6_20260922.jsonl"
DEFAULT_GRADED = ROOT / "bench/results/gemma_safe_routed_full_v6_20260922_graded.jsonl"
DEFAULT_ANALYSIS = ROOT / "bench/results/gemma_safe_routed_full_v6_20260922_analysis.json"
DEFAULT_BASELINE = ROOT / "bench/results/gemma_safe_routed_full_v5_20260922_graded.jsonl"
DEFAULT_SANDBOX = Path("/private/tmp/incise-gemma-safe-routed-full-v6-20260922")
BASE_ANALYSIS = Path("/private/tmp/incise-gemma-safe-routed-full-v6-base-analysis.json")


_previous_expected_tool = full_v5.expected_tool


def expected_tool(task):
    if task["id"] in CREATE_TASKS:
        return create_v1.TOOL
    return _previous_expected_tool(task)


full_v5.ROUTED_TASKS = ROUTED_TASKS
full_v5.FULL_TOOLS = FULL_TOOLS
full_v5.full_v4.ROUTED_TASKS = ROUTED_TASKS
full_v5.full_v4.FULL_TOOLS = FULL_TOOLS
full_v5.full_v4.full_v3.ROUTED_TASKS = ROUTED_TASKS
full_v5.full_v4.full_v3.FULL_TOOLS = FULL_TOOLS
full_v5.full_v4.full_v2.ROUTED_TASKS = ROUTED_TASKS
full_v5.full_v4.full_v2.FULL_TOOLS = FULL_TOOLS
full_v5.full_v4.full_v2.full_v1.targeted.expected_tool = expected_tool


def run_one(args, task, trial):
    row, graded = full_v5.run_one(args, task, trial)
    row["condition"] = "safe-routed-full-v6"
    graded["condition"] = "safe-routed-full-v6"
    if task["id"] in CREATE_TASKS:
        row["expected_create_resolved_arguments"] = create_v1.EXPECTED
    return row, graded


def run(args):
    tasks = roadmap.load_tasks()
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    done = {key for key, row in roadmap.latest_rows(args.out).items()
            if not row.get("error")}
    work = [(task, trial) for task in tasks for trial in range(args.trials)
            if (task["id"], trial) not in done]
    print(f"{len(work)} full-profile-v6 trials to run", flush=True)
    started = time.time()
    with open(args.out, "a", encoding="utf-8", newline="\n") as raw_handle, \
            open(args.graded, "a", encoding="utf-8", newline="\n") as graded_handle:
        for index, (task, trial) in enumerate(work, 1):
            row, graded = run_one(args, task, trial)
            roadmap.write_jsonl(raw_handle, row)
            roadmap.write_jsonl(graded_handle, graded)
            eta = (time.time() - started) / index * (len(work) - index) / 60
            print(f"[{index:3d}/{len(work)}] {task['id']:27s} t{trial:<2d} "
                  f"{(row.get('elapsed_s') or 0):6.1f}s {graded['outcome']:18s} "
                  f"eta {eta:.0f}m", flush=True)


def analyse(args):
    base_args = SimpleNamespace(**vars(args))
    base_args.analysis = str(BASE_ANALYSIS)
    with redirect_stdout(io.StringIO()):
        full_v5.analyse(base_args)
    report = json.loads(BASE_ANALYSIS.read_text(encoding="utf-8"))
    raw = roadmap.latest_rows(args.out)
    graded = roadmap.latest_rows(args.graded)
    transports = {tuple(key) for key in report["transport_pairs"]}
    usable = [key for key in sorted(set(raw) & set(graded)) if key not in transports]

    create_errors = []
    create_keys = [key for key in usable if key[0] in CREATE_TASKS]
    for key in create_keys:
        row = raw[key]
        successes = full_v5.full_v4.successful_results(row, create_v1.TOOL)
        if len(successes) != 1:
            create_errors.append([*key, f"successful calls={len(successes)}"])
            continue
        call, result = successes[0]
        try:
            supplied = json.loads(call.get("function", {}).get("arguments") or "{}")
        except json.JSONDecodeError:
            supplied = "invalid-json"
        details = result.get("details") or {}
        resolved = details.get("resolvedArguments")
        if (supplied != {} or details.get("route") != "frontmatter-create"
                or resolved != row.get("expected_create_resolved_arguments")):
            create_errors.append([
                *key, supplied, details.get("route"), resolved,
                row.get("expected_create_resolved_arguments")])

    frontmatter = report["families"]["frontmatter"]
    frontmatter["floor"] = 105
    frontmatter["status"] = "pass" if frontmatter["correct"] >= 105 else "fail"
    report["routed"]["frontmatter_create_errors"] = create_errors
    report["status"] = "pass" if (
        report["status"] == "pass"
        and report["paired"] >= args.trials * 48 - 2
        and report["overall"]["treatment_correct"] >= 467
        and len(create_keys) == args.trials
        and all(graded[key]["outcome"] == "correct" for key in create_keys)
        and not create_errors
        and frontmatter["status"] == "pass"
    ) else "fail"
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
    value.add_argument("--worker", default=str(full_v5.full_v4.full_v2.pi_bench.DEFAULT_WORKER))
    value.add_argument("--pi-sdk", default=str(full_v5.full_v4.full_v2.pi_bench.DEFAULT_PI_SDK))
    value.add_argument("--node", default="node")
    value.add_argument("--endpoint", default="http://127.0.0.1:8081/v1")
    value.add_argument("--timeout", type=int, default=240)
    return value


if __name__ == "__main__":
    parsed = parser().parse_args()
    run(parsed) if parsed.command == "run" else analyse(parsed)
