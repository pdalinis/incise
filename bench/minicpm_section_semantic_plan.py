#!/usr/bin/env python3
"""Planner-only MiniCPM section arm using request-language semantic labels."""

import argparse
import json
import os
import sys
import time
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bench"))

import armb  # noqa: E402
import minicpm_section_pipeline as prior  # noqa: E402
from incise_ops import OpError, resolve_section, section_outline  # noqa: E402
from runner import call, record  # noqa: E402


SCHEME = "minicpm_section_semantic_plan"
RELATIONSHIPS = ("sibling", "subsection")
ORDERS = ("before-existing", "after-existing")
SHAPES = ("body-only", "one-subsection", "two-subsections")

POSITION_TO_SEMANTIC = {
    "before": ("sibling", "before-existing"),
    "after": ("sibling", "after-existing"),
    "first-child": ("subsection", "before-existing"),
    "last-child": ("subsection", "after-existing"),
}
SHAPE_FOR_COUNT = dict(enumerate(SHAPES))


def semantic_schema(content):
    return {
        "name": "section_insert_semantic_plan",
        "description": (
            "Classify the requested section structure using ordinary document "
            "concepts. Choose an existing anchor and describe how the new "
            "section relates to it. Do not supply section content."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "anchor": {
                    "type": "string",
                    "description": (
                        "Existing section named by the request. Copy its exact "
                        "address from the outline."
                    ),
                    "enum": prior.anchor_options(content),
                },
                "relationship": {
                    "type": "string",
                    "description": (
                        "Choose subsection when the new section goes under, "
                        "inside, or at the end of the anchor section. Choose "
                        "sibling when it goes above, below, before, or after "
                        "the anchor section."
                    ),
                    "enum": list(RELATIONSHIPS),
                },
                "order": {
                    "type": "string",
                    "description": (
                        "Choose before-existing for above, before, or at the "
                        "start. Choose after-existing for below, after, or at "
                        "the end."
                    ),
                    "enum": list(ORDERS),
                },
                "content_shape": {
                    "type": "string",
                    "description": (
                        "Choose body-only when the new section has ordinary "
                        "prose, code, or list text but no named nested heading. "
                        "Choose one-subsection or two-subsections only for "
                        "explicitly named headings nested beneath the new section."
                    ),
                    "enum": list(SHAPES),
                },
            },
            "required": ["anchor", "relationship", "order", "content_shape"],
        },
    }


def expected_plan(task):
    expected = prior.expected_plan(task)
    relationship, order = POSITION_TO_SEMANTIC[expected["position"]]
    return {
        "anchor": expected["anchor"],
        "relationship": relationship,
        "order": order,
        "content_shape": SHAPE_FOR_COUNT[expected["child_count"]],
    }


def canonical_anchor(content, address):
    section = resolve_section(content, address)
    entries = section_outline(content)
    matches = [
        index for index, entry in enumerate(entries)
        if entry["path"] == section.slug
    ]
    if len(matches) != 1:
        raise OpError(f'anchor "{address}" resolves to a duplicate section path')
    return prior.anchor_options(content)[matches[0]]


def canonical_plan(content, received):
    if not isinstance(received, dict):
        return None, "plan arguments are not an object"
    required = ("anchor", "relationship", "order", "content_shape")
    missing = [field for field in required if field not in received]
    if missing:
        return None, f"plan is missing required fields: {', '.join(missing)}"
    try:
        anchor = canonical_anchor(content, received["anchor"])
    except (OpError, TypeError) as exc:
        return None, str(exc)
    if received["relationship"] not in RELATIONSHIPS:
        return None, f"invalid relationship: {received['relationship']!r}"
    if received["order"] not in ORDERS:
        return None, f"invalid order: {received['order']!r}"
    if received["content_shape"] not in SHAPES:
        return None, f"invalid content_shape: {received['content_shape']!r}"
    return {
        "anchor": anchor,
        "relationship": received["relationship"],
        "order": received["order"],
        "content_shape": received["content_shape"],
    }, None


def run_trial(endpoint, task, seed):
    fixture = os.path.join(ROOT, task["fixture"])
    with open(fixture, newline="") as fh:
        content = fh.read()
    schema = semantic_schema(content)
    payload = armb.build_payload(task, "compose_5", seed)
    payload["tools"] = [{"type": "function", "function": schema}]
    payload["tool_choice"] = prior.forced(schema)
    response, elapsed = call(endpoint, payload)
    sampled = record(response, elapsed)
    parsed, error = prior.parse_call(sampled, schema["name"])
    raw_call = (sampled.get("tool_calls") or [None])[0]
    received = parsed[1] if parsed is not None else None
    canonical = None
    if error is None:
        canonical, error = canonical_plan(content, received)
    expected = expected_plan(task)
    matches = {
        field: canonical is not None and canonical.get(field) == value
        for field, value in expected.items()
    }
    return {
        "model": response.get("model"),
        "finish_reason": sampled.get("finish_reason"),
        "elapsed_s": round(elapsed, 2),
        "completion_tokens": sampled.get("completion_tokens") or 0,
        "raw_call": raw_call,
        "received_plan": received,
        "canonical_plan": canonical,
        "expected_plan": expected,
        "field_matches": matches,
        "plan_exact": canonical == expected,
        "plan_error": error,
        "executor_called": False,
        "fixture_sha256": prior.sha256_bytes(content.encode()),
        "schema_sha256": prior.canonical_hash(schema),
        "harness_sha256": prior.sha256_file(__file__),
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
    done = {
        key for key, row in read_last(args.out).items()
        if row.get("error") is None
    }
    work = [
        (task, trial) for task in prior.slots.tasks() for trial in range(args.trials)
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
                f"exact={'yes' if row.get('plan_exact') else 'no ':3s} "
                f"tok={row.get('completion_tokens') or 0:4d} eta {eta:.0f}m",
                flush=True,
            )


def grade(args):
    counts = Counter()
    with open(args.graded, "w") as out:
        for _key, row in sorted(read_last(args.out).items()):
            if row.get("error") or row.get("plan_error"):
                outcome = "invalid_plan"
                detail = row.get("error") or row.get("plan_error")
            elif row.get("plan_exact"):
                outcome, detail = "exact_plan", None
            else:
                outcome, detail = "wrong_plan", "one or more semantic fields differ"
            counts[outcome] += 1
            out.write(json.dumps({
                "task_id": row["task_id"], "trial": row["trial"],
                "scheme": row.get("scheme", SCHEME), "outcome": outcome,
                "detail": detail, "expected_plan": row.get("expected_plan"),
                "canonical_plan": row.get("canonical_plan"),
                "field_matches": row.get("field_matches"),
                "plan_exact": row.get("plan_exact"),
            }) + "\n")
    print(dict(counts))


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
