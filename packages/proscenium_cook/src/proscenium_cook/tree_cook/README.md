# `proscenium_cook.tree_cook`

The cook's C++ source and its compiled module, `_cook`. [AGENTS.md](AGENTS.md) has its build, boundary, style, and test rules. It imports without `bpy`; `tests/bpy_free` imports it with Blender's modules blocked.

## Python

Its only Python module is its `__init__.py`, so no import-linter contract protects modules of its own: the compiled module is invisible to import-linter.

| File | Holds |
|---|---|
| `__init__.py` | The unit's exports: every public name of the compiled module. It imports `pxr.Usd` first, which loads Blender's `usd_ms` and the converters the compiled module's arguments need. |
| `_cook.pyi` | The compiled module's types, so ty checks its callers without a build. |
| `AGENTS.md`, `CLAUDE.md` | Rules for agents working here. `CLAUDE.md` loads `AGENTS.md` for Claude Code. |
| `.clang-format` | The C++ style, the planner's. |
| `.gitignore` | Ignores the built module. |

## C++

| File | Holds |
|---|---|
| `CMakeLists.txt` | The CMake project that builds `_cook`, with the planner's settings, which `tools/native_build.py` configures. |
| `python_bindings.cpp` | Registration of `proscenium_cook.tree_cook._cook`: `usd_version`, `diagnostic_codes`, `NodeDefinitions`, and `TreeCook`, whose `cook` returns its result as plain Python data. |
| `tree_cook.h`, `tree_cook.cpp` | `TreeCook`, which holds the tree's stage and the nodes' caches between cooks, and `CookResult` and `NodeReport`. Its cook reads and checks the tree, orders its nodes, and runs them serially, upstream first, each through its role's context: the scheduler. |
| `tree_reading.h`, `tree_reading.cpp` | Reading the tree from its stage's root layer through Sdf: the tree's own checks (its `/Tree` prim, `tree:format`, no sublayers or arcs), each node's ID, type, definition, and mute flag, the shared checks of a node against its definition, and its links, with their checks: a connection to no output, an incompatible link, too many links. |
| `node_ids.h`, `node_ids.cpp` | Node IDs from prim names and back: `_` doubles, and a character USD's identifiers reject becomes `_<hex codepoint>_`. Only a name's canonical spelling decodes. |
| `node_graph.h`, `node_graph.cpp` | The node graph: each node on a cycle gets an error, the rest are in topological order with ties broken by node ID, and an input's sources are traced back through muted nodes by their definitions' pass-throughs. |
| `node_contexts.h`, `node_contexts.cpp` | The contexts a node's function gets: its inputs (`TreeInputReader`: a link's value, the authored value, or the definition's default), its diagnostics, and its `NodeCache`; and a task's outputs. |
| `cook_diagnostics.h`, `cook_diagnostics.cpp` | The cook's severities and diagnostic codes, each code's name in Python's `DiagnosticCode`, and a cook's diagnostics, the tree's and each node's. |
| `python_error_translation.h`, `python_error_translation.cpp` | Error translation for every entry point, a copy of the planner's: Tf errors and C++ exceptions become Python exceptions. |
| `node_definitions.h`, `node_definitions.cpp` | The node definitions, loaded through Sdf: each type's version and attributes (its inputs, outputs, and properties), with their socket kinds, types, defaults, menus, and pass-throughs. Loading refuses a malformed definition, and definitions and a registry that don't name the same node types. |
| `node_roles.h` | The four roles' function signatures, Value, Authoring, Zone, and Task, and `NodeBehavior`, the variant of them a registration holds. |
| `node_input_reader.h`, `node_input_reader.cpp` | What the generated readers read a node's inputs and properties through: a value, an optional field (`AuthoredField`), a dynamically typed value, a Prim, Prims, Layer, or File input. |
| `nodes/` | The node types' implementations and `node_registry.cpp`, their one list. |
| `node_inputs/` | The generated input headers, one per node type (`tools/node_inputs.py`). |
