#!/usr/bin/env python3
"""MiniCPM two-phase structural-plan and required-content section arm."""

import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bench"))

import armb  # noqa: E402
import minicpm_section_slots as slots  # noqa: E402
from incise_ops import apply_op, resolve_section, section_outline  # noqa: E402
from runner import call, record  # noqa: E402


SCHEME = "minicpm_section_pipeline"
POSITIONS = ("before", "after", "first-child", "last-child")
TASK_SOURCE = os.path.join(ROOT, "bench", "tasks", "sections.json")


def sha256_bytes(value):
    return hashlib.sha256(value).hexdigest()


def sha256_file(path):
    with open(path, "rb") as fh:
        return sha256_bytes(fh.read())


def canonical_hash(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return sha256_bytes(raw)


def anchor_options(content):
    """Return each section's shortest unique, exact semantic address."""
    paths = [entry["path"] for entry in section_outline(content)]
    segmented = [[part.strip() for part in path.split(">")]
                 for path in paths]
    anchors = []
    for parts in segmented:
        chosen = None
        for width in range(1, len(parts) + 1):
            suffix = parts[-width:]
            matches = sum(
                len(other) >= width and other[-width:] == suffix
                for other in segmented
            )
            if matches == 1:
                chosen = " > ".join(suffix)
                break
        if chosen is not None:
            anchors.append(chosen)
    return anchors


def plan_schema(content):
    anchors = anchor_options(content)
    if not anchors:
        raise RuntimeError("fixture has no addressable sections")
    return {
        "name": "section_insert_plan",
        "description": (
            "Choose the structure for one requested section insertion. Copy "
            "one exact existing anchor. 'Immediately above' means before the "
            "named target. 'Under' or 'at the end of' an existing section "
            "means last-child. Count only subsections requested beneath the "
            "new section; do not count the new section itself."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "anchor": {
                    "type": "string",
                    "description": "Exact existing section path from the outline.",
                    "enum": anchors,
                },
                "position": {
                    "type": "string",
                    "description": "Placement relative to the existing anchor.",
                    "enum": list(POSITIONS),
                },
                "child_count": {
                    "type": "integer",
                    "description": (
                        "Number of subsections the request places directly "
                        "beneath the new section."
                    ),
                    "enum": [0, 1, 2],
                },
            },
            "required": ["anchor", "position", "child_count"],
        },
    }


def expected_plan(task):
    first = task["ideal_calls"][0]["args"]
    count = len(task["ideal_calls"]) - 1
    if count != slots.CHILD_COUNT[task["id"]]:
        raise RuntimeError(f"child-count fixture drift for {task['id']}")
    with open(os.path.join(ROOT, task["fixture"]), newline="") as fh:
        content = fh.read()
    entries = section_outline(content)
    resolved = resolve_section(content, first["section"])
    matches = [
        index for index, entry in enumerate(entries)
        if entry["path"] == resolved.slug
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"planner cannot represent duplicate anchor {resolved.slug!r}")
    index = matches[0]
    return {
        "anchor": anchor_options(content)[index],
        "position": first["position"],
        "child_count": count,
    }


def forced(schema):
    return {"type": "function", "function": {"name": schema["name"]}}


def assistant_message(sampled):
    return {
        "role": "assistant",
        "content": sampled.get("content"),
        "tool_calls": sampled.get("tool_calls") or [],
    }


def parse_call(sampled, expected_name):
    calls = sampled.get("tool_calls") or []
    if not calls:
        return None, f"forced {expected_name} phase returned no tool call"
    call0 = calls[0]
    fn = call0.get("function", {})
    if fn.get("name") != expected_name:
        return None, f"forced {expected_name} phase returned {fn.get('name')!r}"
    try:
        args = json.loads(fn.get("arguments") or "{}")
    except json.JSONDecodeError as exc:
        return None, f"unparseable arguments: {exc}"
    if not isinstance(args, dict):
        return None, f"arguments are {type(args).__name__}, not an object"
    return (call0, args), None


def validate_plan(plan, schema):
    required = ("anchor", "position", "child_count")
    missing = [name for name in required if name not in plan]
    if missing:
        return f"plan is missing required fields: {', '.join(missing)}"
    anchors = schema["parameters"]["properties"]["anchor"]["enum"]
    if plan["anchor"] not in anchors:
        return f"plan anchor is not an existing section path: {plan['anchor']!r}"
    if plan["position"] not in POSITIONS:
        return f"plan position is invalid: {plan['position']!r}"
    count = plan["child_count"]
    if isinstance(count, bool) or not isinstance(count, int) or count not in (0, 1, 2):
        return f"plan child_count is invalid: {count!r}"
    return None


def sample(endpoint, payload):
    response, elapsed = call(endpoint, payload)
    sampled = record(response, elapsed)
    return response, sampled


def run_trial(endpoint, task, seed):
    fixture = os.path.join(ROOT, task["fixture"])
    with open(fixture, newline="") as fh:
        before = fh.read()
    doc = before
    expected = expected_plan(task)
    planning_schema = plan_schema(before)
    payload = armb.build_payload(task, "compose_5", seed)
    payload["tools"] = [{"type": "function", "function": planning_schema}]
    payload["tool_choice"] = forced(planning_schema)

    response, planning = sample(endpoint, payload)
    plan_calls = planning.get("tool_calls") or []
    emitted = list(plan_calls)
    turns = [planning]
    parsed, phase_error = parse_call(planning, planning_schema["name"])
    plan_call = plan_calls[0] if plan_calls else None
    received = parsed[1] if parsed is not None else None
    if phase_error is None:
        phase_error = validate_plan(received, planning_schema)

    content_schema = None
    content_call = None
    composed = None
    execution_error = None
    content = None
    content_sample = None
    model = response.get("model")
    finish_reason = planning.get("finish_reason")

    if phase_error is None:
        content_schema = slots.schema_for_child_count(received["child_count"])
        payload["messages"].append(assistant_message(planning))
        payload["messages"].append({
            "role": "tool",
            "tool_call_id": plan_call.get("id"),
            "content": "Plan accepted. Supply the section content.",
        })
        payload["tools"] = [{"type": "function", "function": content_schema}]
        payload["tool_choice"] = forced(content_schema)
        response, content_sample = sample(endpoint, payload)
        model = response.get("model")
        finish_reason = content_sample.get("finish_reason")
        turns.append(content_sample)
        content_calls = content_sample.get("tool_calls") or []
        emitted.extend(content_calls)
        content_call = content_calls[0] if content_calls else None
        parsed_content, phase_error = parse_call(content_sample, content_schema["name"])
        if phase_error is None:
            _raw_call, content = parsed_content
            structure = {
                "path": task["fixture"],
                "parent": received["anchor"],
                "position": received["position"],
            }
            composed, phase_error = slots.compose_with_structure(content, structure)

    if composed is not None:
        fn = composed["function"]
        args = json.loads(fn["arguments"])
        op, op_args = armb.normalize(fn["name"], args)
        after, execution_error = apply_op(doc, op, op_args)
        if execution_error:
            phase_error = execution_error
        else:
            doc = after

    plan_tokens = planning.get("completion_tokens") or 0
    content_tokens = ((content_sample or {}).get("completion_tokens") or 0)
    plan_elapsed = planning.get("elapsed_s") or 0
    content_elapsed = ((content_sample or {}).get("elapsed_s") or 0)
    return {
        "model": model,
        "finish_reason": finish_reason,
        "elapsed_s": round(plan_elapsed + content_elapsed, 2),
        "completion_tokens": plan_tokens + content_tokens,
        "plan_elapsed_s": plan_elapsed,
        "content_elapsed_s": content_elapsed,
        "plan_completion_tokens": plan_tokens,
        "content_completion_tokens": content_tokens,
        "plan_call": plan_call,
        "content_call": content_call,
        "expected_plan": expected,
        "received_plan": received,
        "plan_exact": received == expected,
        "content": content,
        "tool_calls": [composed] if composed is not None else [],
        "emitted_tool_calls": emitted,
        "turns": turns,
        "composed_operation": composed,
        "phase_error": phase_error,
        "execution_error": execution_error,
        "document_changed": doc != before,
        "n_turns": len(turns),
        "max_turns": 2,
        "result_shape": "terminal-success",
        "fixture_sha256": sha256_bytes(before.encode()),
        "task_source_sha256": sha256_file(TASK_SOURCE),
        "harness_sha256": sha256_file(__file__),
        "plan_schema_sha256": canonical_hash(planning_schema),
        "content_schema_sha256": (
            canonical_hash(content_schema) if content_schema is not None else None
        ),
    }


def read_last(path):
    rows = {}
    if not os.path.exists(path):
        return rows
    with open(path) as fh:
        for line in fh:
            row = json.loads(line)
            rows[(row["task_id"], row["trial"])] = row
    return rows


def run(args):
    selected = slots.tasks()
    done = {
        key for key, row in read_last(args.out).items()
        if row.get("error") is None
    }
    work = [
        (task, trial) for task in selected for trial in range(args.trials)
        if (task["id"], trial) not in done
    ]
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    print(f"{len(work)} trials to run, scheme={SCHEME}")
    started = time.time()
    with open(args.out, "a") as fh:
        for index, (task, trial) in enumerate(work, 1):
            try:
                row = run_trial(args.endpoint, task, trial)
                row.update(task_id=task["id"], trial=trial, scheme=SCHEME, error=None)
            except Exception as exc:  # noqa: BLE001
                row = {
                    "task_id": task["id"], "trial": trial, "scheme": SCHEME,
                    "error": f"{type(exc).__name__}: {exc}", "elapsed_s": None,
                }
            fh.write(json.dumps(row) + "\n")
            fh.flush()
            elapsed = time.time() - started
            eta = elapsed / index * (len(work) - index) / 60
            print(
                f"[{index:2d}/{len(work)}] {task['id']:26s} t{trial} "
                f"{row.get('elapsed_s') or 0:5.1f}s "
                f"plan={'yes' if row.get('plan_exact') else 'no ':3s} "
                f"tok={row.get('completion_tokens') or 0:4d} eta {eta:.0f}m",
                flush=True,
            )


def failure_stage(row):
    received = row.get("received_plan")
    expected = row.get("expected_plan")
    if not isinstance(received, dict):
        return "plan_parse"
    if received.get("anchor") != expected.get("anchor"):
        return "anchor"
    if received.get("position") != expected.get("position"):
        return "position"
    if received.get("child_count") != expected.get("child_count"):
        return "child_count"
    if row.get("execution_error"):
        return "execution"
    if row.get("phase_error") or not row.get("tool_calls"):
        return "content"
    return None


def grade(args):
    by_id = {task["id"]: task for task in slots.tasks()}
    outcomes = Counter()
    with open(args.graded, "w") as out:
        for _key, row in sorted(read_last(args.out).items()):
            task = by_id[row["task_id"]]
            if row.get("error"):
                outcome, detail = armb.grade_one(task, row)
            elif not row.get("tool_calls") and row.get("phase_error"):
                outcome, detail = "op_error", row["phase_error"]
            else:
                outcome, detail = armb.grade_one(task, row)
            outcomes[outcome] += 1
            stage = failure_stage(row)
            if outcome != "correct" and stage is None:
                stage = "content"
            out.write(json.dumps({
                "task_id": row["task_id"],
                "trial": row["trial"],
                "scheme": row.get("scheme", SCHEME),
                "outcome": outcome,
                "detail": detail,
                "expected_plan": row.get("expected_plan"),
                "received_plan": row.get("received_plan"),
                "plan_exact": row.get("plan_exact"),
                "failure_stage": stage,
            }) + "\n")
    print(dict(outcomes))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--endpoint", default="http://127.0.0.1:8081/v1/chat/completions")
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--out", required=True)
    parser.add_argument("--graded", required=True)
    parser.add_argument("--grade", action="store_true")
    args = parser.parse_args()
    (grade if args.grade else run)(args)


if __name__ == "__main__":
    main()
