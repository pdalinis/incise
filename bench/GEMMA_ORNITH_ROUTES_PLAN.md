# Gemma confirmation for shared Ornith routes

Recorded 2026-09-23 before running Gemma against either newly added shared
route.

## Purpose

The Ornith campaign added two strict routes to the shared `safe-routed`
profile: `list_set_checked_target` and `section_set_level_target`. Gemma's
automatic profile selection already chooses `safe-routed`, so the routes must
be confirmed with Gemma before they can ship even though their parsers fall
back when a prompt or document target is not exact.

## Fixed experiment

Run the historical local `gemma4-direct-q8` endpoint used by the frozen Gemma
full-v8 evaluation through Pi 0.85.1 and the current production extension for
ten trials, seeds 0 through 9, on each affected task:

- `check-task-nested`
- `promote-api`

Use the same fixtures, prompts, four-turn limit, provider defaults, sampling,
and grader as the frozen Gemma full-v8 evaluation. The only implementation
difference from that pool is the two new production routes. Do not apply the
Ornith-only reasoning, completion-cap, or `parallel_tool_calls` settings.

The harness must record provider framing and verify that each first request
contains only the intended zero-argument target tool. It must also verify one
successful mutation, empty model-supplied arguments, the expected route name,
and the exact host-resolved Incise arguments.

## Gate

The shared routes pass Gemma confirmation only if:

- all 20 final documents are correct;
- there are zero harmful, transport, or malformed outcomes;
- all 20 trials activate exactly the intended route;
- every call has empty model-supplied arguments and exact host-resolved
  arguments;
- every trial performs exactly one successful mutation; and
- no trial exposes an Ornith-only provider setting.

The result is a targeted compatibility check, not a replacement for the frozen
480-case Gemma full-v8 result.
