#!/usr/bin/env python3
"""One-off pilot probe: a single Arm A1 trial against the live llama-server.

Replicates hermes's `patch` tool schema exactly (replace-only variant, which is
what non-OpenAI-family models like gemma get) and asks for one table edit.
Deliberately sends NO sampling parameters, so the server's launch defaults
apply -- which is what hermes does, and therefore what the baseline must be.

Seed of bench/runner.py. Usage:  python3 bench/probe.py
"""

import json
import time
import urllib.request

ENDPOINT = "http://127.0.0.1:8081/v1/chat/completions"
FIXTURE = "corpus/tables/aligned.md"

# Verbatim from ~/.hermes/hermes-agent/tools/file_tools.py PATCH_SCHEMA
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

content = open(FIXTURE).read()

# read_file_tool returns line-numbered content, so the model sees it that way.
numbered = "\n".join(f"{i:5d}\t{ln}" for i, ln in enumerate(content.split("\n"), 1))

INSTRUCTION = (
    "Add a row to the Components table for a component named \"sprocket\" "
    "with status \"active\" and owner \"rowan\". Put it at the end of the table."
)

payload = {
    "messages": [
        {"role": "system", "content": "You are a helpful coding agent. Use the provided tools to edit files."},
        {"role": "user", "content": f"Here is `{FIXTURE}`:\n\n{numbered}\n\n{INSTRUCTION}"},
    ],
    "tools": [{"type": "function", "function": PATCH_SCHEMA}],
    "tool_choice": "auto",
    "cache_prompt": True,
    # NO sampling params -- inherit server defaults, matching hermes.
}

req = urllib.request.Request(
    ENDPOINT,
    data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json"},
)
t0 = time.time()
resp = json.load(urllib.request.urlopen(req, timeout=600))
elapsed = time.time() - t0

msg = resp["choices"][0]["message"]
usage = resp.get("usage", {})

print(f"=== model: {resp.get('model')}")
print(f"=== elapsed: {elapsed:.1f}s   finish: {resp['choices'][0].get('finish_reason')}")
print(f"=== usage: {usage}")
if usage.get("completion_tokens"):
    print(f"=== gen speed: {usage['completion_tokens'] / elapsed:.1f} tok/s")

reasoning = msg.get("reasoning_content")
print(f"\n=== reasoning_content: {len(reasoning) if reasoning else 0} chars")
if reasoning:
    print(reasoning[:600])

print(f"\n=== content:\n{msg.get('content')}")
print("\n=== tool_calls:")
print(json.dumps(msg.get("tool_calls"), indent=2)[:2500])
