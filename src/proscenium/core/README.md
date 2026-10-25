# `proscenium.core`

Everything that imports without `bpy`: the compiled core and its C++ source, source access, and the pure-Python rules and types the Blender-facing tiers share. It may import only itself; `tests/bpy_free` imports it with Blender's modules blocked. Runtime state that needs no `bpy`, such as the stage registry, belongs here, not in `proscenium.runtime`.

The compiled core reads Hydra scene indices ([DECISIONS.md](../../../docs/DECISIONS.md) "Evaluation front end and core language"). AGENTS.md's [Compiled core](../../../AGENTS.md#compiled-core) section has its build, boundary, and style rules.

## Python

| File | Holds |
|---|---|
| `__init__.py` | The package. It imports `pxr.Usd` first, which loads Blender's `usd_ms` and the converters the compiled module's arguments need. |
| `source_access/` | The stages a binding reads its source from ([Source Access](../../../docs/spec/source-access.md)). |
| `binding_ids.py` | `BindingId`, a binding's persistent identifier: a `NewType` of `str`, so the checker tells it from other strings. Every tier uses it. |
| `canonical_candidate.py` | The canonical-candidate rule, as a pure function of what Blender data says about each candidate and each binding index ([Canonical Candidate](../../../docs/spec/source-access.md#canonical-candidate)). `proscenium.runtime.copy_detection` reads that evidence from the records. |
| `requested_settings.py` | `RequestedSettings`, the settings a binding's next synchronization uses ([Binding State](../../../docs/spec/lifecycle.md#binding-state)). The binding's configuration holds them. |
| `results.py` | What operations on a binding report: `Result`, `ResultState`, `Diagnostic`, `DiagnosticCategory`, and `Severity` ([Diagnostics](../../../docs/spec/pipeline.md#diagnostics)). The binding-state records store diagnostics too. |
| `source_entities.py` | Source-entity identifiers: an entity's path in the composed stage, with the instance context its instance-proxy path carries. |
| `_core.pyi` | The compiled module's types, so ty checks its callers without a build. |

## The compiled core

| File | Holds |
|---|---|
| `module.cpp` | The Python module, `proscenium.core._core`. |
| `errors.h`, `errors.cpp` | Error translation for every entry point: Tf errors and C++ exceptions become Python exceptions. |
| `stage_handle.h`, `stage_handle.cpp` | `StageHandle`, the core's reference to a stage it was given, which it drops on `Release()` so the core never keeps a released stage alive. |
| `CMakeLists.txt` | The build, against the locked Blender release's headers, linking only Blender's `usd_ms`. `tools/build_extension.py` runs it through `tools/native_build.py`. |
| `.clang-format`, `.clang-tidy` | The C++ style and checks, run as pre-commit hooks. |
| `.gitignore` | Ignores the built module, `_core.*.so` or `_core.*.pyd`, which the build puts in this directory and only the zip ships. |
