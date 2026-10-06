# M1 — Runtime feasibility, workspace, and test infrastructure: execution plan

## Context

M1 (`docs/milestones/M01-runtime.md`) is the first milestone and a **stop/go gate**. Before any synchronizer code is written, we need evidence that Blender 5.2 LTS + its bundled OpenUSD can do what the spec assumes (stage exchange, handlers, undo, dirty-layer detection, fresh stages, private views). We also need a reproducible dev/test/package workflow, an acceptance specification, and a requirement-to-test matrix that later milestones keep current.

Current state: only docs exist, plus `pyproject.toml` (dev group: `bpy~=5.2` and local `tools/bpy-site-packages`, which puts the wheel's bundled `pxr` on `sys.path`), and a `.venv` with bpy 5.2.2 / Python 3.13.13 / USD 0.26.3. Locally there is `/Applications/Blender.app` (5.2.2 LTS) on an M1 Max with 32 GB running macOS 26.5.1, ALab at `~/Downloads/ALab-2.3.0`, and `~/Downloads/techvar_assets`. ruff, ty, pre-commit, and gh are not installed. There is no git remote.

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
  - `src/proscenium/` is the extension source dir. It holds `blender_manifest.toml` (schema 1.0.0, `blender_version_min = "5.2.0"`, no wheels) and `__init__.py` with minimal `register`/`unregister`.
  - Pure-Python subpackages that will not import `bpy` come later. M1 only adds a placeholder `src/proscenium/core/__init__.py`, so the unit-test layer has a bpy-free import target. pyproject gets a src-layout build config so `proscenium` is importable in the venv.
- **pyproject:**
  - Add `ruff`, `ty`, `pytest`, and `pre-commit` to the dev group.
  - Configure `[tool.ruff]` for PEP8, import ordering (`I` with `known-first-party = ["proscenium"]`; `bpy`/`pxr` treated as third-party), and annotation rules (ANN) to match the README style guide, `[tool.ty]`, and `[tool.pytest.ini_options]` with markers `unit`, `blender`, `isolated`, `alab`, and `slow`.
  - Fill in the project description.
- `.pre-commit-config.yaml`: ruff check, ruff format, ty, and the matrix checker.
- `tools/build_extension.py` runs `validate` and then `build` into `dist/`. It uses the wheel's `blender_ext.py` if Phase A shows that works, and only otherwise falls back to a located Blender binary.
  - After building, it **fails if any package from the dev dependency group got copied into the zip**. It gets the dev package list from `uv`/installed distribution metadata (`bpy`, `bpy-site-packages`, ruff, pytest, …, plus their top-level import names and `.dist-info`), and checks zip entries and any bundled wheels against that list.
  - It does not fail on `pxr` in general.
- **`AGENTS.md`** with the two required instructions:
  - Read PROJECT.md and spec/invariants.md first.
  - Keep invariants.md in sync with the spec in the same change, as a summary that defers to the spec.
  
  It also covers the uv/test/lint/build commands and the style guide. Add a `CLAUDE.md` containing `@AGENTS.md` so Claude Code picks it up.
- `.github/workflows/ci.yml` runs a matrix of `ubuntu-latest`, `windows-latest`, and `macos-latest`:
  - `uv sync`, ruff, ty, and pytest (unit plus bpy-wheel layers).
  - A job that downloads the Blender 5.2.2 portable build for that OS, then runs the feasibility probes, the binary smoke tests, and the extension build.
  - It uploads the feasibility JSON as artifacts.
  - ALab is never run in CI.
- After you add a remote and I push (with your confirmation), I put the Windows/Linux CI results into the feasibility record.

## Phase C — Test infrastructure

- `tests/unit/`: pure Python with no `bpy` import. A conftest guard fails the run if `bpy` gets imported.
- `tests/blender/`: pytest against the bpy wheel in-process, so Blender test processes are reused. An autouse fixture resets state explicitly with `read_factory_settings(use_empty=True)`, clears handlers registered by tests, unregisters the extension, and clears `Usd.StageCache`/the layer registry where needed. It asserts a clean baseline before each test.
- `tests/isolated/`: a helper that runs a test body in a fresh Blender binary subprocess for things the reused process can't do cleanly (load_post across real file loads, extension install, handler leakage), and returns structured JSON results.
- **Support helpers** in `tests/support/`:
  - `blend_roundtrip` saves to a temp `.blend` and reopens it.
  - `undo_helpers` pushes, undoes, and redoes, and skips with a recorded reason where Phase A showed it is unsupported in background mode.
  - Temporary USD directories.
- **Bespoke fixture framework** in `tests/fixtures/`:
  - A registry with stable IDs (e.g. `F-DIRTY-LAYER`) and deterministic pxr generators that write to tmp dirs.
  - Each case declares its operation, expected outcome, requirement IDs, and phase, as acceptance.md requires.
  - M1 ships the framework plus generators used by M1 tests (dirty-layer, cached-stage, private-stage seeds) and stubs for the other named fixtures, each assigned to its owning milestone.
- **Smaller generated CI fixture** (`tests/fixtures/production_like.py`): nested native instancing, multi-material assets, payloads, and a deep organizational hierarchy. Deterministic, with a checksum test.
- **Cross-platform smoke tests:** import pxr, register/unregister the extension, open the CI fixture, and do a save/reopen roundtrip.

## Phase D — Acceptance specification, ALab inventory, matrix

- `docs/testing/acceptance-spec.md` covers:
  - The sampled time-code set rules.
  - The bounds comparison contract: coordinate space, purpose sets, invisibility, extent hints vs evaluated bounds, placeholders and markers, subdivision, displacement, absolute and relative tolerances, empty and unknown bounds.
  - ALab checksums (SHA-256 manifest of the ALab and techvar trees, stored as a file under `docs/testing/alab/`).
  - The reference hardware: M1 Max, 32 GB, macOS 26.5.1, Blender 5.2.2 build hash.
  
  Update the DECISIONS.md bounds row.
- `tools/alab_inventory.py` reads `PROSCENIUM_ALAB_ROOT` (and the techvar path), opens `entry.usda` under load-all and load-none, and counts prim types, applied schemas, and shader IDs, including prototype contents with their instance counts. Output goes to `docs/testing/alab/inventory-{load-all,load-none}.json` plus a short summary. First I'll check whether techvar v2.2.0 needs `install_optional_packages.py`.
- **Matrix** (`docs/testing/requirements.yaml`). I build it by walking PROJECT.md, spec/, and testing/ section by section. Each row has:
  - `id` (e.g. `SRC-FILE-003`) and `spec` (file#anchor).
  - `delivery` milestone, `fixture`, `test_or_oracle`, `qualification` milestone and phase, `high_risk`, and `summary`.
  
  Invariants reference row IDs rather than duplicating them.
- `tools/matrix.py` validates the matrix and renders `requirements-matrix.md`. The validation checks:
  - IDs are unique and every anchor exists.
  - Required fields are present and milestones are valid.
  - Every row has a fixture and oracle.
  - Every invariant bullet maps to an existing ID.
- `tests/unit/test_matrix.py` runs the checker.

## Critical files
`docs/plans/M01-runtime.md`, `tools/feasibility/*`, `docs/feasibility/runtime-record.md`, `src/proscenium/blender_manifest.toml`, `src/proscenium/__init__.py`, `pyproject.toml`, `.pre-commit-config.yaml`, `AGENTS.md`, `CLAUDE.md`, `.github/workflows/ci.yml`, `tools/build_extension.py`, `tests/{unit,blender,isolated,support,fixtures}/`, `docs/testing/acceptance-spec.md`, `tools/alab_inventory.py`, `docs/testing/requirements.yaml`, `tools/matrix.py`, `docs/DECISIONS.md`. The existing `tools/bpy-site-packages` is reused as-is for wheel-based runs.

## Verification
- `uv run python tools/feasibility/run_all.py` produces JSON for both runtimes on macOS. The record matches it.
- `uv run ruff check . && uv run ruff format --check . && uv run ty check` are clean, and `uv run pre-commit run --all-files` passes.
- `uv run pytest -m "unit or blender"` passes, and `uv run pytest -m isolated` passes using the Blender binary.
- `uv run python tools/build_extension.py` creates a validated zip without using the system Blender, if Phase A confirmed that works. A test that plants a dev-dependency file in the source dir shows the leak check fails the build. The isolated install/enable/disable test passes.
- `uv run python tools/matrix.py check` passes, and the generated Markdown is up to date.
- `PROSCENIUM_ALAB_ROOT=… uv run python tools/alab_inventory.py` writes both inventories.
- The CI run is green on all three OSes, and its artifacts fill in the Windows/Linux record sections. That completes the M1 exit condition.
