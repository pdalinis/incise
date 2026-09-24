# Ornith routed, reasoning-off pilot

Recorded 2026-09-23 after the reasoning-mode panel and before collecting any
safe-routed, reasoning-off outcome.

## Prior evidence

On the preregistered 36-pair standard-profile panel, reasoning off was 14/36
correct with 13 harmful final documents versus 16/36 and 11 harmful with
reasoning on. It failed the correctness and safety criteria, despite reducing
mean latency from 117.1 seconds to 29.0 seconds. The effects were heterogeneous:
non-sequential list removal improved from 0/3 to 3/3, while nested section
insertion regressed from 3/3 to 0/3.

The existing high-thinking safe-routed pool independently showed that a routed
list-removal schema improved non-sequential removal from 0/10 to 10/10 and cut
typical latency to 9–29 seconds. This motivates testing the combination rather
than adopting reasoning off globally.

## Treatment and panel

Run the same 12 tasks and seeds 0, 1, and 2 defined in
`ORNITH_THINKING_PLAN.md`, this time with `INCISE_PROFILE=safe-routed` and Pi
thinking `off`. All remaining environment, prompt, sampling, turn, timeout,
fixture, and grading settings are unchanged.

The comparison is descriptive against both existing standard-profile panels.
The go/no-go gate for a complete 480-row reasoning-off safe-routed transfer is:

- at least 30/36 correct;
- zero harmful final documents;
- no transport or provider-framing error;
- no reasoning leakage; and
- mean elapsed time no greater than 45 seconds.

This pilot may justify the full combined treatment only. It cannot justify
reasoning off for the standard profile or Ornith auto-detection. If it fails,
diagnose route coverage and preregister a narrower hybrid; do not weaken the
gate or silently replace either prior pool.
