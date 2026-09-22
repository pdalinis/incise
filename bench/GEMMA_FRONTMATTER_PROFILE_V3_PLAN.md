# Gemma production typed-frontmatter route v3 plan

Date: 2026-09-22

## Question

Does the production Pi `safe-routed` path reproduce the isolated 50/50
typed-frontmatter prompt result when it must classify the original request,
inspect the file, construct the schema, activate the tool, and execute the
mutation itself?

## Frozen scope

- Treatment evidence is frozen through the 50/50 prompt-v2 pool, raw SHA-256
  `ff09c00cf765768b71cfee8f67e40af821b9c44db433c65bfa357b39551ac4d7`
  and graded SHA-256
  `bfd3fb8a075e3741af3fc0a72a6bb20eb329939136c2720fe6f80fe732b97fcb`.
- Model/runtime, Pi version, executor, five tasks, ten seeds, fixtures, and
  graders remain as preregistered in the v1 and v2 plans.
- Prompts return to the unmodified production benchmark framing. The adapter
  obtains flattened values itself with `incise keys`.
- Outputs use `gemma_frontmatter_profile_v3_20260922` and are append-only.

## Production route

The classifier recognizes only these five narrow existing-key intents:

1. changing the build's parallel job count;
2. switching the build from one named mode to another;
3. updating a named author's role;
4. blanking a named key while explicitly retaining it; and
5. marking an existing document as a draft.

It must not route create-key, delete-key, container deletion, absent/empty
frontmatter creation, or multi-key requests. When matched, the adapter reads
the flattened frontmatter, requires at least one scalar leaf, and exposes the
same enum-constrained `frontmatter_clear` or typed `frontmatter_set_*` schema
measured in v2. The model supplies the key and typed value. The adapter owns
the file, adds `must_exist: true`, writes with the read hash, permits one
successful operation, and appends the exact v2 route instruction plus the
flattened read to the system prompt. Tool choice remains automatic.

Unit tests must cover all five positive shapes and all six unsupported frozen
frontmatter tasks before sampling.

## Gate

All 50 production-profile trials must be usable and correct, with zero harmful
outcomes. Every first provider request must expose exactly the expected single
tool, use automatic tool choice, and contain the route instruction. Every
trial must execute exactly one expected tool with canonical model arguments;
the resolved arguments must additionally contain `must_exist: true`. No trial
may make a second successful mutation.

A pass licenses retaining the route and preregistering a full 480-pair v4
composition run. A failure removes only frontmatter routing; the passing v3
section and table routes remain unchanged.
