# `packages/proscenium_ui`

The `proscenium_ui` package: widgets an add-on places in Blender's editors, which the extension's UI uses. Pure Python.

| Path | Holds |
|---|---|
| `pyproject.toml` | The package's project. It depends on nothing that ships: `bpy`, `pxr`, and `numpy` come with Blender. Its `[tool.importlinter]` contracts are the package's import rules ([import rules](../README.md#import-rules)). |
| `src/` | The package's source, `proscenium_ui/` ([its README](src/proscenium_ui/README.md)). |
