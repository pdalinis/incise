# Ornith checkbox and section-level route experiment

Recorded 2026-09-23 before collecting the current-router control and before
implementing either proposed route.

## Hypothesis

The reasoning-off, safe-routed pilot was 30/36 correct after route-aware
grading, with 27/27 correct outcomes on the existing routed operations in the
panel. All three harmful final documents came from two operations the released
router does not recognize: `list-set-checked` and `section-set-level`.

Strict host resolution should make those operations equivalent to the existing
successful zero-argument routes:

- For a quoted checkbox item and quoted list heading, inspect lists and items,
  require one exact checkbox item, then expose a zero-argument tool whose host
  supplies the file, full list address, exact item text, requested boolean, and
  read hash.
- For an explicit promotion request naming the child, parent, numeric heading
  level, and subtree behavior, inspect the outline, require one exact resolved
  section, then expose a zero-argument tool whose host supplies the file,
  section path, level, `subtree: true`, and read hash.

The parsers must be narrow enough to fall back on any unrecognized wording.
Core and CLI behavior do not change.

## Population and fixed runtime

Run ten trials, seeds 0 through 9, for each of:

- `check-task-nested`
- `promote-api`
- `insert-troubleshooting`

The first two are the affected route population. `insert-troubleshooting` is a
latency control: its routed edit was correct in all three prior final documents,
but one post-edit completion exceeded the 900-second worker timeout.

Both current-router control and changed-router treatment use Pi 0.85.1,
Ornith-1.5-9B Q8_0, the official coding sampling values already pinned in
`ORNITH_FULL_PLAN.md`, reasoning disabled, `INCISE_PROFILE=safe-routed`, four
turns, and the same fixtures, prompts, grader, and 900-second worker timeout.
Maximum completion is 2,048 tokens. That cap is identical in both arms and is
well above every valid call and concise completion observed in the prior pools.

## Gate

The changed router is eligible for a full Ornith validation only if:

- checkbox and section-level tasks are 20/20 correct combined;
- all 30 final documents are correct;
- there are zero harmful, transport, framing, or reasoning-leak outcomes;
- every affected trial activates exactly its intended new route and supplies
  the preregistered resolved arguments;
- the troubleshooting control does not regress from its current-router arm;
  and
- mean elapsed time is at most 30 seconds and no completed trial exceeds 90
  seconds.

The control is collected and committed before router implementation. Historical
pools remain immutable. A passed Ornith arm still requires a targeted Gemma
confirmation on these two affected tasks before the shared `safe-routed`
profile can ship, because Gemma auto-selects that profile.
