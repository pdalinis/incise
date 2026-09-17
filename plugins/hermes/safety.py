"""The host's file guards, applied before incise is allowed near a path.

incise is a new write path into the filesystem. Hermes's own file tools consult
`agent.file_safety` before touching anything, and a plugin that shells out to a
binary instead would be a way to write to a denied path without the denial ever
being consulted -- the plugin's most likely real defect, and not one a test of
the edit semantics would catch.

So every path goes through the same three questions `tools/file_tools.py` asks,
by calling the same functions rather than by reimplementing the answer:

  * is this read blocked          -- credential stores, Hermes internals
  * is this write denied          -- denylist, HERMES_WRITE_SAFE_ROOT
  * does this write need approval  -- ~/.ssh/config and friends

**Fail closed.** If `agent.file_safety` cannot be imported, this module refuses
every path rather than allowing every path. A guard that disappears when its
import fails is worse than no guard, because the surrounding code reads as
though it is protected.
"""

from __future__ import annotations

from typing import Optional

try:
    from agent import file_safety as _fs

    _IMPORT_ERROR: Optional[str] = None
except Exception as exc:  # pragma: no cover - depends on host layout
    _fs = None
    _IMPORT_ERROR = str(exc)


def _unavailable() -> str:
    return (
        "incise refuses to touch files because the host's file-safety guards "
        f"could not be loaded ({_IMPORT_ERROR}). This is deliberate: without "
        "them there is nothing checking the denylist or HERMES_WRITE_SAFE_ROOT."
    )


def check_read(path: str) -> Optional[str]:
    """None if reading `path` is permitted, else the host's own refusal."""
    if _fs is None:
        return _unavailable()
    try:
        return _fs.get_read_block_error(path)
    except Exception as exc:
        return f"incise could not check read permission for {path!r}: {exc}"


def check_write(path: str) -> Optional[str]:
    """None if writing `path` is permitted, else the host's own refusal.

    A write implies a read -- incise parses the document before splicing it --
    so the read guard is checked first and its message is the one returned.
    """
    blocked = check_read(path)
    if blocked:
        return blocked
    if _fs is None:
        return _unavailable()
    try:
        denied = _fs.get_write_denied_error(path, verb="Edit")
        if denied:
            return denied
        # `is_write_approval_required` documents that a caller with no
        # interactive channel must treat this as a block. A tool handler has
        # none: there is nobody to prompt between the model's call and the
        # splice, so the answer is no.
        if _fs.is_write_approval_required(path):
            return (
                f"Edit denied: '{path}' requires human approval to write, and a "
                "tool call has no channel to ask on. Edit it directly instead."
            )
    except Exception as exc:
        return f"incise could not check write permission for {path!r}: {exc}"
    return None
