# `tools`

The repository's scripts: the build, the checks that pre-commit runs, and helpers for fixtures and for trying the widgets. Each script's docstring has its usage. `launch_blender.py`, `build_extension.py`, and `matrix.py` are also the `proscenium-blender`, `proscenium-build`, and `proscenium-matrix` commands (`[project.scripts]` in `pyproject.toml`).

| Path | Holds |
|---|---|
| `build_extension.py` | The only distribution build: `dist/proscenium-<version>.zip` for this platform, with the runtime wheels and the planner (`--check`: read-only). Releases ship one zip per platform and Blender minor version on GitHub releases ([DECISIONS.md](../docs/DECISIONS.md) "Native core distribution"). Only the zip's copy of the manifest names the platform and sets `blender_version_max`, so each zip supports one Blender minor version. The workspace's wheels ship only inside the zip, and the extension's own wheel from `uv build` exists only so `proscenium` installs editable in the dev environment. Never publish or distribute either. |
| `native_build.py` | Builds the repository's compiled modules, the planner, the cook, and the Hydra bridge, against the locked Blender release's USD, rebuilding the planner and the cook only when they're out of date, and audits their linkage. |
| `blender_deps.py` | Caches the locked Blender release's exact headers (and Windows import libraries) for the compiled modules. |
| `blender_release.py` | The Blender release the project targets: the `bpy` version locked in `uv.lock`. |
| `blender_paths.py` | Finds the Blender binary, an installed Blender of the locked release, and the extension CLI shipped inside the bpy wheel. |
| `launch_blender.py` | Builds the zip and starts an installed Blender of the locked release with it installed and enabled, with its user dirs in `build/blender-user/` so the user's own Blender setup is untouched (`uv run proscenium-blender [-- BLENDER_ARGS...]`). For development only, never for distributing the zip. |
| `clang_tidy.py` | Runs clang-tidy on the planner, the cook, and the Hydra bridge, each with its build's compile commands (a pre-commit hook). |
| `matrix.py` | Checks and renders the requirement-to-test matrix. |
| `node_inputs.py` | Writes the cook's typed input headers, one per node type, from its node definitions, or checks that they're current (a pre-commit hook). |
| `row_icon_masks.py` | Makes the scene graph widget's masks of Blender's row icons from its icon SVGs, which the widget recolors for instances (`uv run --group icons python tools/row_icon_masks.py`: the `icons` group holds its SVG renderer and PNG decoder, apart from `dev`). |
| `scene_graph_demo.py` | Hosts the scene graph and property viewer widgets in the 3D View's and node editor's sidebars, for trying them by hand in the Blender binary (`Blender --python tools/scene_graph_demo.py`). |
| `alab_checksums.py`, `alab_inventory.py` | Pin and inventory the ALab production-scale fixture ([docs/testing/alab/](../docs/testing/alab/)). |
| `bpy-site-packages/` | Puts the bpy wheel's bundled `pxr` on `sys.path`. |
| `feasibility/` | Evidence, not product code: M1's runtime probes, M1b's Hydra bridge (`hydra_bridge/`), and prototypes and demos for the widgets. Results are in [docs/feasibility/runtime-record.md](../docs/feasibility/runtime-record.md). |
