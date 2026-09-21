#!/usr/bin/env python3
"""MiniCPM host-routed, flat-content section insertion arm."""

import argparse
import copy
import json
import os
import sys
import time
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bench"))

import armb  # noqa: E402
from incise_ops import apply_op  # noqa: E402
from runner import call, record  # noqa: E402


TASK_IDS = {
    "insert-release-at-top", "insert-subsection-last",
    "insert-nested-ratelimits", "insert-troubleshooting",
}
SCHEME = "minicpm_section_slots"

CHILD_COUNT = {
    "insert-release-at-top": 1,
    "insert-subsection-last": 0,
    "insert-nested-ratelimits": 1,
    "insert-troubleshooting": 2,
}

SCHEMA = {
    "name": "section_insert_content",
    "description": (
        "Supply content for one new section. The host already knows the file, "
        "exact parent or anchor, and position. Put requested subsections in the "
        "flat child slots; never put subsection headings in body."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "new_heading": {
                "type": "string",
                "description": "Heading of the new section, without # marks.",
            },
            "body": {
                "type": "string",
                "description": "Prose belonging directly to the new section.",
            },
            "child_1_heading": {
                "type": "string",
                "description": "Heading of the first requested subsection.",
            },
            "child_1_body": {
                "type": "string",
                "description": "Body of the first requested subsection.",
            },
            "child_2_heading": {
                "type": "string",
                "description": "Heading of the second requested subsection.",
            },
            "child_2_body": {
                "type": "string",
                "description": "Body of the second requested subsection.",
            },
        },
        "required": ["new_heading"],
    },
}


def schema_for_child_count(count):
    """Return the required content micro-schema for a routed cardinality."""
    if count not in (0, 1, 2):
        raise ValueError(f"unsupported child count: {count!r}")
    schema = copy.deepcopy(SCHEMA)
    suffix = ("body", "one_child", "two_children")[count]
    schema["name"] = f"section_insert_{suffix}"
    if count == 0:
        keep = {"new_heading", "body"}
        required = ["new_heading", "body"]
        shape = "one section with its body and no subsections"
    else:
        keep = {"new_heading"}
        required = ["new_heading"]
        for index in range(1, count + 1):
            keep.update({f"child_{index}_heading", f"child_{index}_body"})
            required.extend([f"child_{index}_heading", f"child_{index}_body"])
        shape = f"one section with exactly {count} requested subsection{'s' if count > 1 else ''}"
    props = schema["parameters"]["properties"]
    schema["parameters"]["properties"] = {
        name: spec for name, spec in props.items() if name in keep
    }
    schema["parameters"]["required"] = required
    schema["description"] = (
        f"Supply all content for {shape}. The host already knows every "
        "structural argument. Every published field is required."
    )
    return schema


def required_schema(task):
    """Only fields the routed request needs, all required."""
    return schema_for_child_count(CHILD_COUNT[task["id"]])


def forced(schema):
    return {"type": "function", "function": {"name": schema["name"]}}


def tasks():
    path = os.path.join(ROOT, "bench/tasks/sections.json")
    with open(path) as fh:
        all_tasks = json.load(fh)["tasks"]
    return [
        task for task in all_tasks
        if task["id"] in TASK_IDS
    ]


def structural_args(task):
    ideal = task["ideal_calls"][0]["args"]
    return {
        "path": task["fixture"],
        "parent": ideal["section"],
        "position": ideal["position"],
    }


def compose_with_structure(content, structure):
    """Combine model content with host-owned structure into one insert call."""
    args = dict(structure)
    args["new_heading"] = content.get("new_heading")
    if content.get("body") is not None:
        args["body"] = content["body"]
    children = []
    for index in (1, 2):
        heading = content.get(f"child_{index}_heading")
        body = content.get(f"child_{index}_body")
        if body and not heading:
            return None, (
                f"`child_{index}_body` was supplied without "
                f"`child_{index}_heading`; no edit was executed."
            )
        if heading:
            child = {"heading": heading}
            if body is not None:
                child["body"] = body
            children.append(child)
    if children:
        args["children"] = children
    return {
        "type": "function",
        "function": {
            "name": "section_insert",
            "arguments": json.dumps(args, separators=(",", ":")),
        },
    }, None


def compose(task, content):
    """Return a canonical section_insert call, or a host refusal."""
    return compose_with_structure(content, structural_args(task))


def run_trial(endpoint, task, seed, required_slots=False):
    schema = required_schema(task) if required_slots else SCHEMA
    payload = armb.build_payload(task, "compose_5", seed)
    payload["tools"] = [{"type": "function", "function": schema}]
    payload["tool_choice"] = forced(schema)
    response, elapsed = call(endpoint, payload)
    sampled = record(response, elapsed)
    emitted = sampled.get("tool_calls") or []
    phase_error = None
    composed = None
    if not emitted:
        phase_error = "forced section_insert_content phase returned no tool call"
    else:
        fn = emitted[0].get("function", {})
        if fn.get("name") != schema["name"]:
            phase_error = f"forced phase returned {fn.get('name')!r}"
        else:
            try:
                content = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError as exc:
                content = None
                phase_error = f"unparseable arguments: {exc}"
            if content is not None and not isinstance(content, dict):
                phase_error = f"arguments are {type(content).__name__}, not an object"
            if phase_error is None:
                composed, phase_error = compose(task, content)

    with open(os.path.join(ROOT, task["fixture"]), newline="") as fh:
        before = fh.read()
    doc = before
    if composed is not None:
        fn = composed["function"]
        args = json.loads(fn["arguments"])
        op, op_args = armb.normalize(fn["name"], args)
        after, error = apply_op(doc, op, op_args)
        if error:
            phase_error = error
        else:
            doc = after

    return {
        "model": response.get("model"),
        "finish_reason": sampled.get("finish_reason"),
        "elapsed_s": round(elapsed, 2),
        "completion_tokens": sampled.get("completion_tokens") or 0,
        "tool_calls": [composed] if composed is not None else [],
        "emitted_tool_calls": emitted,
        "host_injected": structural_args(task),
        "phase_error": phase_error,
        "document_changed": doc != before,
        "n_turns": 1,
        "result_shape": "terminal-success",
        "max_turns": 1,
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
    selected = tasks()
    done = {
        key for key, row in read_last(args.out).items()
        if row.get("error") is None
    }
    work = [
        (task, trial) for task in selected for trial in range(args.trials)
        if (task["id"], trial) not in done
    ]
    scheme = "minicpm_section_required_slots" if args.required_slots else SCHEME
    print(f"{len(work)} trials to run, scheme={scheme}")
    started = time.time()
    with open(args.out, "a") as fh:
        for index, (task, trial) in enumerate(work, 1):
            try:
                row = run_trial(args.endpoint, task, trial, args.required_slots)
                row.update(task_id=task["id"], trial=trial, scheme=scheme, error=None)
            except Exception as exc:  # noqa: BLE001
                row = {
                    "task_id": task["id"], "trial": trial, "scheme": scheme,
                    "error": f"{type(exc).__name__}: {exc}", "elapsed_s": None,
                }
            fh.write(json.dumps(row) + "\n")
            fh.flush()
            elapsed = time.time() - started
            eta = elapsed / index * (len(work) - index) / 60
            print(
                f"[{index:2d}/{len(work)}] {task['id']:26s} t{trial} "
                f"{row.get('elapsed_s') or 0:5.1f}s "
                f"tok={row.get('completion_tokens') or 0:4d} eta {eta:.0f}m",
                flush=True,
            )


def grade(args):
    by_id = {task["id"]: task for task in tasks()}
    outcomes = Counter()
    with open(args.graded, "w") as out:
        for key, row in sorted(read_last(args.out).items()):
            task = by_id[row["task_id"]]
            if row.get("error"):
                outcome, detail = armb.grade_one(task, row)
            elif not row.get("tool_calls") and row.get("phase_error"):
                outcome, detail = "op_error", row["phase_error"]
            else:
                outcome, detail = armb.grade_one(task, row)
            outcomes[outcome] += 1
            out.write(json.dumps({
                "task_id": row["task_id"], "trial": row["trial"],
                "scheme": row.get("scheme", SCHEME), "outcome": outcome, "detail": detail,
            }) + "\n")
    print(dict(outcomes))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", default="http://127.0.0.1:8081/v1/chat/completions")
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--out", required=True)
    parser.add_argument("--graded", required=True)
    parser.add_argument("--grade", action="store_true")
    parser.add_argument(
        "--required-slots", action="store_true",
        help="route by requested child count and require every content slot",
    )
    args = parser.parse_args()
    (grade if args.grade else run)(args)


if __name__ == "__main__":
    main()
