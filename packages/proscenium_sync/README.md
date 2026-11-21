# `packages/proscenium_sync`

The `proscenium_sync` package: the synchronizer, which the extension registers and its UI reaches through the API. Its wheel holds the planner, so it is built for one platform and Blender minor version.

| Path | Holds |
|---|---|
| `pyproject.toml` | The package's project. It depends on nothing that ships: `bpy` and `pxr` come with Blender. Its wheel leaves out the planner's C++ sources. Its `[tool.importlinter]` contracts are the package's import rules ([import rules](../README.md#import-rules)). |
| `hatch_build.py` | The package's build hook: it builds the planner into `planner/` unless it's current (`tools/build/native_build.py`'s `sync_module`). For an editable install, as `uv sync` makes, that's all, and the install imports the module from there; `pyproject.toml`'s `cache-keys` make `uv sync` rerun it when the planner's sources change. For a wheel, it adds the module and tags the wheel for this platform. |
| `src/` | The package's source, `proscenium_sync/` ([its README](src/proscenium_sync/README.md)). |
