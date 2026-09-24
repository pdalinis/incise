# pi-incise

Structured, byte-preserving Markdown tools for [Pi](https://pi.dev). The package supplies eight tools backed by the native Incise CLI and does not download or compile code during installation.

## Install

Install the stable release with:

```bash
pi install npm:pi-incise
```

Prebuilt binaries are provided for macOS arm64/x64 and glibc Linux arm64/x64. Windows and musl Linux are not supported in v1.

## Recommended model setups

Choose the profile when starting Pi:

* **Ornith 1.5 9B (recommended):** `INCISE_PROFILE=auto pi --thinking off`
* **Gemma (recommended):** `INCISE_PROFILE=auto pi`
* **MiniCPM general editing:** `INCISE_PROFILE=standard pi`
* **MiniCPM list-addition evaluation:** `INCISE_PROFILE=minicpm-list pi`
* **Unknown or changing model families:** `INCISE_PROFILE=standard pi`

For Ornith, configure its Pi model entry with `maxTokens: 2048` and `samplingParams.parallel_tool_calls: false`. The measured result used temperature 0.6, top-p 0.95, top-k 20, min-p 0, presence penalty 0, and repeat penalty 1 through llama.cpp. The profile does not silently change provider decoding settings.

The package default is `standard` for compatibility. `auto` enables the measured `safe-routed` profile for Gemma and Ornith; MiniCPM and unknown families stay on `standard`. If a local provider exposes a generic model ID, set `INCISE_MODEL_FAMILY=gemma`, `INCISE_MODEL_FAMILY=ornith`, `INCISE_MODEL_FAMILY=minicpm`, or `INCISE_MODEL_FAMILY=unknown`.

After Pi starts, run `/incise-doctor`. It reports the requested and effective profiles, detected model family, selected binary, schema state, registered tools, and last route.

## Tools

The default `standard` profile registers `table_edit`, `list_edit`, `section_edit`, `frontmatter_edit`, `table_get`, `md_tables`, `md_lists`, and `md_outline`. Inspect document structure with the relevant read tool before editing, and follow the remedy in any Incise refusal. The former `measured` profile name remains an alias for `standard`.

Set `INCISE_PROFILE=safe-routed` to use guarded request routing directly, or use `auto` with a measured Gemma or Ornith identity. The routed profile retains standard tools as fallback. For requests it can prove unambiguous, it inspects current structure and replaces the broad surface for that turn with one small action-specific tool. Host-owned routes cover measured table predicates, exact list relations and checkbox state, literal section insertion, append, rename, level changes and qualified body replacement, plus typed, create-only, delete, and compound frontmatter edits. Each write carries the inspected hash and permits one successful routed mutation. Ambiguous, unsupported, or structurally inconsistent requests fall back without reinterpretation.

`auto` selects once on the first model-bearing turn. Gemma and Ornith use `safe-routed`; MiniCPM and unknown identities use `standard`. `/incise-doctor` reports the requested profile, effective profile, model family, selection reason, and last route.

Set `INCISE_PROFILE=safe-small` only to evaluate the experimental small-model composition. It omits generic multi-action tools and destructive section/frontmatter operations, but a preregistered MiniCPM5 run failed its family and safety gates, so it is not recommended for general use.

Set `INCISE_PROFILE=minicpm-list` to evaluate the MiniCPM-specific list-addition pipeline. It requires one Markdown path, performs structural selection and item inspection, validates relative anchors, writes with the read hash, and permits at most one successful mutation. The adapter-independent arm reached 21/21 supported additions, while the real Pi composition reached 16/21; it remains opt-in and supports list additions only.

## Measured results

The current Ornith 1.5 9B `auto` profile completed **480/480 full-composition trials (100%) with zero harmful outcomes**. Tables were 60/60, lists 100/100, sections 150/150, frontmatter 110/110, and table reads 60/60. All **360/360 routed trials** passed the exact route audit; all 120 fallback trials retained the standard tool surface. The recorded configuration used the official Q8 checkpoint through llama.cpp, thinking off, `maxTokens: 2048`, and `parallel_tool_calls: false`.

The current Gemma `auto` profile completed **475/479 usable trials (99.2%) with zero harmful outcomes**. Tables, lists, frontmatter, and table reads were perfect; sections were 145/149 with four loud refusals. The later Ornith route additions also passed **60/60 targeted Gemma compatibility trials** across the residual and qualified-preamble changes.

The MiniCPM-specific list pipeline is narrower. Its adapter-independent arm reached **21/21** supported additions from a 13/21 control, while the real Pi profile reached **16/21**. Every executed Pi mutation was correct and no document was damaged; the remaining failures were model no-calls. Keep it opt-in.

These results are tied to the recorded models, llama.cpp runtime, Pi version, prompts, schemas, tasks, seeds, graders, and inference settings. See [the full findings](../../bench/FINDINGS.md), [Ornith final analysis](../../bench/results/ornith_final_v2_safe_routed_20260923_analysis.json), [Ornith route audit](../../bench/results/ornith_final_v2_routes_20260923_analysis.json), and [Gemma v8 analysis](../../bench/results/gemma_safe_routed_full_v8_20260922_analysis.json).

## Binary resolution

The extension uses `INCISE_BIN` first, then the matching optional native package, then `incise` on `PATH`, and finally a release or debug binary from a development checkout. `/incise-doctor` reports the selected path, versions, schema status, and registered-tool count. Version mismatches from explicit overrides are warnings; a mismatched packaged binary disables the tools as an installation-integrity failure.

## Security

Pi extensions and their subprocesses run with the user’s full permissions. Review this package before installation and use OS- or container-level isolation for unattended execution. Incise performs atomic, byte-preserving edits, but it is not a filesystem sandbox.
