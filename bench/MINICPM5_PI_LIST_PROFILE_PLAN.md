# MiniCPM5 Pi list-profile integration plan

Recorded 2026-09-22 before implementing the Pi treatment or inspecting any Pi treatment outcome.

## Question

The adapter-independent integrated arm improved the seven supported list-addition tasks from 13/21 to 21/21. This follow-up asks whether the same state machine survives the real Pi extension boundary, where tool choice is active-tool restriction rather than an OpenAI forced-function field and file discovery begins from a user prompt.

## Scope and isolation

Add an explicit Pi-only profile selected by `INCISE_PROFILE=minicpm-list`. Do not select it from model identity. The existing `measured` default and experimental `safe-small` profile must retain byte-identical schema objects, registration order, normalization, and execution behavior.

The first profile supports one operation: add one item to one existing Markdown list. Other request families and list actions fail closed. Hermes remains unchanged because its current plugin surface does not expose Pi-equivalent per-turn active-tool replacement.

## State machine

Before the agent starts, require exactly one Markdown path in the raw user prompt, resolve it against Pi's working directory, and read the current list summary through the Incise binary. Ambiguous or missing paths activate no mutation tool.

Classify the raw request with the measured fixed rule:

- standalone `insert` plus standalone `between` selects the between route;
- otherwise `immediately after` selects the after route;
- otherwise the append route is used.

Inject the unchanged Incise list summary into the system prompt. Activate only a `list_select` tool whose separately required `heading` and `ordinal` values are dynamically constrained from that summary. The tool owns the file path. Validate the selected pair against one actual current list.

After a valid selection, read that list through `incise items`, retain its hash and structured item array, return the unchanged renderer text, and activate exactly one route-specific content tool:

- append requires only `text`;
- after requires `text` and an exact returned `after` value;
- between requires `text`, exact returned `after` and `before` values, and host validation that the two items are unique, adjacent, ordered structural siblings.

Compose one ordinary `list-add-item` invocation with the host-owned absolute path, validated address, and retained hash as `if_match`. Execute at most one successful mutation for the user turn. Any repeated content call, stale hash, invalid address, invalid anchor, or malformed payload refuses without another write.

## Deterministic verification

Unit-test path extraction, the three request routes, summary-address parsing, pair validation, exact anchor validation, adjacency/depth/parent checks, canonical argument composition, stale-hash propagation, and the one-successful-write latch.

An extension integration test must drive a mocked Pi event lifecycle through address selection, automatic item inspection, content execution, and a refused duplicate call. Existing measured-profile integration tests and `bench/schematest.py` must remain unchanged and pass.

## Live population and gate

Run the same seven list-addition tasks and three seeds as the integrated arm through the real Pi composition with MiniCPM5 Q8_0, temperature 0.7, top-p 0.95, unchanged fixtures and request text. The paired control remains the 13/21 generic routed-list pool. Each fixed pair is sampled once; only transport failures may resume.

Adopt the Pi profile only if all are true:

1. at least 19/21 final documents are correct;
2. every task is correct in at least two seeds;
3. no control-correct pair regresses;
4. no outcome is destructive or collateral;
5. every refusal leaves the fixture byte-identical;
6. all 21 routes match the preregistered mapping;
7. every executed address and anchor is validated against current structured output;
8. no turn executes more than one successful mutation;
9. the measured Gemma/default schema snapshot remains byte-identical.

A pass licenses the opt-in Pi profile only. It does not change the default, validate Hermes, support other list actions, or establish a general MiniCPM profile. A failure must be localized to path discovery, tool invocation, address selection, content or anchor selection, execution, or post-success stopping before another adapter change.

## Artifacts

Keep new Pi raw, graded, and analysis pools under `bench/results/minicpm5_pi_list_profile_20260922*`. Record Pi and Incise versions, model identity, active tool at each phase, raw calls and results, path and route decisions, structured validation, hashes, mutation count, tokens, and latency. Never overwrite the adapter-independent integrated pool.
