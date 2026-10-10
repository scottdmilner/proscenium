# Testing Strategy

How the project is tested. What passing the acceptance suite means is defined in [acceptance.md](acceptance.md).

**Most testing uses small bespoke USD fixtures**, each built to exercise specific requirements. They are fast, run in ordinary CI, and fail in ways that point directly at the broken behavior. Production-scale scenes such as ALab are a final check on integration and performance, not the main source of correctness evidence.

## Test Layers

Use:

- Small temporary USD fixtures for precise semantic tests.
- Snapshot/planning tests without Blender mutation, ideally without importing `bpy`.
- Application tests using hand-constructed display plans without USD access.
- End-to-end Blender tests.
- Save/reopen, undo/redo, and failure-injection tests.
- A small number of production-scale scenes for integration and performance testing.

Cover repeated synchronization, all required change cases, transform edge cases, invalid geometry, materials, nested instancing, per-instance variation, visibility/purpose, unsupported ancestors, source correspondence, multiple bindings, lifecycle safety, and protection of unmanaged content.

Before-publication failure-injection tests assert that the entire published generation is unchanged, not merely that old objects still exist: materials, images, flags, correspondence, ownership metadata, inspection data, and selection resolution. Retirement failure tests assert that the new generation stays active and obsolete leftovers remain tracked and retryable. Each case uses the applicable synchronization or lifecycle outcome checks in [Acceptance Criteria](acceptance.md#bespoke-fixtures).

## Metamorphic Tests

Some results are hard to state in full in advance, but the spec says how they must change when the input changes. Metamorphic tests check those relations between runs. They complement bespoke fixtures and never replace a fixture's own expected results.

- Each relation states the input change, the expected effect on the result, and the requirement that justifies it. The expected effect comes from the spec, like any expected result.
- The milestone that delivers a behavior chooses its relations. Examples:
  - Translating a root prim shifts the world transforms and bounds of its displayed descendants by that translation and changes nothing else.
  - Making a prim instanceable, or no longer instanceable, leaves displayed appearance, bounds, and correspondence unchanged; only resource sharing may differ.
  - Switching the payload policy and switching back gives the same result as never switching.
  - Moving to a time code with identical evaluated values changes nothing, and in Phase 2 writes nothing.
  - An incremental refresh gives the same result as a clean full rebuild (see [Incremental Synchronization Tests](#incremental-synchronization-tests)).
- Relations run on bespoke fixtures. They may also run on generated inputs, provided each generated input is reproducible from a recorded seed.

## Named Contract Fixtures

Each fixture is assigned to a milestone in [milestones/](../milestones/README.md) and referenced by ID.

| ID | Fixture |
|---|---|
| `F-DIRTY-LAYER` | **Dirty-layer conflict:** disk changes and unsaved in-process changes coexist. |
| `F-PRIVATE-STAGE` | **Private-stage fidelity:** caller stage settings differ from defaults. |
| `F-CACHED-STAGE` | **Cached-stage isolation:** ambient stage reuse does not cross-contaminate bindings. |
| `F-FAILED-SETTINGS` | **Failed settings transition:** requested settings change; the published display remains old. |
| `F-SHARED-MATERIAL-FAILURE` | **Shared-material failure:** abort after preparing some material dependencies. |
| `F-PUBLICATION-FAILURE` | **Publication failure:** correspondence or inspection publication fails. |
| `F-PREPARATION-CLEANUP-FAILURE` | **Preparation and disposal both fail:** the old generation is unchanged, prepared leftovers stay inactive and persistently tracked, and retry after save/reopen is safe. |
| `F-RETIREMENT-FAILURE` | **Retirement failure:** the new display is active; obsolete resources remain tracked. |
| `F-OWNERSHIP-AMBIGUITY` | **Ownership ambiguity:** copied binding identities and missing resource tags. |
| `F-UNMANAGED-USER` | **Unmanaged user of managed data:** refresh and removal preserve unrelated content. |
| `F-DETACH-SHARED` | **Detach with shared instance content:** a later refresh cannot mutate the detached result. |
| `F-DETACH-AS-IS` | **Detach surviving content as-is:** preserve ordinary Blender edits and damage without USD access or reconstruction; remove binding-specific metadata and controls, and prevent pending cleanup from deleting detached resources. |
| `F-LIFECYCLE-FAILURE` | **Lifecycle failure and retry:** detach before-commit failure, partial cleanup/removal, save/reopen retry, ownership protection, and undo/redo of committed changes. |
| `F-OFFLINE` | **Unavailable source and assets:** verifies the exact offline persistence promise. |
| `F-NESTED-STRESS` | **Nested instance plus shear plus appearance variation.** |
| `F-TEXTURE-IN-PLACE` | **Texture edited in place:** no USD property changes. |
| `F-SAME-VALUES` | **Same evaluated values at a different time (Phase 2):** no unnecessary display writes. |
| `F-UNDO-AFTER-DAMAGE` | **Undo after partial external display damage.** |
| `F-NO-OP-REFRESH` | **No-op refresh:** resource counts and diagnostics follow [Resource Stability](../spec/lifecycle.md#resource-stability), including separate pending-cleanup accounting and recovery; in Phase 2, zero unnecessary writes. |

## Incremental Synchronization Tests

For incremental synchronization:

- Compare results against a clean full rebuild.
- Separately assert that unaffected content was not unnecessarily rewritten.
- Check resource growth over repeated updates under [Resource Stability](../spec/lifecycle.md#resource-stability), including persistent disposal failures and count recovery after explicit cleanup succeeds.
- Measure required interaction operations as well as synchronization (see [Interaction Testing](../spec/interaction.md#interaction-testing) for what an interaction timing measures).

**Optimize the complete display-and-interaction workflow—not object count alone.**
