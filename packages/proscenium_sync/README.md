# `packages/proscenium_sync`

The `proscenium_sync` package: the synchronizer, which the extension registers and its UI reaches through the API. Its wheel holds the compiled core, so it is built for one platform and Blender minor version.

| Path | Holds |
|---|---|
| `pyproject.toml` | The package's project. It depends on nothing that ships: `bpy` and `pxr` come with Blender. Its wheel leaves out the core's C++ sources. |
| `hatch_build.py` | The wheel's build hook: it builds the compiled core unless it's current (`tools/build_extension.py`'s `sync_core`), adds it to the wheel, and tags the wheel for this platform. An editable install skips it, and imports the module from `core/`. |
| `src/` | The package's source, `proscenium_sync/` ([its README](src/proscenium_sync/README.md)). |
