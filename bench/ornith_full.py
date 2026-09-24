#!/usr/bin/env python3
"""Run and analyse the preregistered Ornith 1.5 9B Pi evaluation."""

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "bench"
sys.path.insert(0, str(BENCH))

import pi_composition as pi_bench  # noqa: E402
from grade import check_result  # noqa: E402


MODEL = {
    "id": "ornith-1.5-9b-q8",
    "name": "Ornith-1.5-9B",
    "reasoning": True,
    "contextWindow": 65_536,
    "maxTokens": 8_192,
    "samplingParams": {
        "temperature": 0.6,
        "top_p": 0.95,
        "top_k": 20,
        "min_p": 0.0,
        "presence_penalty": 0.0,
        "repeat_penalty": 1.0,
    },
    "compat": {
        "supportsDeveloperRole": False,
        "supportsReasoningEffort": False,
        "thinkingFormat": "qwen-chat-template",
    },
}
STANDARD_TOOLS = [
    "table_edit", "list_edit", "section_edit", "frontmatter_edit", "table_get",
    "md_tables", "md_lists", "md_outline",
]
ROUTED_TOOLS = [
    "section_rename_target", "section_replace_target", "section_insert_target",
    "section_append_target", "section_set_level_target",
    "frontmatter_clear", "frontmatter_set_string",
    "frontmatter_set_integer", "frontmatter_set_boolean",
    "frontmatter_create_target", "list_remove_target", "list_append_target",
    "list_set_checked_target",
    "table_query",
]
ALL_TOOLS = STANDARD_TOOLS + ROUTED_TOOLS
PROFILES = {"auto-standard": "auto", "forced-safe-routed": "safe-routed"}
SMOKE_TASKS = {
    "add-row-aligned-short", "add-item-nested-asterisk", "insert-nested-ratelimits",
    "set-build-target", "get-filter-two-columns",
}
HARMFUL = {"wrong", "destructive", "collateral:content", "collateral:formatting"}
ROUTED_TABLE_TASKS = {
    "get-filter-one-column", "get-filter-two-columns",
    "get-filter-no-match", "get-escaped-cell",
}
FAMILY_FLOORS = {
    "table": (57, 60),
    "list": (100, 100),
    "section": (140, 149),
    "frontmatter": (105, 110),
    "table-read": (57, 60),
}
DEFAULT_BINARY = ROOT / "target" / "debug" / "incise"
DEFAULT_SANDBOX = Path("/private/tmp/incise-ornith-full-20260923")
MARKER = ".incise-ornith-full-sandbox"


def read_text(path):
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()


def load_tasks():
    tasks = pi_bench.load_tasks()
    return {task["id"]: task for task in tasks}


def ensure_sandbox(path):
    path = Path(path).resolve()
    if path in (Path("/"), Path.home()):
        raise RuntimeError(f"unsafe sandbox: {path}")
    marker = path / MARKER
    if path.exists() and not marker.exists():
        raise RuntimeError(f"refusing unmarked sandbox: {path}")
    path.mkdir(parents=True, exist_ok=True)
    marker.touch(exist_ok=True)
    return path


def reset_sandbox(path, task=None):
    path = ensure_sandbox(path)
    for child in path.iterdir():
        if child.name == MARKER:
            continue
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()
    (path / ".agent").mkdir()
    if task:
        source = ROOT / task["fixture"]
        destination = path / task["fixture"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    return path


def worker_request(args, task, trial, prompt):
    sandbox = Path(args.sandbox).resolve()
    sampling = {**MODEL["samplingParams"]}
    if args.parallel_tool_calls != "default":
        sampling["parallel_tool_calls"] = args.parallel_tool_calls == "true"
    model = {**MODEL, "maxTokens": args.max_tokens, "samplingParams": sampling}
    return {
        "mode": "run",
        "cwd": str(sandbox),
        "agentDir": str(sandbox / ".agent"),
        "extension": str((ROOT / "plugins/pi/extension/index.ts").resolve()),
        "piSdk": str(Path(args.pi_sdk).resolve()),
        "endpoint": args.endpoint,
        "tools": ALL_TOOLS,
        "model": model,
        "thinkingLevel": "high" if args.thinking == "on" else "off",
        "seed": trial,
        "maxTurns": 4,
        "prompt": prompt,
        "recordActiveTools": True,
        "recordProviderRequests": True,
    }


def call_worker(args, request):
    env = os.environ.copy()
    env["INCISE_BIN"] = str(Path(args.binary).resolve())
    env["INCISE_PROFILE"] = PROFILES[args.condition]
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
    results = {result["tool_call_id"]: result
               for result in row.get("tool_results", [])}
    for call in row.get("tool_calls", []):
        if call.get("function", {}).get("name") != name:
            continue
        result = results.get(call.get("id"))
        if result is not None and not result.get("is_error"):
            return call, result
    return None, None


def grade_row(task, row, before, after):
    if task["id"] not in ROUTED_TABLE_TASKS:
        return pi_bench.grade_actual(task, row, before, after)
    call, result = successful_result(row, "table_query")
    if call is None:
        return pi_bench.grade_actual(task, row, before, after)
    if row.get("error"):
        return ("transport" if pi_bench.is_transport(row["error"])
                else "malformed", row["error"])
    report = (result.get("details") or {}).get("rows")
    return check_result(task, before, after, report)


def run_one(args, task, trial):
    sandbox = reset_sandbox(args.sandbox, task)
    fixture = sandbox / task["fixture"]
    before = read_text(ROOT / task["fixture"])
    prompt = pi_bench.prompt_for(task, before)
    try:
        result = call_worker(args, worker_request(args, task, trial, prompt))
        error = result.get("error")
    except (pi_bench.WorkerError, subprocess.TimeoutExpired) as exc:
        result = {
            "elapsed_s": None, "completion_tokens": 0, "reasoning_tokens": 0,
            "reasoning_characters": 0, "n_turns": 0, "turns": [],
            "tool_calls": [], "tool_results": [], "final_content": "",
            "capped": False, "active_tools": [], "provider_requests": [],
        }
        error = f"{type(exc).__name__}: {exc}"
    after = read_text(fixture)
    row = {
        **result,
        "condition": args.condition,
        "profile": PROFILES[args.condition],
        "thinking": args.thinking,
        "model": MODEL["id"],
        "task_id": task["id"],
        "task_file": task["_task_file"],
        "family": pi_bench.task_family(task),
        "trial": trial,
        "seed": trial,
        "max_turns": 4,
        "max_tokens": args.max_tokens,
        "parallel_tool_calls": args.parallel_tool_calls,
        "error": error,
        "initial_sha256": pi_bench.sha256_bytes(before.encode()),
        "final_sha256": pi_bench.sha256_bytes(after.encode()),
        "final_document": after,
    }
    outcome, detail = grade_row(task, row, before, after)
    document_outcome = None
    document_detail = None
    if after != before:
        document_outcome, document_detail = pi_bench.check_result(
            task, before, after, None)
    graded = {
        "condition": args.condition,
        "task_id": task["id"],
        "family": pi_bench.task_family(task),
        "trial": trial,
        "outcome": outcome,
        "detail": detail,
        "document_outcome": document_outcome,
        "document_detail": document_detail,
    }
    return row, graded


def latest_rows(path):
    return pi_bench.latest_rows(path)


def validate_framing(row):
    errors = []
    requests = row.get("provider_requests") or []
    if not requests:
        return ["no provider request recorded"]
    first = requests[0]
    expected = {
        "model": MODEL["id"], "seed": row["seed"],
        "max_tokens": row.get("max_tokens", 8192),
        "temperature": 0.6, "top_p": 0.95, "top_k": 20, "min_p": 0,
        "presence_penalty": 0, "repeat_penalty": 1,
        "chat_template_kwargs": {
            "enable_thinking": row.get("thinking", "on") == "on",
            "preserve_thinking": True,
        },
    }
    for key, value in expected.items():
        if first.get(key) != value:
            errors.append(f"{key}: expected {value!r}, got {first.get(key)!r}")
    parallel = row.get("parallel_tool_calls", "default")
    expected_parallel = None if parallel == "default" else parallel == "true"
    if first.get("parallel_tool_calls") != expected_parallel:
        errors.append(
            "parallel_tool_calls: expected "
            f"{expected_parallel!r}, got {first.get('parallel_tool_calls')!r}"
        )
    if row["condition"] == "auto-standard":
        for request in requests:
            unexpected = sorted(set(request.get("tools") or []) - set(STANDARD_TOOLS))
            if unexpected:
                errors.append(f"auto activated routed tools: {unexpected}")
    return errors


def write_jsonl(handle, value):
    handle.write(json.dumps(value, separators=(",", ":")) + "\n")
    handle.flush()


def selected_tasks(args):
    tasks = load_tasks()
    if args.command == "smoke":
        return [tasks[task_id] for task_id in sorted(SMOKE_TASKS)]
    if args.task_id:
        unknown = sorted(set(args.task_id) - set(tasks))
        if unknown:
            raise SystemExit(f"unknown task IDs: {', '.join(unknown)}")
        wanted = set(args.task_id)
        return [task for task in tasks.values() if task["id"] in wanted]
    return list(tasks.values())


def run(args):
    tasks = selected_tasks(args)
    raw_path, graded_path = Path(args.out), Path(args.graded)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    graded_path.parent.mkdir(parents=True, exist_ok=True)
    done = {key for key, row in latest_rows(raw_path).items() if not row.get("error")}
    trials = range(args.seed_start, args.seed_start + args.trials)
    work = [(task, trial) for task in tasks for trial in trials
            if (task["id"], trial) not in done]
    print(
        f"{len(work)} Ornith trials, condition={args.condition}, "
        f"thinking={args.thinking}",
        flush=True,
    )
    started = time.time()
    with open(raw_path, "a", encoding="utf-8", newline="\n") as raw_handle, \
            open(graded_path, "a", encoding="utf-8", newline="\n") as graded_handle:
        for index, (task, trial) in enumerate(work, 1):
            row, graded = run_one(args, task, trial)
            framing_errors = validate_framing(row) if not row.get("error") else []
            row["framing_errors"] = framing_errors
            graded["framing_errors"] = framing_errors
            write_jsonl(raw_handle, row)
            write_jsonl(graded_handle, graded)
            eta = (time.time() - started) / index * (len(work) - index) / 60
            print(
                f"[{index:3d}/{len(work)}] {task['id']:27s} s{trial:<2d} "
                f"{(row.get('elapsed_s') or 0):6.1f}s {graded['outcome']:18s} "
                f"think={row.get('reasoning_characters', 0):5d} eta {eta:.0f}m",
                flush=True,
            )


def counts(rows):
    return dict(sorted(Counter(row["outcome"] for row in rows).items()))


def analyse(args):
    raw = latest_rows(args.out)
    graded = latest_rows(args.graded)
    shared = sorted(set(raw) & set(graded))
    usable = [key for key in shared if graded[key]["outcome"] != "transport"]
    families = {}
    floors_pass = True
    for family, (floor, full_n) in FAMILY_FLOORS.items():
        keys = [key for key in usable if graded[key]["family"] == family]
        correct = sum(graded[key]["outcome"] == "correct" for key in keys)
        scaled_floor = floor if args.trials == 10 else None
        status = "not-applicable" if scaled_floor is None else (
            "pass" if len(keys) >= full_n and correct >= scaled_floor else "fail")
        if status == "fail":
            floors_pass = False
        families[family] = {
            "n": len(keys), "correct": correct,
            "rate": round(correct / len(keys), 6) if keys else 0,
            "outcomes": counts(graded[key] for key in keys),
            "gemma_floor": scaled_floor, "status": status,
        }
    correct = sum(graded[key]["outcome"] == "correct" for key in usable)
    harmful_keys = [
        key for key in usable
        if graded[key]["outcome"] in HARMFUL
        or graded[key].get("document_outcome") in HARMFUL
    ]
    harmful = len(harmful_keys)
    framing_errors = [
        [*key, *raw[key].get("framing_errors", [])]
        for key in usable if raw[key].get("framing_errors")
    ]
    tasks = load_tasks()
    multiple_mutations = []
    reasoning_leaks = []
    for key in usable:
        successful_changes = sum(
            not result.get("is_error") and bool((result.get("details") or {}).get("changed"))
            for result in raw[key].get("tool_results") or []
        )
        expected_changes = 0 if graded[key]["family"] == "table-read" else len(
            pi_bench.ideal_calls(tasks[key[0]])
        )
        if successful_changes > expected_changes:
            multiple_mutations.append([*key, successful_changes, expected_changes])
        visible = "\n".join(
            [raw[key].get("final_content") or ""]
            + [call.get("function", {}).get("arguments") or ""
               for call in raw[key].get("tool_calls") or []]
        )
        if "<think>" in visible or "</think>" in visible:
            reasoning_leaks.append(list(key))
    expected = 48 * args.trials
    gate = (
        len(usable) >= max(0, expected - 2)
        and correct >= (472 if args.trials == 10 else 0)
        and harmful == 0 and floors_pass and not framing_errors
        and not multiple_mutations and not reasoning_leaks
    )
    report = {
        "status": "pass" if gate else "fail",
        "condition": args.condition,
        "expected": expected,
        "observed": len(shared),
        "usable": len(usable),
        "correct": correct,
        "correct_rate": round(correct / len(usable), 6) if usable else 0,
        "harmful": harmful,
        "harmful_trials": [list(key) for key in harmful_keys],
        "outcomes": counts(graded[key] for key in usable),
        "families": families,
        "framing_errors": framing_errors,
        "multiple_mutations": multiple_mutations,
        "reasoning_leaks": reasoning_leaks,
        "efficiency": {
            "mean_elapsed_s": round(sum(raw[key].get("elapsed_s") or 0 for key in usable) / len(usable), 3) if usable else 0,
            "mean_completion_tokens": round(sum(raw[key].get("completion_tokens") or 0 for key in usable) / len(usable), 3) if usable else 0,
            "mean_reasoning_tokens": round(sum(raw[key].get("reasoning_tokens") or 0 for key in usable) / len(usable), 3) if usable else 0,
            "mean_reasoning_characters": round(sum(raw[key].get("reasoning_characters") or 0 for key in usable) / len(usable), 3) if usable else 0,
            "mean_tool_calls": round(sum(len(raw[key].get("tool_calls") or []) for key in usable) / len(usable), 3) if usable else 0,
        },
        "gate": {
            "minimum_usable": max(0, expected - 2),
            "minimum_correct": 472 if args.trials == 10 else None,
            "harmful": 0,
            "family_floors": {name: floor for name, (floor, _n) in FAMILY_FLOORS.items()},
        },
    }
    pi_bench.write_new_json(args.analysis, report)
    print(json.dumps(report, indent=2, sort_keys=True))


def preflight(args):
    subprocess.run([args.binary, "--version"], check=True)
    subprocess.run([args.node, "--check", args.worker], check=True)
    response = subprocess.run(
        ["curl", "-fsS", "--max-time", "5", f"{args.endpoint}/models"],
        text=True, capture_output=True, check=True,
    )
    model_ids = [entry["id"] for entry in json.loads(response.stdout).get("data", [])]
    if MODEL["id"] not in model_ids:
        raise SystemExit(f"expected {MODEL['id']}, endpoint returned {model_ids}")
    print("Ornith preflight passed")


def add_runtime(parser):
    parser.add_argument("--condition", choices=sorted(PROFILES), default="auto-standard")
    parser.add_argument("--binary", default=str(DEFAULT_BINARY))
    parser.add_argument("--pi-sdk", default=str(pi_bench.DEFAULT_PI_SDK))
    parser.add_argument("--worker", default=str(pi_bench.DEFAULT_WORKER))
    parser.add_argument("--node", default="node")
    parser.add_argument("--endpoint", default="http://127.0.0.1:8081/v1")
    parser.add_argument("--sandbox", default=str(DEFAULT_SANDBOX))
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--thinking", choices=("on", "off"), default="on")
    parser.add_argument("--max-tokens", type=int, default=8192)
    parser.add_argument(
        "--parallel-tool-calls", choices=("default", "true", "false"),
        default="default",
    )


def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("preflight")
    add_runtime(check)
    check.set_defaults(func=preflight)

    for command in ("smoke", "run"):
        runner = subparsers.add_parser(command)
        add_runtime(runner)
        runner.add_argument("--trials", type=int, default=1 if command == "smoke" else 10)
        runner.add_argument("--seed-start", type=int, default=0)
        runner.add_argument("--task-id", action="append")
        runner.add_argument("--out", required=True)
        runner.add_argument("--graded", required=True)
        runner.set_defaults(func=run)

    report = subparsers.add_parser("analyse")
    report.add_argument("--condition", choices=sorted(PROFILES), default="auto-standard")
    report.add_argument("--trials", type=int, default=10)
    report.add_argument("--out", required=True)
    report.add_argument("--graded", required=True)
    report.add_argument("--analysis", required=True)
    report.set_defaults(func=analyse)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
