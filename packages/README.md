# `packages`

The workspace's library packages: each a uv workspace member with its own `pyproject.toml`, built as a wheel that the extension's zip bundles. Blender installs them as top-level packages in its shared site-packages, so code in them imports absolutely. The extension itself is `src/proscenium/`, the root `pyproject.toml`'s project ([plan](../docs/plans/workspace-packages.md)).

A package boundary goes only where the interface between two sides stands on its own, a USD stage or the extension's public API, so nothing on either side is kept in step with the other by hand. Each package's name starts with `proscenium_`, and is a top-level name of its own, never part of a shared namespace: Blender removes a wheel by deleting its top-level directories.

It holds no package yet.
