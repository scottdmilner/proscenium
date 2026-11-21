# Planner: agent instructions

These rules cover the planner, its inspection layer in `inspection/`, and the Hydra bridge in `tools/feasibility/hydra_bridge/`, which follows the same build and style rules. [README.md](README.md) lists what each file holds.

The planner is the C++ that reads Hydra scene indices, which M1b adopted ([DECISIONS.md](../../../../../docs/DECISIONS.md) "Evaluation front end and core language"). It holds evaluation, the snapshot, planning, source-side diagnostics, and comparing plans for incremental refresh. Everything that touches Blender stays in Python. The display plan is the one boundary: an immutable object whose large arrays Python reads without copying.

## Source and build

- This directory holds only the planner: its C++, the inspection layer's library in `inspection/`, its type stubs, and the `__init__.py` that loads what it links. The package's wheel leaves out C++ sources and CMake files. Only the built module ships, in this package.
- The planner builds from this directory only, against the dependency headers of the Blender release `uv.lock` pins, and links only to Blender's bundled `usd_ms`. `proscenium_sync`'s build hook builds the module (`proscenium_sync.planner._planner`, ignored by `.gitignore`) into this directory whenever `uv sync` sees a change to its sources, and the dev environment's editable install imports it from here; so does `tools/build/build_extension.py`, which ships it in a wheel tagged for the platform. CI builds Linux's on Blender's glibc floor (manylinux_2_28), and sets `PROSCENIUM_SKIP_NATIVE_BUILD` so that `uv sync` doesn't build it.
- The planner and the Hydra bridge both build through `tools/build/native_build.py` (where each is built from and to, toolsets, and the linkage audit) and `tools/build/blender_deps.py` (the pinned headers). Their CMakeLists.txt files set the same flags. The bridge is test code and never goes through `tools/build/build_extension.py`.

## Boundary rules

These come from M1b's findings:

- Every entry point turns Tf errors and C++ exceptions into Python exceptions.
- Arrays for Blender cross as 1-D read-only buffers whose element types match Blender's exactly (`'f'`, `'i'`, `'?'`). Any other type would silently take Blender's slow path.
- Values the planner gives Hydra are Vt's own types. A type made in the planner's module isn't recognized by USD's code.
- The planner never keeps a released stage alive.
- Each workaround for an OpenUSD bug is labeled `WORKAROUND for OpenUSD #<issue>` at every site, and a known-gap check fails when the bug stops reproducing.
- Code that reads Hydra from worker threads never overlaps `SetTime`, `ApplyPendingUpdates`, or stage edits. It collects Tf errors per thread, and releases the GIL while waiting on its workers, since holding it deadlocks.
- A Tf-factory type, such as a scene-index plugin or an adapter, registers through an exported USD helper, as Hf's plugin registry does. It never derives from a header-only factory base, because a type registered that way can't be manufactured on macOS.

## Inspection layer

The inspection layer is a static library of its own, which the planner links, calls, and exposes through its own bindings. It has no Python bindings, and never includes or calls the planner ([its README](inspection/README.md)). The build and style rules here apply to it too.

## Style

- C++17, with warnings as the planner's CMakeLists.txt sets them, and no warnings in any platform's build.
- clang-format and clang-tidy run as pre-commit hooks on the planner and on the Hydra bridge. Each has its own `.clang-format`. clang-tidy's checks are in the root `.clang-tidy`, which covers both and includes the C++ Core Guidelines checks, and every clang-tidy warning fails.
- **Pointers:** no owning raw pointers. `TfCreateRefPtr(new ...)`, as Tf's ref-counted types require, is the exception. A raw `T*` is non-owning and means something when null (a lookup that found nothing, an absent optional argument), and its declaration says what null means. Anything never null is a reference, or a `std::reference_wrapper` in a container.
- **Exceptions to a check:** a `NOLINT` names its check and says why the code needs it.
- Names follow [docs/conventions.md](../../../../../docs/conventions.md). C++ members use the same domain words as their Python counterparts (`object_resource_index` / `objectResourceIndex`).

## Tests

- The planner is tested through its Python module, in the test layers of [tests/README.md](../../../../../tests/README.md).
- Expected values come from the spec, from USD's own APIs (`UsdGeom`, `UsdShade`), or from how the fixture is built, never from Hydra's output.
- A test whose input could crash native code runs in `isolated/`, since a crash ends the process.
