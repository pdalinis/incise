# Gemma safe-routed full Pi composition v2 plan

Date: 2026-09-22

## Question

After the 60/60 table-route v2 confirmation, does the corrected production profile improve the full frozen Gemma population enough to recommend `auto` for Gemma in Pi?

## Frozen conditions

- Treatment code and targeted evidence are frozen through commit `b760463`.
- Control remains `gemma_roadmap_20260921_baseline_graded.jsonl` at 390/480 correct.
- Model/runtime: local `gemma4-direct-q8`, llama.cpp OpenAI-compatible endpoint, Pi 0.85.1, 65,536-token context, thinking disabled.
- Population: all 48 frozen tasks and seeds 0 through 9, with the original prompts, graders, file reset, and four-turn cap.
- Routed population: the two exact section tasks and four explicit-predicate table tasks, 60 trials total. Whole-table and ordinal reads are fallback.
- Outputs use the immutable prefix `gemma_safe_routed_full_v2_20260922`.

The first full run found deterministic 240-second generation timeouts on `rename-setext` seeds 1 and 2, repeated once each. This run retries transport rows once. At most two persistent transport pairs may be excluded and are reported by identity; transport is never counted as a semantic success.

## Adoption gate

The profile passes only if all conditions hold:

1. At least 478 usable pairs remain, treatment has at least 400 correct results, exceeds paired control correctness, and has two-sided exact McNemar `p <= 0.05`.
2. Harmful outcomes (`wrong`, `destructive`, or either collateral class) do not exceed paired control.
3. All 60 routed trials are usable and correct, with exact single-tool provider surfaces and byte-identical ideal filters for routed table reads.
4. Every usable fallback trial advertises exactly the standard eight-tool surface.
5. Family correctness floors hold: tables 57/60, lists 88/100, sections 102/150, frontmatter 74/110, and table reads 46/60.

A pass licenses documenting `auto` as the recommended Pi mode for detected Gemma models while retaining `standard` as the package default for one release cycle. A failure keeps both `safe-routed` and `auto` experimental and requires diagnosis before further sampling.
