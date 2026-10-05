---
name: incise-check
description: Check Markdown for structural hazards that affect Incise addressing or byte-preserving edits, and handle Incise checker findings without broad rewrites.
disable-model-invocation: true
---

# Incise structural check

Use this skill when the user explicitly asks to validate a Markdown file, inspect an Incise checker finding, or verify an Incise edit. This is not a style-lint workflow.

Call `md_check` with the Markdown path. It is the version-matched, read-only
checker supplied by the host integration and returns the versioned JSON report.
Do not search for a launcher or use terminal commands in place of `md_check`.

For a report:

- Stop when `status` is `clean`.
- Treat the check itself as successful even when findings exist; branch on `status` and finding `code`, not the process exit code.
- For an `automatic` finding, use only the report's named Incise repair mechanism with its exact `hash`. Never construct a patch from the prose message.
- For an `explicit` finding, use the repair descriptor's named Incise semantic operation only when the user's request supplies the necessary intent or confirmation.
- For a `manual` finding, explain the ambiguity or ask for intent. Do not raw-patch or reconstruct the document.
- Recheck with `md_check` after a mutation. Stop if the report makes no progress; do not retry a mutation loop indefinitely.

Do not broaden the task to unrelated files or style changes.
