# Hermes safe-routed parity plan

Recorded 2026-09-24 before implementing Hermes request routing or sampling any
Hermes treatment call.

## Question

Can the released Hermes plugin select the same guarded, model-aware Incise
routes as Pi while retaining Hermes file-safety policy, standard-tool fallback,
and result framing? Can that integration reproduce the current Ornith and Gemma
full-composition correctness and zero-harm results through the real Hermes agent
loop?

The current Ornith and Gemma routed claims are Pi-only. Hermes currently
registers the standard model-agnostic composition. A shared
`INCISE_PROFILE=auto` environment now falls back safely to that standard
composition, but that compatibility behavior is not routed parity.

## Proposed adapter behavior

Under explicit `INCISE_PROFILE=safe-routed`, or under `auto` when the turn model
is identified as Gemma or Ornith, the Hermes plugin will:

1. inspect the user request once at turn start;
2. resolve the same exact route and current document structure used by the Pi
   profile;
3. use Hermes `llm_request` middleware to remove the broad Incise schemas and
   expose exactly one request-specific Incise tool while preserving unrelated
   toolsets;
4. keep the standard eight-tool surface byte-identical when no exact route is
   proven;
5. execute host-resolved arguments with the inspected content hash, Hermes read
   and write safety checks, same-file serialization, rollback for compound
   operations, and at most one successful routed mutation per turn; and
6. remove Incise mutation tools from later provider calls after a routed
   success.

The adapter must not silently change reasoning, sampling, output caps, or
parallel-tool settings. Ornith is evaluated with the already adopted settings:
thinking/reasoning off, a 2,048-token output cap, and parallel tool calls
disabled. Gemma retains its recorded provider defaults.

## Deterministic gates before live sampling

- Every route parser, outline/list/table/frontmatter precondition, dynamic
  schema, resolved argument object, fallback, stale-hash refusal, rollback, and
  success latch has a Hermes adapter test.
- A parity audit over the frozen 48-task population must produce the same 360
  routed and 120 fallback decisions as the final Pi Ornith audit, including the
  exact route tool name and host-resolved arguments.
- Middleware tests must prove that foreign tools survive, inactive Incise route
  tools never reach the provider, unknown/MiniCPM identities retain the
  standard surface, and Gemma/Ornith identities select routing under `auto`.
- The real installed Hermes host-safety suite and Plugin Doctor must pass.
- Existing standard and `safe-small` Hermes schemas, ordering, handlers, and
  model-visible bytes remain unchanged when those profiles are selected.

Failure of any deterministic gate blocks live sampling.

## Live conditions

All live trials use purpose-built copies under a temporary benchmark directory,
the official local checkpoints, llama.cpp through the existing OpenAI-compatible
endpoint, Hermes Agent 0.21.3, the frozen 48-task population and graders, and
automatic tool choice. Each row records model identity, Hermes and Incise
versions, profile, task, seed, request, provider-visible Incise tools, raw tool
calls/results, route, resolved arguments, hashes, mutation count, elapsed time,
token usage, final bytes, and grade.

1. **Route smoke:** one treatment call for each of the 48 tasks before any full
   arm. This diagnoses provider-schema and event-loop integration. It is not an
   efficacy result.
2. **Ornith control:** standard Hermes composition, seeds 40 through 49, 480
   trials.
3. **Ornith treatment:** Hermes `auto`, the same tasks and seeds, 480 paired
   trials.
4. **Gemma treatment compatibility:** Hermes `auto`, seeds 40 through 49, 480
   trials after switching the local endpoint to Gemma.

One transport or ordinary-action timeout may be retried once with the same
condition, task, seed, and settings. Both attempts remain recorded. A harmful
treatment result stops that treatment arm immediately for diagnosis and a new
preregistered repair; results before the stop remain immutable. No treatment
route or prompt is changed after its first valid sample.

## Release gates

Hermes routed support is documented as recommended only if:

- each treatment has 480 usable trials after the allowed identical retry;
- Ornith reaches at least 475/480 correct and Gemma reaches at least 475/480
  correct; 480/480 remains the Ornith parity target;
- neither treatment has silent corruption, data loss, an incorrect successful
  mutation, or more than one successful mutation in a turn;
- every expected routed row exposes exactly one Incise route tool, uses the
  expected tool and canonical host-resolved arguments, and preserves unrelated
  tools;
- all expected fallback rows retain the byte-identical standard Incise surface;
- the paired Ornith treatment has no task-family regression greater than one
  observation against its Hermes standard control; and
- all deterministic, Rust, differential, schema, replay, Pi, packaging, and
  Hermes tests pass.

If correctness passes but a latency outlier exceeds 120 seconds, correctness may
ship only with the tail-latency caveat stated beside the result. A failed gate
keeps Hermes on the standard profile; Pi evidence and behavior remain current.

## Artifacts

New files are append-only and use these prefixes:

- `hermes_route_smoke_20260924`
- `ornith_hermes_standard_20260924`
- `ornith_hermes_safe_routed_20260924`
- `gemma_hermes_safe_routed_20260924`
- `hermes_safe_routed_parity_20260924`

No earlier pool is overwritten. Analysis must distinguish deterministic route
parity, live integration correctness, and cross-integration comparison; a Pi
result is never relabeled as a Hermes result.
