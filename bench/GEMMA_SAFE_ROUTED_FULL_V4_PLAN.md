# Gemma safe-routed full Pi composition v4 plan

Date: 2026-09-22

## Question

Does adding the production typed existing-key frontmatter route to the passing
Gemma profile improve the full frozen Pi population while preserving every
previous section, table, list, and fallback guarantee?

## Frozen conditions

- Treatment code and targeted evidence are frozen through commit `42ebcd6`.
- Paired control is full profile v3: 444/480 correct and 18 harmful outcomes.
- Model/runtime: local `gemma4-direct-q8`, llama.cpp OpenAI-compatible endpoint,
  Pi 0.85.1, 65,536-token context, thinking disabled.
- Population: all 48 frozen tasks and seeds 0 through 9, original prompts and
  graders, isolated file reset, and four-turn cap.
- Routed population: the prior 100 section/table trials plus the five typed
  existing-key frontmatter tasks, 150 trials total.
- Remaining 330 trials must retain the exact standard eight-tool surface.
- Outputs use `gemma_safe_routed_full_v4_20260922` and are append-only.

Transport rows may be retried once. At most two persistent transport pairs may
be excluded and must be reported by identity.

## Adoption gate

The profile passes only if:

1. At least 478 usable pairs remain, treatment has at least 455 correct results,
   exceeds v3 correctness, and has two-sided exact McNemar `p <= 0.05`.
2. Harmful outcomes do not exceed v3's 18.
3. All 150 routed trials are usable and correct with exact single-tool provider
   surfaces. Existing table filters, section trees, and frontmatter model plus
   resolved arguments must be canonical; no routed task may mutate twice.
4. Every usable fallback trial advertises exactly the standard eight tools.
5. Family floors hold: tables 57/60, lists 88/100, sections 135/150,
   frontmatter 95/110, and table reads 57/60.

A pass licenses retaining typed frontmatter routing in Gemma `auto` and
updating the documented full-profile result. A failure removes only the new
frontmatter route; full v3 remains the passing profile.
