# Ornith fallback-route treatment

Recorded 2026-09-23 after freezing the held seeds 10 through 19 control and
before implementing or sampling the proposed routes.

## Evidence and hypothesis

The first held safe-routed validation scored 437/480. Its 220 routed trials
were 220/220 correct with no exact-route audit errors. All 43 misses occurred
in generic fallbacks, concentrated in eleven task shapes:

- three exact list insertions;
- a Setext rename and three exact section appends;
- parent-map deletion, a two-key release update, frontmatter creation on an
  absent document, and setting a key in empty frontmatter.

Each prompt contains literal targets and values that the host can parse
strictly, inspect, resolve uniquely, and execute behind a zero-argument tool.
The two-key release update must be one agent-facing tool and two hash-chained
Incise operations so the model cannot leave a partial or type-coerced result.

## Fixed paired treatment

Implement only strict additions to the shared `safe-routed` profile, with
fallback on any parser, inspection, uniqueness, type, or precondition failure.
Core and CLI behavior remain unchanged. Test these tasks at the same held seeds
10 through 19:

- `add-item-nested-asterisk`
- `add-item-ordered-all-ones`
- `add-item-paren-delimiter`
- `rename-setext`
- `notes-second-ordinal`
- `append-atx-line`
- `append-macos-note`
- `delete-build`
- `release-bump`
- `create-on-absent`
- `fill-empty`

Use the identical Ornith-1.5-9B Q8_0, Pi 0.85.1, official coding sampling,
reasoning-off, 2,048-token, `parallel_tool_calls: false`, four-turn, and
900-second-timeout configuration from `ORNITH_HELD_VALIDATION_PLAN.md`.
The paired control is the immutable matching subset of
`ornith_held_safe_routed_20260923`.

## Gate

Proceed to a second fully held validation only if the treatment has:

- 110/110 correct final documents;
- zero harmful, malformed, transport, framing, reasoning-leak, or excess-
  mutation outcomes;
- exactly one successful agent-facing routed call per trial;
- exact model-supplied and host-resolved arguments for every route;
- atomic all-or-nothing behavior for the two-key release route; and
- mean elapsed time at most 20 seconds, with no completed trial above 60
  seconds.

Because Gemma automatically uses the shared profile, passing Ornith treatment
also requires a targeted Gemma confirmation on the eleven affected tasks
before release. A pass does not change model-agnostic provider defaults.
