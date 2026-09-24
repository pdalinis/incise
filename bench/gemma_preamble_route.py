#!/usr/bin/env python3
"""Run Gemma compatibility confirmation for the qualified-preamble route."""

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bench"))

import analyze_ornith_held_routes as held  # noqa: E402
import analyze_ornith_preamble_route as audit  # noqa: E402
import gemma_ornith_routes as base  # noqa: E402


base.TASKS = {"replace-install-preamble", "replace-linux-body"}
specs = {
    **audit.SPECS,
    "replace-linux-body": held.expected_specs()["replace-linux-body"],
}
base.EXPECTED = {
    task_id: {
        "tool": value["tool"], "route": value["route"],
        "arguments": value["resolved"], "supplied": value["supplied"],
    }
    for task_id, value in specs.items()
}


def parser():
    value = argparse.ArgumentParser()
    value.add_argument("command", choices=("run", "analyse"))
    value.add_argument("--trials", type=int, default=10)
    value.add_argument("--out", default=str(ROOT / "bench/results/gemma_preamble_route_20260923.jsonl"))
    value.add_argument("--graded", default=str(ROOT / "bench/results/gemma_preamble_route_20260923_graded.jsonl"))
    value.add_argument("--analysis", default=str(ROOT / "bench/results/gemma_preamble_route_20260923_analysis.json"))
    value.add_argument("--sandbox", type=Path, default=Path("/private/tmp/incise-gemma-preamble-route-20260923"))
    value.add_argument("--binary", default=str(base.roadmap.DEFAULT_BINARY))
    value.add_argument("--worker", default=str(base.pi_bench.DEFAULT_WORKER))
    value.add_argument("--pi-sdk", default=str(base.pi_bench.DEFAULT_PI_SDK))
    value.add_argument("--node", default="node")
    value.add_argument("--endpoint", default="http://127.0.0.1:8081/v1")
    value.add_argument("--timeout", type=int, default=240)
    return value


if __name__ == "__main__":
    args = parser().parse_args()
    base.run(args) if args.command == "run" else base.analyse(args)
