# Agent Instructions

## Before any work

Read [docs/PROJECT.md](docs/PROJECT.md) and [docs/spec/invariants.md](docs/spec/invariants.md) first. For milestone work, also read the milestone file in [docs/milestones/](docs/milestones/), its plan in [docs/plans/](docs/plans/) if one exists, and [docs/DECISIONS.md](docs/DECISIONS.md).

Do not read `docs/archive/` unless the user asks for it. It holds superseded documents kept for history; they describe intentions that were later changed and would mislead current work. Never treat them as requirements or guidance, and don't update them.

## Keep invariants in sync with the spec

- Any change to a guarantee in a spec file updates its statement in `docs/spec/invariants.md` in the same change, and the reverse.
- `invariants.md` stays a summary that links to and defers to the authoritative spec section. It never gains detail of its own. Each bullet ends with the IDs of the matrix rows it summarizes.

## Keep the requirement matrix in sync

- [docs/testing/requirements.yaml](docs/testing/requirements.yaml) has a row for every requirement in PROJECT.md, spec/, and testing/, quoting its text. Any change to those docs updates the affected rows (or the `excluded` list) in the same change, then regenerates the view with `tools/matrix.py render`. Contract decisions update their rows before implementation.
- Before a milestone implements anything, it fills in the fixtures and oracle of the rows it delivers and adds itself to `started`.
- `tools/matrix.py check` fails on drift: a quote no longer in its section, a block no row traces, an invariant without IDs, an unknown fixture or milestone, or a started milestone's row without an oracle (or a behavior row without a fixture). It runs as a pre-commit hook and as a bpy_free test.
- Retired IDs are never reused.

## Layout

- `src/proscenium/`: the extension source dir (`blender_manifest.toml`, `register`/`unregister`).
  - `proscenium/__init__.py` and `proscenium/core/` must import without `bpy`.
  - `proscenium/core/` also holds the compiled core's C++ source. See [Compiled core](#compiled-core).
  - Blender-facing code is in three tiers, each importing only the tiers below it and `core/` ([plan](docs/plans/source-tiers-and-names.md#tiers)):
    - `proscenium/api/`: what callers use, the binding handle and the process's bindings.
    - `proscenium/runtime/`: disposable in-memory state built from the records.
    - `proscenium/persistence/`: versioned records in ID properties.
  - `proscenium/addon.py` registers the extension and its handlers, and may import any tier.
  - Every directory has a `README.md` naming each of its files and subdirectories and what it holds. Update it with any file added, removed, or renamed there (enforced by `tests/bpy_free/test_source_readmes.py`).
- `tests/`: the `bpy_free/`, `blender/`, and `isolated/` layers, plus shared `support/` helpers and `fixtures/`. See [Tests](#tests).
- `tools/`:
  - `build_extension.py`: build script.
  - `native_build.py`, `blender_deps.py`: build compiled modules against the locked Blender release's USD, and audit their linkage.
  - `clang_tidy.py`: runs clang-tidy on the compiled core and the Hydra bridge, each with its build's compile commands (a pre-commit hook).
  - `matrix.py`: checks and renders the requirement-to-test matrix.
  - `alab_checksums.py`, `alab_inventory.py`: pin and inventory the ALab production-scale fixture (`docs/testing/alab/`).
  - `feasibility/`: M1 runtime probes and M1b's Hydra bridge (`hydra_bridge/`). Results are in `docs/feasibility/runtime-record.md`. The bridge is evidence, not product code.
  - `bpy-site-packages/`: puts the bpy wheel's bundled `pxr` on `sys.path`.
- `docs/`: the spec, milestones, decisions, and testing docs. `docs/plans/` holds each milestone's decision log; `docs/archive/` holds superseded documents (see [Before any work](#before-any-work)).

## Commands

All commands run through uv. The dev group includes the `bpy` wheel, so `bpy` and `pxr` import in the uv environment without a Blender install.

```sh
uv sync                                   # install the dev environment
uv run pre-commit run --all-files         # all lint checks (ruff, ty, clang-format, clang-tidy, lock, matrix); same as CI
uv run pytest -n auto                     # all tests, in parallel; select layers with -m (e.g. -m bpy_free)
uv run python tools/build_extension.py    # dist/proscenium-<version>.zip for this platform (--check: read-only)
uv run python tools/matrix.py check       # requirement matrix (render: regenerate requirements-matrix.md)
uv run python tools/feasibility/run_all.py  # feasibility probes (wheel, pytest, binary)
uv run pre-commit install                 # once per clone
```

Tests and probes that need the Blender binary find it through the `BLENDER` env var, or else the platform default install path. Without a binary, binary tests are skipped, unless `PROSCENIUM_REQUIRE_BLENDER` is set (as in CI).

## Compiled core

M1b adopted a C++ core that reads Hydra scene indices ([DECISIONS.md](docs/DECISIONS.md) "Evaluation front end and core language"). It holds evaluation, the snapshot, planning, source-side diagnostics, and Phase 2 comparison. Everything that touches Blender stays in Python. The display plan is the one boundary: an immutable object whose large arrays Python reads without copying.

- **Source:** C++ in `src/proscenium/core/`, beside that package's Python. The manifest's `[build]` patterns keep C++ sources and CMake files out of the zip; only the built module ships, in the same package.
- **Build:** through `tools/build_extension.py`, from `src/proscenium/core/` only: one zip per platform, built on that platform, against the dependency headers of the Blender release `uv.lock` pins, and linked only to Blender's bundled `usd_ms`. The module (`proscenium.core._core`, ignored by `core/.gitignore`) is built into that package. Only the zip's copy of the manifest names the platform and sets `blender_version_max`, so each zip supports one Blender minor version (5.2.x). CI builds Linux's on Blender's glibc floor (manylinux_2_28). The Hydra bridge in `tools/feasibility/` is test code and never goes through it. Both build through `tools/native_build.py` (toolsets and the linkage audit) and `tools/blender_deps.py` (the pinned headers); the core's and the bridge's CMakeLists.txt set the same flags.
- **Boundary rules** (M1b findings):
  - Every entry point turns Tf errors and C++ exceptions into Python exceptions.
  - Arrays for Blender cross as 1-D read-only buffers whose element types match Blender's exactly (`'f'`, `'i'`, `'?'`). Any other type would silently take Blender's slow path.
  - Values the core gives Hydra are Vt's own types; a type made in the core's module isn't recognized by USD's code.
  - The core never keeps a released stage alive.
  - Each workaround for an OpenUSD bug is labeled `WORKAROUND for OpenUSD #<issue>` at every site, and a known-gap check fails when the bug stops reproducing.
- **Style:** C++17, warnings as the core's CMakeLists.txt sets them, and no warnings in any platform's build. clang-format and clang-tidy run as pre-commit hooks on the core and on the Hydra bridge in `tools/feasibility/`. Each has its own `.clang-format`; clang-tidy's checks are in the root `.clang-tidy`, which covers both and includes the C++ Core Guidelines checks, and every clang-tidy warning fails.
  - **Pointers:** no owning raw pointers; `TfCreateRefPtr(new ...)`, as Tf's ref-counted types require, is the exception. A raw `T*` is non-owning and means something when null (a lookup that found nothing, an absent optional argument), and its declaration says what null means. Anything never null is a reference, or `std::reference_wrapper` in a container.
  - **Exceptions to a check:** a `NOLINT` names its check and says why the code needs it.
- **Inspection layer:** a C++ library that maps picked prims to selection targets by kind on the live stage ([interaction contract](docs/spec/interaction-contract.md#two-layers-and-the-live-stage)). The core calls it and exposes it through the core's own bindings; it has no Python bindings, and never includes or calls the core. The build and style rules above apply to it too. M7 builds it.
- **Tests:** through the core's Python module, in the test layers below. Expected values come from the spec, from USD's own APIs (`UsdGeom`, `UsdShade`), or from how the fixture is built, never from Hydra's output. A test whose input could crash native code runs in `isolated/`, since a crash ends the process.

## Tests

[tests/README.md](tests/README.md) documents the test tree: which layer to use, the helpers, the fixture framework, and the rules. Read it before writing tests. In summary:

- Layers are directories named for what a test runs in, not how much it covers. Each test gets its directory's marker:
  - `bpy_free/`: plain Python with Blender modules blocked. Prefer it.
  - `blender/`: the bpy wheel in a reused process, reset and checked clean before every test.
  - `isolated/`: a fresh wheel or binary process per test, for what a reset can't make clean.
- Bespoke fixtures are registered in `tests/fixtures/registry.py`. Generators are context managers that write into a tmp dir. Static layers are `.usda` files in `tests/fixtures/scenes/`.
- Tests run in parallel. Write only under `tmp_path`, never into the repository, and copy scenes before opening them.
- Expected results come from the spec or from how the fixture is built, never from recording the implementation's output.

## Distribution

`tools/build_extension.py` is the only distribution build. Its output, `dist/proscenium-<version>.zip`, is what Blender installs. Releases ship one zip per platform and Blender minor version on GitHub releases ([DECISIONS.md](docs/DECISIONS.md) "Native core distribution"). The Python wheel from `uv build` only exists so `proscenium` installs editable in the dev environment. Never publish or distribute it.

## Dependencies

- Runtime dependencies go in `[project] dependencies`. The build bundles them as wheels and syncs the generated block between the markers in `blender_manifest.toml`. Never edit that block by hand. The rest of the manifest, including `[build]`, is hand-written.
- Tooling, stubs, and `bpy` go in the dev group and never ship.
- Never bundle another OpenUSD build: the extension uses the `pxr` bundled with Blender.

## Style

- Follow PEP 8 (ruff, line length 120) and annotate every function signature.
- Classes declare their typed attributes in the class body, above `__init__`.
- Mark every method override with `typing.override` (ty's `missing-override-decorator` rule enforces it).
- Names:
  - One concept per word, the [Glossary](docs/PROJECT.md#glossary)'s where it has one. A bare generic such as `index`, `source`, or `binding` is never used where it could mean more than one thing: `binding_index` and `ownership_index`, `source_kind`, `candidate` for one record or copy of a binding identity.
  - Spec terms keep their meaning. A *generation* is a published generation, a *layer* a USD layer or a pipeline layer, a *synchronization* one attempt, and a *claim* and a *candidate* what the spec defines. None names anything else, and the source tiers are tiers, never layers.
  - Exceptions end in `Error`, so they aren't mistaken for values (ruff's N818 enforces it).
  - A type names its domain: `DiagnosticCategory`, `DecisionReason`, not `Category` or `Reason`.
  - A function is named for its effect. One that decodes or encodes a stored record is `read_*` or `write_*`; one that changes held state and writes it through to the record is `set_*`; any other is named for what it returns (`config(binding_id)`, `index_texts()`); and an operation the spec defines takes the spec's verb (`synchronize`, `reload`).
- Prefer short docstrings plus inline comments over long docstrings. Docstrings follow pep257 (ruff's D rules): a one-line summary ending in a period or question mark, then a blank line before any more. Public objects in `src/` and `tools/` have one; tests and `tools/feasibility/` need one only where it adds something.
- Keep files under ~600 lines, and rarely over ~1000. Split larger ones into submodules.
- USD test scenes are `.usda` files on disk with a comment stating their purpose, not Python strings.
- Evidence docs (feasibility records, decision rows) claim only what a check actually tested.
- Docs and decision logs state the current decision and its reasons, not how it was reached. Don't describe earlier drafts, revisions, or options that were never decided on ("revised four times", "three, not four", "no longer", "rather than X" where X was never adopted). Name a rejected alternative only when its reason still guides later work.
- Keep Git commits as small, self-contained, and parseable as possible: one new feature per commit.
