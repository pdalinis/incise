# Gemma safe-routed full Pi composition v3 plan

Date: 2026-09-22

## Question

After the 40/40 host-owned section-insertion confirmation, does adding that
route to the passing production profile improve the full frozen Gemma/Pi
population without regressing other operations?

## Frozen conditions

- Treatment code and targeted evidence are frozen through commit `4e7c889`.
- Paired control is the passing full-profile-v2 pool at 406/480 correct and 28
  harmful outcomes.
- Model/runtime: local `gemma4-direct-q8`, llama.cpp OpenAI-compatible endpoint,
  Pi 0.85.1, 65,536-token context, thinking disabled.
- Population: all 48 frozen tasks and seeds 0 through 9, with original prompts,
  graders, isolated file reset, and four-turn cap.
- Routed population: two exact section guard tasks, four explicit-predicate
  table reads, and four explicit section-insertion tasks, 100 trials total.
- Remaining 380 trials must retain the exact standard eight-tool surface.
- Outputs use the immutable prefix `gemma_safe_routed_full_v3_20260922`.

Transport rows may be retried once. At most two persistent transport pairs may
be excluded and must be reported by identity.

## Adoption gate

The profile passes only if all conditions hold:

1. At least 478 usable pairs remain, treatment has at least 430 correct results,
   exceeds paired v2 correctness, and has two-sided exact McNemar `p <= 0.05`.
2. Harmful outcomes do not exceed the paired v2 control count of 28.
3. All 100 routed trials are usable and correct, with exact single-tool
   provider surfaces. Table filters and section-insertion resolved arguments
   must match their canonical values; insertion model arguments must be empty.
4. Every usable fallback trial advertises exactly the standard eight tools.
5. Family floors hold: tables 57/60, lists 88/100, sections 135/150,
   frontmatter 74/110, and table reads 57/60.

A pass licenses retaining section insertion in Gemma `auto` and updating its
documented measured scope. A failure removes only the insertion route; the
already passing v2 rename, body-replacement, and table-query routes remain.
