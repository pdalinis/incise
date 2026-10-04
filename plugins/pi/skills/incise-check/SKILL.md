---
name: incise-check
description: Check Markdown for structural hazards that affect Incise addressing or byte-preserving edits, and handle Incise checker findings without broad rewrites.
disable-model-invocation: true
---

# Incise structural check

Use this skill when the user explicitly asks to validate a Markdown file, inspect an Incise checker finding, or verify an Incise edit. This is not a style-lint workflow.

Run the version-matched launcher bundled beside this file:

- If `scripts/check.mjs` exists, run `node --experimental-strip-types <skill-directory>/scripts/check.mjs PATH`.
- Otherwise run `python3 <skill-directory>/scripts/check.py PATH`.

Resolve the script path relative to this `SKILL.md`. Do not substitute an unrelated `incise` executable from `PATH`; the launcher selects the same binary as the host integration. The launcher prints the versioned JSON report.

For a report:

- Stop when `status` is `clean`.
- Treat the check itself as successful even when findings exist; branch on `status` and finding `code`, not the process exit code.
- For an `automatic` finding, rerun the launcher with `PATH --fix-safe --if-match HASH`, using the report's exact `hash`. Never construct a patch from the prose message.
- For an `explicit` finding, use the repair descriptor's named Incise semantic operation only when the user's request supplies the necessary intent or confirmation.
- For a `manual` finding, explain the ambiguity or ask for intent. Do not raw-patch or reconstruct the document.
- Recheck after a mutation. Stop if the report makes no progress; do not retry a mutation loop indefinitely.

Do not broaden the task to unrelated files or style changes.
