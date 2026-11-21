# `proscenium`

The extension's source directory: what `tools/build/build_extension.py` zips into the extension Blender installs. It holds the extension's manifest and registration and the temporary UI. The synchronizer it registers, the widgets the temporary UI hosts, and the cook its node tree runs are the workspace's packages, `proscenium_sync`, `proscenium_ui`, and `proscenium_cook` ([`packages/`](../../packages/README.md)), which the extension depends on and its zip bundles as wheels.

| Path | Holds |
|---|---|
| `blender_manifest.toml` | The extension manifest. Its `[build]` patterns keep these READMEs and the agent instructions out of the zip. |
| `AGENTS.md` | Rules for agents working here. `[build]` keeps it out of the zip. |
| `__init__.py` | The package, exporting `addon.py`'s `register` and `unregister`, which Blender calls. |
| `addon.py` | The extension's registration: the synchronizer's (`proscenium_sync.register`), then the temporary UI's. |
| `workspace/` | `proscenium.blend`, which holds only the Proscenium workspace's layout, saved in Blender 5.2, for `interface/workspace_access.py` to append. |
| `interface/` | The temporary UI, which M12 replaces: the Source Select tool, minimal panels, and the cook's node tree, over `proscenium_sync`'s and `proscenium_cook`'s names and `proscenium_ui`'s widgets only. |

## Import rules

The workspace's [import rules](../../packages/README.md#import-rules) hold here, as the root [`pyproject.toml`](../../pyproject.toml)'s contracts state them. Relative imports are the exception: Blender installs the extension as `bl_ext.<repository>.proscenium`, so it imports its own parents relatively.

`__init__.py`, the extension's entry, is no unit's.
