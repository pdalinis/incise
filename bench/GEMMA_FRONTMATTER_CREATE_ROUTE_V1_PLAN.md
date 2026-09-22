# Gemma guarded frontmatter-create route v1 plan

Date: 2026-09-22

## Question

Can a host-resolved, create-only frontmatter route eliminate Gemma's remaining
`build.caching` substitutions without permitting an existing key or parent map
to be overwritten?

## Frozen conditions

- Paired control is the matching full-v5 `add-build-cache` pool: 4/10 correct,
  four wrong `build.caching` writes, and two loud operation errors.
- Population is `add-build-cache` at seeds 0 through 9, ten pairs total.
- Model/runtime is local `gemma4-direct-q8`, llama.cpp, Pi 0.85.1, 65,536-token
  context, thinking disabled, and the production `safe-routed` profile.
- Original prompt, fixture, grader, isolated reset, and four-turn cap are
  unchanged.
- Outputs use `gemma_frontmatter_create_route_v1_20260922` and are append-only.

## Treatment

Recognize only the measured request, `Turn on caching for the build.`, after
removing the benchmark's structural-summary preamble or Pi's optional
`In @file,` prefix. Before inference, the adapter must:

1. extract exactly one Markdown path;
2. inspect flattened frontmatter values;
3. require YAML frontmatter in the present state;
4. require `build` to be an existing map;
5. require both `build.cache` and `build.caching` to be absent; and
6. retain the inspection content hash.

It then exposes only zero-argument `frontmatter_create_target`. The adapter
supplies `key=build.cache`, boolean `value=true`, and `must_absent=true`, writes
with the inspection hash, and permits one successful mutation. Any failed
precondition or unsupported request falls back to the standard profile.

Transport failures may be retried once. No other pair may be resampled.

## Gate

All ten treatment trials must be usable and correct, with zero destructive or
collateral outcomes and zero regressions among the four baseline-correct pairs.
The six treatment-only recoveries must give two-sided exact McNemar `p <= 0.05`.
Every first provider request must expose exactly `frontmatter_create_target`
under automatic tool choice and include its route-specific instruction; every
model call must supply `{}`; every resolved argument must equal
`{"key":"build.cache","value":true,"must_absent":true}`; and no trial may
mutate twice.

A pass licenses retaining the route and preregistering a full v6 composition
run. A failure removes only guarded frontmatter creation; full v5 remains
current.

## Non-goals

This experiment does not generalize arbitrary natural-language key names,
create top-level frontmatter keys, create parent maps, route frontmatter
deletion, or change the standard `frontmatter_edit` schema.
