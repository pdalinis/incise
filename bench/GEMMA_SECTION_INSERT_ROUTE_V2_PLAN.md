# Gemma host-owned section insertion literals v2

Date: 2026-09-22

## Diagnosis and question

Section insertion route v1 improved the frozen population from 4/40 to 28/40
with no harmful outcomes, but failed its 32/40 and per-task gates. All ten
release misses copied an outline path or root heading into `new_heading`; the
two other misses added redundant subsection text to an otherwise exact quoted
body. Anchor selection, placement, mutation count, and executor behavior were
correct in every trial.

This follow-up asks whether the host should own literal insertion content as
well as structure when every field is explicitly recoverable from the request.

## Frozen conditions

- Direct control is the 40 route-v1 pairs. The earlier full-profile-v2 4/40
  result remains the product baseline and is reported as context.
- Model/runtime, Pi version, fixtures, prompts, graders, seeds, and two-turn cap
  are identical to v1.
- Population remains the same four insertion tasks and seeds 0 through 9.
- The adapter must parse the existing anchor, placement relation, new heading,
  every subsection heading, and every quoted body before routing. Release
  headings may be composed only from an explicit version plus ISO date.
- When all fields parse, Pi exposes a zero-argument `section_insert_target`
  confirmation tool. The host executes one atomic `section-insert` call with
  the exact parsed tree and a content-hash precondition. If any field is
  missing or ambiguous, the request falls back to the standard profile.
- Outputs use the immutable prefix
  `gemma_section_insert_route_v2_20260922`.

Transport rows may be retried once. At most one persistent transport pair may
be excluded and must be reported by identity.

## Adoption gate

The route passes only if all conditions hold:

1. At least 39 usable pairs remain, at least 38 are correct, and treatment
   correctness exceeds route v1.
2. Every task scores at least 9/10 among its usable pairs.
3. There are zero destructive or collateral outcomes and at most one
   regression among v1-correct pairs.
4. Every usable first provider request exposes only
   `section_insert_target`, and every model call supplies an empty object.
5. Every successful result reports byte-for-byte canonical resolved arguments,
   and no turn performs more than one successful mutation.

A pass licenses replacing the failed v1 content-slot candidate with v2 in the
Gemma `auto` composition and then running a new full 480-pair confirmation. A
failure removes section insertion from the profile pending a different design.
