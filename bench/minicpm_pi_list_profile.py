#!/usr/bin/env python3
"""Run the preregistered MiniCPM list pipeline through the real Pi extension."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from collections import Counter

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "bench"
sys.path.insert(0, str(BENCH))

import minicpm_list_integrated as integrated  # noqa: E402
from grade import check_result  # noqa: E402

RESULT_PREFIX = "PI_BENCH_RESULT="
DEFAULT_EXTENSION = ROOT / "plugins" / "pi" / "extension" / "index.ts"
DEFAULT_PI_SDK = (
    ROOT / "plugins" / "pi" / "node_modules" / "@earendil-works"
    / "pi-coding-agent" / "dist" / "index.js"
)
DEFAULT_WORKER = BENCH / "pi_trial.mjs"
DEFAULT_BINARY = ROOT / "target" / "debug" / "incise"
DEFAULT_SANDBOX = Path("/private/tmp/incise-minicpm-pi-list-profile")
MARKER = ".incise-minicpm-pi-list-profile"
CONTENT_TOOLS = {"list_append_item", "list_insert_after", "list_insert_between"}
SCHEME = "minicpm_pi_list_profile"


def sha256_bytes(value):
    return hashlib.sha256(value).hexdigest()


def sha256_file(path):
    with open(path, "rb") as handle:
        return sha256_bytes(handle.read())


def read_text(path):
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()


def ensure_sandbox(path):
    path = Path(path).resolve()
    if path == Path("/") or path == Path.home():
        raise RuntimeError(f"refusing unsafe sandbox path: {path}")
    marker = path / MARKER
    if path.exists() and not marker.exists():
        raise RuntimeError(f"refusing to clean unmarked sandbox: {path}")
    path.mkdir(parents=True, exist_ok=True)
    marker.touch(exist_ok=True)
    return path


def reset_sandbox(path, task):
    path = ensure_sandbox(path)
    for child in path.iterdir():
        if child.name == MARKER:
            continue
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()
    (path / ".agent").mkdir()
    source = ROOT / task["fixture"]
    destination = path / task["fixture"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    return path


def prompt_for(task):
    return f"File: @{task['fixture']}\n\n{task['instruction']}"


def worker_request(args, sandbox, task, trial):
    return {
        "mode": "run",
        "cwd": str(sandbox),
        "agentDir": str(sandbox / ".agent"),
        "extension": str(Path(args.extension).resolve()),
        "piSdk": str(Path(args.pi_sdk).resolve()),
        "endpoint": args.endpoint,
        "tools": [],
        "seed": trial,
        "maxTurns": 4,
        "prompt": prompt_for(task),
        "recordActiveTools": True,
        "model": {
            "id": "minicpm5-2b-q8",
            "name": "openbmb/MiniCPM5-2B Q8_0",
            "contextWindow": 65_536,
            "maxTokens": 8_192,
            "samplingParams": {"temperature": 0.7, "top_p": 0.95},
        },
    }


def call_worker(args, request):
    env = os.environ.copy()
    env["INCISE_PROFILE"] = "minicpm-list"
    env["INCISE_BIN"] = str(Path(args.binary).resolve())
    process = subprocess.run(
        [args.node, str(Path(args.worker).resolve())],
        input=json.dumps(request),
        text=True,
        capture_output=True,
        timeout=args.timeout,
        env=env,
    )
    if process.returncode != 0:
        detail = process.stderr.strip() or process.stdout.strip()
        raise RuntimeError(detail or f"worker exited {process.returncode}")
    matches = [line for line in process.stdout.splitlines()
               if line.startswith(RESULT_PREFIX)]
    if len(matches) != 1:
        raise RuntimeError(
            f"worker returned {len(matches)} result records; stdout={process.stdout!r}")
    return json.loads(matches[0][len(RESULT_PREFIX):])


def result_by_call(row):
    return {result["tool_call_id"]: result for result in row.get("tool_results", [])}


def successful_mutations(row):
    results = result_by_call(row)
    return sum(
        call.get("function", {}).get("name") in CONTENT_TOOLS
        and call.get("id") in results
        and not results[call["id"]].get("is_error")
        for call in row.get("tool_calls", [])
    )


def validation_report(row):
    results = result_by_call(row)
    selected = []
    content = []
    routes = []
    for call in row.get("tool_calls", []):
        name = call.get("function", {}).get("name")
        result = results.get(call.get("id"), {})
        details = result.get("details") or {}
        if name == "list_select":
            selected.append(details.get("validated") is True)
            if isinstance(details.get("route"), str):
                routes.append(details["route"])
        elif name in CONTENT_TOOLS:
            content.append(details.get("validated") is True)
            if isinstance(details.get("route"), str):
                routes.append(details["route"])
    return {
        "selection_validated": bool(selected) and all(selected),
        "content_validated": bool(content) and all(content),
        "reported_routes": routes,
    }


def grade_actual(task, row, before, after):
    if row.get("error"):
        return "transport", row["error"]
    errors = [
        result.get("content", "tool failed")
        for result in row.get("tool_results", []) if result.get("is_error")
    ]
    if after == before:
        if errors:
            return "op_error", errors[-1]
        if not row.get("tool_calls"):
            return "malformed", "no tool call"
        return "wrong", "tool sequence changed nothing"
    outcome, detail = check_result(task, before, after)
    if outcome == "wrong" and errors:
        return "op_error", f"{detail}; after: {errors[-1]}"
    return outcome, detail


def run_one(args, task, trial):
    sandbox = reset_sandbox(args.sandbox, task)
    fixture = sandbox / task["fixture"]
    before = read_text(ROOT / task["fixture"])
    started = time.time()
    try:
        result = call_worker(args, worker_request(args, sandbox, task, trial))
        error = result.get("error")
    except (RuntimeError, subprocess.TimeoutExpired) as exc:
        result = {
            "elapsed_s": round(time.time() - started, 2),
            "completion_tokens": 0,
            "n_turns": 0,
            "turns": [],
            "tool_calls": [],
            "tool_results": [],
            "active_tools": [],
            "final_content": "",
            "capped": False,
        }
        error = f"{type(exc).__name__}: {exc}"
    after = read_text(fixture)
    validation = validation_report(result)
    expected_route = integrated.EXPECTED_ROUTE[task["id"]]
    route_correct = (
        bool(validation["reported_routes"])
        and all(route == expected_route for route in validation["reported_routes"])
    )
    row = {
        **result,
        **validation,
        "scheme": SCHEME,
        "task_id": task["id"],
        "trial": trial,
        "seed": trial,
        "error": error,
        "expected_route": expected_route,
        "route_correct": route_correct,
        "successful_mutations": successful_mutations(result),
        "document_changed": after != before,
        "initial_sha256": sha256_bytes(before.encode()),
        "final_sha256": sha256_bytes(after.encode()),
        "final_document": after,
        "fixture_sha256": sha256_file(ROOT / task["fixture"]),
        "extension_sha256": sha256_file(args.extension),
        "pipeline_sha256": sha256_file(
            ROOT / "plugins" / "pi" / "extension" / "minicpm-list.ts"),
        "worker_sha256": sha256_file(args.worker),
        "binary": str(Path(args.binary).resolve()),
    }
    outcome, detail = grade_actual(task, row, before, after)
    graded = {
        "scheme": SCHEME,
        "task_id": task["id"],
        "trial": trial,
        "outcome": outcome,
        "detail": detail,
        "route_correct": route_correct,
        "selection_validated": row["selection_validated"],
        "content_validated": row["content_validated"],
        "successful_mutations": row["successful_mutations"],
    }
    return row, graded


def read_last(path):
    rows = {}
    if not Path(path).exists():
        return rows
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                row = json.loads(line)
                rows[(row["task_id"], row["trial"])] = row
    return rows


def write_jsonl(handle, value):
    handle.write(json.dumps(value, separators=(",", ":")) + "\n")
    handle.flush()


def run(args):
    tasks = integrated.tasks()
    done = {key for key, row in read_last(args.out).items() if not row.get("error")}
    work = [(task, trial) for task in tasks for trial in range(args.trials)
            if (task["id"], trial) not in done]
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.graded).parent.mkdir(parents=True, exist_ok=True)
    print(f"{len(work)} Pi trials to run, scheme={SCHEME}")
    started = time.time()
    with open(args.out, "a", encoding="utf-8", newline="\n") as raw_handle, \
            open(args.graded, "a", encoding="utf-8", newline="\n") as graded_handle:
        for index, (task, trial) in enumerate(work, 1):
            row, graded = run_one(args, task, trial)
            write_jsonl(raw_handle, row)
            write_jsonl(graded_handle, graded)
            elapsed = time.time() - started
            eta = elapsed / index * (len(work) - index) / 60
            print(
                f"[{index:2d}/{len(work)}] {task['id']:27s} t{trial} "
                f"{graded['outcome']:10s} writes={row['successful_mutations']} "
                f"eta {eta:.0f}m",
                flush=True,
            )
    print(dict(Counter(row["outcome"] for row in read_last(args.graded).values())))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", default="http://127.0.0.1:8081/v1")
    parser.add_argument("--extension", default=str(DEFAULT_EXTENSION))
    parser.add_argument("--pi-sdk", default=str(DEFAULT_PI_SDK))
    parser.add_argument("--worker", default=str(DEFAULT_WORKER))
    parser.add_argument("--binary", default=str(DEFAULT_BINARY))
    parser.add_argument("--sandbox", default=str(DEFAULT_SANDBOX))
    parser.add_argument("--node", default="node")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--out", required=True)
    parser.add_argument("--graded", required=True)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
