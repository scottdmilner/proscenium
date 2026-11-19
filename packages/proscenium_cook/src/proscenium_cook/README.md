# `proscenium_cook`

The cook: it reads one node tree from a USD stage and evaluates it, node by node, into a stage for each Stage Output and Viewer node, with diagnostics for its nodes ([plan](../../../../docs/plans/cook-module.md)). All of it is C++, in `tree_cook/`, and bpy-free: it reads and writes USD only.

| Path | Holds |
|---|---|
| `__init__.py` | The package's public API: `TreeCook`, `CookResult`, `NodeReport`, `NodeDiagnostic`, `Severity`, `DiagnosticCode`, and `usd_version`, the OpenUSD release the compiled module was built against. |
| `cook_api.py` | `TreeCook`, which holds the tree's stage and cooks it through the compiled module, turning each result into `cook_results`' types. It loads the node definitions once a process, and importing it fails when the compiled module reports other diagnostic codes than `DiagnosticCode`. |
| `cook_results.py` | What a cook returns: `CookResult`, `NodeReport`, `NodeDiagnostic`, `Severity`, and `DiagnosticCode`, the cook's fixed vocabulary of codes. |
| `node_definitions.usda` | The node definitions: one `class` prim per node type, with its version and its inputs, outputs, and properties, their types, defaults, menus, and in `customData` their socket kinds. The cook loads it through Sdf, and `tools/node_attributes.py` writes the attribute headers from it. |
| `tree_cook/` | The cook's C++ source and its built module, `_cook`. |

## Import rules

The workspace's [import rules](../../../README.md#import-rules) hold here, as [this package's `pyproject.toml`](../../pyproject.toml)'s contracts state them. Other packages reach it only through its public API, the names its `__init__.py` exports, and import none of its units.
