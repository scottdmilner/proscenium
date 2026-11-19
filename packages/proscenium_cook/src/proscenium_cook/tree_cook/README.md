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
| `python_bindings.cpp` | Registration of `proscenium_cook.tree_cook._cook`: `usd_version`, `diagnostic_codes`, `NodeDefinitions`, and `TreeCook`, whose `cook` returns its result as plain Python data, with each stage owned by Python. |
| `tree_cook.h`, `tree_cook.cpp` | `TreeCook`, which holds the tree's stage and the nodes' caches between cooks, and `CookResult` and `NodeReport`. Its cook reads and checks the tree, finds its zones, computes its value nodes, makes each zone's layer and checks that no zone saves to a file another zone saves to or a task reads, however it's spelled, then runs its tasks serially, upstream first, each node through its role's context: the scheduler. A zone's task cooks its chain into a scratch layer, which starts as a copy of its Template, moves it into the zone's layer, and keeps the copy's write table beside it, which its begin reports; it stops at a chain node with an error. A link that brings nothing warns on the node it enters, naming the node it comes from. |
| `layer_copies.h`, `layer_copies.cpp` | `CopyLayer`, a copy of a layer the tree reads, such as a zone's Template: its content through `TransferContent`, with each relative asset path anchored to the source's file in one `UsdUtilsModifyAssetPaths` pass, and the `WriteTable` of the paths anchored. |
| `zone_chains.h`, `zone_chains.cpp` | The tree's zones: each begin paired with the end its `zone:end` names, and its chain, followed forward along Editable Layer links. Reports the chain's errors: an unpaired begin or end, a branch, a broken chain and the nodes on it, a mismatched pair, an authoring node in no chain. |
| `task_graph.h`, `task_graph.cpp` | The task graph: one task per zone and per task node, ordered upstream first by the Layer and File links between tasks (`TopologicalOrder`), ties broken by node ID. A task on a cycle of tasks is left out, with an error on each of its nodes. |
| `tree_reading.h`, `tree_reading.cpp` | Reading the tree from its stage's root layer through Sdf: the tree's own checks (its `/Tree` prim, `tree:format`, no sublayers or arcs), each node's ID, type, definition, and mute flag, the shared checks of a node against its definition, and its links, with their checks: a connection to no output, an incompatible link, too many links. |
| `node_ids.h`, `node_ids.cpp` | Node IDs from prim names and back: `_` doubles, and a character USD's identifiers reject becomes `_<hex codepoint>_`. Only a name's canonical spelling decodes. |
| `node_graph.h`, `node_graph.cpp` | `TopologicalOrder`, the Kahn's algorithm both graphs order by, and the node graph: each node on a cycle gets an error, the rest are in topological order with ties broken by node ID, and each link's sources are traced back through muted nodes by their definitions' pass-throughs. |
| `node_contexts.h`, `node_contexts.cpp` | The contexts a node's function gets: its inputs (`TreeInputReader`: a link's value, the authored value, or the definition's default), its diagnostics, its `NodeCache`, and the expansion of a `//` path from the base directory; and a task's committed outputs and a Stage Output's stage. |
| `cook_diagnostics.h`, `cook_diagnostics.cpp` | The cook's severities and diagnostic codes, each code's name in Python's `DiagnosticCode`, and a cook's diagnostics, the tree's and each node's. |
| `python_error_translation.h`, `python_error_translation.cpp` | Error translation for every entry point, a copy of the planner's: Tf errors and C++ exceptions become Python exceptions. |
| `node_definitions.h`, `node_definitions.cpp` | The node definitions, loaded through Sdf: each type's version and attributes (its inputs, outputs, and properties), with their socket kinds, types, defaults, menus, and pass-throughs, and a zone node's end and partner. Loading refuses a malformed definition, definitions and a registry that don't name the same node types, and a zone node without a zone's implementation, or the reverse. |
| `node_roles.h` | The four roles' function signatures, Value, Authoring, Zone (a begin's file and the layer it starts from, an end's outputs), and Task (with the file a task reads), and `NodeBehavior`, the variant of them a registration holds. |
| `node_input_reader.h`, `node_input_reader.cpp` | What the generated readers read a node's inputs and properties through: a value, an optional field (`AuthoredField`), a dynamically typed value, a Prim, Prims, Layer, or File input. |
| `nodes/` | The node types' implementations, each with its generated attribute header (`tools/node_attributes.py`), and `node_registry.cpp`, their one list. |
