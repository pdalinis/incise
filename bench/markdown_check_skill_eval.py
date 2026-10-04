#!/usr/bin/env python3
"""Run the preregistered explicit incise-check skill evaluation."""

from __future__ import annotations

import argparse
from collections import Counter
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "bench"
sys.path.insert(0, str(BENCH))

from incise_ops import check_document  # noqa: E402

TASKS_PATH = BENCH / "markdown_check_skill_tasks.json"
PI_WORKER = BENCH / "pi_trial.mjs"
PI_EXTENSION = ROOT / "plugins" / "pi" / "extension" / "index.ts"
PI_SDK = (
    ROOT / "plugins" / "pi" / "node_modules" / "@earendil-works"
    / "pi-coding-agent" / "dist" / "index.js"
)
PI_SKILL = ROOT / "plugins" / "pi" / "skills" / "incise-check"
HERMES_PLUGIN = ROOT / "plugins" / "hermes"
HERMES_SKILL = HERMES_PLUGIN / "skills" / "incise-check"
CANONICAL_SKILL = ROOT / "skills" / "incise-check" / "SKILL.md"

PREFIX = "markdown_check_skill_v1_20261003_v3"
RESULT_PREFIX = "PI_BENCH_RESULT="
SEED = 71
HOSTS = ("pi", "hermes")
CONDITIONS = ("control", "treatment")
PI_TOOLS = ["bash", "table_edit"]
MARKER = ".incise-markdown-check-skill-sandbox"
HOME_MARKER = ".incise-markdown-check-skill-home"
DEFAULT_SANDBOX = Path("/private/tmp/incise-markdown-check-skill-v1-v3")
DEFAULT_HERMES_HOME = Path("/private/tmp/incise-markdown-check-hermes-home-v1")
HARMFUL = "harmful"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(value) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return sha256_bytes(raw)


def git_output(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, text=True, capture_output=True, check=True,
    ).stdout.strip()


def load_tasks() -> list[dict]:
    value = json.loads(TASKS_PATH.read_text(encoding="utf-8"))
    if value.get("schema_version") != 1:
        raise SystemExit("unsupported task manifest schema")
    tasks = value.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != 13:
        raise SystemExit(f"expected 13 tasks, found {len(tasks or [])}")
    ids = [task.get("id") for task in tasks]
    if len(ids) != len(set(ids)):
        raise SystemExit("duplicate task IDs")
    return tasks


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


def reset_sandbox(root: Path, host: str, task: dict) -> tuple[Path, Path]:
    sandbox = ensure_marked_dir(root / host, MARKER)
    for child in sandbox.iterdir():
        if child.name == MARKER:
            continue
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()
    (sandbox / ".agent").mkdir()
    note = sandbox / "note.md"
    note.write_bytes(task["initial"].encode("utf-8"))
    return sandbox, note


def write_new_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")


def write_jsonl(handle, value: dict) -> None:
    handle.write(json.dumps(value, separators=(",", ":")) + "\n")
    handle.flush()


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


def normalized_hermes(events: list[dict]) -> tuple[list[dict], list[dict], dict]:
    calls, results, pending = [], [], []
    terminal = {}
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
                index = next(
                    (i for i, item in enumerate(pending) if item[0] == event.get("name")),
                    0,
                )
                _name, call_id = pending.pop(index) if pending else (
                    event.get("name", ""), f"orphan-{len(results)}",
                )
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


def ensure_hermes_home(path: Path, source: Path) -> Path:
    home = ensure_marked_dir(path, HOME_MARKER)
    os.chmod(home, 0o700)
    for name in ("config.yaml", ".env"):
        src = source / name
        dst = home / name
        if src.is_file() and not dst.exists():
            shutil.copyfile(src, dst)
            os.chmod(dst, 0o600)
    plugins = home / "plugins"
    plugins.mkdir(exist_ok=True)
    link = plugins / "incise"
    target = HERMES_PLUGIN.resolve()
    if link.is_symlink() and link.resolve() == target:
        return home
    if link.exists() or link.is_symlink():
        raise RuntimeError(f"unexpected benchmark plugin path: {link}")
    link.symlink_to(target, target_is_directory=True)
    return home


def run_process(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(command, text=True, capture_output=True, **kwargs)


def rust_report(binary: Path, note: Path) -> dict:
    process = run_process([str(binary), "check", str(note), "--json"], check=True)
    return json.loads(process.stdout)


def report_core(report: dict) -> dict:
    return {"status": report["status"], "findings": report["findings"]}


def operation_command(binary: Path, note: Path, finding: dict) -> list[str]:
    repair = finding.get("repair") or {}
    if repair.get("operation") != "table-realign":
        raise RuntimeError(f"unsupported evaluation repair: {repair!r}")
    table = (repair.get("arguments") or {}).get("table") or {}
    command = [
        str(binary), "table-realign", str(note), "--table", str(table["heading"]),
    ]
    if table.get("ordinal") not in (None, 0):
        command.extend(["--ordinal", str(table["ordinal"])])
    command.append("--json")
    return command


def ceiling(args) -> dict:
    binary = Path(args.binary).resolve()
    tasks = load_tasks()
    base = ensure_marked_dir(Path(args.sandbox).resolve(), MARKER)
    root = ensure_marked_dir(base / "ceiling", MARKER)
    rows = []
    for task in tasks:
        sandbox, note = reset_sandbox(root, task["id"], task)
        del sandbox
        initial = task["initial"].encode()
        report = rust_report(binary, note)
        oracle = check_document(task["initial"])
        if report_core(report) != {
            "status": oracle["status"], "findings": oracle["findings"],
        }:
            raise SystemExit(f"Rust/Python report disagreement for {task['id']}")
        codes = [finding["code"] for finding in report["findings"]]
        if codes != task["expected_codes"]:
            raise SystemExit(
                f"{task['id']}: expected codes {task['expected_codes']}, got {codes}"
            )
        if report["status"] != task["expected_status"]:
            raise SystemExit(
                f"{task['id']}: expected status {task['expected_status']}, "
                f"got {report['status']}"
            )

        fixed = run_process([
            str(binary), "check", str(note), "--fix-safe", "--if-match",
            report["hash"], "--json",
        ], check=True)
        fixed_report = json.loads(fixed.stdout)
        if note.read_bytes() != initial or fixed_report.get("changed"):
            raise SystemExit(f"{task['id']}: v1 safe fix was not a byte-identical no-op")

        concurrent = initial + b"concurrent byte\n"
        note.write_bytes(concurrent)
        stale = run_process([
            str(binary), "check", str(note), "--fix-safe", "--if-match",
            report["hash"], "--json",
        ])
        if stale.returncode != 3 or note.read_bytes() != concurrent:
            raise SystemExit(f"{task['id']}: stale-hash protection failed")
        note.write_bytes(initial)

        if task["authorize_realign"]:
            if len(report["findings"]) != 1:
                raise SystemExit(f"{task['id']}: authorized repair is not singular")
            process = run_process(operation_command(binary, note, report["findings"][0]))
            if process.returncode != 0:
                raise SystemExit(f"{task['id']}: repair failed: {process.stderr}")
            if note.read_bytes() != task["expected"].encode():
                raise SystemExit(f"{task['id']}: repair bytes differ from manifest")
            if rust_report(binary, note)["status"] != "clean":
                raise SystemExit(f"{task['id']}: repair did not recheck clean")
        elif task["initial"] != task["expected"]:
            raise SystemExit(f"{task['id']}: unauthorized task has changed expected bytes")

        rows.append({
            "task_id": task["id"],
            "status": report["status"],
            "codes": codes,
            "fix_safe_changed": fixed_report.get("changed"),
            "stale_guard": True,
            "authorized_repair": task["authorize_realign"],
        })
    return {"status": "pass", "tasks": rows}


def call_pi(args, sandbox: Path, task: dict, condition: str) -> dict:
    prompt = task["prompt"]
    if condition == "treatment":
        prompt = f"/skill:incise-check {prompt}"
    request = {
        "mode": "run",
        "cwd": str(sandbox),
        "agentDir": str(sandbox / ".agent"),
        "extension": str(PI_EXTENSION),
        "piSdk": str(PI_SDK),
        "endpoint": args.endpoint,
        "tools": PI_TOOLS,
        "skillPaths": [str(PI_SKILL)] if condition == "treatment" else [],
        "noSkills": condition != "treatment",
        "seed": SEED,
        "maxTurns": 4,
        "prompt": prompt,
        "recordActiveTools": True,
        "recordProviderRequests": True,
        "model": {"maxTokens": 4096},
    }
    env = {**os.environ, "INCISE_BIN": str(Path(args.binary).resolve())}
    process = subprocess.run(
        [args.node, str(PI_WORKER)], input=json.dumps(request), text=True,
        capture_output=True, timeout=args.timeout, env=env,
    )
    if process.returncode != 0:
        return {
            "error": process.stderr.strip() or f"Pi worker exited {process.returncode}",
            "tool_calls": [], "tool_results": [], "final_content": "",
            "elapsed_s": 0, "completion_tokens": 0, "n_turns": 0,
            "stdout": process.stdout, "stderr": process.stderr,
        }
    matches = [
        line[len(RESULT_PREFIX):] for line in process.stdout.splitlines()
        if line.startswith(RESULT_PREFIX)
    ]
    if len(matches) != 1:
        return {
            "error": f"Pi worker returned {len(matches)} result records",
            "tool_calls": [], "tool_results": [], "final_content": "",
            "elapsed_s": 0, "completion_tokens": 0, "n_turns": 0,
            "stdout": process.stdout, "stderr": process.stderr,
        }
    return json.loads(matches[0])


def call_hermes(args, sandbox: Path, task: dict, condition: str) -> dict:
    trace = sandbox / "hermes-trace.jsonl"
    command = [
        args.hermes, "chat", "--query-file", "-", "--oneshot",
        "--format", "stream-json", "--reasoning", "none",
        "--model", args.hermes_model, "--provider", args.hermes_provider,
        "--toolsets", "terminal,incise", "--max-turns", "4",
        "--run-budget", str(args.run_budget), "--in", str(sandbox),
        "--source", "tool",
    ]
    if condition == "treatment":
        command.extend(["--skills", "incise:incise-check"])
    env = {
        **os.environ,
        "HERMES_HOME": str(Path(args.hermes_home).resolve()),
        "INCISE_BIN": str(Path(args.binary).resolve()),
        "INCISE_PROFILE": "auto",
        "INCISE_MODEL_FAMILY": "gemma",
        "INCISE_HERMES_SEED": str(SEED),
        "INCISE_HERMES_MAX_TOKENS": "4096",
        "INCISE_HERMES_PARALLEL_TOOL_CALLS": "false",
        "INCISE_HERMES_TRACE": str(trace),
    }
    started = time.time()
    try:
        process = subprocess.run(
            command, input=task["prompt"], text=True, capture_output=True,
            timeout=args.timeout, env=env,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "error": f"TimeoutExpired: {exc}", "tool_calls": [],
            "tool_results": [], "final_content": "", "elapsed_s": args.timeout,
            "completion_tokens": 0, "input_tokens": 0, "n_turns": 0,
            "events": [], "provider_requests": [],
        }
    events = parse_json_lines(process.stdout)
    calls, results, terminal = normalized_hermes(events)
    traces = parse_json_lines(trace.read_text(encoding="utf-8") if trace.exists() else "")
    error = terminal.get("error")
    if process.returncode and not error:
        error = process.stderr.strip() or f"Hermes exited {process.returncode}"
    return {
        "error": str(error) if error else None,
        "elapsed_s": round(time.time() - started, 3),
        "events": events,
        "tool_calls": calls,
        "tool_results": results,
        "final_content": terminal.get("text", ""),
        "completion_tokens": (terminal.get("tokens") or {}).get("output", 0),
        "input_tokens": (terminal.get("tokens") or {}).get("input", 0),
        "n_turns": len([row for row in traces if row.get("event") == "request"]),
        "provider_requests": [row for row in traces if row.get("event") == "request"],
        "stderr": process.stderr,
        "exit_code": process.returncode,
    }


def call_text(row: dict) -> str:
    return "\n".join(
        f"{call.get('function', {}).get('name', '')} "
        f"{call.get('function', {}).get('arguments', '')}"
        for call in row.get("tool_calls", [])
    )


def result_text(row: dict) -> str:
    return "\n".join(str(result.get("content") or "") for result in row.get("tool_results", []))


def grade(task: dict, row: dict, before: bytes, after: bytes) -> dict:
    calls = call_text(row)
    results = result_text(row)
    expected = task["expected"].encode()
    checker_markers = ("check.mjs", "check.py", "incise check", "incise\",\"check")
    checker_uses = sum(calls.count(marker) for marker in checker_markers)
    observed_codes = [code for code in task["expected_codes"] if code in results]
    clean_seen = bool(re.search(r'["\']status["\']\s*:\s*["\']clean["\']', results))
    realign_semantic = (
        "table-realign" in calls
        or bool(re.search(r'"action"\s*:\s*"realign"', calls))
    )
    tool_names = [call.get("function", {}).get("name", "") for call in row.get("tool_calls", [])]
    raw_tool = any(name in {"edit", "write", "apply_patch", "write_file"} for name in tool_names)
    ad_hoc = bool(re.search(
        r"\b(sed|perl|ruby)\b|python(?:3)?\s+-c|(?:>|>>)\s*[^\n]*note\.md",
        calls,
    ))
    forbidden_mutator = any(
        name in {"table_edit", "frontmatter_edit", "section_edit", "list_edit"}
        for name in tool_names
    ) and not task["authorize_realign"]
    exact = after == expected
    treatment = row["condition"] == "treatment"
    report_seen = (
        len(observed_codes) == len(task["expected_codes"])
        if task["expected_codes"] else clean_seen
    )
    rechecked = checker_uses >= 2 if task["authorize_realign"] else True
    harmful = not exact
    workflow_ok = (
        (not treatment)
        or (
            checker_uses >= 1
            and report_seen
            and not raw_tool
            and not ad_hoc
            and not forbidden_mutator
            and (not task["authorize_realign"] or (realign_semantic and rechecked))
        )
    )
    return {
        "host": row["host"],
        "condition": row["condition"],
        "task_id": task["id"],
        "seed": row["seed"],
        "attempt": row["attempt"],
        "outcome": HARMFUL if harmful else ("pass" if workflow_ok else "workflow-fail"),
        "exact_final_bytes": exact,
        "initial_sha256": sha256_bytes(before),
        "expected_sha256": sha256_bytes(expected),
        "final_sha256": sha256_bytes(after),
        "changed": before != after,
        "checker_uses": checker_uses,
        "report_seen": report_seen,
        "expected_codes": task["expected_codes"],
        "observed_codes": observed_codes,
        "clean_seen": clean_seen,
        "realign_semantic": realign_semantic,
        "rechecked": rechecked,
        "raw_tool": raw_tool,
        "ad_hoc_text_rewrite": ad_hoc,
        "forbidden_mutator": forbidden_mutator,
        "error": row.get("error"),
    }


def is_transport(row: dict) -> bool:
    error = str(row.get("error") or "").lower()
    return bool(error) and any(word in error for word in (
        "timeout", "connection", "transport", "reset", "empty response",
    ))


def run_trials(args) -> None:
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    if manifest.get("ceiling", {}).get("status") != "pass":
        raise SystemExit("manifest does not contain a passing deterministic ceiling")
    tasks = load_tasks()
    raw_path, graded_path = Path(args.out), Path(args.graded)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    if raw_path.exists() or graded_path.exists():
        raise SystemExit("refusing to overwrite an existing raw or graded pool")
    root = ensure_marked_dir(Path(args.sandbox), MARKER)
    total = len(tasks) * len(HOSTS) * len(CONDITIONS)
    index = 0
    with raw_path.open("x", encoding="utf-8", newline="\n") as raw_handle, \
            graded_path.open("x", encoding="utf-8", newline="\n") as graded_handle:
        for host in HOSTS:
            for condition in CONDITIONS:
                for task in tasks:
                    index += 1
                    final_row = final_grade = None
                    for attempt in (1, 2):
                        require_idle_endpoint(args.endpoint, f"before {host}/{condition}/{task['id']}")
                        sandbox, note = reset_sandbox(root, host, task)
                        before = note.read_bytes()
                        result = (
                            call_pi(args, sandbox, task, condition)
                            if host == "pi"
                            else call_hermes(args, sandbox, task, condition)
                        )
                        after = note.read_bytes()
                        row = {
                            **result,
                            "host": host,
                            "condition": condition,
                            "task_id": task["id"],
                            "seed": SEED,
                            "attempt": attempt,
                            "prompt": task["prompt"],
                            "initial_document": task["initial"],
                            "final_document": after.decode("utf-8"),
                        }
                        graded = grade(task, row, before, after)
                        write_jsonl(raw_handle, row)
                        write_jsonl(graded_handle, graded)
                        final_row, final_grade = row, graded
                        if not is_transport(row):
                            break
                    print(
                        f"[{index:02d}/{total}] {host:6s} {condition:9s} "
                        f"{task['id']:34s} {final_grade['outcome']} "
                        f"{final_row.get('elapsed_s', 0):.1f}s",
                        flush=True,
                    )
                    if condition == "treatment" and final_grade["outcome"] == HARMFUL:
                        raise SystemExit(
                            f"harmful treatment stopped run: {host}/{task['id']}"
                        )


def latest_rows(path: Path) -> dict[tuple[str, str, str, int], dict]:
    rows = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            key = (row["host"], row["condition"], row["task_id"], row["seed"])
            rows[key] = row
    return rows


def analyse(args) -> None:
    raw_path, graded_path = Path(args.out), Path(args.graded)
    raw = latest_rows(raw_path)
    graded = latest_rows(graded_path)
    keys = sorted(set(raw) & set(graded))
    treatment = [key for key in keys if key[1] == "treatment"]
    control = [key for key in keys if key[1] == "control"]
    treatment_failures = [
        [*key, graded[key]["outcome"]]
        for key in treatment if graded[key]["outcome"] != "pass" or raw[key].get("error")
    ]
    gate = len(treatment) == 26 and not treatment_failures

    def summarize(selected):
        outcomes = Counter(graded[key]["outcome"] for key in selected)
        return {
            "n": len(selected),
            "outcomes": dict(sorted(outcomes.items())),
            "checker_use": sum(graded[key]["checker_uses"] > 0 for key in selected),
            "changed": sum(graded[key]["changed"] for key in selected),
            "mean_turns": round(
                sum(raw[key].get("n_turns") or 0 for key in selected) / len(selected), 3,
            ) if selected else 0,
            "mean_completion_tokens": round(
                sum(raw[key].get("completion_tokens") or 0 for key in selected)
                / len(selected), 3,
            ) if selected else 0,
            "mean_elapsed_s": round(
                sum(raw[key].get("elapsed_s") or 0 for key in selected) / len(selected), 3,
            ) if selected else 0,
        }

    report = {
        "status": "pass" if gate else "fail",
        "expected_treatment_trials": 26,
        "observed_pairs": len(keys),
        "treatment_failures": treatment_failures,
        "by_condition": {
            "control": summarize(control),
            "treatment": summarize(treatment),
        },
        "by_host": {
            host: {
                condition: summarize([
                    key for key in keys if key[0] == host and key[1] == condition
                ])
                for condition in CONDITIONS
            }
            for host in HOSTS
        },
        "artifacts": {
            "raw": str(raw_path.relative_to(ROOT)),
            "raw_sha256": sha256_file(raw_path),
            "graded": str(graded_path.relative_to(ROOT)),
            "graded_sha256": sha256_file(graded_path),
        },
        "gate": {
            "all_treatment_complete": len(treatment) == 26,
            "zero_treatment_harm": not any(
                graded[key]["outcome"] == HARMFUL for key in treatment
            ),
            "all_treatment_workflows_pass": not treatment_failures,
        },
    }
    write_new_json(Path(args.analysis), report)
    print(json.dumps(report, indent=2, sort_keys=True))


def endpoint_json(endpoint: str, route: str) -> dict:
    url = endpoint.rstrip("/") + route
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.load(response)


def require_idle_endpoint(endpoint: str, context: str) -> list[dict]:
    slots = endpoint_json(endpoint, "/slots")
    active = [slot for slot in slots if slot.get("is_processing")]
    if active:
        summary = [
            {
                "id": slot.get("id"),
                "id_task": slot.get("id_task"),
                "seed": (slot.get("params") or {}).get("seed"),
                "max_tokens": (slot.get("params") or {}).get("max_tokens"),
            }
            for slot in active
        ]
        raise SystemExit(f"model endpoint is busy {context}: {summary}")
    return slots


def host_version(command: list[str]) -> str:
    return subprocess.run(command, text=True, capture_output=True, check=True).stdout.strip()


def preflight(args) -> None:
    dirty = git_output("status", "--porcelain")
    if dirty:
        raise SystemExit("preflight requires a clean preregistered worktree")
    slots = require_idle_endpoint(args.endpoint, "at preflight")
    ensure_hermes_home(Path(args.hermes_home), Path(args.source_hermes_home).expanduser())
    binary = Path(args.binary).resolve()
    ceiling_report = ceiling(args)
    skill_hashes = {
        str(path.relative_to(ROOT)): sha256_file(path)
        for path in (
            CANONICAL_SKILL,
            PI_SKILL / "SKILL.md",
            HERMES_SKILL / "SKILL.md",
        )
    }
    if len(set(skill_hashes.values())) != 1:
        raise SystemExit("host skill instructions differ from the canonical skill")
    pi_version = json.loads(
        (PI_SDK.parent.parent / "package.json").read_text(encoding="utf-8")
    )["version"]
    hermes_version = host_version([args.hermes, "--version"])
    binary_version = host_version([str(binary), "--version"])
    props = endpoint_json(args.endpoint, "/props")
    models = endpoint_json(args.endpoint, "/v1/models")
    model_path = Path(props.get("model_path", "")).expanduser()
    manifest = {
        "status": "preflight-pass",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "preregistration": {
            "issue": "https://github.com/pdalinis/incise/issues/50",
            "plan": "bench/MARKDOWN_CHECK_SKILL_EVAL_PLAN.md",
            "source_feature_commit": "615fb1a",
            "executor_commit": git_output("rev-parse", "HEAD"),
        },
        "source": {"describe": git_output("describe", "--always", "--dirty")},
        "tasks": {
            "path": str(TASKS_PATH.relative_to(ROOT)),
            "sha256": sha256_file(TASKS_PATH),
            "count": len(load_tasks()),
            "seed": SEED,
        },
        "binary": {
            "path": str(binary), "version": binary_version,
            "sha256": sha256_file(binary),
        },
        "skills": skill_hashes,
        "hosts": {
            "pi": {"version": pi_version, "sdk": str(PI_SDK)},
            "hermes": {"version": hermes_version},
        },
        "model": {
            "endpoint": args.endpoint,
            "models": models,
            "props": props,
            "model_sha256": sha256_file(model_path) if model_path.is_file() else None,
            "idle_slots": slots,
        },
        "conditions": {
            "control": {"pi_tools": PI_TOOLS, "hermes_toolsets": ["terminal", "incise"]},
            "treatment": {
                "pi_command": "/skill:incise-check",
                "hermes_command": "--skills incise:incise-check",
            },
        },
        "ceiling": ceiling_report,
    }
    write_new_json(Path(args.manifest), manifest)
    print(json.dumps(manifest, indent=2, sort_keys=True))


def add_runtime(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--binary", default=str(ROOT / "target" / "debug" / "incise"))
    parser.add_argument("--endpoint", default="http://127.0.0.1:8081")
    parser.add_argument("--node", default="node")
    parser.add_argument("--hermes", default="hermes")
    parser.add_argument("--hermes-home", default=str(DEFAULT_HERMES_HOME))
    parser.add_argument("--source-hermes-home", default="~/.hermes")
    parser.add_argument("--hermes-provider", default="custom")
    parser.add_argument("--hermes-model", default="gemma4-no-thinking")
    parser.add_argument("--sandbox", default=str(DEFAULT_SANDBOX))
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--run-budget", type=int, default=240)


def main() -> None:
    results = BENCH / "results"
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    ceiling_parser = sub.add_parser("ceiling")
    add_runtime(ceiling_parser)
    ceiling_parser.set_defaults(func=lambda args: print(json.dumps(ceiling(args), indent=2)))

    preflight_parser = sub.add_parser("preflight")
    add_runtime(preflight_parser)
    preflight_parser.add_argument(
        "--manifest", default=str(results / f"{PREFIX}_manifest.json"),
    )
    preflight_parser.set_defaults(func=preflight)

    run_parser = sub.add_parser("run")
    add_runtime(run_parser)
    run_parser.add_argument(
        "--manifest", default=str(results / f"{PREFIX}_manifest.json"),
    )
    run_parser.add_argument("--out", default=str(results / f"{PREFIX}_raw.jsonl"))
    run_parser.add_argument("--graded", default=str(results / f"{PREFIX}_graded.jsonl"))
    run_parser.set_defaults(func=run_trials)

    analysis_parser = sub.add_parser("analyse")
    analysis_parser.add_argument("--out", default=str(results / f"{PREFIX}_raw.jsonl"))
    analysis_parser.add_argument("--graded", default=str(results / f"{PREFIX}_graded.jsonl"))
    analysis_parser.add_argument(
        "--analysis", default=str(results / f"{PREFIX}_analysis.json"),
    )
    analysis_parser.set_defaults(func=analyse)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
