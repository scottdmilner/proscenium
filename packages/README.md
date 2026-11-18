# `packages`

The workspace's library packages: each a uv workspace member with its own `pyproject.toml`, built as a wheel that the extension's zip bundles. Blender installs them as top-level packages in its shared site-packages, so code in them imports absolutely. The extension itself is `src/proscenium/`, the root `pyproject.toml`'s project ([plan](../docs/plans/workspace-packages.md)).

A package boundary goes only where the interface between two sides stands on its own, a USD stage or the extension's public API, so nothing on either side is kept in step with the other by hand. Each package's name starts with `proscenium_`, and is a top-level name of its own, never part of a shared namespace: Blender removes a wheel by deleting its top-level directories.

| Path | Holds |
|---|---|
| `proscenium_sync/` | The synchronizer: the bindings, their synchronization and interaction, the API, and the planner, in a wheel for each platform ([its README](proscenium_sync/README.md)). |
| `proscenium_ui/` | The widgets the extension uses to build the UI: the scene graph and the property viewer ([its README](proscenium_ui/README.md)). |

## Import rules

These rules hold in the extension and in each package, with each one's own tiers: [the extension's](../src/proscenium/README.md#import-rules), [`proscenium_sync`'s](proscenium_sync/src/proscenium_sync/README.md#import-rules), and [`proscenium_ui`'s](proscenium_ui/src/proscenium_ui/README.md#import-rules).

A package imports only the packages its `pyproject.toml` depends on, and absolutely: `from proscenium_sync import bindings`. Within a package, a relative import reaches only a sibling or a descendant (`from . import list_steps`, `from .columned_list import column_layout`), and every other import is absolute (`from proscenium_sync.persistence import manifests`), as ruff's TID252 enforces everywhere but the extension, which Blender installs as `bl_ext.<repository>.proscenium`, so it imports its own parents relatively.

The code is in units, each a package or a single module, in tiers. A unit imports only from itself and from units in lower tiers, and the lowest tier's units import only themselves. A tier that never imports `bpy` imports no Blender module, even through another module ([tiers](../docs/plans/source-tiers-and-names.md#tiers)).

A package reaches another only through its public API, the units another package may import ([plan](../docs/plans/import-linter-checks.md#public-apis)): `proscenium_sync`'s `bindings` and `registration`, and `proscenium_ui`'s two widgets' `display` and `widget_updates`. Within a package, the tiers apply.

Units reach each other through public modules and exported names. A package unit's `__init__.py` exports its public modules and names, its own or its modules', and nothing else; a module unit is public itself. Code in another unit imports a public module from its package and names each use through it: `from proscenium_sync.persistence import manifests`, then `manifests.Manifest`, and `from proscenium_sync import results`, then `results.Result`. Where a module's qualified uses would nest, as in `results.Result(results.Diagnostic(results.DiagnosticCode.X, ...))`, it imports the names from the public module instead: `from proscenium_sync.results import Diagnostic, DiagnosticCode, Result`. A package that exports names is used the same way: imported from its parent, each use named through it (`from proscenium_sync import synchronization`, then `synchronization.synchronize`), or its names imported from it. Nothing imports a name a package doesn't export, or anything from a module its package doesn't export. A unit's own modules import each other directly, and tests reach into any module.

Module names are unique across `src/proscenium/` and the packages here, and name what the module holds, so a use names its unit and doesn't repeat itself: `binding_records.BindingConfig`, `binding_settings.PayloadPolicy`.

import-linter checks these rules, as `lint-imports` pre-commit hooks, one for each file of contracts (`[tool.importlinter]`). Each library package's `pyproject.toml` holds its own: its units in tiers, which of its units are reached only through their `__init__.py` (those that export names rather than all their modules), its bpy-free code's imports, and the rule that a unit's modules import each other without cycles. The root [`pyproject.toml`](../pyproject.toml) holds the extension's, and those between packages: the public APIs and the package dependencies. Every import counts, at module level, in functions, and under `TYPE_CHECKING`. ty rejects an import of a name a package doesn't export. `tests/bpy_free/test_no_blender_imports.py` checks that the bpy-free code imports in a fresh interpreter with Blender's modules blocked.
