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

Before-publication failure-injection tests assert that the entire published generation is unchanged, not merely that old objects still exist: materials, images, flags, correspondence, ownership metadata, and selection resolution. Retirement failure tests assert that the new generation stays active and obsolete leftovers remain tracked and retryable. Each case uses the applicable synchronization or lifecycle outcome checks in [Acceptance Criteria](acceptance.md#bespoke-fixtures).

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
| `F-DIRTY-LAYER` | **Dirty layers:** disk changes and unsaved in-process changes coexist, including a dirty layer that contributes only through a payload. A binding displays them as loaded, and a requested reload of its reused stage rereads the disk content, discarding the edits, and keeps the opinions in its anonymous layers. |
| `F-PRIVATE-STAGE` | **Evaluation-stage fidelity:** an attached stage's settings differ from defaults and change between synchronizations. |
| `F-CACHED-STAGE` | **Cached-stage isolation:** a caller may attach a cached source stage; an ambient cache context never supplies a binding's evaluation stage, which is distinct from the source stage and every other binding's evaluation stage and is never placed in a stage cache. |
| `F-MULTI-BINDING` | **Independent bindings on one source:** bindings with different settings and payload policies sharing a caller-supplied stage, bindings on stages callers opened from `.usd`, `.usda`, and `.usdc` copies of one scene, and an anonymous stage containing the flattened scene whose unsaved opinions can be displayed without those files. |
| `F-SOURCE-CHANGE` | **Source change during evaluation:** a contributing layer changes while the binding evaluates; the attempt is discarded before publication. The source changing after a generation is synchronized, by an edit, a reload, or a new attachment, makes `cache` cache nothing. |
| `F-REATTACH` | **Release and reattachment:** a caller's stage independently attached to two binding handles, released through one handle, replaced with explicit confirmation for a different root layer, and restored through persistent binding identifiers after reopening. |
| `F-SCHEMA-VERSIONS` | **Schema versions:** binding, ownership, and pending-cleanup records at an older supported version, at an older version whose migration fails, at a newer version, and unreadable. |
| `F-BINDING-STATE` | **Binding state through handles:** bindings created, configured, synchronized, saved and reopened, undone, and removed through handles, with a persistent selection over two bindings. |
| `F-FAILED-SETTINGS` | **Failed settings transition:** requested settings change; the published display remains old. |
| `F-CACHED-TIME-CODES` | **Cached time codes:** time codes cached in a published generation, a `cache` call that fails, a generation synchronized at the default time code, and synchronizing again. |
| `F-SHARED-MATERIAL-FAILURE` | **Shared-material failure:** abort after preparing some material dependencies. |
| `F-PUBLICATION-FAILURE` | **Publication failure:** correspondence publication fails. |
| `F-PREPARATION-CLEANUP-FAILURE` | **Preparation and disposal both fail:** the old generation is unchanged, prepared leftovers stay inactive and persistently tracked, and retry after save/reopen is safe. |
| `F-RETIREMENT-FAILURE` | **Retirement failure:** the new display is active; obsolete resources remain tracked. |
| `F-OWNERSHIP-AMBIGUITY` | **Ownership ambiguity:** copied binding identities on each copy route, a missing, cleared, or duplicated binding index, a linked binding, managed content copied without its manifest, and manifest entries whose content was deleted. |
| `F-UNMANAGED-USER` | **Unmanaged user of managed data:** refresh and removal preserve unrelated content. |
| `F-DETACH-SHARED` | **Detach with shared instance content:** a later refresh cannot mutate the detached result. |
| `F-DETACH-AS-IS` | **Detach surviving content as-is:** preserve ordinary Blender edits and damage without USD access or reconstruction; remove binding-specific metadata and controls, and prevent pending cleanup from deleting detached resources. |
| `F-LIFECYCLE-FAILURE` | **Lifecycle failure and retry:** detach before-commit failure, partial cleanup/removal, save/reopen retry, ownership protection, and undo/redo of committed changes. |
| `F-OFFLINE` | **Unavailable source and assets:** verifies the exact offline persistence promise. |
| `F-NESTED-STRESS` | **Nested instance plus shear plus appearance variation.** |
| `F-APPEARANCE-CASES` | **Representation feasibility cases:** the primvar and material-connection cases of [Primvar Support Matrix](../spec/support/geometry.md#representation-feasibility-cases) and [Connection Grammar](../spec/support/materials.md#representation-feasibility-cases), one per scene subtree. |
| `F-TEXTURE-IN-PLACE` | **Texture edited in place:** no USD property changes. |
| `F-SAME-VALUES` | **Same evaluated values at a different time (Phase 2):** no unnecessary display writes. |
| `F-UNDO-AFTER-DAMAGE` | **Undo after partial external display damage.** |
| `F-NO-OP-REFRESH` | **No-op refresh:** resource counts and diagnostics follow [Resource Stability](../spec/lifecycle.md#resource-stability), including separate pending-cleanup accounting and recovery; in Phase 2, zero unnecessary writes. |
| `F-KIND-HIERARCHY` | **Kind hierarchy:** an assembly, group, and component above meshes, a mesh under no model, components outside a valid model hierarchy, and intermediate prims with nothing Hydra needs to keep; selection by kind and expansion follow the composed stage. |
| `F-NESTED-SELECTION` | **Selection floors in nested native instances:** one prototype used inside and outside an outer instance, and a kind on an instance root; nothing inside instance contents is a selection target. |
| `F-UNIVERSE-MEMBERSHIP` | **Browsing-universe membership:** invisible, guide-only, render-only, inactive, abstract, and unloaded content, a guide made explicitly visible by an ancestor's `guideVisibility`, a materials scope, an empty organizational prim, an unsupported gprim shown as a placeholder or marker, and visibility that changes over time. |
| `F-TRANSFORMS` | **Transforms the planner places:** ordered transform operations, a pivot, matrix ops, negative and nonuniform scale, shear, transforms authored on meshes, reset transform stacks outside and inside a native instance, a payload, a translate sampled over time with two equal samples, and a projective matrix in a layer of its own. |
| `F-UNITS-UP-AXIS` | **Units and up-axis conversion:** one scene as a Y-up stage in centimeters and a Z-up stage in meters, with a mesh and a native instance, synchronized into target scenes of different unit scales with conversion off and on. |
| `F-VISIBILITY-PURPOSE` | **Visibility and purpose:** inherited invisibility, a mesh of each purpose, an inherited purpose, a proxy and render pair, and visibility sampled over time with declared transitions. |
| `F-UNSUPPORTED-CONTENT` | **Unsupported content:** untranslated types with authored, computed, and no bounds, implicit shapes and a NURBS patch converted exactly and inexactly, a point instancer, a placeholder whose transform, visibility, and purpose still apply, and a supported mesh beneath an unsupported ancestor. |
| `F-POINT-INSTANCERS` | **Point instancers:** a point instancer without ids, points of each prototype kind (an Xform, a mesh root, a native instance) with their own transforms, a point hidden by `invisibleIds`, per-point and constant primvars, and an unused prototype child; one with ids, a negative one included; and one inside two native instances. |

## Incremental Synchronization Tests

For incremental synchronization:

- Compare results against a clean full rebuild.
- Separately assert that unaffected content was not unnecessarily rewritten.
- Check resource growth over repeated updates under [Resource Stability](../spec/lifecycle.md#resource-stability), including persistent disposal failures and count recovery after explicit cleanup succeeds.
- Measure required interaction operations as well as synchronization (see [Interaction Testing](../spec/interaction.md#interaction-testing) for what an interaction timing measures).

**Optimize the complete display-and-interaction workflow—not object count alone.**
