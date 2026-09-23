# Gemma section insertion request-boundary correction v3

Date: 2026-09-22

## Diagnosis and question

V2 never exposed its intended routed tool. Pi benchmark prompts begin with an
Incise structural summary, a blank line, and then the user request. The summary
contains a quoted example address, so the exact-literal parser saw too many
quoted values and conservatively selected the standard fallback in all 40
trials.

This revision asks whether parsing the request block, rather than the generated
structural preamble, allows the otherwise unchanged host-owned insertion route
to meet its gate.

## Frozen conditions

- The only treatment change is the parser boundary: if a prompt begins with
  Incise `Sections in ...` summary framing, insertion intent is parsed from the
  text after the first blank line. Prompts without that framing remain whole.
- A unit test must include the real quoted summary example and all four frozen
  request forms before sampling.
- All other route-v2 behavior remains fixed: exact anchor resolution, exact
  version/date and quoted-body parsing, zero-argument tool, one atomic write,
  content-hash precondition, one-success latch, and standard fallback on any
  ambiguity.
- Population, model/runtime, Pi version, fixtures, seeds, graders, and two-turn
  cap remain identical to v1 and v2.
- Direct control remains route v1 at 28/40; full-profile-v2 at 4/40 remains the
  product baseline. The invalid v2 fallback sample is reported but is not the
  behavioral control.
- Outputs use the immutable prefix
  `gemma_section_insert_route_v3_20260922`.

Transport rows may be retried once. At most one persistent transport pair may
be excluded and must be reported by identity.

## Adoption gate

The v2 gate is retained unchanged:

1. At least 39 usable pairs remain, at least 38 are correct, and treatment
   correctness exceeds route v1.
2. Every task scores at least 9/10 among its usable pairs.
3. There are zero destructive or collateral outcomes and at most one
   regression among v1-correct pairs.
4. Every usable first provider request exposes only
   `section_insert_target`, and every model call supplies an empty object.
5. Every successful result reports byte-for-byte canonical resolved arguments,
   and no turn performs more than one successful mutation.

A pass licenses the route for the Gemma `auto` composition and a new full
480-pair confirmation. A failure removes section insertion from the profile
pending a different design.
