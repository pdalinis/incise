#!/usr/bin/env python3
"""Run `incise check` through the Hermes plugin's binary resolver."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT))

import runner  # noqa: E402


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print("usage: check.py PATH [--fix-safe --if-match HASH]", file=sys.stderr)
        return runner.EXIT_USAGE
    code, payload, stderr = runner.invoke(["check", *args])
    print(json.dumps(payload, ensure_ascii=True))
    if stderr:
        print(stderr, end="" if stderr.endswith("\n") else "\n", file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
