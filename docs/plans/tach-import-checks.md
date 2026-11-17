# Import checks with tach: plan

How the workspace's [import rules](../../packages/README.md#import-rules) come to be checked by [tach](https://github.com/tach-org/tach) and ruff in place of `tests/bpy_free/test_import_tiers.py`, and the refactors that makes for. It changes no behavior and adds no requirement. The rules themselves change in one place: what a package may import of another package becomes that package's public API ([Public APIs](#public-apis)).

## Why tach

`test_import_tiers.py` reads every module's imports with `ast` and checks them against tiers, exports, and dependencies that it and the READMEs each spell out. Tach checks the same rules from one configuration, in Rust, in about half a second over the workspace, and fails with the file, the line, and the rule. Its configuration is the tiers' and exports' one statement, so the READMEs and AGENTS.md describe the rules and link to it instead of restating it.

Tach treats each directory with a `pyproject.toml` as a package. `tach check` checks imports within a package: layers, declared dependencies, and interfaces. `tach check-external` checks imports between packages against each importer's `pyproject.toml`, by distribution only: it can't tell `proscenium_sync.bindings` from `proscenium_sync.runtime`. That split shapes what follows.

## What tach checks

The configuration is a root `tach.toml` and a `tach.domain.toml` beside each package's source (`src/proscenium/`, `packages/proscenium_sync/src/proscenium_sync/`, `packages/proscenium_ui/src/proscenium_ui/`), so a package's units are configured where they live:

- **The root `tach.toml`:** the three source roots, the layers, and:
  - `ignore_type_checking_imports = false`, so type-only imports count, as they do now
  - `root_module = "dependenciesonly"`, so a package's or a grouping package's `__init__.py`, which belongs to no unit, imports only what the root module declares (the extension's `addon`, and `proscenium_sync`'s API modules, [Public APIs](#public-apis)), and a module outside every unit neither imports a unit nor is imported by one
  - `exact = true`, so a declared dependency that nothing uses fails
  - `[external] exclude`, which lists what Blender provides rather than a wheel: `bpy` and Blender's other modules (`mathutils`, `idprop`, `gpu`, `gpu_extras`, `bpy_extras`, `blf`), `pxr`, `numpy`, and `_typeshed`, the type checker's stubs
- **Tiers are layers.** One `layers` list holds every package's tiers, highest first, named for their package (`sync6` to `sync1`, `ui5` to `ui1`, and the extension's two). Tach checks layers only within a package, so the order between packages' layers means nothing. Each unit is a module in its tier's layer. Where a tier holds several units, each declares `depends_on = []`, since tach otherwise lets units of one layer import each other. The lowest tier's units declare it too, so they import only themselves.
- **Exports are interfaces.** Each package unit has an `[[interfaces]]` entry whose `expose` lists its `__init__.py`'s `__all__`. An exported module is exposed as `name(\.[A-Za-z]\w*)?`, since `expose` is a full-match pattern and names may be imported from a public module. A module unit (`results`, `search_box`, ...) has no entry, since it is public itself.
- **A package imports only what its `pyproject.toml` declares:** `tach check-external`.
- **Imports inside functions** count, as tach's `local_imports` rule does by default.

A draft of this configuration passes on the current tree. Each of these was injected into a copy of the tree, and tach failed on it:
- an import of a higher tier, at module level, inside a function, and under `TYPE_CHECKING`
- an import between two units of one tier
- an import by a lowest-tier unit of another of its tier
- an unexported name, an unexported module, and the planner's `_planner`
- the extension's `from .. import addon` in `interface/`
- a grouping package's `__init__.py` importing its unit
- a module outside every unit importing one
- a package importing a workspace package it doesn't declare

## Public APIs

Tach can't check which modules of another package an import reaches, and the rule it would check is the wrong one: `interface/` imports only `bindings/` because `bindings/` is the synchronizer's API. Since the packages split, that is a rule about `proscenium_sync`, not about `interface/`: **each library package names its public API, the units another package may import, and no other package imports anything else of it.** Within a package, the tiers still apply.

- **`proscenium_sync`'s public API is its own names:** what `bindings` exports, and `registration`'s `register` and `unregister`. Callers write `proscenium_sync.BINDINGS`, `proscenium_sync.BindingHandle`, and `proscenium_sync.register()`, and import nothing below the package. The package's `__init__.py` still imports without `bpy`, so importing the planner never loads Blender: it loads the API's modules on first use, through a module `__getattr__` (PEP 562), from one literal map of each exported name to the unit that defines it. `__all__` is the map's keys, and `TYPE_CHECKING` imports of the same names give type checkers and editors their real types. A short `bpy_free` test checks that the map, `__all__`, and the `TYPE_CHECKING` imports name the same names, and `test_no_blender_imports.py` keeps checking that `import proscenium_sync` loads no `bpy`. An error in an API module surfaces on first use rather than at `import proscenium_sync`. Blender imports the extension's `addon.py` at registration, which uses the API at once, so in practice the timing is the same.
- **`proscenium_ui`'s public API** is the widgets: `scene_graph_widget.display` and `property_viewer_widget.display`, imported as modules (`from proscenium_ui.scene_graph_widget import display`). Their names overlap (`create_view`, `set_stage`, `register`, `ViewNotFoundError`), so they can't share one namespace at the package's top.
- **Every other library `__init__.py`,** `proscenium_ui`'s and the grouping packages' (`scene_graph_widget/`, `property_viewer_widget/`), holds only its docstring. That keeps them importable without `bpy` with nothing to check but tach's `root_module` setting and `test_no_blender_imports.py`.
- **The extension's units** may import either package's public API, and `addon.py` and `interface/` keep their tiers: `addon.py` registers the synchronizer and the temporary UI.
- **How it's checked.** A `ruff.toml` in `src/proscenium/`, extending the root configuration, bans (ruff's TID251, `banned-api`) every unit of `proscenium_sync`, with no exceptions, and every unit of `proscenium_ui` but its two `display` packages, each with a message naming the API. A nested `ruff.toml` banning `proscenium_sync.runtime` fails both `from proscenium_sync import runtime` and `from proscenium_sync.runtime import ownership` in `interface/`, and the root configuration's per-file ignores still apply there. `banned-api` lists what's banned, so a unit added to either package gets its entry in the same change as its tach module. Should tach come to apply a package's interfaces to the workspace packages that import it, that replaces the ban list.
- **Tach and the lazy `__init__.py`:** tach counts its `TYPE_CHECKING` imports, so the root module (`<root>`, the packages' `__init__.py` files) declares `depends_on = ["proscenium_sync.bindings", "proscenium_sync.registration"]`, beside the extension's `proscenium.addon`.
- **When Blender's Python reaches 3.15,** PEP 810's `lazy from .bindings import BindingHandle` replaces the map and `__getattr__`. Blender 5.2 bundles 3.13.

Tools and tests aren't in a source root, so neither tach nor this ban checks them: `tools/row_icon_masks.py` reads a column module, and tests reach into any module.

## What else replaces the test

- **The bpy-free tiers** (`planner/`, `source_access/`, `results`, `widget_model/`, `prim_tree/`, `property_list/`). Tach's `cannot_depend_on_external` applies only to a dependency the package declares, and `bpy` is excluded, never declared, so tach skips it (`check_import` in tach's `src/checks/external_dependency.rs` returns before the module's own rules). Each bpy-free unit's directory gets a `ruff.toml`, extending the root configuration, that bans `bpy` and Blender's other modules with TID251. That fails an import at module level, inside a function, and under `TYPE_CHECKING`, and leaves the tiers above alone. `test_no_blender_imports.py` stays: it imports the bpy-free code with Blender blocked, which no static check does, and it covers the package and grouping `__init__.py` files that no unit's `ruff.toml` reaches.
- **Cycles among a unit's modules.** Tach checks cycles only in the configured `depends_on` graph, between modules it is told about, and the layers already rule out cycles between units. A unit's files aren't tach modules. The rule stays, as a short test, `test_unit_module_cycles.py`, that walks `tach map`'s file-to-file dependency map for cycles within each unit, so it reads no imports itself. Its commit first checks that the map counts type-only imports, as the configuration says; if it doesn't, the test keeps its own `ast` reading of each module's imports.
- **The guard tests** (`test_an_import_out_of_form_is_found` and the like) go with the checks they guard: tach's and ruff's own suites test the checkers, and each check here was shown to fail on its violation above.

`test_application_imports.py` (APP-08) stays as it is. It skips type-only imports, which the tiers count, and tach sets that once for every module.

## Refactors

- **`results.py` becomes `results/`,** a package unit whose `__init__.py` exports what the module defines, so it can hold its bpy-free `ruff.toml`. Imports of it are unchanged: `from proscenium_sync.results import Diagnostic, Result` and `from proscenium_sync import results`. Its tach entry becomes a package unit's, with an interface.
- **The tier tables move into the configuration.** Each package README's [Import rules](../../packages/proscenium_sync/src/proscenium_sync/README.md#import-rules) section keeps what its tiers mean (which are bpy-free, what its public API is) and links to its `tach.domain.toml` for the tiers themselves, which `tach show` draws.
- **`__all__` and the interfaces** both name a unit's exports. `__all__` stays: it is what ruff and ty read as re-exports. A change to one changes the other in the same change. A name missing from an interface fails its first import, and a name an interface has but `__all__` lacks is allowed through. No check compares them.

## CI and tooling

- tach goes in the `lint` group, pinned through `uv.lock`, like ruff.
- Two pre-commit hooks, `uv run --frozen tach check` and `uv run --frozen tach check-external`, with `pass_filenames: false`, run on Python files, `tach.toml`, `tach.domain.toml`, and `pyproject.toml` files. CI runs them through `pre-commit run --all-files`, as it does every lint check. `check-external` reads installed distributions' metadata, which `uv sync` provides.
- Ruff's nested `ruff.toml` files run through the existing ruff hook, which finds each file's closest configuration.

## Docs

- **AGENTS.md:** the Layout section's import-rule bullets say what the rules are and that tach and ruff check them, linking to `packages/README.md#import-rules`, and drop the restated tiers. `proscenium/interface/`'s bullet says it imports the packages' public APIs, and the `proscenium_sync/` bullet says its `__init__.py` exports the API, loaded on first use, and still imports without `bpy`.
- **`packages/README.md#import-rules`:** the rules, with the public-API rule in place of what `interface/` may import, and the paragraph on checks naming tach's configuration, the nested `ruff.toml` files, and `test_no_blender_imports.py`.
- **The package and directory READMEs:** each directory's README names its new `tach.domain.toml` or `ruff.toml` (`test_source_readmes.py` requires it). `src/proscenium/interface/README.md` names the public APIs. The two `display/` READMEs' cycle sentence names `test_unit_module_cycles.py`.
- **`tests/README.md`:** `test_import_tiers.py`'s entry becomes `test_unit_module_cycles.py`'s, and the lazy API's test gets one.
- **References to `test_import_tiers.py`:** `process_bindings.py`'s docstring, [node-tree.md](../phase3/node-tree.md) (a new package gets its `tach.domain.toml`), and [scene-graph-ui.md](../phase3/scene-graph-ui.md).
- **Unchanged:** no matrix row or invariant names these checks. `docs/archive/` and the earlier plans keep what they were written with.

## Commits

Each commit is one change, passes `pre-commit` and the test suite on its own, and updates the docs, READMEs, and tests that name what it changes. Files move with `git mv` before their content changes.

1. This plan.
2. **`results.py` becomes `results/`.**
3. **tach checks the tiers, exports, and package dependencies:** the lint group, `tach.toml` and the three `tach.domain.toml` files, the two hooks, and the tier tables' move. `test_import_tiers.py` loses the tests tach replaces and their guards. AGENTS.md and the READMEs follow.
4. **The bpy-free tiers by ruff:** each bpy-free unit's `ruff.toml`. `test_import_tiers.py` loses its Blender-import test.
5. **`proscenium_sync`'s API at its top:** the lazy `__init__.py`, its `bpy_free` test, `<root>`'s tach dependencies, and the extension's imports of `bindings` and `registration` becoming `proscenium_sync`'s names. The other library `__init__.py` files already hold only their docstrings.
6. **The packages' public APIs:** the rule in `packages/README.md` and the package READMEs, and `src/proscenium/ruff.toml`'s ban list. `test_import_tiers.py` loses its `interface/` test.
7. **Cycles among a unit's modules:** `test_unit_module_cycles.py` over `tach map`, and `test_import_tiers.py` goes.
8. **The proposal to tach upstream,** in [tach-org/tach](https://github.com/tach-org/tach)'s issues, posted once the user has reviewed its text. It asks for two changes, each with the case here and the code it concerns:
   - a module's `cannot_depend_on_external` applies to a dependency in `[external] exclude` too, so a module can be kept from a module the environment provides rather than a declared dependency (`check_import` in `src/checks/external_dependency.rs` returns for an excluded dependency before the module's own rules). With it, tach checks the bpy-free tiers, and their `ruff.toml` files retire.
   - a package's interfaces apply to imports from the other packages of a workspace, which tach now checks only by distribution (`InternalDependencyExtractor` in `src/processors/dependency.rs` keeps only imports within the importer's package). With it, tach checks the public APIs, and `src/proscenium/ruff.toml`'s ban list retires.

   The first is small enough to offer as a pull request with the issue. Retiring the `ruff.toml` files waits for a tach release that has the change.

## Decision log

- **Adopt tach (with the user, 2026-11-17).** Tach checks the tiers, exports, and package dependencies, from configuration beside each package. Ruff checks the bpy-free tiers. What tach can't check stays a test only where nothing else checks it.
- **What a package may import of another is that package's public API (with the user, 2026-11-17).** The rule that `interface/` imports only `bindings/` predates the packages. Since they split, the boundary is the package's, and it holds for every importer: `proscenium_sync`'s public API is `bindings`' exports and `registration`'s two functions, and `proscenium_ui`'s is its widgets.
- **`proscenium_sync` exports its API from its top, loaded by a module `__getattr__` (with the user, 2026-11-17).** The package's `__init__.py` stays importable without `bpy`, which the planner's tests and SNAP-08's oracle need, while its `__all__` is the API. `importlib.util.LazyLoader` defers a module's execution, not a name's, so getting an exported name from a lazy module runs it at once. PEP 810's `lazy from` needs Python 3.15, and the third-party `lazy_loader` would be one more bundled wheel for the same `__getattr__`.
- **The ban list checks the public APIs, and the cycle rule stays, over `tach map` (with the user, 2026-11-17).** What tach can't check yet goes upstream as a proposal, the plan's last step, and the ban list and the bpy-free `ruff.toml` files retire when tach checks the same.
