# Gemma safe-routed full Pi composition plan

Date: 2026-09-22

## Question

Does the production Pi `safe-routed` profile improve the complete frozen Gemma task population without degrading requests that fall back to the standard Incise tools?

## Frozen conditions

- Treatment: `plugins/pi/extension/index.ts` at commit `7c480b2`, with `INCISE_PROFILE=safe-routed`.
- Control: `bench/results/gemma_roadmap_20260921_baseline{,_graded}.jsonl` from the current-checkout standard profile.
- Model/runtime: local `gemma4-direct-q8`, llama.cpp OpenAI-compatible endpoint, Pi 0.85.1, 65,536-token context, thinking disabled.
- Population: all 48 frozen tasks, seeds 0 through 9, for 480 paired trials.
- Prompts, file reset, maximum four turns, and family graders are unchanged from the control.
- A deterministic classifier preflight found six routed tasks: `rename-closed-atx`, `replace-linux-body`, `get-filter-one-column`, `get-filter-two-columns`, `get-filter-no-match`, and `get-escaped-cell`. The narrow confirmation previously measured both section tasks plus `get-filter-two-columns` and `get-filter-no-match`; the single-column and escaped-cell routes are newly tested here. The other 42 tasks must receive the standard eight-tool surface.
- Outputs use the new immutable prefix `gemma_safe_routed_full_20260922`.

No MiniCPM or Hermes claim is in scope. Persistent transport failures are reported separately and prevent the 480-pair gate from passing.

## Adoption gate

The full profile passes only if all conditions hold:

1. All 480 pairs are usable and at least 400 treatment trials are correct, compared with 390 in control.
2. Treatment correctness exceeds control with two-sided exact paired McNemar `p <= 0.05`.
3. Harmful outcomes (`wrong`, `destructive`, or either collateral class) do not exceed control.
4. All 60 routed trials are correct, have zero harmful, unfiltered, or misreported outcomes, and advertise exactly the selected route-specific tool on the first provider request.
5. All 420 fallback trials advertise exactly the standard eight-tool surface; no more than five baseline-correct fallback pairs regress.
6. Family correctness floors hold: tables 57/60, lists 88/100, sections 102/150, frontmatter 74/110, and table reads 46/60. These are five-percentage-point noninferiority bounds rounded conservatively to whole trials.

A pass licenses making `auto` the recommended Pi mode for Gemma, but the package default remains `standard` until the installation and migration behavior is explicitly changed and tested. A failure leaves `safe-routed` opt-in and is diagnosed by routed versus fallback strata before any resampling.
