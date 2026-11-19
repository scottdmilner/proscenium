# `proscenium_cook`

The cook: it reads one node tree from a USD stage and evaluates it, node by node, into a stage for each Stage Output and Viewer node, with diagnostics for its nodes ([plan](../../../../docs/plans/cook-module.md)). All of it is C++, in `tree_cook/`, and bpy-free: it reads and writes USD only.

| Path | Holds |
|---|---|
| `__init__.py` | The package's public API: the compiled module's names that other packages use. For now, `usd_version`, the OpenUSD release the module was built against. |
| `tree_cook/` | The cook's C++ source and its built module, `_cook`. |

## Import rules

The workspace's [import rules](../../../README.md#import-rules) hold here, as [this package's `pyproject.toml`](../../pyproject.toml)'s contracts state them. Other packages reach it only through its public API, the names its `__init__.py` exports, and import none of its units.
