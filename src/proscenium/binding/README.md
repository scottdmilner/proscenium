# `proscenium.binding`

Everything about [bindings](../../../docs/PROJECT.md#glossary) apart from the compiled core: their records, runtime state, source access, and results. It's kept apart from `proscenium.core`, so the Blender-facing code and the core and its Hydra code change independently. Code outside it imports its units, `runtime`, `persistence`, `source_access`, and `results`, and uses what each exports, never the modules inside them (checked by `tests/bpy_free/test_import_tiers.py`); tests reach into the modules. It holds the two tiers, `runtime/` over `persistence/`, and the bpy-free code they and `proscenium.api` build on ([tiers](../../../docs/plans/source-tiers-and-names.md#tiers)).

| Path | Holds |
|---|---|
| `__init__.py` | The package. It imports none of its units, so importing `source_access/` or `results.py`, which runs it first, never imports `bpy`. |
| `runtime/` | Disposable in-memory state built from `persistence/`'s records. The upper tier. |
| `persistence/` | Versioned records in Blender ID properties. The lower tier. |
| `source_access/` | The stages a binding reads its source from, and the binding identifiers, canonical-candidate rule, requested settings, and source-entity identifiers they're found and made by. bpy-free, used by both tiers. |
| `results.py` | What operations on a binding report: `Result`, whose state derives from its aggregated diagnostics (`result_state`, `aggregated`), `ResultState`, `Diagnostic`, `DiagnosticCode`, the list of stable codes, each with one `DiagnosticCategory` and `Severity`, ([Diagnostics](../../../docs/spec/pipeline.md#diagnostics)). The binding-state records store diagnostics too. bpy-free, used by both tiers. |
