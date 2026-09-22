# Gemma safe-routed production-profile confirmation

Date: 2026-09-22

## Question

Does the production Pi `safe-routed` profile preserve the gains measured with the isolated Gemma benchmark extension when target discovery, tool activation, execution, and the one-success latch run through the shipped adapter path?

## Frozen scope

- Model and runtime: the same local `gemma4-direct-q8` llama.cpp endpoint, Pi 0.85.1, 65,536-token context, thinking disabled, and seeds 0 through 9 used by the 2026-09-21 roadmap campaign.
- Product extension: `plugins/pi/extension/index.ts` with `INCISE_PROFILE=safe-routed`.
- Tasks: `rename-closed-atx`, `replace-linux-body`, `get-filter-two-columns`, and `get-filter-no-match`.
- Trials: 10 per task, 40 total.
- Prompts and graders: unchanged from `bench/gemma_roadmap.py`.
- Historical control: the matching rows in `gemma_roadmap_20260921_baseline_graded.jsonl`.
- New output names use the immutable prefix `gemma_safe_routed_profile_20260922`.

The frontmatter typed-value arm is excluded because it failed its preregistered no-regression gate. Generic section insertion is excluded because it regressed sharply. No MiniCPM behavior is included in this confirmation.

## Gates

Each of the two arms must independently satisfy all of the following:

1. At least 18 of 20 trials are correct.
2. Zero destructive, collateral-content, collateral-formatting, unfiltered, or misreported outcomes.
3. Zero regressions among matching baseline-correct trials.
4. The first provider request advertises exactly the route-specific tool selected by the production classifier.
5. All 40 planned results are present.

Passing licenses continued opt-in evaluation of `safe-routed`; it does not change the package default. Default `auto` adoption requires a later full-composition run across the complete task population. Failure leaves `standard` as the supported profile and requires fixing or narrowing the production classifier before resampling.
