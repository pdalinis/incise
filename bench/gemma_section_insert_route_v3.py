#!/usr/bin/env python3
"""Run the request-boundary correction for Gemma section insertion."""

import argparse
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "bench"
sys.path.insert(0, str(BENCH))

import gemma_roadmap as roadmap  # noqa: E402
import gemma_section_insert_route_v2 as v2  # noqa: E402


DEFAULT_RAW = ROOT / "bench/results/gemma_section_insert_route_v3_20260922.jsonl"
DEFAULT_GRADED = ROOT / "bench/results/gemma_section_insert_route_v3_20260922_graded.jsonl"
DEFAULT_ANALYSIS = ROOT / "bench/results/gemma_section_insert_route_v3_20260922_analysis.json"
DEFAULT_CONTROL = ROOT / "bench/results/gemma_section_insert_route_v1_20260922_graded.jsonl"
DEFAULT_PRODUCT_BASELINE = ROOT / "bench/results/gemma_safe_routed_full_v2_20260922_graded.jsonl"
DEFAULT_SANDBOX = Path("/private/tmp/incise-gemma-section-insert-route-v3-20260922")


def run_one(args, task, trial):
    row, graded = v2.run_one(args, task, trial)
    row["condition"] = "section-insert-route-v3"
    graded["condition"] = "section-insert-route-v3"
    return row, graded


def run(args):
    tasks = [task for task in roadmap.load_tasks() if task["id"] in v2.TASKS]
    raw_path = Path(args.out)
    graded_path = Path(args.graded)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    graded_path.parent.mkdir(parents=True, exist_ok=True)
    done = {key for key, row in roadmap.latest_rows(raw_path).items()
            if not row.get("error")}
    work = [(task, trial) for task in tasks for trial in range(args.trials)
            if (task["id"], trial) not in done]
    print(f"{len(work)} section-insert-route-v3 trials to run", flush=True)
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
    value.add_argument("--worker", default=str(roadmap.pi_bench.DEFAULT_WORKER))
    value.add_argument("--pi-sdk", default=str(roadmap.pi_bench.DEFAULT_PI_SDK))
    value.add_argument("--node", default="node")
    value.add_argument("--endpoint", default="http://127.0.0.1:8081/v1")
    value.add_argument("--timeout", type=int, default=240)
    return value


if __name__ == "__main__":
    parsed = parser().parse_args()
    run(parsed) if parsed.command == "run" else v2.analyse(parsed)
