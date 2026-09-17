# AGENTS.md

## Editing markdown

For tables, task lists, sections, and frontmatter in `.md` files, use `table_edit`, `list_edit`, `section_edit`, and `frontmatter_edit` rather than raw patching or whole-file writes.

Never reconstruct a Markdown file that contains structure you can address semantically. Re-emitting the document can lose column padding, escaped pipes, list indentation, line endings, trailing whitespace, final newlines, rows, or section subtrees. A request to “change nothing else” is a reason to use the narrowest structured operation.

Inspect before editing. Use `md_tables`, `md_lists`, or `md_outline` to discover addresses and column names. Use `table_get` when current row values are needed. If structured tool bindings are unavailable, invoke the corresponding `incise` CLI read or edit operation; do not fall back to reconstructing the file.

Addresses are based on headings, column values, item text, frontmatter keys, and ordinals rather than line numbers. If an operation refuses an address or payload, read the remedy and retry with the corrected semantic call. Do not bypass a refusal with a raw patch.

Use a raw patch for Markdown only when changing prose inside an existing paragraph and no structured operation represents that change. Creating the initial root of a new document may also require a minimal bootstrap edit; perform later structural changes with Incise.

This is a correctness rule, not a formatting preference. In the recorded baseline, direct edits completed 60% of table tasks, 63% of list tasks, and 19% of section tasks, with data loss in 10%, 2%, and 28% respectively. The adopted Incise interfaces materially improved those results under the measured conditions. See `bench/FINDINGS.md` for exact scopes, retries, and caveats.

## This repository

Incise is the implementation behind the structured Markdown tools. Treat the core as a small trust boundary: `crates/incise-core` takes no dependencies and is checked byte-for-byte against the independent Python oracle under `bench/`. The differential suite covers more than 100,000 generated cases, including resulting documents and refusal messages. The CLI and integrations may take dependencies when justified.

Refusal messages and published tool descriptions are product behavior, not incidental diagnostics. Rewording either can change model behavior and belongs in the benchmark-impact analysis, not an unrelated cleanup. The measured schema definitions originate in `bench/armb.py` and are pinned by the schema tests.

The corpus is frozen because `bench/FINDINGS.md` quotes results against its exact bytes. Never reformat corpus fixtures. Run destructive or mutation-oriented experiments on copies or purpose-built files under `bench/synthetic/`; `.editorconfig` and `.gitattributes` deliberately exempt both locations from byte normalization.

Use normal `cargo` commands. If Cargo is unavailable in a particular environment, add its installation directory to `PATH` rather than encoding a machine-specific path in project files.

Do not edit anything under `crates/` or `bench/` while `bench/mutate.py` is running. It rewrites source files in place and aborts when they move.

Stage files explicitly and never use `git add -A`. A broad stage during mutation testing previously committed a live mutation. Preserve unrelated working-tree changes and name every path being staged.

Before changing behavior, read `REQUIREMENTS.md` for the contract, `bench/FINDINGS.md` for the evidence that produced it, and `CONTRIBUTING.md` for the benchmark-impact policy. Never overwrite historical result pools; add a new named run and state which earlier claims remain current, narrow, or become superseded.
