# Ornith reasoning-mode experiment

Recorded 2026-09-23 after stopping the preregistered safe-routed transfer at
144/480 rows and before collecting any outcome with reasoning disabled. The
completed high-thinking rows remain immutable in
`ornith_full_safe_routed_transfer_20260923*.jsonl`; the interruption was a
runtime-policy decision, not a basis for deleting or replacing observations.

## Why this experiment exists

The standard-profile baseline used Ornith's native reasoning mode and completed
479 usable trials at 75.6% correct. Several simple operations took two to six
minutes, with no consistent correctness benefit. The interrupted routed run
then reproduced a 377-second destructive checkbox edit. Before spending hours
on another full pool, test whether disabling reasoning gives a better
correctness, safety, and latency operating point.

Pi's `qwen-chat-template` compatibility path treats every non-off thinking
level as the same `enable_thinking: true` request. The local server and current
model configuration expose no independently verified reasoning budget.
Consequently this experiment compares `high` with `off`; labels such as `low`
would not create a distinct treatment.

## Fixed paired panel

Run seeds 0, 1, and 2 for these 12 tasks under the released standard profile,
for 36 treatment trials:

- `add-row-aligned-short`
- `add-item-loose`
- `remove-item-non-sequential`
- `check-task-nested`
- `insert-release-at-top`
- `promote-api`
- `insert-nested-ratelimits`
- `insert-troubleshooting`
- `set-build-target`
- `add-build-cache`
- `get-filter-two-columns`
- `get-filter-no-match`

The high-thinking controls are the same task/seed pairs in the already frozen
`ornith_full_auto_20260923` pool. All other environment, prompt, tool, sampling,
turn, timeout, fixture, and grading settings remain unchanged. The treatment
must record `chat_template_kwargs.enable_thinking: false`, zero visible
reasoning characters, and no reasoning leakage.

## Decision rule

Prefer reasoning off for the next complete safe-routed transfer when it:

1. has no transport or framing failures;
2. has no more harmful final documents than the paired high-thinking control;
3. is no worse than one correct trial below the control; and
4. reduces mean elapsed time by at least 50%.

Correctness and final-document safety outrank speed. If off misses the
correctness allowance or increases harm, retain reasoning for a separately
preregistered targeted policy rather than relabeling this panel. If off passes,
run a new 480-row safe-routed pool with distinct filenames; do not resume or
overwrite the interrupted high-thinking pool.
