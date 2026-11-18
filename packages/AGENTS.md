# Packages: agent instructions

[README.md](README.md) describes the workspace's packages. Read its [import rules](README.md#import-rules) before you add or move an import, a module, or a unit. The contracts in each `pyproject.toml` state those rules, and `lint-imports` checks them.

Every directory here has a `README.md` that names each of its files and subdirectories and what it holds. Update it whenever you add, remove, or rename a file there (`tests/bpy_free/test_source_readmes.py` checks this).

## Dependencies

- Runtime dependencies go in the root `pyproject.toml`'s `[project] dependencies`. That means the workspace's packages, each a `[tool.uv.sources]` workspace member, and any third-party package.
  - The build bundles them as wheels, building the workspace's own wheels from source.
  - The build syncs the generated block between the markers in `src/proscenium/blender_manifest.toml`, which names only `uv.lock`'s wheels. Never edit that block by hand. The rest of the manifest, including `[build]`, is hand-written.
- A package depends on another of the workspace only through its own `pyproject.toml`'s dependencies.
- Tooling, stubs, and `bpy` go in the dev group, and never ship.
- Never bundle another OpenUSD build. The extension uses the `pxr` bundled with Blender.

The planner's C++ has its own rules ([proscenium_sync's planner](proscenium_sync/src/proscenium_sync/planner/AGENTS.md)).
