# Cook: agent instructions

These rules cover the cook's C++. [README.md](README.md) lists what each file holds, and [the plan](../../../../../docs/plans/cook-module.md) how it's built, a node or two at a time.

## Source and build

- This directory holds only the cook: its C++, its type stubs, and the `__init__.py` that loads what it links. The package's wheel leaves out C++ sources and CMake files. Only the built module ships, in this package.
- The cook builds as the planner does: through `tools/native_build.py` (`COOK`), from this directory only, against the dependency headers of the Blender release `uv.lock` pins, linking only to Blender's bundled `usd_ms`. `tools/build_extension.py` builds the module (`proscenium_cook.tree_cook._cook`, ignored by `.gitignore`) into this directory, where the dev environment's editable install imports it, and `proscenium_cook`'s build hook ships it in a wheel tagged for the platform.
- Its `CMakeLists.txt` sets the planner's flags. A change to one's flags changes the other's.

## Node types

A node type is a registered function in its role's signature (`node_roles.h`), never a class with state ([the plan](../../../../../docs/plans/cook-module.md#node-types-in-c)). Adding one takes, in the same change:
- its definition, a `class` prim in `../node_definitions.usda`;
- its attribute header beside it in `nodes/`, from `uv run python tools/node_attributes.py render`, never edited by hand;
- one `.cpp` file in `nodes/` with its function and its helpers in an anonymous namespace, and its function's declaration in `nodes/node_types.h`. A zone's begin and end share one file, since each is half of one zone;
- its diagnostic codes, in `cook_diagnostics.h` and in Python's `DiagnosticCode`, which importing the package checks against each other;
- its line in `nodes/node_registry.cpp`, and its source in `CMakeLists.txt`;
- its entry in `nodes/README.md`.

Behavior stays in C++, never in the definitions file. A node reads its inputs and properties, commits its outputs, and names any of them only through its generated structs, so renaming or retyping one breaks the compile of the node that uses it.

## The planner's rules

[The planner's rules](../../../../proscenium_sync/src/proscenium_sync/planner/AGENTS.md) for its boundary, its style, and its tests apply here too, with the cook's names:

- Every entry point turns Tf errors and C++ exceptions into Python exceptions. The cook's error translation starts as a copy of the planner's, not a shared library.
- C++17, Google style with a 120-column limit (`.clang-format`), and the root `.clang-tidy`'s checks, which pre-commit runs here too. No warnings in any platform's build.
- The cook is tested through its Python module, in the test layers of [tests/README.md](../../../../../tests/README.md). Expected values come from the spec, the node tree's design, or USD's own APIs.
