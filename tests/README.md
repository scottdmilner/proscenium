# Tests

What is tested and what passing means are defined in [docs/testing/strategy.md](../docs/testing/strategy.md) and [docs/testing/acceptance.md](../docs/testing/acceptance.md). Which requirements exist, and which milestone delivers each, is in the [requirement-to-test matrix](../docs/testing/requirements-matrix.md). This file covers how the test tree is organized and how to use it.

## Running

```sh
uv run pytest -n auto                 # everything, in parallel worker processes
uv run pytest -n auto -m bpy_free     # one layer: bpy_free, blender, or isolated
uv run pytest tests/blender/test_smoke.py -k undo   # a single file or test, serially
```

Environment variables:

| Variable | Effect |
|---|---|
| `BLENDER` | Path to the Blender binary for the isolated layer's binary runs. Without it, the platform default install path is tried. |
| `PROSCENIUM_REQUIRE_BLENDER` | Binary runs fail, rather than skip, when no binary is found. Set in CI. |
| `PROSCENIUM_ALAB_ROOT` | [ALab example production scene](https://dpel.aswf.io/alab/) checkout location. Tests marked `alab` are skipped without it. |

Variables can also be set in a `.env` file at the repository root (gitignored; copy `.env.example`). The root conftest loads it; variables already set in the environment take precedence.

## Choosing a layer

Layers are named for what a test runs in, not for how much it covers: unit and integration tests can live in any layer. Each test lives in one layer directory and automatically gets that directory's marker. A test outside the layer directories is a collection error.

| Layer | Runs in | Use it for | Cost per test |
|---|---|---|---|
| `bpy_free/` | Plain Python. Blender modules are blocked; the wheel's bundled packages (e.g. `pxr`, `MaterialX`) are allowed. | Anything that doesn't need Blender: USD evaluation and planning, fixture generators, docs consistency. Prefer this layer. | ms |
| `blender/` | The bpy wheel, in a process each worker reuses, reset before every test | Code that reads or writes Blender data: registration, save/reopen, undo, datablocks | ~30 ms reset |
| `isolated/` | A fresh process per test: the bpy wheel, or also the Blender binary | Behavior that needs a fresh process: real startup and file loads with handlers, extension install, process-wide state that a reset can't undo; and smoke tests that must also pass in the binary users run | ~0.85 s (wheel), ~1.2 s (binary) |

Start in the cheapest layer that can express the test. Move a test to `isolated/` only when the blender layer's reset can't give it a clean, honest starting point.

Extra markers, added per test: `alab` for tests that need ALab (`PROSCENIUM_ALAB_ROOT`), and `slow` for long-running tests.

## Contents

```
tests/
├── conftest.py               layer markers, the alab skip, a throwaway Blender user dir
├── bpy_free/                 tests that run without Blender
│   ├── conftest.py           blocks Blender modules during this layer's tests
│   └── bpy_blocker.py        the blocker; also run as a script by test_no_blender_imports.py
├── blender/                  in-process bpy-wheel tests
│   ├── conftest.py           reset + clean-baseline check per test; `extension` fixture
│   └── state.py              the reset, baseline check, and cleanup
├── isolated/                 fresh-process tests
│   ├── conftest.py           `wheel`, `runtime`, and `hydra_bridge` fixtures
│   ├── harness.py            run_isolated: starts the fresh process, returns the body's result
│   ├── runner.py             the script the fresh process executes
│   └── bodies/               functions run inside the fresh process
├── support/                  helpers used by more than one layer or by fixtures/
├── tools/                    scripts for inspecting fixtures; not tests
└── fixtures/                 bespoke USD fixtures
    ├── registry.py           the named contract fixtures
    ├── source_access.py      generators for F-DIRTY-LAYER, F-PRIVATE-STAGE, F-CACHED-STAGE, F-REATTACH, F-MULTI-BINDING
    ├── interaction.py        generators for F-KIND-HIERARCHY, F-NESTED-SELECTION, F-UNIVERSE-MEMBERSHIP
    ├── appearance.py         generators for F-APPEARANCE-CASES and F-NESTED-STRESS
    ├── records.py            the generator for F-SCHEMA-VERSIONS, and its test schema
    ├── production_like.py    the smaller generated CI fixture
    └── scenes/               static layers the generators copy
        └── __init__.py       the Scene index and copy_scene
```

### `conftest.py` (root)

- Marks each test with its layer, so `-m bpy_free` selects `tests/bpy_free/` without per-test markers.
- Skips `alab` tests without `PROSCENIUM_ALAB_ROOT`.
- Points `BLENDER_USER_RESOURCES` at a temporary dir per worker, so neither the wheel nor any Blender subprocess touches the developer's real Blender configuration.

### `bpy_free/`

`bpy_free/conftest.py` blocks Blender modules (`bpy`, `bmesh`, `mathutils`, ...) while this layer's test files are imported and while each of its tests runs. A test here that imports one fails with `ImportError`. Blender modules are recognized by origin rather than a name list: anything loaded from the bpy wheel's package dir (except its bundled site-packages, with third-party packages such as `pxr` and `MaterialX`), and anything bpy's C code creates at import (see `bpy_blocker.py`). Modules already loaded by blender-layer tests in the same worker are hidden for the duration, so the block holds in mixed runs too.

`test_no_blender_imports.py` checks the rule from [AGENTS.md](../AGENTS.md#layout) directly: `proscenium` and every `proscenium.core` module import in a fresh interpreter with Blender blocked.

### `blender/`

All blender-layer tests in a worker share one bpy-wheel process. The autouse `clean_blender` fixture, using `blender/state.py`, does the following:

1. Before the test, it resets to Blender's empty factory state and asserts a clean baseline: the extension isn't registered, handlers match Blender's own, there is no data beyond the factory UI and one empty scene, `UsdUtils.StageCache` is empty, and no file-backed layer with unsaved edits is still loaded.
2. After the test, it unregisters the extension, removes handlers the test added, and clears the stage cache.

A test therefore always starts clean, even after a failing test. If the baseline assertion fires, something escaped the reset; fix the reset rather than the test. `test_state_reset.py` shows that each kind of leftover is detected and removed.

The `extension` fixture registers the extension in-process from `src/` (not installed). It's unregistered afterwards even if the test doesn't do it. The `bindings` fixture gives a fresh `Bindings`, the process's bindings, which handles use, with the extension registered: the API's in-memory state (`proscenium.runtime`) needs the extension's load, undo, and redo handlers.

### `isolated/`

A test calls `run_isolated(runtime, body, function, tmp_path, **kwargs)` from `isolated/harness.py`. It starts a fresh process running `isolated/runner.py`, which resets to the empty factory state and calls `function(**kwargs)` from a module in `isolated/bodies/`. The test then asserts on the returned value.

- A **body** module runs inside Blender's Python, with no pytest. It can import `bpy`, `pxr`, `support`, `fixtures`, `proscenium` (from `src/`), and `tools/` modules. Its arguments and return value must be JSON-compatible. If it raises, the test fails with the traceback from the fresh process; if the process exits nonzero, even after returning, it fails with the process output.
- The **`wheel`** fixture is a fresh bpy-wheel process. Use it by default.
- The **`runtime`** fixture is parametrized over the wheel and the Blender binary. Use it for cross-platform smoke tests that should also pass in the runtime users run. The **`binary`** fixture is the binary alone, for a check another layer already makes with the wheel. Binary runs are skipped without a binary, unless `PROSCENIUM_REQUIRE_BLENDER` is set.
- Each call gets its own Blender user dir under the test's `tmp_path`.
- The **`hydra_bridge`** fixture is the directory of M1b's compiled Hydra bridge (`tools/feasibility/hydra_bridge/`), which M4's prototype tests pass to their bodies. It builds the bridge from its sources once per run, into `build/hydra-bridge/` as `build.py` does; when nothing changed, the build only checks. `PROSCENIUM_HYDRA_BRIDGE` names a prebuilt one instead, as CI does on Linux, where the build must run on Blender's glibc floor.

Current tests:
- `test_roundtrip.py`: save/reopen with persistent and transient `load_post` handlers, and the extension's own load handler dropping an attachment.
- `test_ci_fixture.py`: the CI fixture's inventory with the binary's `pxr`, under both payload policies.
- `test_extension.py`: installing, enabling, and disabling the zip built by `tools/build_extension.py` in check mode (`sync=False`), which only reads `src/proscenium` and fails if its wheels or manifest are out of date with `uv.lock`, or its compiled core with its sources (run `tools/build_extension.py` to sync them). The installed copy's compiled core loads and matches the host's USD version, disabling removes the handlers, record namespaces, and classes it registered, and the zip's manifest names this platform.
- `test_baseline.py`: M4's object baseline, the bridge and its `apply.py`, and Phase D's batched alternative (`batch.py`, read from Blender's evaluated instances), each on `F-APPEARANCE-CASES` and `F-NESTED-STRESS`: one object per drawn copy and destination it displays in (one hidden object for a copy shown in neither), with its source and instance context; each face's material per destination, by its material purpose; meshes shared exactly among copies with equal mesh content, as USD computes it; each copy's world transform, in the plan and as Blender evaluates it (a sheared object through its parent empty, a sheared instance through its own transform), as `UsdGeom` computes it; each feasibility case's appearance values where the baseline stores them (display color and opacity, reader primvars, UV maps); with Hydra's own transforms asserted still wrong under a reset stack inside an instance (OpenUSD #862).
- `test_update.py`: updating the baseline's display with the bridge's `update.py`. Rebuilding one unit from the same plan, on `F-APPEARANCE-CASES` and `F-NESTED-STRESS` (one object, a shared mesh or material with its users repointed or replaced, an asset copy, and everything): preparation leaves the display untouched, and afterward it holds the same values, with new data exactly where the unit says, nothing left over, and an old mesh that an object outside the display uses kept intact. Updating by the plan diff after edits, on those fixtures and `F-UNIVERSE-MEMBERSHIP`: the display then holds what a fresh application of the new plan does, keeps exactly the data the diff matches, renumbers its objects, and writes nothing when nothing changed.
- `test_detach.py`: detaching the baseline's display with the bridge's `detach.py`, after Blender-side edits, on `F-APPEARANCE-CASES`, `F-NESTED-STRESS`, and `F-UNIVERSE-MEMBERSHIP`: it removes every `proscenium_` property and keeps everything else, edits and placeholders included, and the saved file reopens the same without the bridge.
- `test_plan_diff.py`: the bridge's plan diff after edits to the caller's stage, on `F-APPEARANCE-CASES`, `F-UNIVERSE-MEMBERSHIP`, and `F-NESTED-STRESS`: what each edit changes as the fixture is built (a transform, a prototype's points, a material, a constant primvar, visibility, removed and added prims, a payload unloaded and reloaded), and nothing when nothing is edited.
- `test_correspondence.py`: the baseline plan's correspondence on the interaction and appearance fixtures, at each time code they publish: its viewport display elements, each object's floor, and the browsing universe, against `support/interaction_oracle.py`.
- `test_interaction.py`: the headless interaction functions (the bridge's C++ correspondence and kind promotion, with a Python display component: the baseline's `selection.py`, or the batched display's `batch_selection.py`), by each check in `support/interaction_checks.py` on each interaction fixture, for both representations. The batched display's adapter reads what each carrier covers, and what a pick on it supplies, from the instances Blender evaluates it to.
- `test_stage_handle.py`: the compiled core's `StageHandle` keeps a stage alive until `release()`, then lets a stage its caller dropped expire, and never destroys one its caller still holds.

### `support/`

Helpers used by more than one layer or by `fixtures/`. A helper used by only one layer lives in that layer's directory instead.

| Module | Use it to |
|---|---|
| `usd.py` | `open_fresh(path, load)`: open a stage that no stage cache can hand back. |
| `blend.py` | `save_and_reopen(path)`: save and reopen the open file. Any bpy reference held across it is invalid afterwards. `collection_content(collection)`: a collection's objects as plain data (world matrices, parents, mesh geometry, and materials), read with bpy alone, to compare across a reopen or a process. |
| `copies.py` | `run(route, tmp_path)`: run one of `F-OWNERSHIP-AMBIGUITY`'s copy routes on a published binding "Shot". `records_by_name()`: every record in the file, with ID pointers as names, and each collection's objects, to check that detection changed nothing. |
| `display.py` | `publish_by_hand(binding_id, destination, display)`: build `F-OFFLINE`'s saved display and record it as a publication would, since nothing publishes until M5. `expected_content(display)` is what `collection_content` reads from it. |
| `undo.py` | `push`, `undo`, `redo` an undo step, failing if none is available. `require_global_undo()` skips when global undo is off, where background-mode undo is unavailable (see the [feasibility record](../docs/feasibility/runtime-record.md#undo)). |
| `interaction_oracle.py` | Expected results of the [interaction contract](../docs/spec/interaction-contract.md) on a fixture's live stage, from USD's own APIs: display elements, floors, the browsing universe, and kind-level targets. Checks of a representation's headless functions compare against it. |
| `interaction_checks.py` | The checks of a representation's seven headless interaction functions against `interaction_oracle.py`, written once and reused by M4, M7, and M10. A representation passes an adapter, a `Display`, that publishes generations of an interaction fixture's live stage; `CHECKS` names each check, and each check names its matrix rows. Uses bpy, so it runs where the display does. |

### `fixtures/`

Bespoke fixtures are the main correctness evidence ([acceptance.md](../docs/testing/acceptance.md#bespoke-fixtures)): small, generated by code, and deterministic.

- **`registry.py`** lists every named contract fixture from [strategy.md](../docs/testing/strategy.md#named-contract-fixtures). Each entry has its stable ID, the milestones whose Tests section names it, and, once written, its generator. A fixture without a generator is a stub; its owning milestone adds the generator. Each entry also lists its **cases**: one run of an operation (synchronize, cleanup, detach, or remove binding) with a declared outcome (success, completed with issues, or failure), the matrix rows its assertions check, and its qualification phase, the highest phase among those rows. Tests select a case by fixture and name. `bpy_free/test_fixture_registry.py` fails if the registry drifts from strategy.md or the milestone files, and `bpy_free/test_fixture_cases.py` if a case cites a row that doesn't list its fixture, has the wrong phase, or leaves a started milestone's row unchecked.
- **Generators** are context managers that take a fresh directory:

  ```python
  with source_access.dirty_layer(tmp_path) as scene:
      ...  # scene.caller, scene.dirty, scene.disk_values, ...
  ```

  Entering writes the fixture and builds any in-process state, such as open stages, unsaved edits, or cache entries. Leaving releases that state. The yielded object carries the values the fixture is built to produce. Tests compare against those, not against recorded output.
- **`source_access.py`** has the generators for `F-DIRTY-LAYER`, `F-PRIVATE-STAGE`, `F-CACHED-STAGE`, `F-REATTACH`, `F-MULTI-BINDING`, `F-BINDING-STATE`, and `F-OFFLINE` (owned by M3), all over `scenes/source_access/`. Each docstring states what state it sets up, and `bpy_free/test_source_access_fixtures.py` checks that the generator actually produces it.
- **`copies.py`** has the generator for `F-OWNERSHIP-AMBIGUITY`: a source, and for each copy route the outcome the canonical-candidate rule gives it, derived from the rule and the route. `support/copies.py` runs the routes, which are Blender operations.
- **`interaction.py`** has the generators for `F-KIND-HIERARCHY`, `F-NESTED-SELECTION`, and `F-UNIVERSE-MEMBERSHIP` over `scenes/interaction/`. Each yields the live stage and the results the scene is built to produce, written out by hand; `bpy_free/test_interaction_fixtures.py` checks that `support/interaction_oracle.py` derives the same results. `tools/show_interaction_fixtures.py` prints them (run it from the repository root as `uv run python tests/tools/show_interaction_fixtures.py`).
- **`appearance.py`** has the generators for `F-APPEARANCE-CASES`, the representation feasibility cases, and `F-NESTED-STRESS`, over `scenes/appearance/` (with the texture `grid.png`). Each yields the live stage and what its scene is built to display, written out by hand: sharing sets, display color and opacity, materials per destination and per face, the values primvar readers show, UV sets under UV-set names, and for the stress fixture each drawn mesh's world transform, determinant sign, shear, and purposes. `bpy_free/test_appearance_fixtures.py` checks them against USD's own APIs (`UsdGeom.XformCache`, `FindPrimvarWithInheritance`, `ComputeBoundMaterial` by purpose, GeomSubsets).
- **`records.py`** has the generator for `F-SCHEMA-VERSIONS`: records of a three-version test schema as ID properties store them (older, current, failed-migration, newer, invalid, and unreadable), and the `Sample` dataclass they load as, with what loading each must give, plus binding configurations a newer extension or damage could leave. They are values rather than files. `bpy_free/test_record_loading.py` loads them directly, and `blender/test_records.py` stores them in a scene to check save/reopen and that writing refuses to replace the newer and unreadable ones; `blender/test_bindings.py` stores the binding configurations and checks the binding refuses.
- **`production_like.py`** is the smaller generated CI fixture: a deep organizational hierarchy, instanceable crate payloads with nested instanceable bolts, multi-material assets, and one non-instanced crate. `expected_inventory(params, load_all)` derives what each payload policy must compose. `bpy_free/test_production_like.py` checks that against USD, and also checks determinism and a pinned checksum. Change the checksum only deliberately, together with the generator or its assets.
- **`scenes/`** holds static `.usda` layers, one directory per scene. Each layer has a header comment saying what it's for. Write static content as files here, not as Python strings.
  - `scenes/__init__.py` indexes them: the `Scene` enum has one member per directory, and `copy_scene(Scene.SOURCE_ACCESS, tmp_path)` copies a scene's files into `tmp_path` and returns it. Generators copy a scene, then make runtime-specific edits through the Sdf API.
  - To add a scene, create its directory and add a `Scene` member. `bpy_free/test_fixture_registry.py` fails if the index and the directories differ, or if a layer lacks its purpose comment.

To add a named fixture's generator, write it in a module under `fixtures/`, set it as the fixture's `build` in `registry.py`, and add a test in `bpy_free/` showing it produces the state it claims.

## Rules

Tests run in parallel worker processes. USD stages and layers, stage caches, and Blender data are per process, so workers never share them, but files on disk are shared:

- Write only under the test's `tmp_path`, or `tmp_path_factory` for session-scoped fixtures. Never write into the repository, including `src/`, `dist/`, and the manifest.
- Copy scenes with `fixtures.scenes.copy_scene` before opening them; never open `fixtures/scenes/` in place. Pass the test's `tmp_path` as the destination.
- Use fixture generators in a `with` block, so their stages, edited layers, and cache entries are released.
- Within a worker, tests run one at a time, but a stage or layer a test keeps alive is visible to later tests. Don't hold USD objects in module globals or session fixtures unless they're read-only.
- Expected results come from the spec or from how a fixture is built, never from recording the implementation's output.
- Import modules from your own directory relatively (`from .harness import run_isolated`), and modules from other directories absolutely (`from fixtures import production_like`, `from support.usd import open_fresh`). Isolated bodies use absolute imports only: the runner loads them by file path, outside any package.
