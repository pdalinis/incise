# Ornith qualified-preamble route

Recorded 2026-09-23 after the final seeds 30 through 39 holdout stopped at
238/480 because `replace-install-preamble` seed 31 destructively replaced the
root section body. This plan precedes implementation and any treatment samples.

## Evidence and treatment

The failed trial correctly read the outline, then copied `Deep heading nesting`
instead of `Install` into `section_edit`. The executor safely preserved every
subsection, but the successful call changed the wrong section body and the
model's verification read did not detect the error.

Recognize only the benchmark's explicit qualified form: replace the
introductory paragraph under a named section, identified as the paragraph
before a named subsection, with an exact quoted replacement. Resolve the named
section uniquely against `md_outline`, verify that the named subsection is its
direct child, and publish `section_replace_target` with no arguments. The host
owns the file, resolved section, literal replacement, overwrite acknowledgement,
and read hash. Fall back on every parse, hierarchy, or uniqueness failure. Core
and CLI behavior remain unchanged.

## Targeted and compatibility gates

Run `replace-install-preamble` against Ornith seeds 30 through 39 using the
same reasoning-off, 2,048-token, `parallel_tool_calls: false`, four-turn
configuration. Require 10/10 correct, zero harmful outcomes, exactly one
successful zero-argument routed mutation per trial, exact host-resolved
arguments, and no framing or reasoning-leak errors.

Run `replace-install-preamble` and the existing `replace-linux-body` route
against Gemma seeds 0 through 9 with normal provider defaults. Require 20/20
correct, zero harmful outcomes, and unchanged exact route behavior. This
confirms the dynamic body-bearing route remains intact while the qualified
request uses the host-owned variant.

## Fresh final holdout

The aborted 238-sample pool remains historical evidence and is never combined
with post-change samples. After both targeted gates pass, rerun all 48 tasks at
Ornith seeds 30 through 39 into a new result pool. Apply the unchanged release
gate: at least 478 usable, at least 472 correct, zero harmful final documents,
lists 100/100, sections at least 140/150, frontmatter at least 105/110, each
table family at least 57/60, and zero route, framing, reasoning-leak, or
excess-mutation errors.
