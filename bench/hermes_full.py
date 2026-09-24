#!/usr/bin/env python3
"""Run and analyse the preregistered Incise composition through Hermes.

This harness drives the installed ``hermes chat`` loop and records its public
stream-JSON protocol plus Incise's metadata-only request-routing trace.  It
uses the frozen 48-task population and the same mechanical grader as the Pi
composition runs.
"""

from __future__ import annotations

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

import pi_composition as composition  # noqa: E402
from grade import check_result  # noqa: E402


STANDARD_TOOLS = [
    "table_edit", "list_edit", "section_edit", "frontmatter_edit",
    "table_get", "md_tables", "md_lists", "md_outline",
]
HARMFUL = {"wrong", "destructive", "collateral:content", "collateral:formatting"}
ROUTED_TABLE_TASKS = {
    "get-filter-one-column", "get-filter-two-columns",
    "get-filter-no-match", "get-escaped-cell",
}
PROFILES = {
    "route-smoke": ("auto", "ornith"),
    "ornith-standard": ("auto", "unknown"),
    "ornith-auto": ("auto", "ornith"),
    "gemma-auto": ("auto", "gemma"),
}
MARKER = ".incise-hermes-full-sandbox"
HOME_MARKER = ".incise-hermes-benchmark-home"
DEFAULT_SANDBOX = Path("/private/tmp/incise-hermes-full-20260924")
DEFAULT_HERMES_HOME = Path("/private/tmp/incise-hermes-home-20260924")
DEFAULT_ROUTES = BENCH / "results" / "hermes_safe_routed_parity_20260924.json"


def read_text(path: Path) -> str:
    with path.open(encoding="utf-8", newline="") as handle:
        return handle.read()


def ensure_marked_dir(path: Path, marker_name: str) -> Path:
    path = path.resolve()
    if path in (Path("/"), Path.home()):
        raise RuntimeError(f"unsafe benchmark directory: {path}")
    marker = path / marker_name
    if path.exists() and not marker.exists():
        raise RuntimeError(f"refusing unmarked benchmark directory: {path}")
    path.mkdir(parents=True, exist_ok=True)
    marker.touch(exist_ok=True)
    return path


def ensure_hermes_home(path: Path, source_home: Path) -> Path:
    path = ensure_marked_dir(path, HOME_MARKER)
    os.chmod(path, 0o700)
    for name in ("config.yaml", ".env"):
        source = source_home / name
        destination = path / name
        if source.is_file() and not destination.exists():
            shutil.copyfile(source, destination)
            os.chmod(destination, 0o600)
    plugins = path / "plugins"
    plugins.mkdir(exist_ok=True)
    link = plugins / "incise"
    target = (ROOT / "plugins" / "hermes").resolve()
    if link.is_symlink() and link.resolve() == target:
        return path
    if link.exists() or link.is_symlink():
        raise RuntimeError(f"unexpected Incise plugin entry in benchmark home: {link}")
    link.symlink_to(target, target_is_directory=True)
    return path


def reset_sandbox(path: Path, task: dict | None = None) -> Path:
    path = ensure_marked_dir(path, MARKER)
    for child in path.iterdir():
        if child.name == MARKER:
            continue
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()
    if task:
        source = ROOT / task["fixture"]
        destination = path / task["fixture"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    return path


def load_tasks() -> dict[str, dict]:
    return {task["id"]: task for task in composition.load_tasks()}


def route_expectations(path: Path) -> dict[str, dict]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("status") != "pass" or len(value.get("routes", [])) != 48:
        raise RuntimeError(f"route parity artifact is not a passing 48-task audit: {path}")
    return {row["task_id"]: row for row in value["routes"]}


def parse_json_lines(text: str) -> list[dict]:
    rows = []
    for line in text.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def normalized_events(events: list[dict]) -> tuple[list[dict], list[dict], dict]:
    calls: list[dict] = []
    results: list[dict] = []
    pending: list[tuple[str, str]] = []
    terminal: dict = {}
    for event in events:
        if event.get("type") == "tool_use":
            call_id = str(event.get("tool_call_id") or f"hermes-{len(calls)}")
            name = str(event.get("name") or "")
            arguments = event.get("input") if isinstance(event.get("input"), dict) else {}
            calls.append({
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments, separators=(",", ":"))},
            })
            pending.append((name, call_id))
        elif event.get("type") == "tool_result":
            call_id = event.get("tool_call_id")
            if not call_id:
                index = next((i for i, item in enumerate(pending) if item[0] == event.get("name")), 0)
                _name, call_id = pending.pop(index) if pending else (event.get("name", ""), f"orphan-{len(results)}")
            raw = str(event.get("output") or "")
            try:
                details = json.loads(raw)
            except json.JSONDecodeError:
                details = {}
            results.append({
                "tool_call_id": str(call_id),
                "name": str(event.get("name") or ""),
                "is_error": bool(event.get("is_error")),
                "content": raw,
                "details": details if isinstance(details, dict) else {},
            })
        elif event.get("type") == "result":
            terminal = event
    return calls, results, terminal


def successful_result(row: dict, name: str):
    results = {result["tool_call_id"]: result for result in row.get("tool_results", [])}
    for call in row.get("tool_calls", []):
        if call.get("function", {}).get("name") != name:
            continue
        result = results.get(call.get("id"))
        if result is not None and not result.get("is_error"):
            return call, result
    return None, None


def grade_row(task: dict, row: dict, before: str, after: str):
    if task["id"] not in ROUTED_TABLE_TASKS:
        return composition.grade_actual(task, row, before, after)
    call, result = successful_result(row, "table_query")
    if call is None:
        return composition.grade_actual(task, row, before, after)
    if row.get("error"):
        return ("transport" if composition.is_transport(row["error"]) else "malformed", row["error"])
    return check_result(task, before, after, (result.get("details") or {}).get("rows"))


def request_environment(args, *, condition: str, seed: int, trace: Path) -> dict[str, str]:
    profile, family = PROFILES[condition]
    env = os.environ.copy()
    env.update({
        "HERMES_HOME": str(Path(args.hermes_home).resolve()),
        "INCISE_BIN": str(Path(args.binary).resolve()),
        "INCISE_PROFILE": profile,
        "INCISE_MODEL_FAMILY": family,
        "INCISE_HERMES_SEED": str(seed),
        "INCISE_HERMES_TRACE": str(trace),
    })
    if condition == "gemma-auto":
        env["INCISE_HERMES_MAX_TOKENS"] = str(args.gemma_max_tokens)
        env.pop("INCISE_HERMES_PARALLEL_TOOL_CALLS", None)
    else:
        env["INCISE_HERMES_MAX_TOKENS"] = str(args.max_tokens)
        env["INCISE_HERMES_PARALLEL_TOOL_CALLS"] = "false"
    return env


def invoke_hermes(args, prompt: str, condition: str, seed: int, trace: Path):
    command = [
        args.hermes, "chat", "--query-file", "-", "--oneshot",
        "--format", "stream-json", "--reasoning", "none",
        "--model", args.model_alias, "--provider", args.provider,
        "--toolsets", "incise", "--max-turns", "4",
        "--run-budget", str(args.run_budget), "--in", str(Path(args.sandbox).resolve()),
        "--ignore-rules", "--source", "tool",
    ]
    started = time.time()
    process = subprocess.run(
        command, input=prompt, text=True, capture_output=True,
        timeout=args.timeout,
        env=request_environment(args, condition=condition, seed=seed, trace=trace),
    )
    elapsed = time.time() - started
    events = parse_json_lines(process.stdout)
    calls, results, terminal = normalized_events(events)
    traces = parse_json_lines(trace.read_text(encoding="utf-8") if trace.exists() else "")
    error = terminal.get("error")
    if process.returncode and not error:
        if "didn't produce a reply" in str(terminal.get("text") or ""):
            error = "ordinary empty response after Hermes retries"
        else:
            error = process.stderr.strip() or f"hermes exited {process.returncode}"
    return {
        "elapsed_s": round(elapsed, 3),
        "events": events,
        "tool_calls": calls,
        "tool_results": results,
        "final_content": terminal.get("text", ""),
        "completion_tokens": (terminal.get("tokens") or {}).get("output", 0),
        "input_tokens": (terminal.get("tokens") or {}).get("input", 0),
        "n_turns": len([row for row in traces if row.get("event") == "request"]),
        "provider_requests": [row for row in traces if row.get("event") == "request"],
        "route_plans": [row for row in traces if row.get("event") == "plan"],
        "stderr": process.stderr,
        "exit_code": process.returncode,
        "error": str(error) if error else None,
    }


def framing_errors(row: dict, expected: dict, condition: str) -> list[str]:
    errors: list[str] = []
    requests = row.get("provider_requests") or []
    plans = row.get("route_plans") or []
    if not requests:
        return ["no provider request trace"]
    for request in requests:
        if request.get("max_tokens") != row["max_tokens"]:
            errors.append(f"max_tokens={request.get('max_tokens')!r}")
        if request.get("parallel_tool_calls") != row["parallel_tool_calls"]:
            errors.append(f"parallel_tool_calls={request.get('parallel_tool_calls')!r}")
        if request.get("seed") != row["seed"]:
            errors.append(f"seed={request.get('seed')!r}")
    first_tools = requests[0].get("tools")
    wanted = expected["expected"] if condition != "ornith-standard" else "standard"
    if wanted == "standard":
        if first_tools != sorted(STANDARD_TOOLS):
            errors.append(f"fallback tools={first_tools!r}")
        if plans and plans[0].get("route") is not None:
            errors.append(f"unexpected plan={plans[0].get('route')!r}")
    else:
        if first_tools != [wanted]:
            errors.append(f"routed tools={first_tools!r}, expected={[wanted]!r}")
        if not plans or plans[0].get("route_tool") != wanted:
            errors.append(f"route plan={plans[0].get('route_tool') if plans else None!r}")
        calls = [call for call in row.get("tool_calls", []) if call.get("function", {}).get("name") == wanted]
        if len(calls) != 1:
            errors.append(f"expected one {wanted} call, got {len(calls)}")
        successful = [
            result for result in row.get("tool_results", [])
            if result.get("name") == wanted and not result.get("is_error")
        ]
        if successful:
            details = successful[0].get("details") or {}
            if details.get("route") != expected.get("kind"):
                errors.append(f"route kind={details.get('route')!r}")
            if details.get("resolvedArguments") != expected.get("resolved"):
                errors.append("resolved arguments differ from deterministic parity artifact")
        if len(requests) > 1 and any(
            tool in STANDARD_TOOLS or tool == wanted
            for tool in (requests[1].get("tools") or [])
        ):
            errors.append(f"Incise tools survived routed success: {requests[1].get('tools')!r}")
    return errors


def run_one(args, task: dict, seed: int, attempt: int, expected: dict):
    sandbox = reset_sandbox(Path(args.sandbox), task)
    fixture = sandbox / task["fixture"]
    before = read_text(ROOT / task["fixture"])
    prompt = composition.prompt_for(task, before)
    trace = sandbox / f"trace-{task['id']}-{seed}-{attempt}.jsonl"
    try:
        result = invoke_hermes(args, prompt, args.condition, seed, trace)
    except subprocess.TimeoutExpired as exc:
        result = {
            "elapsed_s": args.timeout, "events": [], "tool_calls": [],
            "tool_results": [], "final_content": "", "completion_tokens": 0,
            "input_tokens": 0, "n_turns": 0, "provider_requests": [],
            "route_plans": [], "stderr": "", "exit_code": None,
            "error": f"TimeoutExpired: {exc}",
        }
    after = read_text(fixture)
    row = {
        **result,
        "condition": args.condition,
        "profile": PROFILES[args.condition][0],
        "model_family": PROFILES[args.condition][1],
        "model_alias": args.model_alias,
        "backend_model": args.backend_model,
        "task_id": task["id"],
        "task_file": task["_task_file"],
        "family": composition.task_family(task),
        "trial": seed,
        "seed": seed,
        "attempt": attempt,
        "max_turns": 4,
        "max_tokens": args.gemma_max_tokens if args.condition == "gemma-auto" else args.max_tokens,
        "reasoning": "none",
        "parallel_tool_calls": None if args.condition == "gemma-auto" else False,
        "initial_sha256": composition.sha256_bytes(before.encode()),
        "final_sha256": composition.sha256_bytes(after.encode()),
        "final_document": after,
    }
    outcome, detail = grade_row(task, row, before, after)
    document_outcome = document_detail = None
    if after != before:
        document_outcome, document_detail = check_result(task, before, after)
    frame = framing_errors(row, expected, args.condition) if not row.get("error") else []
    row["framing_errors"] = frame
    graded = {
        "condition": args.condition,
        "task_id": task["id"],
        "family": composition.task_family(task),
        "trial": seed,
        "attempt": attempt,
        "outcome": outcome,
        "detail": detail,
        "document_outcome": document_outcome,
        "document_detail": document_detail,
        "framing_errors": frame,
    }
    return row, graded


def write_jsonl(handle, value: dict) -> None:
    handle.write(json.dumps(value, separators=(",", ":")) + "\n")
    handle.flush()


def latest_rows(path: Path) -> dict[tuple[str, int], dict]:
    rows = {}
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            rows[(row["task_id"], row["trial"])] = row
    return rows


def all_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def retryable(row: dict, graded: dict) -> bool:
    return graded.get("outcome") == "transport" or row.get("error") == "ordinary empty response after Hermes retries"


def run(args) -> None:
    tasks = load_tasks()
    if args.task_id:
        unknown = sorted(set(args.task_id) - set(tasks))
        if unknown:
            raise SystemExit(f"unknown task IDs: {', '.join(unknown)}")
        tasks = {name: task for name, task in tasks.items() if name in set(args.task_id)}
    expected = route_expectations(Path(args.routes))
    raw_path, graded_path = Path(args.out), Path(args.graded)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    graded_path.parent.mkdir(parents=True, exist_ok=True)
    completed = latest_rows(raw_path)
    prior_rows = all_rows(raw_path)
    prior_attempts = Counter((row["task_id"], row["trial"]) for row in prior_rows)
    work = [
        (task, seed)
        for task in tasks.values()
        for seed in range(args.seed_start, args.seed_start + args.trials)
        if (
            (task["id"], seed) not in completed
            or (
                completed[(task["id"], seed)].get("error")
                and prior_attempts[(task["id"], seed)] < 2
            )
        )
    ]
    print(f"{len(work)} Hermes trials, condition={args.condition}", flush=True)
    started = time.time()
    with raw_path.open("a", encoding="utf-8", newline="\n") as raw_handle, \
            graded_path.open("a", encoding="utf-8", newline="\n") as graded_handle:
        for index, (task, seed) in enumerate(work, 1):
            first_attempt = prior_attempts[(task["id"], seed)] + 1
            for attempt in range(first_attempt, 3):
                row, graded = run_one(args, task, seed, attempt, expected[task["id"]])
                write_jsonl(raw_handle, row)
                write_jsonl(graded_handle, graded)
                if not retryable(row, graded):
                    break
            harmful = (
                graded["outcome"] in HARMFUL
                or graded.get("document_outcome") in HARMFUL
            )
            eta = (time.time() - started) / index * (len(work) - index) / 60
            print(
                f"[{index:3d}/{len(work)}] {task['id']:27s} s{seed:<2d} "
                f"{row['elapsed_s']:6.1f}s {graded['outcome']:18s} eta {eta:.0f}m",
                flush=True,
            )
            if harmful and args.condition in ("route-smoke", "ornith-auto", "gemma-auto"):
                raise SystemExit(f"harmful treatment result; stopped at {task['id']} seed {seed}")


def count_outcomes(rows) -> dict[str, int]:
    return dict(sorted(Counter(row["outcome"] for row in rows).items()))


def analyse(args) -> None:
    raw = latest_rows(Path(args.out))
    graded = latest_rows(Path(args.graded))
    keys = sorted(set(raw) & set(graded))
    usable = [key for key in keys if graded[key]["outcome"] != "transport"]
    correct = sum(graded[key]["outcome"] == "correct" for key in usable)
    harmful = [
        key for key in usable
        if graded[key]["outcome"] in HARMFUL or graded[key].get("document_outcome") in HARMFUL
    ]
    expected_routes = route_expectations(Path(args.routes))
    framing = []
    for key in usable:
        errors = framing_errors(raw[key], expected_routes[key[0]], args.condition)
        if errors:
            framing.append([*key, *errors])
    multiple = []
    for key in usable:
        changed = sum(
            not result.get("is_error") and bool((result.get("details") or {}).get("changed"))
            for result in raw[key].get("tool_results", [])
        )
        if changed > len(composition.ideal_calls(load_tasks()[key[0]])):
            multiple.append([*key, changed])
    expected_n = args.trials * 48
    treatment = args.condition in ("route-smoke", "ornith-auto", "gemma-auto")
    minimum = 475 if args.trials == 10 and treatment else 0
    gate = len(usable) == expected_n and correct >= minimum and not harmful and not framing and not multiple
    families = {}
    for family in ("table", "list", "section", "frontmatter", "table-read"):
        family_keys = [key for key in usable if graded[key]["family"] == family]
        family_correct = sum(graded[key]["outcome"] == "correct" for key in family_keys)
        families[family] = {
            "n": len(family_keys), "correct": family_correct,
            "rate": round(family_correct / len(family_keys), 6) if family_keys else 0,
            "outcomes": count_outcomes(graded[key] for key in family_keys),
        }
    report = {
        "status": "pass" if gate else "fail",
        "condition": args.condition,
        "expected": expected_n,
        "observed": len(keys),
        "usable": len(usable),
        "correct": correct,
        "correct_rate": round(correct / len(usable), 6) if usable else 0,
        "outcomes": count_outcomes(graded[key] for key in usable),
        "families": families,
        "harmful": len(harmful),
        "harmful_trials": [list(key) for key in harmful],
        "framing_errors": framing,
        "multiple_mutations": multiple,
        "efficiency": {
            "mean_elapsed_s": round(sum(raw[key].get("elapsed_s") or 0 for key in usable) / len(usable), 3) if usable else 0,
            "mean_completion_tokens": round(sum(raw[key].get("completion_tokens") or 0 for key in usable) / len(usable), 3) if usable else 0,
            "mean_tool_calls": round(sum(len(raw[key].get("tool_calls") or []) for key in usable) / len(usable), 3) if usable else 0,
        },
        "gate": {"minimum_correct": minimum, "zero_harm": True, "exact_provider_surface": True},
    }
    composition.write_new_json(args.analysis, report)
    print(json.dumps(report, indent=2, sort_keys=True))


def preflight(args) -> None:
    ensure_hermes_home(Path(args.hermes_home), Path(args.source_hermes_home).expanduser())
    sandbox = ensure_marked_dir(Path(args.sandbox), MARKER)
    subprocess.run([args.binary, "--version"], check=True)
    version = subprocess.run([args.hermes, "--version"], text=True, capture_output=True, check=True).stdout.strip()
    if "0.21.3" not in version:
        raise SystemExit(f"expected Hermes 0.21.3, got {version!r}")
    parity_check = sandbox / "hermes-safe-routed-parity-preflight.json"
    subprocess.run(
        [sys.executable, str(BENCH / "hermes_safe_routed_parity.py"), "--out", str(parity_check)],
        check=True,
        env={**os.environ, "INCISE_BIN": str(Path(args.binary).resolve())},
    )
    route_expectations(parity_check)
    route_expectations(Path(args.routes))
    print(f"Hermes preflight passed ({version})")


def add_runtime(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--condition", choices=sorted(PROFILES), default="route-smoke")
    parser.add_argument("--binary", default=str(ROOT / "target" / "debug" / "incise"))
    parser.add_argument("--hermes", default="hermes")
    parser.add_argument("--hermes-home", default=str(DEFAULT_HERMES_HOME))
    parser.add_argument("--source-hermes-home", default="~/.hermes")
    parser.add_argument("--sandbox", default=str(DEFAULT_SANDBOX))
    parser.add_argument("--routes", default=str(DEFAULT_ROUTES))
    parser.add_argument("--model-alias", default="claude-opus-5.5")
    parser.add_argument("--backend-model", default="ornith-1.5-9b-q8")
    parser.add_argument("--provider", default="custom")
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--gemma-max-tokens", type=int, default=8192)
    parser.add_argument("--run-budget", type=int, default=240)
    parser.add_argument("--timeout", type=int, default=300)


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    check = subparsers.add_parser("preflight")
    add_runtime(check)
    check.set_defaults(func=preflight)
    runner = subparsers.add_parser("run")
    add_runtime(runner)
    runner.add_argument("--trials", type=int, default=1)
    runner.add_argument("--seed-start", type=int, default=40)
    runner.add_argument("--task-id", action="append")
    runner.add_argument("--out", required=True)
    runner.add_argument("--graded", required=True)
    runner.set_defaults(func=run)
    report = subparsers.add_parser("analyse")
    report.add_argument("--condition", choices=sorted(PROFILES), required=True)
    report.add_argument("--trials", type=int, required=True)
    report.add_argument("--out", required=True)
    report.add_argument("--graded", required=True)
    report.add_argument("--analysis", required=True)
    report.add_argument("--routes", default=str(DEFAULT_ROUTES))
    report.set_defaults(func=analyse)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
