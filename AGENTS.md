# Agent Instructions

## Before any work

Read [docs/PROJECT.md](docs/PROJECT.md) and [docs/spec/invariants.md](docs/spec/invariants.md) first. For milestone work, also read:

- the milestone's file in [docs/milestones/](docs/milestones/);
- its plan in [docs/plans/](docs/plans/), if one exists;
- [docs/DECISIONS.md](docs/DECISIONS.md).

Don't read `docs/archive/` unless the user asks for it. It holds superseded documents, which would mislead current work.

## Repository map

Each directory's README says what it holds.

- [`src/proscenium/`](src/proscenium/README.md): the extension: its manifest, its registration, and the temporary UI.
- [`packages/`](packages/README.md): the workspace's library packages, which the extension's zip bundles as wheels.
  - [`proscenium_sync`](packages/proscenium_sync/src/proscenium_sync/README.md): the synchronizer, with its API and the planner (C++).
  - [`proscenium_ui`](packages/proscenium_ui/src/proscenium_ui/README.md): the widgets.
  - [`proscenium_cook`](packages/proscenium_cook/src/proscenium_cook/README.md): the cook, which evaluates a node tree into stages (C++).
- [`tests/`](tests/README.md): the `bpy_free/`, `blender/`, and `isolated/` test layers, their helpers, and the fixtures.
- [`tools/`](tools/README.md): the build, the checks that pre-commit runs, and the feasibility evidence.
- [`docs/`](docs/PROJECT.md#documentation-map): the spec, milestones, decisions, plans, and testing docs.

## Before you change…

Some directories have an `AGENTS.md` with rules for working there. Read it before changing anything in that directory, even if the change starts elsewhere.

| Working on | Read first |
|---|---|
| A requirement, the spec, the matrix, a milestone's start, or any doc | [docs/AGENTS.md](docs/AGENTS.md) |
| Imports, or adding, moving, or renaming a module or unit | [packages/README.md#import-rules](packages/README.md#import-rules), via [packages/AGENTS.md](packages/AGENTS.md) and [src/proscenium/AGENTS.md](src/proscenium/AGENTS.md) |
| A dependency | [packages/AGENTS.md#dependencies](packages/AGENTS.md#dependencies) |
| C++, the planner, its build, or the Hydra bridge | [the planner's AGENTS.md](packages/proscenium_sync/src/proscenium_sync/planner/AGENTS.md) |
| The cook's C++ or its build | [the cook's AGENTS.md](packages/proscenium_cook/src/proscenium_cook/tree_cook/AGENTS.md), then the planner's |
| Tests or fixtures | [tests/AGENTS.md](tests/AGENTS.md) |
| Feasibility probes | [tools/feasibility/AGENTS.md](tools/feasibility/AGENTS.md) |
| The name of anything | [docs/conventions.md](docs/conventions.md) |

## Commands

All commands run through uv. The dev group includes the `bpy` wheel, so `bpy` and `pxr` import in the uv environment without a Blender install.

```sh
uv sync                                   # install the dev environment
uv run pre-commit run --all-files         # all lint checks (ruff, ty, import-linter, clang-format, clang-tidy, lock, matrix); same as CI
uv run pytest -n auto                     # all tests, in parallel; select layers with -m (e.g. -m bpy_free)
uv run proscenium-build                   # dist/proscenium-<version>.zip for this platform (--check: read-only)
uv run proscenium-blender                 # build, then run Blender with Proscenium enabled, apart from the user's Blender setup
uv run proscenium-matrix check            # requirement matrix (render: regenerate requirements-matrix.md)
uv run python tools/feasibility/run_all.py  # feasibility probes (wheel, pytest, binary)
uv run pre-commit install                 # once per clone
```

Tests that need the Blender binary find it as [tests/README.md](tests/README.md#running) says. Without a binary they are skipped.

## Rules for every change

- Every directory in `src/proscenium/` and `packages/` has a `README.md` naming each of its files and subdirectories and what each holds. Update it with any file you add, remove, or rename there.
- Rename tracked files with `git mv`, and update every reference to them in the same change ([conventions](docs/conventions.md)).
- Follow PEP 8 and annotate every function signature (ruff and ty check the rest of the style rules).
- Classes declare their typed attributes in the class body, above `__init__`.
- Prefer short docstrings plus inline comments over long docstrings. Public objects in `src/`, `packages/`, and `tools/` have one.
- Comments and docstrings describe the code as it is, in the present tense: what it does and why. They don't recount earlier runs or revisions of the code.
- Keep files under ~600 lines, and rarely over ~1000. Split larger ones into submodules.
- Keep Git commits small, self-contained, and parseable: one new feature per commit.
- Make any change that takes more than two commits in a Git worktree of its own, not in the main checkout.
- `tools/build_extension.py` is the only distribution build. Never publish or distribute the zip or any wheel ([tools/README.md](tools/README.md)).
- Never bundle another OpenUSD build. The extension uses the `pxr` bundled with Blender.
