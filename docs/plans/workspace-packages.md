# Workspace packages: plan

How the extension's code becomes several Python packages in a uv workspace, so code outside the extension package imports absolutely, and the compiled core becomes the planner. It changes no behavior and adds no requirement. Where it and a spec file disagree, the spec file wins, apart from the wording this plan changes in the spec itself ([Docs](#docs)).

## Why packages

Blender installs the extension as `bl_ext.<repository>.proscenium`, so code inside it imports relatively, and deep units give long chains (`from ....widget_model import ...`). Wheels the extension bundles are installed as top-level packages, so code in them imports absolutely (`from proscenium_ui.widget_model import search_matching`).

## Where the packages split

A package boundary goes only where the interface between two sides stands on its own, so nothing on either side is kept in step with the other by hand:

- **A USD stage.** The widgets read a stage their host gives them ([DECISIONS.md](../DECISIONS.md) "Phase 3 ordering"), and the cook takes and returns stages as `pxr` objects ([node-tree.md](../phase3/node-tree.md#where-it-lives)).
- **The public API.** `interface/` reaches the product only through `bindings/`.

The planner and the synchronizer stay one package. The display plan is the application layer's input, and nothing else reads it. The two sides share vocabularies that a package boundary would turn into version dependencies between wheels:
- the representation roles, which `RoleName` in `plan.h` names and ownership records store as `manifests.RepresentationRole`
- the diagnostic codes, which `results.PLANNER_CODES` lists and `synchronization/evaluation.py` checks on import
- the representation version, which `application.REPRESENTATION_VERSION` declares and the planner checks
- the plan's buffer layouts and their -1 sentinels
- the planning settings' purpose tokens
- the type stubs

## Packages

| Package | Holds | Imports | Wheel |
|---|---|---|---|
| `proscenium_sync` | The bindings' code, the synchronization transaction, the display component of interaction, the API, and the planner | `pxr`, `bpy` | One per platform: it holds the planner's compiled module |
| `proscenium_ui` | The widgets and their models: everything in `ui/` now | `pxr`, `bpy`, `numpy` | Pure Python |
| `proscenium` (the extension) | The manifest, registration, and the temporary UI | Both packages above | None: it is the zip |

Neither library package imports the other. The cook, when it becomes product code, is a package of its own, `proscenium_cook`, with its own compiled module, for the reason above.

Blender's wheel manager (`_bpy_internal/extensions/wheel_manager.py` in the bpy 5.2 wheel, read from its source) installs every extension's wheels into one shared `extensions/.local/lib/python3.13/site-packages`, and where two extensions bundle the same distribution it keeps the highest version. So the packages' names are prefixed with `proscenium_`, so they can't collide with another extension's wheels. No other extension of ours bundles them, so their versions never conflict. A package's modules stay loaded until Blender restarts, as the compiled module already does.

## Layout

The extension stays at `src/proscenium/`, and the root `pyproject.toml` stays its project (never distributed) and becomes the workspace root. Each library package is a workspace member:

```
pyproject.toml                       the workspace root and the extension's project
src/proscenium/                      the extension
  blender_manifest.toml
  __init__.py
  addon.py
  interface/
packages/
  proscenium_sync/
    pyproject.toml
    README.md
    src/proscenium_sync/
      __init__.py
      registration.py                the record namespace's property group and the handlers addon.py installs now
      bindings/
      synchronization/
      interaction/
      runtime/                       binding/runtime/ now
      persistence/                   binding/persistence/ now
      source_access/                 binding/source_access/ now
      results.py                     binding/results.py now
      planner/                       the C++ source, the inspection layer, _planner, its stubs
  proscenium_ui/
    pyproject.toml
    README.md
    src/proscenium_ui/
      widget_model/
      scene_graph_widget/
      property_viewer_widget/
      columned_list/
      widget_resources/
      search_box.py
      text_wrapping.py
      widget_updates.py
tests/                               unchanged layers, over all three packages
```

`binding/`'s units move up a level, since a package of its own needs no grouping package around them. Their names keep the domain `binding/` gave them. `ui/`'s units become `proscenium_ui`'s, and the two `*_widget/` grouping packages remain.

## Import rules

- **Between packages:** each package imports only the packages its `pyproject.toml` depends on, and absolutely: `from proscenium_sync import bindings`. The extension still imports its own modules relatively, a dot deep.
- **Within a package:** a relative import reaches only a sibling or a descendant (`from . import list_steps`, `from .columned_list import column_layout`), and every other import is absolute (`from proscenium_ui.widget_model import text_matching`), so no import climbs with `..`. Ruff's TID252 (`ban-relative-imports = "parents"`) enforces it everywhere but the extension, which Blender installs as `bl_ext.<repository>.proscenium`, so it can't import its own modules absolutely. The import layers stay, each package's lowest import layers still `bpy`-free: in the synchronizer, the planner, source access, and results; in the widgets, the widgets' models.
- **Public modules and exported names** apply as now, with a package as the outermost unit. A package's `__init__.py` exports the units other packages use, and nothing else imports another package's units that it doesn't export.
- **Module names stay unique across all three packages,** so a test's patch target and an editor tab still name one module.

`tests/bpy_free/test_import_tiers.py` checks both levels: each package's imports against its declared dependencies, and the import layers within each. `test_no_blender_imports.py` covers each package's lowest import layers, and `test_source_readmes.py` covers `packages/`.

## The planner

`core/` becomes `planner/`, and `_core` becomes `_planner`. *The planner* is the compiled unit's name in code and docs. It reads Hydra scene indices for evaluation, takes the snapshot, plans, reports source-side diagnostics, compares plans, and keeps correspondence through the inspection layer, which it links.

- **It exports its names,** and its compiled module is its own. Callers write `planner.Plan`, `planner.plan`, `planner.diff_plans`, and `planner.SceneIndexChain`, never `_planner`. The module's test-only hooks (`_post_tf_error`, `_drop_next_capture_notices`, `_copied_prim_count`, `_hydra_composed_worlds`) stay private, and tests reach them as they do private reads ([tests/README.md](../../tests/README.md)).
- **The vocabularies the planner shares with the application layer stay where they are,** inside the one package, under the checks that keep them consistent now.
- **One `SourceUnavailableError` reaches the API's callers:** source access's (ICON-08). The planner raises its own only for a correspondence whose stage has expired, and none reaches the API: `shown_displays` raises source access's when the binding has no live stage, the binding holds its live stage until it is released, and every attachment advances the source revision, so a kept correspondence never outlives its stage. Code below the API that builds a correspondence itself, `interaction/` and its tests, sees the planner's.
- The C++ namespaces (`proscenium`, `proscenium_inspection`) are unchanged.

## Registration

The synchronizer's registration is `registration.py`, which exports `register` and `unregister`: the record namespace's property group under `id_property_records.NAMESPACE`, the file-load, undo, and redo handlers that drop or prune the bindings' stages and clear `kept_manifests`, and the frame-change handler and message-bus subscriptions that mirror source selections. `addon.py` calls them, then registers the temporary UI. The record namespace's name and the property group's stored keys are unchanged, so saved files read as before.

## Build and distribution

- **The synchronizer's wheel** is built by its hatch build hook (`packages/proscenium_sync/hatch_build.py`), which calls `tools/build/native_build.py`'s `sync_module` on the planner, as `tools/build/build_extension.py` does, keeping the linkage audit, the pinned headers, and `build/planner/build.json`'s check of whether the module is current. It adds the module, which Git ignores, to the wheel. The wheel's tag names the uv environment's Python, which matches Blender 5.2's 3.13, and the platform floor the linkage audit holds the module to (`native_build.wheel_tag`: `macosx_11_0_arm64`, `manylinux_2_28_x86_64`, `win_amd64`). An editable install skips the hook.
- **The members' wheels build without isolation,** in the uv environment, since the planner's build needs the dev group's CMake and Ninja and links the installed bpy wheel's `usd_ms`. The `build` group holds hatchling for it.
- **`tools/build/build_extension.py`** builds each workspace member's wheel with `uv build --package`, and exports the third-party runtime wheels from `uv.lock` without the workspace members. The manifest's generated `wheels` list names both. The members' wheels are built into the temporary copy, and only its manifest names them, so the checked-in generated block names only `uv.lock`'s wheels, the same on every platform, and `--check` still only reads the source dir.
- **One zip per platform and Blender minor version,** as [DECISIONS.md](../DECISIONS.md) "Native core distribution" has it: the synchronizer's wheel carries the platform, the manifest's `platforms` still names it, and `blender_version_max` is unchanged.
- **The dev environment** installs every member editable. The compiled module is built in place, in `planner/`, and stays ignored by Git.
- **`tests/isolated/test_extension.py`** checks the installed zip: Blender extracts the wheels into its shared site-packages, and enabling the extension loads the synchronizer, its compiled module, and the widgets from there. That makes it the check that the wheels install as described above.

## Docs

- **AGENTS.md:** the Layout section describes the packages. The Compiled core section becomes the Planner section, for `packages/proscenium_sync/src/proscenium_sync/planner/`. Commands and Dependencies name the workspace. Its rules are unchanged.
- **The spec** says *the planner* where it says *the compiled core* or *the core*:
  - [interaction-contract.md](../spec/interaction-contract.md#two-layers-and-the-live-stage), in the two-layers section and the list of core bindings
  - [pipeline.md](../spec/pipeline.md)'s "the core does not translate"

  The matrix rows that quote or name those sentences change with them, then `tools/matrix.py render`. No invariant names the core. *Core Architecture* in PROJECT.md is the architecture's name and stays.
- **DECISIONS.md:** rows that name `core/`, `_core`, or the compiled core's paths name the planner and its paths. "Native core distribution" keeps its title and says how the planner ships. The rows' decisions are unchanged.
- **[node-tree.md](../phase3/node-tree.md#where-it-lives):** the cook is a package of its own, `proscenium_cook`.
- **READMEs:** each moved directory's README moves with it. `src/proscenium/README.md`'s import layer table splits into each package's README. `packages/README.md` lists the packages and the boundary rule above.
- **Unchanged:** `docs/archive/` and the closed milestone plans keep the paths they were written with.

## Commits

Each commit is one change, passes `pre-commit` and the test suite on its own, and updates the docs, READMEs, and tests that name what it moves or renames. Files move with `git mv` before their content changes. On its own branch, after the `attribute-viewer` and `ui-shared-display` worktrees merge, since every file they touch moves.

1. This plan.
2. **The core exporting its names** (`core.Plan`, never `_core.Plan`), before anything moves.
3. **The workspace,** with no member: the root `pyproject.toml` as its root, and `packages/README.md`.
4. **`proscenium_ui`:** `ui/` moves into it, its imports follow the import rules above (ruff's TID252), and the extension depends on it. `tools/build/build_extension.py` bundles the workspace's packages' wheels, the import rules' test checks each package's import layers and the imports between packages, and the package's README holds its import layer table. It is first because nothing but `interface/` imports it.
5. **The synchronizer's registration** in `registration.py`, which `addon.py` calls, before the move, so the extension reaches the bindings' code only through `bindings/` and it.
6. **`proscenium_sync`:** `binding/`'s units, `synchronization/`, `interaction/`, `bindings/`, and `core/` move into it, with its per-platform wheel built by its build hook, and CI's paths.
7. **The core becomes the planner:** `core/` to `planner/`, `_core` to `_planner`, `build/core/` to `build/planner/`, and the spec, matrix, DECISIONS.md, and AGENTS.md wording.

## Decision log

- **Plan (with the user, 2026-11-16).** Packages split only where the interface is a USD stage or the public API. The planner and the synchronizer are one package, since the plan's vocabularies are theirs alone. The core is renamed the planner.
- **The stage editor ships in this extension (with the user, 2026-11-16).** So no other extension of ours bundles these packages, and the shared site-packages' version rule never applies between our own wheels.
- **Each package is its own top-level name, never a portion of a shared namespace (with the user, 2026-11-16).** Blender's wheel manager removes a wheel by deleting each top-level directory its zip holds, and skips extracting a wheel whose `dist-info` is present (`wheel_manager.py`, read from its source). Wheels sharing a namespace directory would delete each other's files when one's version changes alone. This holds for `proscenium_cook` too.
- **Tests stay in `tests/`.** Their layers are named for what a test runs in, and the fixture framework and support helpers serve every package.
