# ALab production-scale fixture

The tree used by [Production-Scale Validation: ALab](../acceptance.md#production-scale-validation-alab), and what it contains.

## Installing

- ALab **v2.3.0** asset structure, with techvar assets **v2.2.0** installed into `ALab/fragment` by ALab's `install_optional_packages.py --techvar`. The baked-procedurals, texture-pack, and trailer-cameras packages are not installed; their placeholder layers stay in place.
- Set `PROSCENIUM_ALAB_ROOT` to the directory holding `entry.usda`, in the environment or in the repository's `.env` (see `.env.example`).
- `tools/alab_checksums.py --check` verifies the tree against [subtrees.sha256](subtrees.sha256). It hashes every file except dotfiles (14,150 files), then pins one SHA-256 per subtree: each top-level entry, with `fragment/` split into its children because the optional packages install there, plus a `.` line for the whole tree. A mismatch names the subtrees that differ; the per-file manifest is written to `build/alab/sha256sums.txt` (not committed) for comparing two machines. On the reference machine, every file of the separately downloaded techvar v2.2.0 package (9,869 files) matched its installed copy.

## Inventory

`tools/alab_inventory.py` writes [inventory.md](inventory.md). The full counts, with each prototype's first use and instance counts, go to `build/alab/inventory-load-all.json` and `inventory-load-none.json`, which are not committed; rerun the script to get them.

What the inventory shows, as inputs for judging ALab runs:

- Under load-none, nothing is loaded: `/root`, the stage's only root prim, is itself a payload. 4,541 prims are composed but unloaded. A load-none run is therefore judged against an empty display.
- No native-instance prototype contains another instance, so ALab does not exercise nested native instancing. That coverage comes from bespoke fixtures, `F-NESTED-STRESS`, and the generated CI fixture.
- Under load-all, the scene includes content the [deferred list](../../spec/support/visibility.md#deferred-and-out-of-scope) covers, such as point instancers, curves, points, cameras, and lights.
- Time codes run from 1004 to 1057.

The `alab`-marked test in `tests/bpy_free/test_alab_tools.py` checks that the committed manifest and `inventory.md` match the tree.
