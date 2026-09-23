"""Finding and running the ``incise`` binary.

Everything this plugin does is a subprocess call. There is no Python
reimplementation of any operation and there must not be: ``incise_ops.py`` and
``incise-core`` are a differential pair tested byte-for-byte against each other
across 110406 cases, and a third implementation here would be a third thing to
keep in step with no test watching it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

# The exit codes the CLI documents. Each means something different to a caller,
# which is the whole reason they are distinct: a refusal should be answered by
# changing the call, a stale hash by re-reading the file, and a usage fault by
# neither.
EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_USAGE = 2
EXIT_STALE = 3

_BINARY: Optional[str] = None
_BINARY_SOURCE: Optional[str] = None
_SEARCHED = False


def _checkout_root(start: Path) -> Optional[Path]:
    """Return the source checkout containing *start*, if there is one."""
    for parent in start.resolve().parents:
        if (parent / "Cargo.toml").exists() and (parent / "crates").is_dir():
            return parent
    return None


def _source_candidates(root: Path) -> Iterable[str]:
    """Yield executable checkout builds from newest to oldest.

    Source-linked Hermes installs are development installs. Prefer the build
    produced most recently instead of assuming an older optimized binary is
    more representative than a newer debug build. A release build wins an
    exact timestamp tie.
    """
    paths = [
        root / "target" / profile / "incise"
        for profile in ("release", "debug")
    ]
    existing = [path for path in paths if path.is_file() and os.access(path, os.X_OK)]
    existing.sort(
        key=lambda path: (path.stat().st_mtime_ns, path.parent.name == "release"),
        reverse=True,
    )
    yield from (str(path) for path in existing)


def _candidates():
    env = os.environ.get("INCISE_BIN")
    if env:
        yield env, "INCISE_BIN"

    # A source-linked plugin should exercise the checkout it came from, not an
    # unrelated installed binary. Hermes Plugin Doctor may not preserve a
    # one-shot INCISE_BIN override, which makes this ordering load-bearing for
    # development and release validation.
    root = _checkout_root(Path(__file__))
    if root is not None:
        for path in _source_candidates(root):
            yield path, "source checkout (newest build)"

    found = shutil.which("incise")
    if found:
        yield found, "PATH"


def binary() -> Optional[str]:
    """The `incise` executable, or None. Resolved once."""
    global _BINARY, _BINARY_SOURCE, _SEARCHED
    if _SEARCHED:
        return _BINARY
    _SEARCHED = True
    for path, source in _candidates():
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            _BINARY = path
            _BINARY_SOURCE = source
            break
    return _BINARY


def binary_source() -> Optional[str]:
    """How the cached binary was selected, for installation diagnostics."""
    binary()
    return _BINARY_SOURCE


def reset_cache() -> None:
    """Forget the resolved binary. For tests, and for a mid-session rebuild."""
    global _BINARY, _BINARY_SOURCE, _SEARCHED
    _BINARY, _BINARY_SOURCE, _SEARCHED = None, None, False


def available() -> Optional[str]:
    """``check_fn`` contract: None when usable, else the reason it is not."""
    if binary():
        return None
    return (
        "incise is not installed. Install it with "
        "`cargo install incise-cli --locked`, put the binary on PATH, or set "
        "INCISE_BIN to it."
    )


def invoke(argv: list, timeout: float = 30.0) -> Tuple[int, Dict[str, Any], str]:
    """Run `incise <argv> --json`.

    Returns ``(exit_code, parsed_stdout, raw_stderr)``. `--json` puts everything
    the CLI has to say on stdout as one object, refusals included, so the parsed
    dict is the answer in every case the CLI itself produced. The raw stderr is
    carried anyway for the cases it does not: clap's own argument errors, and
    anything that killed the process before it could print.
    """
    exe = binary()
    if not exe:
        return EXIT_USAGE, {"ok": False, "error": available()}, ""

    try:
        done = subprocess.run(
            [exe] + [str(a) for a in argv] + ["--json"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return EXIT_USAGE, {"ok": False, "error": f"incise timed out after {timeout}s"}, ""
    except OSError as exc:
        return EXIT_USAGE, {"ok": False, "error": f"cannot run {exe}: {exc}"}, ""

    try:
        parsed = json.loads(done.stdout) if done.stdout.strip() else {}
    except json.JSONDecodeError:
        parsed = {}

    if not parsed:
        detail = (done.stderr or done.stdout).strip() or f"incise exited {done.returncode}"
        parsed = {"ok": False, "error": detail}

    return done.returncode, parsed, done.stderr
