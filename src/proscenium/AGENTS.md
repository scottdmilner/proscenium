# Extension: agent instructions

[README.md](README.md) describes the extension's source directory.

- The workspace's [import rules](../../packages/README.md#import-rules) hold here. Read them before adding or moving an import or a module. The one exception: Blender installs the extension as `bl_ext.<repository>.proscenium`, so it imports its own parents relatively.
- `interface/`, the temporary UI that M12 replaces, imports only the packages' public APIs (`proscenium_sync`'s names, and `proscenium_ui`'s widgets and `widget_updates`), besides `bpy` and USD.
- Every directory here has a `README.md` that names each of its files and subdirectories. Update it whenever you add, remove, or rename a file there.
- Never edit the generated block in `blender_manifest.toml` by hand ([dependencies](../../packages/AGENTS.md#dependencies)).
