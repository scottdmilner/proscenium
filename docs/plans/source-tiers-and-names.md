# Source tiers and names: plan

How `src/proscenium/` is arranged so its structure shows in the tree, and how its classes and functions are named. It changes no behavior apart from what the [Semantics](#semantics) section names, and adds no requirement. Where it and a spec file disagree, the spec file wins, apart from the API names this plan changes in the spec itself ([Spec changes](#spec-changes)).

## Tiers

`src/proscenium/` holds three packages: `api/`, what callers use; `binding/`, the bindings' code; and `core/`, the compiled core. The bindings' code and the core are separate packages, so the Blender-facing code and the core and its Hydra code change independently.

The code is in units, each a package or a single module, in tiers. A unit imports only from itself and from units in lower tiers, and the lowest tier's units import only themselves:

| Tier | Unit | Holds |
|---|---|---|
| 6 | `addon.py` | The extension's registration and its handlers, which drive `binding.runtime` and `api` |
| 5 | `api/` | What callers use: the binding handle and the process's bindings ([Synchronization API](../spec/source-access.md#synchronization-api)) |
| 4 | `synchronization/` | The synchronization transaction and the application layer it applies plans with ([Synchronization Transaction](../spec/pipeline.md#synchronization-transaction)) |
| 3 | `binding/runtime/` | Disposable in-memory state built from the records ([Undo and Runtime State](../spec/lifecycle.md#undo-and-runtime-state)) |
| 2 | `binding/persistence/` | Versioned records in ID properties ([Persistence](../spec/lifecycle.md#persistence)) |
| 1 | `core/` | The compiled core: its C++ source and built module |
| 1 | `binding/source_access/` | The stages a binding reads its source from ([Source Access](../spec/source-access.md)), binding identifiers, the canonical-candidate rule, requested settings, and source-entity identifiers |
| 1 | `binding/results.py` | Results and diagnostics ([Diagnostics](../spec/pipeline.md#diagnostics)) |

Units reach each other through public modules. A package unit's `__init__.py` exports its public modules, and nothing else, so a module it doesn't export is the unit's own; a module unit is public itself. Code in another unit imports a public module from its package and names each use through it, so calls read as `state.start_tracking()` and `configs.read_configs()`. Where those uses would nest, as results' do in building a result from a diagnostic and its code, it imports the names from the module instead (`from ..binding.results import Diagnostic, DiagnosticCode, Result`), which reaches no further into the unit. Module names are unique across `src/proscenium/` and name what the module holds, so a use names its unit without repeating itself. `binding/__init__.py` imports none of its units, so importing a lowest-tier unit never imports `bpy`. The lowest tier holds what the `bpy_free` tests import, so runtime state that needs no `bpy`, such as the stage registry, stays in `binding/source_access/`. Each Python module is in the package whose code it uses: `core/` holds only the compiled core, its type stubs, and the import that loads what it links. The tiers are called tiers, and the packages packages, never layers, since the spec's layers are snapshot, plan, and application ([Synchronization Layer Boundaries](../spec/pipeline.md#synchronization-layer-boundaries)), and USD has layers of its own.

A `bpy_free` test reads every module's imports with `ast`, without importing it, and fails on an import against this table.

### Layout

```
src/proscenium/
  __init__.py
  addon.py
  api/
    __init__.py
    bindings.py                  Bindings, BINDINGS, BindingHandle, RequestedSettings
  binding/
    __init__.py
    runtime/
      __init__.py                what api and addon call, and the errors that reach their callers
      state.py                   the state, tracking, rebuilding, and the checks of held references
      binding_configs.py         lookups by binding identity, creation, configuration writes, index-entry restoration
      ownership_index.py         Claim, each destination's claims, manifest lookups and writes
      copy_detection.py          copied-binding detection from the records
    persistence/
      __init__.py                the records, and the reads and writes runtime, api, and addon use
      records.py                 the versioned-record framework
      configs.py         BindingConfig, DestinationTag, BindingIndex
      manifests.py               ManifestEntry, Manifest, and their records
      binding_state.py           GenerationMetadata, LastSynchronizationAttempt
      selection.py               PersistentSelection
    results.py                   Result, ResultState, Diagnostic, DiagnosticCategory, Severity
    source_access/
      __init__.py                the stages, BindingId, RequestedSettings
      stages.py          BindingStages, PayloadPolicy, SourceUnavailableError
      registry.py          StageRegistry
      identifiers.py             BindingId
      canonical_candidate.py     the canonical-candidate rule
      binding_settings.py      RequestedSettings
      source_entities.py
  core/                          the compiled core: _core and its C++ source
```

Module names are unique across the tiers, and named for the spec section they implement where there is one, as `canonical_candidate.py` is for [Canonical Candidate](../spec/source-access.md#canonical-candidate). The modules of `binding/runtime/` share helpers without a leading underscore, and call each other's through the module (`state.current_state()`), so a test can patch one in one place; its `__init__` is its public surface, exporting only what `api/` and `addon.py` call and the errors that reach their callers. No module of `binding/runtime/` is named for a function its `__init__` exports, which would replace the module on the package: `binding_configs.py`, beside `configs()`, and `copy_detection.py`, beside `copied_bindings()`.

## Conventions

These go in AGENTS.md's Style section:

- **One concept per word, the Glossary's where it has one.** A bare `index`, `source`, or `binding` is never used where it could mean more than one thing: `binding_index` and `ownership_index`, `candidate` for one record or copy of a binding identity.
- **Spec terms keep their meaning.** *Generation* is a published generation, *layer* a USD layer or a pipeline layer, *synchronization* one attempt, and *claim* and *candidate* what the spec defines. None names anything else.
- **Exceptions end in `Error`**, so they aren't mistaken for values (ruff's N818, without `noqa`).
- **A type names its domain:** `DiagnosticCategory`, `CanonicalCandidateReason`, not `Category` or `Reason`.
- **A function is named for its effect.** One that decodes or encodes a stored record is `read_*` or `write_*`; one that changes held state and writes it through to the record is `set_*`; any other is named for what it returns (`config(binding_id)`, `index_texts()`); and an operation the spec defines takes the spec's verb (`synchronize`, `reload`).

## Renames

| Now | After | Why |
|---|---|---|
| `Synchronization`, `SYNCHRONIZATION`, `proscenium.synchronization` | `Bindings`, `BINDINGS`, `proscenium.api.bindings` | It is the file's bindings and their runtime stages; a synchronization is one attempt |
| `Synchronization.bindings(scene)`, `.copied_bindings()` | `Bindings.in_scene(scene)`, `.copied()` | |
| `Synchronization.file_loaded()`, `.prune()` | `.drop_all_stages()`, `.prune_stages()` | |
| `BindingSource` | `BindingStages` | It holds a binding's source stage and evaluation stage; its `source` is the source |
| `SourceRegistry`, `Synchronization.sources` | `StageRegistry`, `Bindings.stages` | |
| `SourceRegistry.prune(existing, unreadable)` | `StageRegistry.prune(existing)` | The set of existing binding identities, including unreadable and disabled bindings |
| `indexes._Binding` | `state.Binding`, then `Candidate` | It is one candidate of a binding identity |
| `core.copies.Candidate` | `CandidateEvidence` | What the rule reads about a candidate |
| `Decision`, `Reason`, `UNREADABLE` | `CanonicalDecision`, `CanonicalCandidateReason`, `UNREADABLE_INDEX_ENTRY` | |
| `candidates`, `candidates.Identity`, `Found`, `find()` | `copy_detection`, `IdentityCandidates`, `CopyDetection`, `detect()` | |
| `Identity.copies` | `IdentityCandidates.tagged_copies` | |
| `_Share`, `_Ownership`, `_State`, `_Stale` | `DestinationClaims`, `OwnershipIndex`, `State`, `StaleError` | |
| `indexes.find_copies()` | `refresh_if_tags_changed()` | It drops the state when tags changed, and returns nothing |
| `indexes.rebuilds()` | `rebuild_count()` | |
| `indexes.update_manifest()` | `set_manifest_entries()` | A write-through, like `set_manifest` |
| `_ask`, `_current`, `_alive`, `_valid`, `_canonical`, `_existing`, `_restore_entry` | `query`, `current_state`, `alive`, `valid`, `canonical`, `existing`, `restore_missing_binding_index_entry` | Shared by the modules of `runtime/` |
| `_give_manifest`, `_named` | `_cache_manifest`, `_datablock_of` | |
| `Category` | `DiagnosticCategory` | |
| `Refusal`, `Refused`, `RecordRefused` | `RefusalReason`, `RefusedRecord`, `RefusedRecordError` | A reason, a value, and an exception |
| `Schema.kind`, `Schema.record` | `Schema.name`, `Schema.record_type` | `record` is a type |
| `bindings.update()`, `all_bindings()`, `tagged_collections()` | `configs.write_config()`, `read_configs()`, `read_tags()` | They write and read records |
| `BindingNotFound`, `Disabled`, `NotTracking`, `SourceUnavailable`, `_Stale` | `BindingNotFoundError`, `BindingDisabledError`, `NotRegisteredError`, `SourceUnavailableError`, `StaleError` | |

### Stored field names

A record's field names are its stored keys. Binding configuration version 1 stores `root_layer_identifier`, `destination`, and `settings`.

## Semantics

- **A disabled binding is reported one way.** Runtime lookups return a binding with copies and no canonical candidate in band, as `configs()` already does, and only the writers (`set_config`, `set_manifest`, `set_manifest_entries`) raise `BindingDisabledError`. The API turns the in-band value into its result, as it does for an unreadable configuration.
- **The API's rule for refusals is stated once,** in its module docstring: an operation returns a result with the refusal, and a query (`requested_settings`) raises.

## Spec changes

The Synchronization API's design note in [source-access.md](../spec/source-access.md#synchronization-api) names the API's module, class, and instance, and its sentence "operations that span bindings belong to the process's synchronization" names the concept. Both change with the rename, with the matrix row that quotes the note (`tools/matrix.py render` after) and the DECISIONS.md row "Synchronization API". The DECISIONS.md rows that name `proscenium/indexes.py` and `indexes.set_manifest`, M5's milestone file, and `tests/README.md` follow the modules they name. The closed M3 plan keeps the names it was written with; the [Renames](#renames) table maps them.

## Commits

Each commit is one change, passes `pre-commit` and the test suite on its own, and updates the docstrings, docs, and tests that name what it moves or renames. Files move with `git mv`, before their content changes.

1. This plan.
2. **Moves into the tiers**, keeping each module's name: `results.py` to `core/`; `records.py`, `bindings.py`, `ownership.py`, `binding_state.py`, and `selection.py` to `persistence/`; `indexes.py` and `candidates.py` to `runtime/`; `synchronization.py` to `api/`. AGENTS.md's Layout section describes the tiers.
3. **The import-direction test.**
4. **`runtime/indexes.py` split** into `state.py`, `binding_configs.py`, and `ownership_index.py`, with `Claim` moving from `persistence/ownership.py` to `ownership_index.py`, and `persistence/ownership.py` renamed `manifests.py`. The names the modules now share, and the types that move, take their names from the [Renames](#renames) table here; `_Binding` becomes `Binding` until commit 7 frees `Candidate`.
5. **Exceptions end in `Error`.**
6. **Binding stages:** `binding_source.py` and `registry.py` renamed, and their classes, attributes, and `prune`'s parameter.
7. **Copied bindings:** `runtime/candidates.py` renamed `copy_detection.py` and `core/copies.py` `canonical_candidate.py`, with their types and functions, and `state.Binding` renamed `Candidate`.
8. **Records:** the refusal names, `Schema`'s fields, and the binding records' module and functions.
9. **Runtime names:** the state's public functions (`find_copies`, `rebuilds`, `update_manifest`).
10. **`DiagnosticCategory`.**
11. **A disabled binding reported in band** by runtime lookups.
12. **The API:** `api/synchronization.py` to `api/bindings.py`, its class, instance, and methods, with the spec, matrix, and DECISIONS.md changes above.
13. **The binding record**, at version 1, with its last attached root-layer identifier, destination, and requested settings.
14. **AGENTS.md's Style section** gains the conventions.

## Decision log

- **Plan (with the user, 2026-10-21).** The tiers, conventions, renames, and semantics above, with the spec changes they need.
- **The runtime split (commit 4).** `binding_configs.py`, not `configs.py`: the package exports `configs()`, which would replace a submodule of that name. The modules call each other's helpers through the module, so the tests that patch `current_state` and `_add_share` patch them in one place.
- **Copied bindings (commit 7).** `copy_detection.py`, not `copied_bindings.py`, for the reason `binding_configs.py` is: the package exports `copied_bindings()`. It is named for the `CopyDetection` it returns.
- **The API (commit 12).** The blender tests' `sync` fixture is `bindings`, for the `Bindings` it gives, so *synchronization* names only an attempt in the tests too. The spec section keeps its name, Synchronization API.
- **Units in tiers, reached through public modules (M5, with the user, after M5's D4).** Two export styles, names from most packages and modules from persistence, made the rules a list of per-package cases, and exporting names made each package's `__init__.py` restate its modules' APIs. So every unit is in one tier table, from `addon.py` down, and every package unit exports its modules, each use named through one, or, where those uses would nest, imported by name from the module. Modules were renamed so a use doesn't repeat its module: `binding_records.py` is `configs.py`, `ledger.py` `ledgers.py` (also since runtime's `ledger()` would shadow it), `binding_ids.py` `identifiers.py`, `binding_stages.py` `stages.py`, `stage_registry.py` `registry.py`, `requested_settings.py` `binding_settings.py` (`settings` would be shadowed by `BindingConfig.settings`, a stored field), and runtime's `current_stages.py` `stage_tracking.py`. `api/bindings.py` keeps its name, which the spec states, and re-exports `RequestedSettings` and `Result`, the types its callers pass and receive, so callers outside `proscenium` import only it. `SceneRecords.records()` is `records_found()`, since it would shadow `records` in its class.
- **Reads in persistence (after commit 14).** The binding records' functions that decode records are `read_configs()` and `read_tags()`. `scene_bindings()`, `index_texts()`, and `tagged_uids()` find where records are without decoding them, so they keep names for what they return.
