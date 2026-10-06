# Agent Instructions

## Before any work

Read [docs/PROJECT.md](docs/PROJECT.md) and [docs/spec/invariants.md](docs/spec/invariants.md) first. For milestone work, also read the milestone file in [docs/milestones/](docs/milestones/), its plan in [docs/plans/](docs/plans/) if one exists, and [docs/DECISIONS.md](docs/DECISIONS.md).

## Keep invariants in sync with the spec

- Any change to a guarantee in a spec file updates its statement in `docs/spec/invariants.md` in the same change, and the reverse.
- `invariants.md` stays a summary that links to and defers to the authoritative spec section. It never gains detail of its own.

## Layout

- `src/proscenium/`: the extension source dir (`blender_manifest.toml`, `register`/`unregister`).
  - `proscenium/__init__.py` and `proscenium/core/` must import without `bpy`.
  - Blender-facing code goes in modules such as `proscenium/addon.py`.
- `tests/`: tests are split by layer, selected with pytest markers:
  - `unit`: pure Python, no `bpy`.
  - `blender`: in-process `bpy` wheel.
  - `isolated`: fresh Blender binary per test.
  - `alab`: needs `PROSCENIUM_ALAB_ROOT`.
  - `slow`.
- `tools/`:
  - `build_extension.py`: build script.
  - `feasibility/`: M1 runtime probes. Results are in `docs/feasibility/runtime-record.md`.
  - `bpy-site-packages/`: puts the bpy wheel's bundled `pxr` on `sys.path`.
- `docs/`: the spec, milestones, decisions, and testing docs.

## Commands

All commands run through uv. The dev group includes the `bpy` wheel, so `bpy` and `pxr` import in the uv environment without a Blender install.

```sh
uv sync                                   # install the dev environment
uv run pre-commit run --all-files         # all lint checks (ruff, ty, lock); same as CI
uv run pytest                             # all tests; select layers with -m (e.g. -m unit)
uv run python tools/build_extension.py    # dist/proscenium-<version>.zip for this platform
uv run python tools/feasibility/run_all.py  # feasibility probes (wheel, pytest, binary)
uv run pre-commit install                 # once per clone
```

Tests and probes that need the Blender binary find it through the `BLENDER` env var, or else the platform default install path.

## Distribution

`tools/build_extension.py` is the only distribution build. Its output, `dist/proscenium-<version>.zip`, is what Blender installs. The Python wheel from `uv build` only exists so `proscenium` installs editable in the dev environment. Never publish or distribute it.

## Dependencies

- Runtime dependencies go in `[project] dependencies`. The build bundles them as wheels and syncs the generated block between the markers in `blender_manifest.toml`. Never edit that block by hand. The rest of the manifest, including `[build]`, is hand-written.
- Tooling, stubs, and `bpy` go in the dev group and never ship.
- Never bundle another OpenUSD build: the extension uses the `pxr` bundled with Blender.

## Style

- Follow PEP 8 (ruff, line length 120) and annotate every function signature.
- Prefer short docstrings plus inline comments over long docstrings.
- Keep files under ~600 lines, and rarely over ~1000. Split larger ones into submodules.
- USD test scenes are `.usda` files on disk with a comment stating their purpose, not Python strings.
- Evidence docs (feasibility records, decision rows) claim only what a check actually tested.
