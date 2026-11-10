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
  - `proscenium/api/`, `proscenium/binding/`, and `proscenium/core/`: what callers use, the bindings' code, and the compiled core. The bindings' code is kept apart from the core, so the Blender-facing code and the core and its Hydra code change independently.
  - The code is in units, each a package or a single module, in tiers; a unit imports only from itself and from units in lower tiers. [`src/proscenium/README.md`](src/proscenium/README.md#import-rules) has the table and the rules, which `tests/bpy_free/test_import_tiers.py` enforces. From the top:
    - `proscenium/addon.py`: registers the extension and its handlers.
    - `proscenium/api/`: what callers use, the binding handle and the process's bindings.
    - `proscenium/synchronization/`: the synchronization transaction and the application layer it applies display plans with (M5's a stub, which M7 replaces).
    - `proscenium/binding/runtime/`: disposable in-memory state built from the records.
    - `proscenium/binding/persistence/`: versioned records in ID properties.
    - The lowest tier, which must import without `bpy`, as must `proscenium/__init__.py` and `proscenium/binding/__init__.py`: `proscenium/core/`, the compiled core, its C++ source and built module (see [Compiled core](#compiled-core)); `proscenium/binding/source_access/`, the stages a binding reads its source from, binding identifiers, the canonical-candidate rule, requested settings, and source-entity identifiers; and `proscenium/binding/results.py`, results and diagnostics.
  - Units reach each other through public modules and exported names: a package unit's `__init__.py` exports its public modules and names, its own or its modules', and nothing else, and a module unit is public itself. Code in another unit imports a public module from its package and names each use through it (`from ..binding.persistence import manifests`, then `manifests.Manifest`), or, where those uses would nest, imports the names from the module (`from ..binding.results import Diagnostic, DiagnosticCode, Result`). A package that exports names is used the same way: imported from its parent, each use named through it (`from .. import synchronization`, then `synchronization.synchronize`), or its names imported from it. Never import a name a package doesn't export, or anything from a module its package doesn't export. Module names are unique across `src/proscenium/` and name what they hold, so a use doesn't repeat itself (`binding_records.BindingConfig`, `binding_settings.PayloadPolicy`).
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
- `docs/`: the spec, milestones, decisions, and testing docs. `docs/plans/` holds each milestone's decision log; `docs/phase3/` holds design notes for Phase 3, which are not requirements; `docs/archive/` holds superseded documents (see [Before any work](#before-any-work)).

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

M1b adopted a C++ core that reads Hydra scene indices ([DECISIONS.md](docs/DECISIONS.md) "Evaluation front end and core language"). It holds evaluation, the snapshot, planning, source-side diagnostics, and comparing plans for incremental refresh. Everything that touches Blender stays in Python. The display plan is the one boundary: an immutable object whose large arrays Python reads without copying.

- **Source:** C++ in `src/proscenium/core/`, which holds only the compiled core: its C++, its type stubs, and the `__init__.py` that loads what it links. The manifest's `[build]` patterns keep C++ sources and CMake files out of the zip; only the built module ships, in the same package.
- **Build:** through `tools/build_extension.py`, from `src/proscenium/core/` only: one zip per platform, built on that platform, against the dependency headers of the Blender release `uv.lock` pins, and linked only to Blender's bundled `usd_ms`. The module (`proscenium.core._core`, ignored by `core/.gitignore`) is built into that package. Only the zip's copy of the manifest names the platform and sets `blender_version_max`, so each zip supports one Blender minor version (5.2.x). CI builds Linux's on Blender's glibc floor (manylinux_2_28). The Hydra bridge in `tools/feasibility/` is test code and never goes through it. Both build through `tools/native_build.py` (toolsets and the linkage audit) and `tools/blender_deps.py` (the pinned headers); the core's and the bridge's CMakeLists.txt set the same flags.
- **Boundary rules** (M1b findings):
  - Every entry point turns Tf errors and C++ exceptions into Python exceptions.
  - Arrays for Blender cross as 1-D read-only buffers whose element types match Blender's exactly (`'f'`, `'i'`, `'?'`). Any other type would silently take Blender's slow path.
  - Values the core gives Hydra are Vt's own types; a type made in the core's module isn't recognized by USD's code.
  - The core never keeps a released stage alive.
  - Each workaround for an OpenUSD bug is labeled `WORKAROUND for OpenUSD #<issue>` at every site, and a known-gap check fails when the bug stops reproducing.
  - Code that reads Hydra from worker threads never overlaps `SetTime`, `ApplyPendingUpdates`, or stage edits, collects Tf errors per thread, and releases the GIL while waiting on its workers; holding it deadlocks.
  - A Tf-factory type, such as a scene-index plugin or an adapter, registers through an exported USD helper, as Hf's plugin registry does, never by deriving from a header-only factory base. A type registered that way can't be manufactured on macOS.
- **Style:** C++17, warnings as the core's CMakeLists.txt sets them, and no warnings in any platform's build. clang-format and clang-tidy run as pre-commit hooks on the core and on the Hydra bridge in `tools/feasibility/`. Each has its own `.clang-format`; clang-tidy's checks are in the root `.clang-tidy`, which covers both and includes the C++ Core Guidelines checks, and every clang-tidy warning fails.
  - **Pointers:** no owning raw pointers; `TfCreateRefPtr(new ...)`, as Tf's ref-counted types require, is the exception. A raw `T*` is non-owning and means something when null (a lookup that found nothing, an absent optional argument), and its declaration says what null means. Anything never null is a reference, or `std::reference_wrapper` in a container.
  - **Exceptions to a check:** a `NOLINT` names its check and says why the code needs it.
- **Inspection layer:** a C++ library that maps picked prims to selection targets by kind on the live stage ([interaction contract](docs/spec/interaction-contract.md#two-layers-and-the-live-stage)). The core calls it and exposes it through the core's own bindings; it has no Python bindings, and never includes or calls the core. The build and style rules above apply to it too. M7 builds it.
- **Tests:** through the core's Python module, in the test layers below. Expected values come from the spec, from USD's own APIs (`UsdGeom`, `UsdShade`), or from how the fixture is built, never from Hydra's output. A test whose input could crash native code runs in `isolated/`, since a crash ends the process.

## Tests

[tests/README.md](tests/README.md) documents the test tree: which layer to use, the helpers, the fixture framework, and the rules. Read it before writing tests. In summary:

- Layers are directories named for what a test runs in, not how much it covers. Each test gets its directory's marker:
  - `bpy_free/`: plain Python that reads and writes no Blender data, so it needs no reset. Prefer it.
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
  - These rules cover types, functions, methods, parameters, dataclass fields, other attributes, and file and module names in product code, tests, fixtures, tools, and prototypes, including C++ equivalents. Review names at their call sites and field accesses: their meaning should be clear without reading the implementation or finding a comment elsewhere.
  - One concept per word, the [Glossary](docs/PROJECT.md#glossary)'s where it has one. A bare generic such as `index`, `source`, or `binding` is never used where it could mean more than one thing: `binding_index` and `ownership_index`, `candidate` for one record or copy of a binding identity.
  - Spec terms keep their meaning. A *generation* is a published generation, a *layer* a USD layer or a pipeline layer, a *synchronization* one attempt, and a *claim* and a *candidate* what the spec defines. None names anything else, and the source's tiers are tiers, never layers.
  - Do not call primvar value types, Blender attribute types, or interpolation modes "kinds"; name their actual role so they cannot be confused with USD model kinds.
  - Prefer familiar, precise words, such as `index` for a position. Spell out domain distinctions that affect how a value is used; avoid unexplained abbreviations and generic names such as `data`, `kind`, `place`, or `previous` when the reader must reconstruct what they hold. Keep names concise where the enclosing type or module already supplies an unambiguous domain.
  - Exceptions end in `Error`, so they aren't mistaken for values (ruff's N818 enforces it).
  - A type names its domain and responsibility: `DiagnosticCategory`, `DecisionReason`, `PostgresConnectionPool`. Avoid abstract labels such as `Category`, `Reason`, or `DataManager` that require reading their implementation to understand them.
  - A function is named for its effect. One that decodes or encodes a stored record is `read_*` or `write_*`; one that changes held state and writes it through to the record is `set_*`; any other is named for what it returns (`config(binding_id)`, `index_texts()`); and an operation the spec defines takes the spec's verb (`synchronize`, `reload`).
  - Name side effects explicitly: creating a resource, installing a handler, registering a holder, and clearing a cache use those verbs. Use `ensure_*` or `get_or_create_*` only when an existing suitable value is reused. A name must not imply reuse when every call creates a new value.
  - Members distinguish values from their references: `object_resource_index` for a plan index, `manifest_entry_key` for a stored key, `source_path` for a path, `module_path` for a file path, and `candidate_count` for a count. Name the indexed collection when several are in scope. Boolean names read as predicates (`is_canonical`, `visible_in_viewport`); a predicate name must not hold an index or a count.
  - Collection names say what their elements represent: `resource_indices`, `source_entity_paths`, `dependency_entry_keys`. When a mapping's keys or direction need context, name them too (`prim_index_by_path`, `previous_mesh_indices_by_holder`). Do not name a collection of indices as though it contained the objects themselves.
  - Include units, coordinate space, or lifecycle state when they change the interpretation: `stage_durations_seconds`, `world_matrix`, `local_bounds`, `requested_settings`, `applied_settings`, `attempted_settings`. Distinguish observed results from predictions and counts from the collections counted.
  - Corresponding Python and C++ members use the same domain words and meaning, following each language's existing spelling convention (`object_resource_index` / `objectResourceIndex`). Keep declarations, Python bindings, type stubs, and callers aligned. Preserve external API spellings where required by an override or protocol.
  - A persisted field name is part of its storage schema. Schemas that have not shipped may be edited in place without a version bump or migration. Once a schema has shipped, renaming a field includes the schema version and migrations needed to read existing records, with compatibility checks. Review other serialized keys and externally consumed names for compatibility before changing them.
  - Files and modules name their responsibility so imports and editor tabs identify what they contain: `stage_registry.py`, `frame_capture.py`, `loaded_usd_libraries.cpp`. Avoid catch-all names such as `common.py` or `data.py`, and distinguish implementation modules from their probes and benchmarks. Keep conventional entry and configuration filenames (`__init__.py`, `conftest.py`, `CMakeLists.txt`).
  - Rename tracked files with `git mv`. Update imports, package exports, CMake inputs, script paths, README inventories, documentation references, and affected requirement-matrix rows in the same change. Preserve the import tiers and unique module-name rule under `src/proscenium/`.
- Prefer short docstrings plus inline comments over long docstrings. Docstrings follow pep257 (ruff's D rules): a one-line summary ending in a period or question mark, then a blank line before any more. Public objects in `src/` and `tools/` have one; tests and `tools/feasibility/` need one only where it adds something.
- Keep files under ~600 lines, and rarely over ~1000. Split larger ones into submodules.
- USD test scenes are `.usda` files on disk with a comment stating their purpose, not Python strings.
- Evidence docs (feasibility records, decision rows) claim only what a check actually tested.
- Docs and decision logs state the current decision and its reasons, not how it was reached. Don't describe earlier drafts, revisions, or options that were never decided on ("revised four times", "three, not four", "no longer", "rather than X" where X was never adopted). Name a rejected alternative only when its reason still guides later work.
- Keep Git commits as small, self-contained, and parseable as possible: one new feature per commit.
