# `proscenium/core/inspection`

The inspection layer ([interaction contract](../../../../docs/spec/interaction-contract.md#two-layers-and-the-live-stage), DECISIONS.md "Inspection layer"): selection targets by model kind on the live stage, ported from the bridge's `inspection`. A static library of its own, which the core links and calls from `correspondence.cpp`. Its sources include only USD's headers and the standard library's, never the core's, it links only Blender's USD, and it has no Python bindings; `tests/bpy_free/test_core_inspection.py` checks each (ICON-04, ICON-05). It is read-only (ICON-06). Nothing here ships: the manifest's `[build]` patterns keep its sources and CMake file out of the zip.

| File | Holds |
|---|---|
| `kind_targets.h`, `kind_targets.cpp` | `KindTarget`, the nearest ancestor-or-self of a floor on the stage whose authored kind is a level or derives from it, or the floor; and `IsRegisteredKind`, whether a kind is a selection level. |
| `CMakeLists.txt` | The `proscenium_inspection` target, with the core's compile settings, USD's headers and their TBB and Python dependencies, and Blender's USD as its only link input. |
