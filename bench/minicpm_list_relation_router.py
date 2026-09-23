#!/usr/bin/env python3
"""MiniCPM chooses between validated after and between list micro-tools."""

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
import minicpm_list_required_after as base  # noqa: E402
import minicpm_routed as routed  # noqa: E402
import minicpm_section_pipeline as provenance  # noqa: E402
from incise_ops import apply_op  # noqa: E402
from runner import call, record  # noqa: E402


SCHEME = "minicpm_list_relation_router"
EXPECTED_RELATION = {
    "add-item-nested-asterisk": "after",
    "add-item-ordered-renumber": "between",
}


def relation_schemas(item_texts):
    after = copy.deepcopy(base.edit_schema(item_texts))
    after["description"] = (
        "Use only when the request says the new item belongs after one named "
        "existing item. Supply the new text and that one exact existing item."
    )
    between = copy.deepcopy(base.between_schema(item_texts))
    between["description"] = (
        "Use only when the request names both surrounding existing items. "
        "Supply the new text, then copy the exact after and before boundaries "
        "in request order."
    )
    return after, between


def parse_relation_call(sampled):
    calls = sampled.get("tool_calls") or []
    if len(calls) != 1:
        return None, (
            f"relation phase returned {len(calls)} tool calls; exactly one is required")
    call0 = calls[0]
    fn = call0.get("function", {})
    if fn.get("name") not in {"list_insert_after", "list_insert_between"}:
        return None, f"relation phase returned unknown tool {fn.get('name')!r}"
    try:
        args = json.loads(fn.get("arguments") or "{}")
    except json.JSONDecodeError as exc:
        return None, f"unparseable arguments: {exc}"
    if not isinstance(args, dict):
        return None, f"arguments are {type(args).__name__}, not an object"
    return (call0, args), None


def sample(endpoint, payload):
    response, elapsed = base.call(endpoint, payload)
    return response, record(response, elapsed)


def run_trial(endpoint, task, seed, list_get_schema):
    fixture = os.path.join(ROOT, task["fixture"])
    with open(fixture, newline="") as fh:
        before = fh.read()
    doc = before
    payload = armb.build_payload(task, "compose_5", seed)
    payload["tools"] = [{"type": "function", "function": list_get_schema}]
    payload["tool_choice"] = routed.forced("list_get")

    response, read_sample = sample(endpoint, payload)
    model = response.get("model")
    read_calls = read_sample.get("tool_calls") or []
    emitted = list(read_calls)
    turns = [read_sample]
    parsed, phase_error = routed._parse_call(read_sample, "list_get")
    read_call = read_calls[0] if read_calls else None
    read_args = parsed[1] if parsed is not None else None
    read_report = None
    rendered = None
    allowed_items = []
    schemas = None
    relation_sample = None
    relation_call = None
    content = None
    selected_relation = None
    composed = None
    execution_error = None
    validation_passed = None

    if phase_error is None:
        read_report, rendered, phase_error = armb.read_call(
            doc, "list_get", read_args)
    if phase_error is None:
        allowed_items = base.exact_item_texts(read_report)
        if not allowed_items:
            phase_error = "list_get returned no exact item texts"
    if phase_error is None:
        schemas = relation_schemas(allowed_items)
        payload["messages"].append(routed._assistant_message(read_sample))
        payload["messages"].append({
            "role": "tool", "tool_call_id": read_call.get("id"),
            "content": rendered,
        })
        payload["tools"] = [
            {"type": "function", "function": schema} for schema in schemas]
        payload["tool_choice"] = "auto"
        response, relation_sample = sample(endpoint, payload)
        model = response.get("model")
        turns.append(relation_sample)
        relation_calls = relation_sample.get("tool_calls") or []
        emitted.extend(relation_calls)
        relation_call = relation_calls[0] if relation_calls else None
        parsed_relation, phase_error = parse_relation_call(relation_sample)
        if phase_error is None:
            call0, content = parsed_relation
            name = call0["function"]["name"]
            selected_relation = (
                "after" if name == "list_insert_after" else "between")
            if selected_relation == "after":
                composed, phase_error = base.compose(
                    task, read_args, content, allowed_items)
                validation_passed = phase_error is None
            else:
                composed, validation_passed, phase_error = base.compose_between(
                    task, read_args, read_report, content, allowed_items)

    if composed is not None:
        fn = composed["function"]
        args = json.loads(fn["arguments"])
        op, op_args = armb.normalize(fn["name"], args)
        after, execution_error = apply_op(doc, op, op_args)
        if execution_error:
            phase_error = execution_error
        else:
            doc = after

    read_tokens = read_sample.get("completion_tokens") or 0
    route_tokens = ((relation_sample or {}).get("completion_tokens") or 0)
    read_elapsed = read_sample.get("elapsed_s") or 0
    route_elapsed = ((relation_sample or {}).get("elapsed_s") or 0)
    executed = ([read_call] if read_call is not None else [])
    if composed is not None:
        executed.append(composed)
    expected_relation = EXPECTED_RELATION[task["id"]]
    return {
        "model": model,
        "finish_reason": (
            (relation_sample or read_sample).get("finish_reason")),
        "elapsed_s": round(read_elapsed + route_elapsed, 2),
        "completion_tokens": read_tokens + route_tokens,
        "read_elapsed_s": read_elapsed,
        "route_elapsed_s": route_elapsed,
        "read_completion_tokens": read_tokens,
        "route_completion_tokens": route_tokens,
        "read_call": read_call,
        "relation_call": relation_call,
        "read_report": read_report,
        "allowed_items": allowed_items,
        "content": content,
        "expected_relation": expected_relation,
        "selected_relation": selected_relation,
        "relation_correct": selected_relation == expected_relation,
        "validation_passed": validation_passed,
        "tool_calls": executed,
        "emitted_tool_calls": emitted,
        "composed_operation": composed,
        "turns": turns,
        "phase_error": phase_error,
        "execution_error": execution_error,
        "document_changed": doc != before,
        "n_turns": len(turns),
        "max_turns": 2,
        "result_shape": "terminal-success",
        "fixture_sha256": provenance.sha256_bytes(before.encode()),
        "harness_sha256": provenance.sha256_file(__file__),
        "list_get_schema_sha256": provenance.canonical_hash(list_get_schema),
        "relation_schemas_sha256": (
            provenance.canonical_hash(schemas) if schemas is not None else None),
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
    schemas = routed.load_schemas(args.binary)
    list_get_schema = schemas["list_get"]
    done = {
        key for key, row in read_last(args.out).items()
        if row.get("error") is None
    }
    work = [
        (task, trial) for task in base.tasks() for trial in range(args.trials)
        if (task["id"], trial) not in done
    ]
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    print(f"{len(work)} trials to run, scheme={SCHEME}")
    started = time.time()
    with open(args.out, "a") as fh:
        for index, (task, trial) in enumerate(work, 1):
            try:
                row = run_trial(args.endpoint, task, trial, list_get_schema)
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
                f"[{index}/{len(work)}] {task['id']:27s} t{trial} "
                f"route={row.get('selected_relation') or '-':7s} "
                f"{row.get('elapsed_s') or 0:5.1f}s eta {eta:.0f}m",
                flush=True,
            )


def grade(args):
    by_id = {task["id"]: task for task in base.tasks()}
    outcomes = Counter()
    with open(args.graded, "w") as out:
        for _key, row in sorted(read_last(args.out).items()):
            task = by_id[row["task_id"]]
            mutations = [
                call for call in row.get("tool_calls") or []
                if call.get("function", {}).get("name") not in armb.READS
            ]
            if row.get("error"):
                outcome, detail = armb.grade_one(task, row)
            elif not mutations and row.get("phase_error"):
                outcome, detail = "op_error", row["phase_error"]
            else:
                outcome, detail = armb.grade_one(task, row)
            outcomes[outcome] += 1
            out.write(json.dumps({
                "task_id": row["task_id"], "trial": row["trial"],
                "scheme": row.get("scheme", SCHEME), "outcome": outcome,
                "detail": detail,
                "expected_relation": row.get("expected_relation"),
                "selected_relation": row.get("selected_relation"),
                "relation_correct": row.get("relation_correct"),
                "validation_passed": row.get("validation_passed"),
            }) + "\n")
    print(dict(outcomes))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--endpoint", default="http://127.0.0.1:8081/v1/chat/completions")
    parser.add_argument(
        "--binary", default=os.path.join(ROOT, "target", "debug", "incise"))
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--out", required=True)
    parser.add_argument("--graded", required=True)
    parser.add_argument("--grade", action="store_true")
    args = parser.parse_args()
    (grade if args.grade else run)(args)


if __name__ == "__main__":
    main()
