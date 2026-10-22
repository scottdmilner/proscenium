# Source tiers and names: plan

How `src/proscenium/` is arranged so its structure shows in the tree, and how its classes and functions are named. It changes no behavior apart from what the [Semantics](#semantics) section names, and adds no requirement. Where it and a spec file disagree, the spec file wins, apart from the API names this plan changes in the spec itself ([Spec changes](#spec-changes)).

## Tiers

The Blender-facing code is three tiers. Each imports only the tiers below it, and `core/` is below all three:

| Package | Holds | May import |
|---|---|---|
| `api/` | What callers use: the binding handle and the process's bindings ([Synchronization API](../spec/source-access.md#synchronization-api)) | `runtime`, `persistence`, `core` |
| `runtime/` | Disposable in-memory state built from the records ([Undo and Runtime State](../spec/lifecycle.md#undo-and-runtime-state)) | `persistence`, `core` |
| `persistence/` | Versioned records in ID properties ([Persistence](../spec/lifecycle.md#persistence)) | `core` |
| `core/` | Everything that imports without `bpy`: the compiled core, source access, the canonical-candidate rule, source-entity identifiers, results and diagnostics | `core` |

`addon.py` registers the extension and its handlers, which drive `runtime` and `api`, so it may import any of them. `core/` is a different axis from the three tiers: it holds what the `bpy_free` tests import, so runtime state that needs no `bpy`, such as the stage registry, stays there. The tiers are called packages or tiers, never layers, since the spec's layers are snapshot, plan, and application ([Synchronization Layer Boundaries](../spec/pipeline.md#synchronization-layer-boundaries)), and USD has layers of its own.

A `bpy_free` test reads every module's imports with `ast`, without importing it, and fails on an import against this table.

### Layout

```
src/proscenium/
  __init__.py
  addon.py
  api/
    __init__.py
    bindings.py                Bindings, BINDINGS, BindingHandle, RequestedSettings, AttachResult
  runtime/
    __init__.py                the public lookups and writes
    state.py                   the state, tracking, rebuilding, and the checks of held references
    binding_configs.py         lookups by binding identity, creation, configuration writes, index-entry restoration
    ownership_index.py         Claim, each destination's claims, manifest lookups and writes
    copy_detection.py          copied-binding detection from the records
  persistence/
    __init__.py
    records.py                 the versioned-record framework
    binding_records.py         BindingConfig, DestinationTag, BindingIndex
    manifests.py               ManifestEntry, Manifest, and their records
    binding_state.py           Generation, LastAttempt
    selection.py               PersistentSelection
  core/
    results.py                 Result, ResultState, Diagnostic, DiagnosticCategory, Severity
    canonical_candidate.py     the canonical-candidate rule
    source_entities.py
    source_access/
      sources.py               FileSource, AttachedSource, PayloadPolicy, SourceKind
      binding_stages.py        BindingStages and its two kinds
      stage_registry.py        StageRegistry
```

Module names are unique across the tiers, and named for the spec section they implement where there is one, as `canonical_candidate.py` is for [Canonical Candidate](../spec/source-access.md#canonical-candidate). The modules of `runtime/` share helpers without a leading underscore, and call each other's through the module (`state.current_state()`), so a test can patch one in one place; its `__init__` is its public surface. No module of `runtime/` is named for a function its `__init__` exports, which would replace the module on the package: `binding_configs.py`, beside `configs()`, and `copy_detection.py`, beside `copied_bindings()`.

## Conventions

These go in AGENTS.md's Style section:

- **One concept per word, the Glossary's where it has one.** A bare `index`, `source`, or `binding` is never used where it could mean more than one thing: `binding_index` and `ownership_index`, `source_kind`, `candidate` for one record or copy of a binding identity.
- **Spec terms keep their meaning.** *Generation* is a published generation, *layer* a USD layer or a pipeline layer, *synchronization* one attempt, and *claim* and *candidate* what the spec defines. None names anything else.
- **Exceptions end in `Error`**, so they aren't mistaken for values (ruff's N818, without `noqa`).
- **A type names its domain:** `DiagnosticCategory`, `DecisionReason`, not `Category` or `Reason`.
- **Verbs by tier:** `persistence` reads and writes records (`read_*`, `write_*`); `runtime` names a lookup by what it returns (`config(binding_id)`) and a write-through by `set_*`; `api` uses the spec's verbs.

## Renames

| Now | After | Why |
|---|---|---|
| `Synchronization`, `SYNCHRONIZATION`, `proscenium.synchronization` | `Bindings`, `BINDINGS`, `proscenium.api.bindings` | It is the file's bindings and their runtime stages; a synchronization is one attempt |
| `Synchronization.bindings(scene)`, `.copied_bindings()` | `Bindings.in_scene(scene)`, `.copied()` | |
| `Synchronization.file_loaded()`, `.prune()` | `.on_file_loaded()`, `.prune_stages()` | |
| `BindingSource`, `FileBindingSource`, `AttachedBindingSource` | `BindingStages`, `FileBindingStages`, `AttachedBindingStages` | It holds a binding's source stage and evaluation stage; its `source` is the source |
| `SourceRegistry`, `Synchronization.sources` | `StageRegistry`, `Bindings.stages` | |
| `SourceRegistry.prune(existing, unreadable)` | `StageRegistry.prune(existing, inactive)` | The second set also holds disabled bindings |
| `BindingConfig.source`, `.key` | `.source_kind`, `.source_key` | `source_key` is the spec's term; see [Stored field names](#stored-field-names) |
| `indexes._Binding` | `state.Binding`, then `Candidate` | It is one candidate of a binding identity |
| `core.copies.Candidate` | `CandidateEvidence` | What the rule reads about a candidate |
| `Decision`, `Reason`, `UNREADABLE` | `CanonicalDecision`, `DecisionReason`, `UNREADABLE_INDEX_ENTRY` | |
| `candidates`, `candidates.Identity`, `Found`, `find()` | `copy_detection`, `IdentityCandidates`, `CopyDetection`, `detect()` | |
| `Identity.copies` | `IdentityCandidates.tagged_copies` | |
| `_Share`, `_Ownership`, `_State`, `_Stale` | `DestinationClaims`, `OwnershipIndex`, `State`, `StaleError` | |
| `indexes.find_copies()` | `refresh_if_tags_changed()` | It drops the state when tags changed, and returns nothing |
| `indexes.rebuilds()` | `rebuild_count()` | |
| `indexes.update_manifest()` | `set_manifest_entries()` | A write-through, like `set_manifest` |
| `_ask`, `_current`, `_alive`, `_valid`, `_canonical`, `_existing`, `_restore_entry` | `query`, `current_state`, `alive`, `valid`, `canonical`, `existing`, `restore_entry` | Shared by the modules of `runtime/` |
| `_give_manifest`, `_named` | `_cache_manifest`, `_datablock_of` | |
| `Category` | `DiagnosticCategory` | |
| `Refusal`, `Refused`, `RecordRefused` | `RefusalReason`, `RefusedRecord`, `RefusedRecordError` | A reason, a value, and an exception |
| `Schema.kind`, `Schema.record` | `Schema.name`, `Schema.record_type` | `record` is a type |
| `bindings.update()`, `all_bindings()` | `binding_records.write_config()`, `config_records()` | |
| `BindingNotFound`, `Disabled`, `NotTracking`, `SourceUnavailable`, `_Stale` | `BindingNotFoundError`, `BindingDisabledError`, `NotRegisteredError`, `SourceUnavailableError`, `StaleError` | |

### Stored field names

A record's field names are its stored keys, so renaming `BindingConfig.source` and `.key` changes what the binding record stores. The binding record stays at version 1 with the new keys (with the user): it has no released files to migrate, and a version 1 record stored with the old keys is refused as invalid. No other renamed name is stored.

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
13. **The binding record's `source_kind` and `source_key`**, at version 1.
14. **AGENTS.md's Style section** gains the conventions.

## Decision log

- **Plan (with the user, 2026-10-21).** The tiers, conventions, renames, and semantics above, with the spec changes they need.
- **The runtime split (commit 4).** `binding_configs.py`, not `configs.py`: the package exports `configs()`, which would replace a submodule of that name. The modules call each other's helpers through the module, so the tests that patch `current_state` and `_add_share` patch them in one place.
- **Copied bindings (commit 7).** `copy_detection.py`, not `copied_bindings.py`, for the reason `binding_configs.py` is: the package exports `copied_bindings()`. It is named for the `CopyDetection` it returns.
