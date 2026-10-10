# M1 — Runtime feasibility, workspace, and test infrastructure: execution plan (archived)

> **Archived. Do not use as guidance.** This is the working plan as it stood during M1, kept for history only. Parts of it describe intentions that were later changed or reversed, and its relative links are not maintained. The current record is [docs/plans/M01-runtime.md](../../plans/M01-runtime.md); requirements are in PROJECT.md, spec/, and testing/.

## Context

M1 (`docs/milestones/M01-runtime.md`) is the first milestone and a **stop/go gate**. Before any synchronizer code is written, we need evidence that Blender 5.2 LTS + its bundled OpenUSD can do what the spec assumes (stage exchange, handlers, undo, dirty-layer detection, fresh stages, private views). We also need a reproducible dev/test/package workflow, an acceptance specification, and a requirement-to-test matrix that later milestones keep current.

Current state: only docs exist, plus `pyproject.toml` (dev group: `bpy~=5.2` and local `tools/bpy-site-packages`, which puts the wheel's bundled `pxr` on `sys.path`), and a `.venv` with bpy 5.2.2 / Python 3.13.13 / USD 0.26.3. Locally there is `/Applications/Blender.app` (5.2.2 LTS) on an M1 Max with 32 GB running macOS 26, and local downloads of ALab v2.3.0 and the techvar assets. ruff, ty, pre-commit, and gh are not installed. There is no git remote.

Decisions taken with the user:
- Windows/Linux are verified through **GitHub Actions** (the user adds a remote; I don't push without asking).
- The matrix is **YAML plus a pytest checker**, with a generated Markdown view.
- **Pause for review after the feasibility phase**, before tooling, fixtures, and the matrix.

Per the memory feedback: docs record requirements, and mechanisms are written as findings or suggestions for M3/M5. Windowed/UI-mode testing is out of scope and is recorded only as future work.

## Step 0 — Save plan
Copy this approved plan to `docs/plans/M01-runtime.md` before any other work. Work happens on branch `m01-runtime`. I'll suggest commits at phase boundaries but only commit when you say so. Your existing uncommitted README/pyproject changes stay as they are.

## Phase A — Runtime feasibility (then STOP for review)

Probes are scripts that emit JSON. They run in two runtimes:
(a) the `bpy` wheel under the uv venv, and
(b) the real Blender binary via `blender -b --factory-startup --python <probe>`.
The binary is what users run, so the record treats its results as authoritative.

Files:
- `tools/feasibility/` contains one probe module per topic plus `run_all.py`. `run_all.py` locates Blender via the `BLENDER` env var, falling back to platform-default paths, and writes `build/feasibility/<platform>-<runtime>.json`.
- `docs/feasibility/runtime-record.md` is the human-readable record, with one section per platform. macOS is filled in now; Windows/Linux are filled in from CI artifacts in Phase B.

Probe topics (each maps to an M1 bullet):
1. **Environment:** Blender build hash and version, Python version, `pxr` version, available `pxr` modules (Usd, UsdGeom, UsdShade, UsdLux, UsdSkel, Sdf, Ar, Tf, Vt, Gf, UsdUtils, …), module file paths, `Plug.Registry` plugin list and search paths, MaterialX presence, and whether Blender's USD importer and the Python `pxr` share one library (compare `Plug` registrations and `Sdf.Layer` registry visibility after `bpy.ops.wm.usd_import`).
2. **Stage exchange:** caller code creates a `Usd.Stage` (file-backed and in-memory/anonymous). Extension-style code in a separate registered module receives the same object, sees its unsaved edits, and shares the layer registry. Check that this works both in the binary and in the wheel.
3. **Handlers:** `load_post`, `undo_post`, and `redo_post` fire, with counts, under both the binary and the wheel, and inside pytest. Includes the `persistent` decorator across file loads.
4. **Undo:** a Python-API call that mutates data and pushes `bpy.ops.ed.undo_push`; then undo/redo restores it. Record behavior with `use_global_undo` on and off, and in background mode. Unsupported cases are recorded as findings, not worked around.
5. **In-memory source candidates** (source-access design note): open a private stage over the caller's root and session layers with a different load policy. Check that unsaved caller edits are visible and that the caller's load state, population mask, muted layers, and edit target are unchanged. Check two private stages with different payload policies side by side, and what can and can't be reproduced (mask, muting, resolver context, interpolation).
6. **Dirty layers and fresh stages:** detect dirty contributing layers via `GetUsedLayers()` including arc-introduced layers; open a fresh stage while a `Usd.StageCache`/`StageCacheContext` holds one (verify the stage is not reused); reload clean layers and observe the effect on other stages.
7. **Private disk view:** try candidate ways to compose the on-disk state without touching shared registry layers: anonymous copies plus a remapping resolver context, `Sdf.Layer.OpenAsAnonymous` per layer with asset-path remapping, and a separate `Ar` context. Record whether any of them is reliable. The result feeds the DECISIONS.md row "Private disk view feasibility".
8. **Packaging:** build and validate a minimal extension. First try doing this **from the bpy wheel alone**. The wheel ships `bpy/5.2/scripts/addons_core/bl_pkg/cli/blender_ext.py`, which only imports the standard library. Run it as `python blender_ext.py validate|build --source-dir … --output-dir …`, located via `bpy`'s package path. If that works, packaging won't need a system Blender binary. Also try installing and enabling in-process with the wheel (`bpy.ops.extensions.package_install_files` into a temporary user repo), then register/unregister in background mode. Compare the results with `blender --command extension …` from the binary.

Deliverable for the checkpoint: the macOS section of the record, a summary of any blockers, and the proposed DECISIONS.md updates (private disk view; any undo/handler caveats). **I stop here and wait for your go-ahead.**

## Phase B — Workspace, extension skeleton, tooling, CI

- **Layout:**
  - `src/proscenium/` is the extension source dir. It holds `blender_manifest.toml` (schema 1.0.0, `blender_version_min = "5.2.0"`, license MIT, wheels generated by the build) and `__init__.py` with minimal `register`/`unregister`. `__init__.py` stays bpy-free and imports Blender-facing code (`addon.py`) only on register.
  - Pure-Python subpackages that will not import `bpy` come later. M1 only adds a placeholder `src/proscenium/core/__init__.py`, so the bpy-free test layer has an import target. pyproject gets a src-layout build config so `proscenium` is importable in the venv.
- **pyproject:**
  - Add `ruff`, `ty`, `pytest`, `pre-commit`, and `packaging` to the dev group, plus the stub packages `fake-bpy-module-5.2` and `types-usd`. These install as `bpy-stubs`/`pxr-stubs`, so they don't shadow the runtime modules. `types-usd` 24.5 lags the bundled USD 0.26.
  - Configure `[tool.ruff]` for PEP8, import ordering (`I` with `known-first-party = ["proscenium"]`; `bpy`/`pxr` treated as third-party), and annotation rules (ANN) to match the README style guide, `[tool.ty]`, and `[tool.pytest.ini_options]` with markers `bpy_free`, `blender`, `isolated`, `alab`, and `slow`.
  - Fill in the project description.
- `.pre-commit-config.yaml`: ruff check, ruff format, ty, `uv lock --check`, and (Phase D) the matrix checker.
- `tools/build_extension.py` builds for the current machine, using only the wheel's `blender_ext.py`. It always runs from the uv environment, so there is no Blender binary fallback.
  - It exports the runtime dependencies (never the dev group) from uv.lock as a pylock and selects this machine's wheels with `packaging.pylock`.
  - It syncs `src/proscenium/wheels/` (gitignored), keeping wheels whose sha256 matches the lock and downloading only missing ones.
  - It rewrites the `wheels` key between the generated-block markers in the manifest. The block sits above `[build]`, which stays hand-written. `platforms` is omitted while nothing is platform-dependent.
  - Then it runs validate → build → validate on the archive.
  - `--check` (`build(..., sync=False)`, added in Phase C) never writes to the source dir. It fails if the wheels or the generated block are out of date. The extension test uses it, so concurrent test workers build from `src/` without copying it or racing on it. CI runs the normal build before the tests, so the wheels are present.
  - There is no leak check. Blender only installs wheels listed in the manifest, and the manifest's wheels come from the runtime lock alone.
- **`AGENTS.md`** with the two required instructions:
  - Read PROJECT.md and spec/invariants.md first.
  - Keep invariants.md in sync with the spec in the same change, as a summary that defers to the spec.
  
  It also covers the uv/test/lint/build commands and the style guide. Add a `CLAUDE.md` containing `@AGENTS.md` so Claude Code picks it up.
- `.github/actions/setup-blender` downloads the Blender 5.2.2 portable build for the runner OS (cached, checksum-verified) and exports `BLENDER`.
- `.github/workflows/ci.yml` runs on push/PR:
  - A lint job (ruff, ty).
  - A test matrix over `ubuntu-latest`, `windows-latest`, and `macos-latest`: set up Blender, `uv sync`, pytest (all layers, including isolated binary tests), and the extension build, uploading the zip.
  - ALab is never run in CI.
- `.github/workflows/feasibility.yml` is manual only (`workflow_dispatch`). It runs `run_all.py --strict` on the same three OSes and uploads the JSON results.
- After you add a remote and push, you trigger the feasibility workflow, and I put the Windows/Linux results into the feasibility record.

## Phase C — Test infrastructure

Tests run in parallel with pytest-xdist (`pytest -n auto`). Each test gets the marker of its layer directory. Measured on the reference machine:
- Resetting a reused process costs about 30 ms.
- A fresh bpy-wheel process costs about 0.85 s, and the binary about 1.2 s.
- Forking a process with bpy loaded aborts (bpy is multi-threaded).

So reused workers are the default, and fresh processes are kept for the cases that need them. Stages and Blender data are per process. Files are the shared resource: tests write only under `tmp_path`, copy scenes before opening them, and never write into the repo.

- `tests/bpy_free/`: plain Python. Layers are named for the runtime, not for test granularity; unit and integration tests can live in any layer. A conftest blocks Blender modules while this layer's tests are collected and run, so importing them fails the test. Blender modules already loaded by other layers are hidden from `sys.modules` meanwhile. A subprocess test imports `proscenium` and every `proscenium.core` module with Blender blocked.
- `tests/blender/`: the bpy wheel in-process, one reused process per worker. Before each test, an autouse fixture resets with `read_factory_settings(use_empty=True)` and asserts a clean baseline. The baseline covers:
  - The extension is not registered.
  - Handlers match Blender's own, compared by name, since Blender re-creates its handler functions on reset.
  - No data beyond the factory UI and one empty scene.
  - An empty `UsdUtils.StageCache`.
  - No dirty file-backed layer still loaded.

  After each test it unregisters the extension, removes added handlers, and clears the stage cache. Finding recorded in the reset code: Blender 5.2.2 appends pose_library's load handlers again on every factory reset, so reset drops the duplicates.
- `tests/isolated/`: `run_isolated` (`isolated/harness.py`) runs a body function from `tests/isolated/bodies/` in a fresh process and returns its JSON result. The default runtime is a fresh bpy-wheel process. Smoke tests use the `runtime` fixture to also run in the binary. Without a binary these are skipped, unless `PROSCENIUM_REQUIRE_BLENDER` is set, as in CI.
- Layer-specific helpers live in their layer: `bpy_free/bpy_blocker.py`, `blender/state.py` (reset and baseline), and `isolated/harness.py` plus `runner.py`.
- **Shared helpers** in `tests/support/`:
  - `blend.save_and_reopen`.
  - `undo`: push, undo, and redo. Skips when global undo is off, where background-mode undo fails its poll.
  - `usd`: `open_fresh` under `BlockStageCaches`.
- **Bespoke fixture framework** in `tests/fixtures/`:
  - `registry.py` lists the 19 named fixtures with stable IDs. Each records the milestones whose Tests section names it, and an optional generator (a context manager writing into a tmp dir). A test keeps the IDs and milestones in sync with strategy.md and the milestone files.
  - `scenes/` holds the static layers, one directory per scene. `scenes/__init__.py` indexes them in a `Scene` enum, and `copy_scene(Scene..., tmp_path)` is the only way to use them. A test keeps the index in sync with the directories and checks that every layer has a purpose comment.
  - Fixture cases (operation, outcome, requirement IDs, and phase, as acceptance.md requires) are not declared yet. Phase D designs their schema together with the matrix and its link to tests. Each owning milestone declares the cases for its fixtures; M3 owns the cases for the three seeds below.
  - M1 ships generators for `F-DIRTY-LAYER`, `F-PRIVATE-STAGE`, and `F-CACHED-STAGE` over a shared static scene. Tests check that each generator produces the state it claims. The other 16 are stubs assigned to their milestones.
- **Smaller generated CI fixture** (`tests/fixtures/production_like.py`):
  - Static assets on disk: crate and bolt meshes with two materials each, GeomSubsets, and a ground mesh.
  - A generated layout: a deep organizational hierarchy, instanceable crate payloads with nested instanceable bolts, and one non-instanced crate.
  - `expected_inventory` derives the counts for each payload policy from the parameters, and a test checks them against USD.
  - Determinism and a pinned checksum are tested, and CI checks them on all three OSes.
- **Cross-platform smoke tests:**
  - Blender modules import in the blender layer, and `pxr` is Blender's bundled one.
  - Register/unregister.
  - Save/reopen, and an undo/redo step.
  - In fresh wheel and binary processes: save/reopen with persistent and transient `load_post` handlers, the CI fixture's inventory under both policies, and installing, enabling, and disabling the built extension zip.

## Phase D — Acceptance details, ALab inventory, matrix

A first draft went further: fixtures and oracles on every row, 44 planned fixtures, a case schema with a qualification mode, risk flags, a full bounds contract, and a time-code helper. Most of that encoded designs that M2–M14 own, so it was cut back to what M1 needs and can know now.

- No separate acceptance specification. Once its premature parts were cut, the rest fit in the files it summarized:
  - acceptance.md#sampled-time-codes gained the time-code details: fixtures declare their transitions and seed extra samples from their ID; offsets are binary fractions; M6 sets the sample counts.
  - The bounds comparison contract moved to M4 (DECISIONS.md row, M4 deliverables, acceptance.md#bounds-comparison-contract), because what was independent of the representation was too thin to be a contract. The DECISIONS row keeps the M1 finding: `BBoxCache`'s aligned world range is looser than the points' box under rotation (1.414 against 0.707 for a rotated triangle).
  - The ALab pin is a bullet in acceptance.md's ALab section; `docs/testing/alab/README.md` has the install recipe (v2.3.0 with techvar v2.2.0 installed into `ALab/fragment`; every file of the separate techvar download matched its installed copy) and the inventory findings. `tools/alab_checksums.py` writes and `--check`s `docs/testing/alab/subtrees.sha256`: one hash per subtree (top-level entries, `fragment/` per child) and one for the whole tree, over a per-file manifest of 14,150 files (dotfiles excluded) that is written to `build/alab/` but not committed.
  - The reference hardware is the feasibility record's macOS environment row (Apple M1 Max, 32 GB, macOS 26, Blender 5.2.2 `d13f752e3b9c`), which acceptance.md#performance points to, with the measurement conditions.
- `tools/alab_inventory.py` writes `docs/testing/alab/inventory.md`, which is committed, and full JSON counts with the per-prototype list to `build/alab/`, which is not. It counts types, applied schemas, kinds, and shader IDs in the default traversal, with prototypes counted once and expanded by their uses. A self-check compares scene plus expanded counts with an instance-proxy traversal (47,401 under load-all). Findings:
  - Under load-none, nothing loads: `/root`, the only root prim, is a payload. 381 prototypes exist only below unloaded payloads and are not counted.
  - No prototype contains another instance, so ALab exercises no nested native instancing.
- **Matrix** (`docs/testing/requirements.yaml`, rendered to `requirements-matrix.md`). Decided with the user:
  - Each row quotes its requirement text. The checker requires every bullet, paragraph, table row, and code block in PROJECT.md, spec/, and testing/ to be quoted by a row or excluded with a reason, or with the IDs it restates. Short lead-ins ending in ":" are skipped. A row's quote must match exactly one block.
  - Row kinds: behavior, contract (covered by the settling decision record), and process (covered by a tooling or CI check). acceptance.md gained a bullet saying so.
  - Each invariant bullet ends with its row IDs, which must belong to sections the bullet links.
  - Rows record id, quote, kind, delivery, and phase. Fixtures and oracles are recorded only where known now: the named contract fixtures and M1's own rows. A milestone fills in its rows before implementing them and adds itself to `started`; the checker then requires them.
  - Permissions, scope limits, and design guidance with no checkable outcome (for example "One source prim may produce multiple display elements"), and statements that are true by construction, place an architectural boundary, or outline contents traced by other rows, are excluded with a reason naming the milestone they guide; acceptance.md says so.
  - Result: 261 rows (197 behavior, 19 contract, 45 process). In-memory source rows are Phase 2, since PROJECT.md lists in-memory sources under Phase 2; file-backed refresh is Phase 1.
- `tools/matrix.py check` validates fields, milestones (from file names, including M1b), fixtures, quotes, completeness, invariants, the `started` rule, and that the view is current; `render` regenerates the view. It runs as a pre-commit hook. `tests/bpy_free/test_matrix.py` runs it and shows that each kind of drift is caught.
- Deferred: fixture cases and their schema (M3, with its first fixtures), planned fixtures (each delivering milestone), coverage-per-phase qualification (M12/M14), and risk flags (M4's risk matrix).

## Addendum — Hydra bridge (added 2026-10-09)

After Phase C, a side investigation found that Hydra's scene-index API could serve as the evaluation front end, but Blender's Python `pxr` lacks `Hd`, `Hdsi`, and `UsdImaging`. A compiled bridge (`tools/feasibility/hydra_bridge/`, scikit-build-core + CMake, headers cached in gitignored `external/`) links to Blender's `libusd_ms` on macOS arm64 and passes 27 checks in the wheel and the binary; see the [record](../feasibility/runtime-record.md#compiled-hydra-bridge--macos-arm64). The front-end and core-language decision is a new gate, [M1b](../milestones/M01b-evaluation-gate.md), between M1 and M3.

Effects on this plan:
- Phase B's `feasibility.yml` gains a bridge build-and-run step on all three OSes once the CMake build supports Windows and Linux. That work and its results belong to M1b and do not gate M1's exit.
- Phase B's "pure-Python subpackages" under `proscenium/core/` stay provisional until M1b decides; if Hydra is adopted, the core becomes a compiled module and `AGENTS.md`'s layout, build, and test rules change with it.
- Phase D's matrix accepts `M1b` as a delivery milestone.

## Critical files
`docs/plans/M01-runtime.md`, `tools/feasibility/*`, `docs/feasibility/runtime-record.md`, `src/proscenium/blender_manifest.toml`, `src/proscenium/__init__.py`, `pyproject.toml`, `.pre-commit-config.yaml`, `AGENTS.md`, `CLAUDE.md`, `.github/workflows/ci.yml`, `tools/build_extension.py`, `tests/{bpy_free,blender,isolated,support,fixtures}/`, `tools/alab_inventory.py`, `docs/testing/requirements.yaml`, `tools/matrix.py`, `docs/DECISIONS.md`. The existing `tools/bpy-site-packages` is reused as-is for wheel-based runs.

## Verification
- `uv run python tools/feasibility/run_all.py` produces JSON for both runtimes on macOS. The record matches it.
- `uv run ruff check . && uv run ruff format --check . && uv run ty check` are clean, and `uv run pre-commit run --all-files` passes.
- `uv run pytest -n auto` passes, including the isolated binary cases when a Blender binary is found (required in CI).
- `uv run python tools/build_extension.py` creates a validated zip without using the system Blender, and syncs the manifest's wheels from uv.lock. The isolated install/enable/disable test passes.
- `uv run python tools/matrix.py check` passes (it also checks that the generated Markdown is up to date).
- `PROSCENIUM_ALAB_ROOT=… uv run python tools/alab_inventory.py` writes both inventories, and `tools/alab_checksums.py --check` passes.
- The CI run is green on all three OSes, and its artifacts fill in the Windows/Linux record sections. That completes the M1 exit condition.
