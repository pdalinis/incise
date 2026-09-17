#!/usr/bin/env python3
"""Arm A1 runner: hermes-style `patch` tool calls against the local llama-server.

Serial by design (the server runs --parallel 1), resumable, and time-boxable,
because it shares a machine with the operator's real work.

Records raw responses only. Grading is a separate pass (grade.py) so results can
be re-graded without re-spending GPU time.

  python3 bench/runner.py --trials 10 --condition reasoning_on
  python3 bench/runner.py --trials 10 --condition reasoning_off
  python3 bench/runner.py --probe-conditions      # find how to disable thinking
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Verbatim from ~/.hermes/hermes-agent/tools/file_tools.py PATCH_SCHEMA.
# The replace-only variant: _is_openai_family_main() gates V4A mode to the
# OpenAI/codex family, so a gemma model sees exactly this.
PATCH_SCHEMA = {
    "name": "patch",
    "description": (
        "Targeted find-and-replace edits in files. Use this instead of sed/awk in terminal. "
        "Uses fuzzy matching (9 strategies) so minor whitespace/indentation differences won't break it. "
        "Returns a unified diff. Auto-runs syntax checks after editing. "
        "Finds a unique string and replaces it."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path to edit."},
            "old_string": {
                "type": "string",
                "description": "Exact text to find and replace. Must be unique in the file unless replace_all=true. Include surrounding context lines to ensure uniqueness.",
            },
            "new_string": {
                "type": "string",
                "description": "Changed replacement text; it must differ from old_string. Pass empty string '' to delete the matched text.",
            },
            "replace_all": {
                "type": "boolean",
                "description": "Replace all occurrences instead of requiring a unique match (default: false)",
                "default": False,
            },
        },
        "required": ["path", "old_string", "new_string"],
    },
}

SYSTEM_PROMPT = (
    "You are a helpful coding agent with access to tools for reading and editing "
    "files. Use the provided tools to make the requested edit. Make only the edit "
    "that was asked for."
)

# Per-condition request overrides. Everything not listed here is left unset so
# the server's launch flags apply -- which is what hermes does, and therefore
# what the baseline must do.
CONDITIONS = {
    "reasoning_on": {},
    "reasoning_off": {"chat_template_kwargs": {"enable_thinking": False}},
    "reasoning_off_budget": {"reasoning_budget": 0},
    # Repeat-penalty control (PLAN.md 1.1). Identical to reasoning_off except
    # repeat_penalty is pinned to 1.0 instead of inheriting the server's 1.15,
    # so the pair isolates the confound. Verify the server honors it first:
    #   python3 bench/runner.py --probe-repen
    "repen_off": {
        "chat_template_kwargs": {"enable_thinking": False},
        "repeat_penalty": 1.0,
    },
}


def line_numbered(content):
    """Mimic hermes read_file output, so the model must strip line numbers
    when constructing old_string -- a known error source we reproduce."""
    return "\n".join(f"{i:5d}\t{ln}" for i, ln in enumerate(content.split("\n"), 1))


def build_payload(task, condition, seed):
    fixture_path = os.path.join(ROOT, task["fixture"])
    content = open(fixture_path, newline="").read()
    payload = {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Here is `{task['fixture']}`:\n\n{line_numbered(content)}\n\n{task['instruction']}",
            },
        ],
        "tools": [{"type": "function", "function": PATCH_SCHEMA}],
        "tool_choice": "auto",
        "cache_prompt": True,
        "seed": seed,
    }
    payload.update(CONDITIONS[condition])
    return payload


def call(endpoint, payload, timeout=900):
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        resp = json.load(r)
    return resp, time.time() - t0


def record(resp, elapsed):
    choice = resp["choices"][0]
    msg = choice["message"]
    usage = resp.get("usage", {}) or {}
    reasoning = msg.get("reasoning_content") or ""
    return {
        "model": resp.get("model"),
        "finish_reason": choice.get("finish_reason"),
        "elapsed_s": round(elapsed, 2),
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "cached_tokens": (usage.get("prompt_tokens_details") or {}).get("cached_tokens"),
        "reasoning_chars": len(reasoning),
        "reasoning_content": reasoning,
        "content": msg.get("content"),
        "tool_calls": msg.get("tool_calls"),
    }


def probe_conditions(endpoint, tasks):
    """Find which request parameter actually disables the thinking trace.
    One request per candidate -- cheap, and avoids wasting a 90-minute run."""
    task = tasks[0]
    for name in CONDITIONS:
        try:
            resp, elapsed = call(endpoint, build_payload(task, name, 0))
            r = record(resp, elapsed)
            print(
                f"{name:24s} reasoning_chars={r['reasoning_chars']:6d}  "
                f"completion_tokens={r['completion_tokens']:5d}  {r['elapsed_s']:6.1f}s  "
                f"tool_call={'yes' if r['tool_calls'] else 'NO'}"
            )
        except urllib.error.HTTPError as e:
            print(f"{name:24s} HTTP {e.code}: {e.read().decode()[:200]}")
        except Exception as e:  # noqa: BLE001
            print(f"{name:24s} ERROR: {type(e).__name__}: {e}")


def probe_repen(endpoint, tasks):
    """Verify the server actually honors `repeat_penalty` before trusting a null.

    `reasoning_budget: 0` is silently ignored by this server (see --probe-conditions),
    so an unhonored parameter producing "no difference" is a live failure mode.
    Greedy decoding at a fixed seed is deterministic, so if an extreme penalty
    does not change the output, the parameter is being dropped.
    """
    task = tasks[0]
    out = {}
    for rp in (1.0, 1.9):
        payload = build_payload(task, "reasoning_off", 0)
        payload.update({"repeat_penalty": rp, "temperature": 0.0, "top_k": 1})
        resp, elapsed = call(endpoint, payload)
        r = record(resp, elapsed)
        calls = r["tool_calls"] or []
        out[rp] = calls[0]["function"]["arguments"] if calls else r["content"]
        print(f"  repeat_penalty={rp}  tokens={r['completion_tokens']}  {r['elapsed_s']:.1f}s")
    same = out[1.0] == out[1.9]
    print(f"\n  outputs identical: {same}")
    if same:
        print("  !! repeat_penalty appears to be IGNORED by this server.")
        print("  !! A null result from the repen_off condition would be meaningless.")
    else:
        print("  OK -- parameter is honored; the repen_off condition is meaningful.")
    return not same


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", default="http://127.0.0.1:8081/v1/chat/completions")
    ap.add_argument("--tasks", default=os.path.join(ROOT, "bench/tasks/tables.json"))
    ap.add_argument("--out", default=os.path.join(ROOT, "bench/results/trials.jsonl"))
    ap.add_argument("--trials", type=int, default=10)
    ap.add_argument("--condition", default="reasoning_on", choices=list(CONDITIONS))
    ap.add_argument("--time-budget", type=float, default=0, help="minutes; 0 = unlimited")
    ap.add_argument("--probe-conditions", action="store_true")
    ap.add_argument("--probe-repen", action="store_true")
    args = ap.parse_args()

    tasks = json.load(open(args.tasks))["tasks"]

    if args.probe_conditions:
        probe_conditions(args.endpoint, tasks)
        return

    if args.probe_repen:
        probe_repen(args.endpoint, tasks)
        return

    os.makedirs(os.path.dirname(args.out), exist_ok=True)

    # Resume: skip trials already on disk.
    done = set()
    if os.path.exists(args.out):
        for line in open(args.out):
            try:
                t = json.loads(line)
                done.add((t["task_id"], t["condition"], t["trial"]))
            except (json.JSONDecodeError, KeyError):
                continue
    if done:
        print(f"resuming: {len(done)} trials already recorded")

    # Task-major ordering so the shared prompt prefix stays warm in the cache.
    work = [
        (task, trial)
        for task in tasks
        for trial in range(args.trials)
        if (task["id"], args.condition, trial) not in done
    ]
    if not work:
        print("nothing to do")
        return

    print(f"{len(work)} trials to run, condition={args.condition}")
    started = time.time()
    with open(args.out, "a") as fh:
        for n, (task, trial) in enumerate(work, 1):
            if args.time_budget and (time.time() - started) / 60 >= args.time_budget:
                print(f"\ntime budget reached; {len(work) - n + 1} trials left (resumable)")
                break
            try:
                resp, elapsed = call(args.endpoint, build_payload(task, args.condition, trial))
                row = record(resp, elapsed)
                row.update(task_id=task["id"], condition=args.condition, trial=trial, error=None)
            except Exception as e:  # noqa: BLE001
                row = {
                    "task_id": task["id"], "condition": args.condition, "trial": trial,
                    "error": f"{type(e).__name__}: {e}", "elapsed_s": None,
                }
            fh.write(json.dumps(row) + "\n")
            fh.flush()
            el = time.time() - started
            eta = (el / n) * (len(work) - n) / 60
            print(
                f"[{n:3d}/{len(work)}] {task['id']:26s} t{trial:<2d} "
                f"{(row.get('elapsed_s') or 0):6.1f}s  "
                f"tok={row.get('completion_tokens') or 0:5d}  "
                f"{'ERR ' + row['error'][:40] if row.get('error') else ''}  eta {eta:.0f}m",
                flush=True,
            )


if __name__ == "__main__":
    sys.exit(main())
