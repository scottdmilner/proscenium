# `tools`

The repository's scripts: the build, the checks that pre-commit runs, and helpers for fixtures and for trying the widgets. Each script's docstring has its usage. `launch_blender.py`, `build/build_extension.py`, and `matrix.py` are also the `proscenium-blender`, `proscenium-build`, and `proscenium-matrix` commands (`[project.scripts]` in `pyproject.toml`).

| Path | Holds |
|---|---|
| `build/` | The build: the extension's zip and the compiled modules, whose packages' build hooks import it ([its README](build/README.md)). |
| `blender_paths.py` | Finds the Blender binary, an installed Blender of the locked release, and the extension CLI shipped inside the bpy wheel. |
| `launch_blender.py` | Builds the zip and starts an installed Blender of the locked release with it installed and enabled, with its user dirs in `build/blender-user/` so the user's own Blender setup is untouched (`uv run proscenium-blender [-- BLENDER_ARGS...]`). For development only, never for distributing the zip. |
| `clang_tidy.py` | Runs clang-tidy on the planner, the cook, and the Hydra bridge, each with its build's compile commands (a pre-commit hook). |
| `matrix.py` | Checks and renders the requirement-to-test matrix. |
| `node_attributes.py` | Writes the cook's typed attribute headers, one per node type beside its `.cpp`, from its node definitions, or checks that they're current (a pre-commit hook). |
| `row_icon_masks.py` | Makes the scene graph widget's masks of Blender's row icons from its icon SVGs, which the widget recolors for instances (`uv run --group icons python tools/row_icon_masks.py`: the `icons` group holds its SVG renderer and PNG decoder, apart from `dev`). |
| `scene_graph_demo.py` | Hosts the scene graph and property viewer widgets in the 3D View's and node editor's sidebars, for trying them by hand in the Blender binary (`Blender --python tools/scene_graph_demo.py`). |
| `alab_checksums.py`, `alab_inventory.py` | Pin and inventory the ALab production-scale fixture ([docs/testing/alab/](../docs/testing/alab/)). |
| `bpy-site-packages/` | Puts the bpy wheel's bundled `pxr` on `sys.path`. |
| `feasibility/` | Evidence, not product code: M1's runtime probes, M1b's Hydra bridge (`hydra_bridge/`), and prototypes and demos for the widgets. Results are in [docs/feasibility/runtime-record.md](../docs/feasibility/runtime-record.md). |
