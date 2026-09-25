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
* **MiniCPM5 2B (recommended):** `INCISE_PROFILE=auto pi --thinking off`
* **Unknown or changing model families:** `INCISE_PROFILE=standard pi`

For Ornith, configure its Pi model entry with `maxTokens: 2048` and `samplingParams.parallel_tool_calls: false`. The measured result used temperature 0.6, top-p 0.95, top-k 20, min-p 0, presence penalty 0, and repeat penalty 1 through llama.cpp.

For MiniCPM5, the measured result used the official Q8_0 checkpoint through llama.cpp, thinking off, a 65,536-token context, `maxTokens: 8192`, temperature 0.7, and top-p 0.95. The profile does not silently change provider decoding settings.

The package default is `standard` for model-agnostic compatibility. `auto` enables the measured `safe-routed` profile for Gemma, MiniCPM, and Ornith; unknown families stay on `standard`. If a local provider exposes a generic model ID, set `INCISE_MODEL_FAMILY=gemma`, `INCISE_MODEL_FAMILY=minicpm`, `INCISE_MODEL_FAMILY=ornith`, or `INCISE_MODEL_FAMILY=unknown`.

After Pi starts, run `/incise-doctor`. It reports the requested and effective profiles, detected model family, selected binary, schema state, registered tools, and last route.

## Tools

The default `standard` profile registers `table_edit`, `list_edit`, `section_edit`, `frontmatter_edit`, `table_get`, `md_tables`, `md_lists`, and `md_outline`. Inspect document structure with the relevant read tool before editing, and follow the remedy in any Incise refusal. The former `measured` profile name remains an alias for `standard`.

Set `INCISE_PROFILE=safe-routed` to use guarded request routing directly, or use `auto` with a measured Gemma, MiniCPM, or Ornith identity. The routed profile retains standard tools as fallback. For requests it can prove unambiguous, it inspects current structure and replaces the broad surface for that turn with one small action-specific tool. Host-owned routes cover exact table reads and mutations, list relations and checkbox state, literal section insertion, append, deletion, rename, level changes and qualified body replacement, plus typed, create-only, delete, and compound frontmatter edits. Each write carries the inspected hash and permits one successful routed mutation. Ambiguous, unsupported, or structurally inconsistent requests fall back without reinterpretation.

`auto` selects once on the first model-bearing turn. Gemma, MiniCPM, and Ornith use `safe-routed`; unknown identities use `standard`. `/incise-doctor` reports the requested profile, effective profile, model family, selection reason, and last route.

Set `INCISE_PROFILE=safe-small` only to reproduce the earlier experimental small-model composition. It omits generic multi-action tools and destructive section/frontmatter operations, but that older MiniCPM5 run failed its family and safety gates and has been superseded by the measured `auto` route profile.

Set `INCISE_PROFILE=minicpm-list` only to reproduce the earlier MiniCPM-specific list-addition pipeline. It supports list additions only; the general MiniCPM recommendation is now `auto`.

## Measured results

The current MiniCPM5 2B `auto` profile completed **480/480 full-composition trials (100%) with zero harmful outcomes**. Tables were 60/60, lists 100/100, sections 150/150, frontmatter 110/110, and table reads 60/60. All **470/470 routed trials** passed exact tool-surface and host-resolved-argument audits; all 10 standard fallbacks exposed the unchanged eight-tool surface. The recorded configuration used the official Q8_0 checkpoint through llama.cpp with thinking off, a 65,536-token context, `maxTokens: 8192`, temperature 0.7, and top-p 0.95.

The current Ornith 1.5 9B `auto` profile completed **480/480 full-composition trials (100%) with zero harmful outcomes**. Tables were 60/60, lists 100/100, sections 150/150, frontmatter 110/110, and table reads 60/60. All **360/360 routed trials** passed the exact route audit; all 120 fallback trials retained the standard tool surface. The recorded configuration used the official Q8 checkpoint through llama.cpp, thinking off, `maxTokens: 2048`, and `parallel_tool_calls: false`.

The current Gemma `auto` profile completed **475/479 usable trials (99.2%) with zero harmful outcomes**. Tables, lists, frontmatter, and table reads were perfect; sections were 145/149 with four loud refusals. Every one of the 17 MiniCPM v3 affected tasks then passed across three seeds for Gemma (**51/51**) and Ornith (**51/51**) before the MiniCPM composition run.

These results are tied to the recorded models, llama.cpp runtime, Pi version, prompts, schemas, tasks, seeds, graders, and inference settings. See [the full findings](../../bench/FINDINGS.md), [MiniCPM composition analysis](../../bench/results/minicpm5_safe_routed_composition_v3_20260925_corrected_analysis.json), [Ornith final analysis](../../bench/results/ornith_final_v2_safe_routed_20260923_analysis.json), and [Gemma v8 analysis](../../bench/results/gemma_safe_routed_full_v8_20260922_analysis.json).

## Binary resolution

The extension uses `INCISE_BIN` first, then the matching optional native package, then `incise` on `PATH`, and finally a release or debug binary from a development checkout. `/incise-doctor` reports the selected path, versions, schema status, and registered-tool count. Version mismatches from explicit overrides are warnings; a mismatched packaged binary disables the tools as an installation-integrity failure.

## Security

Pi extensions and their subprocesses run with the user’s full permissions. Review this package before installation and use OS- or container-level isolation for unattended execution. Incise performs atomic, byte-preserving edits, but it is not a filesystem sandbox.
