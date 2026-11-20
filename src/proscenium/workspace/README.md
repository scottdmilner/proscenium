# `proscenium/workspace`

The Proscenium workspace's layout, which the extension's zip includes and the workspace operator (`interface/workspace_access.py`) appends to a file.

| File | Holds |
|---|---|
| `proscenium.blend` | One workspace, named Proscenium, and no other data the operator appends. Saved in the oldest Blender the manifest supports (`blender_version_min`). To change it, open it, edit the workspace, and save it; keep its name, which the operator appends by. |
