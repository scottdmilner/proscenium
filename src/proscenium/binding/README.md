# `proscenium.binding`

Everything about [bindings](../../../docs/PROJECT.md#glossary) apart from the compiled core: their records, runtime state, source access, and results. It's kept apart from `proscenium.core`, so the Blender-facing code and the core and its Hydra code change independently. Its units are `runtime/` (tier 3), `persistence/` (tier 2), and `source_access/` and `results.py` (the lowest tier), which code in other units imports by the [import rules](../README.md#import-rules).

| Path | Holds |
|---|---|
| `__init__.py` | The package. It imports none of its units, so importing `source_access/` or `results.py`, which runs it first, never imports `bpy`. |
| `runtime/` | Lookups and writes on `persistence/`'s records, read when called, and every binding's stages. The upper tier. |
| `persistence/` | Versioned records in Blender ID properties. The lower tier. |
| `source_access/` | The stages a binding reads its source from, and the binding identifiers, canonical-candidate rule, requested settings, and source-entity identifiers they're found and made by. bpy-free, used by both tiers. |
| `results.py` | What operations on a binding report: `Result`, whose state derives from its aggregated diagnostics (`result_state`, `deduplicated_diagnostics`) and never from its cleanup status, `ResultState`, `Diagnostic`, `DiagnosticCode`, the list of stable codes, each with one `DiagnosticCategory` and `Severity`, ([Diagnostics](../../../docs/spec/pipeline.md#diagnostics)). The binding-state records store diagnostics too. bpy-free, used by both tiers. |
