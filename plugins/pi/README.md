# pi-incise

Structured, byte-preserving Markdown tools for [Pi](https://pi.dev). The package supplies eight tools backed by the native Incise CLI and does not download or compile code during installation.

## Install

Install the stable release with:

```bash
pi install npm:pi-incise
```

Prebuilt binaries are provided for macOS arm64/x64 and glibc Linux arm64/x64. Windows and musl Linux are not supported in v1.

## Tools

The default `standard` profile registers `table_edit`, `list_edit`, `section_edit`, `frontmatter_edit`, `table_get`, `md_tables`, `md_lists`, and `md_outline`. Inspect document structure with the relevant read tool before editing, and follow the remedy in any Incise refusal. The former `measured` profile name remains an alias for `standard`.

Set `INCISE_PROFILE=safe-routed` before starting Pi to use model-agnostic request routing directly. It retains the standard tools as a fallback, but for requests it can prove unambiguous it replaces them for that turn with one small, action-specific tool. The current measured routes are exact section rename, exact section-body replacement, explicit literal section insertion, exact quoted-sentence section append, table reads with explicit column/value predicates, typed edits to existing frontmatter keys, guarded creation of `build.cache`, exact quoted list-item removal, and same-heading list append resolved by an exact existing item. The adapter resolves the file and structural target, owns exact table filters and insertion or append content, constrains existing-key paths to inspected scalar leaves, verifies `build` is a map and `build.cache` is absent before create-only writes, validates exact current list items before removal or containing-item selection, uses a content hash plus `must_exist` or `must_absent` where applicable, permits one successful routed operation, and leaves tools from other extensions active. Ambiguous targets, fuzzy item matches, unsupported append wording, whole-table reads, ordinal reads, other frontmatter creation, frontmatter deletion or multi-key changes, and unsupported requests fall back to the standard profile.

`INCISE_PROFILE=auto` is the recommended Gemma setup. It selects capabilities from the active Pi model identity: Gemma uses `safe-routed`, while MiniCPM and unknown families remain on `standard` because no general MiniCPM composition has passed evaluation. Selection is fixed on the first model-bearing turn. If a local provider exposes a generic model ID, set `INCISE_MODEL_FAMILY=gemma`; `minicpm` and `unknown` are also accepted. `/incise-doctor` reports the requested profile, effective profile, detected model family, selection reason, and last route. The latest full Gemma/Pi treatment attempted all 480 trials and retained 479 paired rows after one persistent generation timeout. Correctness rose from 473/479 to 475/479 and harmful outcomes fell from 1 to 0. Lists reached 100/100, sections 145/149 with only loud refusals, frontmatter 110/110, and tables plus table reads 60/60. All 200 routed trials were correct, and all 279 usable fallback trials retained the standard tool surface. The package default remains `standard` for one compatibility release cycle.

Set `INCISE_PROFILE=safe-small` only to evaluate the experimental small-model composition. It exposes `md_tables`, `table_get`, `table_add_row`, `table_update_cell`, `md_lists`, `list_get`, `list_add_item`, `md_outline`, `section_insert`, `section_append`, `frontmatter_get`, and `frontmatter_set`. It intentionally omits generic multi-action tools and destructive section/frontmatter operations. A preregistered MiniCPM5 run found a significant list-addition gain but section and frontmatter regressions, including 0/27 correct frontmatter trials, so this profile is not recommended for general use.

Set `INCISE_PROFILE=minicpm-list` to evaluate the MiniCPM-specific list-addition pipeline. Each request must name exactly one Markdown path. Pi activates a required heading-and-ordinal selector, reads the selected list, then activates one append, after, or between content tool with exact current-item constraints. The adapter supplies the file and list address, validates relative anchors, writes with the read hash, and permits at most one successful mutation in that user turn. The adapter-independent arm reached 21/21 supported additions, while the real Pi composition reached 16/21; keep this profile opt-in. It supports adding list items only.

The preregistered real-Pi run reached 16/21 rather than the adapter-independent result of 21/21. Every executed mutation was correct and no document was damaged, but five trials stopped in prose instead of invoking the sole active phase tool. A paired forced-choice follow-up also reached 16/21 even though every observed active-phase request transmitted the exact advertised tool choice; the local MiniCPM/llama.cpp path did not enforce it. Compact list-only framing reached 19/21 and eliminated all no-call failures, but two previously correct trials wrote the wrong new item text. Neither treatment is shipped, and the profile remains evaluation-only.

## Binary resolution

The extension uses `INCISE_BIN` first, then the matching optional native package, then `incise` on `PATH`, and finally a release or debug binary from a development checkout. `/incise-doctor` reports the selected path, versions, schema status, and registered-tool count. Version mismatches from explicit overrides are warnings; a mismatched packaged binary disables the tools as an installation-integrity failure.

## Security

Pi extensions and their subprocesses run with the user’s full permissions. Review this package before installation and use OS- or container-level isolation for unattended execution. Incise performs atomic, byte-preserving edits, but it is not a filesystem sandbox.
