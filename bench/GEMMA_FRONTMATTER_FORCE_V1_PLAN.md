# Gemma forced typed-frontmatter route v1 plan

Date: 2026-09-22

## Question

The preregistered typed existing-key frontmatter route improved its targeted
population from 26/50 to 45/50 and eliminated destructive outcomes, but missed
its strict gate because five trials answered in prose instead of calling the
sole active tool. Does forcing that exact tool recover all five without
changing the route, arguments, prompt, or executor behavior?

## Frozen conditions

- Paired control is the immutable typed-frontmatter pool
  `gemma_roadmap_20260921_frontmatter`: raw SHA-256
  `ee50a36105747d70e6d17a8db53495f39d4fb29f0e6b3372415dfcbeddfc246b`
  and graded SHA-256
  `c3825e775a5853b762507ed916644729cf77780273c76487329605f1cbf8e0d2`.
- Control is 45/50 correct. Its five failures are no-tool prose responses on
  `clear-title` trials 1 and 6, `set-build-jobs` trial 6, and
  `set-draft-true` trials 1 and 6.
- Population is the same five tasks and seeds 0 through 9: `set-build-jobs`,
  `set-build-target`, `set-dana-role`, `clear-title`, and `set-draft-true`.
- Model/runtime is local `gemma4-direct-q8` through llama.cpp at
  `127.0.0.1:8081`, Pi 0.85.1, 65,536-token context, and thinking disabled.
- Fixtures and graders are frozen by `bench/tasks/frontmatter.json`, SHA-256
  `f1279fd405ed2fab140a6948881f7db9243a87dcd201d7e10efb86958f4c8989`.
- The typed-route implementation is frozen by
  `bench/gemma_bench_extension.ts`, SHA-256
  `8754801ad4c14202dede37a006b12c091c0cf6643c1fd0d24b6e0076555d7f4d`.
- Raw outputs use the new immutable prefix
  `gemma_frontmatter_force_v1_20260922`.

## Treatment

Use the same prompt, flattened frontmatter read, one typed action-specific
tool, enum of existing scalar paths, `must_exist: true`, two-turn cap, and
Incise invocation as the control. The only change is an OpenAI-compatible
`tool_choice` naming the sole advertised routed tool on provider requests where
that tool is present. Requests after success, when no route tool is active,
must not be forced.

Transport failures may be retried once. No other pair may be resampled.

## Gate

The targeted route passes only if all of the following hold:

1. All 50 pairs are usable and all 50 treatment results are correct.
2. There are no destructive or collateral outcomes and no control-only wins.
3. Every first routed provider request advertises exactly the expected single
   tool and carries the exact matching function `tool_choice`.
4. Every successful mutation uses exactly that tool once, with the canonical
   key and typed value for its task; no other tool call or mutation occurs.
5. The route configurations remain identical to the frozen control.

The paired exact McNemar result is reported but is not a targeted-arm gate:
with only five available gains, a perfect 0-to-5 split has two-sided
`p = 0.0625`. A pass licenses production integration behind Gemma
`safe-routed` followed by a new full 480-pair composition run. It does not by
itself license updating `auto` claims.
