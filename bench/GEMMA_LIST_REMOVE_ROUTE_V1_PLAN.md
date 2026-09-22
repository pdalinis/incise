# Gemma exact list-removal route v1 plan

Date: 2026-09-22

## Question

Can a host-resolved exact-item removal route eliminate Gemma's destructive
positional reinterpretation of a quoted list item without regressing an
already-correct removal task?

## Frozen conditions

- Paired control is the matching full-v4 pool. `remove-item-non-sequential`
  scored 5/10, with four destructive results and one collateral-content
  result; `remove-item-mixed` scored 10/10.
- Population is those two tasks at seeds 0 through 9, 20 pairs total.
- Model/runtime is local `gemma4-direct-q8`, llama.cpp, Pi 0.85.1, 65,536-token
  context, thinking disabled, and the production `safe-routed` profile.
- Original prompts, fixtures, graders, and isolated resets are unchanged.
- Outputs use `gemma_list_remove_route_v1_20260922` and are append-only.

## Treatment

Recognize only requests that explicitly name both the existing list and the
existing item in quotation marks while asking to remove that item. Support the
two measured word orders: `remove ... from the list under ...` and `in the list
under ..., remove ...`.

Before inference, the adapter must:

1. extract exactly one Markdown path;
2. inspect current lists and resolve the quoted heading to one unique suffix;
3. inspect that list's actual items;
4. require the quoted item text to match exactly one current item; and
5. retain the item-read content hash.

It then exposes only zero-argument `list_remove_target`. The adapter supplies
the file, full heading plus ordinal, and exact `match`, invokes
`list-remove-item` with the read hash, and permits one successful mutation.
Any ambiguity or unsupported request falls back to the standard profile.

Transport failures may be retried once. No other pair may be resampled.

## Gate

All 20 treatment trials must be usable and correct, with zero destructive or
collateral outcomes and zero regressions among the 15 baseline-correct pairs.
Every first provider request must expose exactly `list_remove_target`; every
model call must supply `{}`; every resolved argument must equal the canonical
full list address and exact item text; and no trial may mutate twice.

A pass licenses retaining the route and preregistering a full v5 composition
run. A failure removes only list removal routing; full v4 remains current.
