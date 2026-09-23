# Gemma typed-frontmatter route prompt v2 plan

Date: 2026-09-22

## Question

Forced `tool_choice` left the typed existing-key route unchanged at 45/50.
Every request carried the exact forced name, but the same five responses used
prose and several explicitly reasoned that no tool was available because Pi's
base system prompt says `Available tools: (none)` for dynamically registered
custom tools. Does one route-specific system instruction close that discovery
gap without changing the tool or its arguments?

## Frozen conditions

- Paired control remains the original typed-frontmatter pool: raw SHA-256
  `ee50a36105747d70e6d17a8db53495f39d4fb29f0e6b3372415dfcbeddfc246b`
  and graded SHA-256
  `c3825e775a5853b762507ed916644729cf77780273c76487329605f1cbf8e0d2`.
- The failed forced arm is retained separately. It scored the same 45/50 with
  raw SHA-256
  `19e14dfc3a277c6d05db4f187f35f0b1bdbd0d2d22257fbbab2b7e7c5e97936d`.
- Population, tasks, seeds, model, runtime, Pi version, executor, fixtures,
  flattened read, typed tool schema, prompt, two-turn cap, and grading are the
  same as `GEMMA_FRONTMATTER_FORCE_V1_PLAN.md`.
- Outputs use the new immutable prefix
  `gemma_frontmatter_prompt_v2_20260922`.

## Treatment

Remove forced `tool_choice`. Append exactly one route-specific paragraph to
the Pi system prompt:

> Incise inspected the frontmatter and activated `<tool>`. This custom tool is
> available even if the base tool summary says none. Call `<tool>` exactly
> once to perform the requested edit; do not describe or simulate the call.

The expected typed tool name is substituted for `<tool>`. Nothing else changes:
the model still supplies the enum-constrained existing key and typed value, and
the adapter still adds `must_exist: true`.

Transport failures may be retried once. No other pair may be resampled.

## Gate

The arm passes only if all 50 pairs are usable and correct, with zero harmful
outcomes and zero control-only wins. Every routed provider request must expose
exactly the expected single tool, carry automatic (null) `tool_choice`, and
contain the exact appended instruction. Every successful mutation must use the
expected tool once with canonical arguments, and every route configuration
must match the frozen control.

A pass licenses integrating the same instruction with a narrow Gemma
frontmatter route and running a new full 480-pair composition evaluation. A
failure rejects prompt-only repair and moves the next experiment to a
host-owned zero-argument mutation.
