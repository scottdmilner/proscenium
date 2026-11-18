# `proscenium`

The extension's source directory: what `tools/build_extension.py` zips into the extension Blender installs. It holds the extension's manifest and registration and the temporary UI. The synchronizer it registers and the widgets the temporary UI hosts are the workspace's packages, `proscenium_sync` and `proscenium_ui` ([`packages/`](../../packages/README.md)), which the extension depends on and its zip bundles as wheels.

| Path | Holds |
|---|---|
| `blender_manifest.toml` | The extension manifest. Its `[build]` patterns keep these READMEs and the agent instructions out of the zip. |
| `AGENTS.md`, `CLAUDE.md` | Rules for agents working here. `CLAUDE.md` loads `AGENTS.md` for Claude Code. `[build]` keeps both out of the zip. |
| `__init__.py` | The package, exporting `addon.py`'s `register` and `unregister`, which Blender calls. |
| `addon.py` | The extension's registration: the synchronizer's (`proscenium_sync.register`), then the temporary UI's. |
| `interface/` | The temporary UI, which M12 replaces: the Source Select tool and minimal panels, over `proscenium_sync`'s names and `proscenium_ui`'s widgets only. |

## Import rules

The workspace's [import rules](../../packages/README.md#import-rules) hold here, as the root [`pyproject.toml`](../../pyproject.toml)'s contracts state them. Relative imports are the exception: Blender installs the extension as `bl_ext.<repository>.proscenium`, so it imports its own parents relatively.

`__init__.py`, the extension's entry, is no unit's.
