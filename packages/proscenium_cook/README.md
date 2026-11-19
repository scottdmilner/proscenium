# `packages/proscenium_cook`

The `proscenium_cook` package: the cook, which evaluates a node tree, given as a USD stage, into a stage for each Stage Output node and one for the active Viewer, with diagnostics for its nodes ([plan](../../docs/plans/cook-module.md), [Node Tree](../../docs/phase3/node-tree.md)). Its wheel holds the cook's compiled module, so it is built for one platform and Blender minor version. It's a runtime dependency, which the extension's zip bundles, for the temporary UI's cook tree ([`interface/`](../../src/proscenium/interface/README.md)).

| Path | Holds |
|---|---|
| `pyproject.toml` | The package's project. It depends on nothing that ships: `pxr` comes with Blender. Its wheel leaves out the cook's C++ sources. Its `[tool.importlinter]` contracts are the package's import rules ([import rules](../README.md#import-rules)). |
| `hatch_build.py` | The wheel's build hook: it builds the cook's module unless it's current (`tools/native_build.py`'s `sync_module`), adds it to the wheel, and tags the wheel for this platform. An editable install skips it, and imports the module from `tree_cook/`. |
| `src/` | The package's source, `proscenium_cook/` ([its README](src/proscenium_cook/README.md)). |
