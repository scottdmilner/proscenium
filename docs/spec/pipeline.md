# Synchronization Pipeline

Layer boundaries, the synchronization transaction, and diagnostics. Cross-cutting guarantees are summarized in [invariants.md](invariants.md).

## Synchronization Layer Boundaries

```text
USD stage + explicit time code + binding settings + planning context
                    ↓
        Evaluated source snapshot
                    ↓
               Display plan
                    ↓
          Blender application
```

### Evaluated Source Snapshot

Resolve supported USD semantics:

- Source hierarchy, identities, and metadata.
- Evaluated transforms and inherited properties.
- Geometry, primvars, visibility, and purpose.
- Effective material assignments and supported networks.
- Native instances, shared contents, and instance context.
- Source-side diagnostics.

This model must not contain Blender datablock references. It remains independent of the display implementation.

This separation does not require copying all scene data or serializing an intermediate scene. Shared arrays and immutable resource descriptions are acceptable where safe. Snapshot lifetime rules:

- Snapshot data cannot change during planning or application.
- The snapshot keeps alive whatever storage it lends out, such as shared arrays.
- Persisted inspection data does not depend on a live USD stage.
- Application does not retain borrowed buffers beyond the synchronization that supplied them.

Design note (suggested, not settled; [M1b](../milestones/M01b-evaluation-gate.md) decides): evaluation may read display semantics from OpenUSD's Hydra scene-index chain through a compiled core, with planning in the same core and the display plan handed to Python application. The requirements above still apply:

- Values are captured into the snapshot before planning, so a live, lazily evaluated scene index is never the snapshot.
- Source hierarchy and identities come from the composed USD stage. Hydra may generate, aggregate, or omit paths, so its paths and instance indices are not source identities.
- Conversions made by Hydra filters, such as implicit surfaces or NURBS turned into meshes, are reported as approximations where inexact.
- Hydra prim types the core does not translate, such as basis curves, points, or volumes, still receive per-behavior placeholders and diagnostics.
- Both viewport and render purpose sets remain available.
- Application never queries the scene index.

### Display Plan

Describe how the evaluated snapshot will be represented:

- Display elements and resource descriptions.
- Sharing and dependency relationships.
- Source/display correspondence.
- Representation-specific transforms and display flags.
- Placeholders and fallbacks.
- Planning diagnostics, including features the chosen representation cannot reproduce exactly.

The display plan may be Blender-specific. It can describe meshes, modifiers, material nodes, or instance resources. Backend independence belongs primarily in the source snapshot; do not invent a universal renderer abstraction unnecessarily.

Planning is deterministic: the same snapshot, binding settings, and planning context yield the same plan.

The **planning context** is a small immutable set of plain values captured before planning, such as the target scene's unit scale, the representation version, material translation configuration, color-space decisions, relevant engine settings, validated external asset descriptors, and the approximation policy. Anything planning depends on must arrive through one of its three inputs. The context is a value object, not a plugin framework.

### Blender Application

Consume the plan and create or update Blender resources.

- Apply planned geometry, materials, transforms, instances, and flags.
- Maintain ownership and source-correspondence indexes.
- Publish display and inspection state consistently (see [Synchronization Transaction](#synchronization-transaction)).
- Retire obsolete managed resources under the [Ownership and Lifecycle](lifecycle.md#ownership-and-lifecycle) rules.
- Handle application failures safely.
- Report failures that only application can detect as diagnostics: resource-consumption failures (a texture that has disappeared or fails to decode), runtime failures (a resource or node operation fails), and state-change failures (the destination became invalid).
- When a resource fails during application, abort the transaction unless the plan already authorized a fallback for that resource. Application never invents a semantic fallback.

The application-layer interface serves the chosen display implementation. Do not build a general-purpose plugin framework.

**Application must not query USD to fill in unresolved source semantics.** It consumes already resolved state and representation decisions. Inherited visibility and material-binding precedence, for example, belong upstream. If application code needs to resolve them, the boundary is leaking.

### Why the Boundary Is Enforced

Every feature extends both evaluation/planning and application explicitly. This avoids two extremes:

- A monolithic importer that mixes USD evaluation with Blender mutation.
- Completing the entire source translator before discovering that its output cannot support the chosen Blender representation.

Prototyping the display representation before building the full translator guards against the second.

**Source-semantic diagnostics are produced before the display layer.** Evaluation and planning detect invalid data, unsupported features, approximations, lossy conversions, missing dependencies, and representation capability limits. All source-semantic diagnostics and known representation limitations exist before any Blender data is mutated. This means:

- A synchronization that fails for source reasons fails before touching the existing display.
- Planning tests can assert every source-semantic diagnostic without Blender.
- The application layer never needs USD-semantic checks to decide what to warn about.

Application may still report resource-consumption, runtime, and state-change failures, because some can only be detected when the resource is actually consumed.

## Synchronization Transaction

Each synchronization is a transaction:

```text
Acquire source
    → Evaluate and validate
    → Plan
    → Prepare replacement resources
    → Publish
    → Retire obsolete resources
```

- **Before publication,** any failure preserves the previous published generation unchanged and attempts to dispose of prepared work. Failed disposal leaves leftovers persistently tracked as [pending cleanup](lifecycle.md#pending-cleanup), excluded from active display and correspondence, and retryable. The attempt remains a fatal failure, reporting both the original failure and pending cleanup. For a first synchronization, no untracked partial content remains.
- **Preparation** never mutates resources reachable from the published generation unless a complete rollback mechanism covers the mutation. Shared meshes, materials, images, and node groups are the main risk.
- **Publication** switches the whole generation together (see [Binding State](lifecycle.md#binding-state)). It never leaves a silently mixed old/new result.
- **After publication,** retirement failures do not fail the synchronization. Obsolete resources that could not be removed stay persistently tracked as pending cleanup, become noncanonical, are excluded from the active display and correspondence, and are reported with retryable cleanup diagnostics.

Ownership tracking covers newly created prepared resources before subsequent fallible work, with enough persistent evidence to recover from failed disposal. They remain isolated from the active display until publication. Reused published resources remain protected by the existing manifest and are never disposal candidates. Publication makes the new resources active and marks obsolete resources for retirement. Deferred disposal does not permit failed preparation to become visible or substitute for restoring any mutated published state.

Failure safety covers recoverable failures. Process termination, native crashes, and catastrophic allocation failure are not promised to be recoverable.

These guarantees apply equally to incremental mutations in Phase 2.

Undo grouping is **not** a substitute for failure-safe staging or rollback.

## Diagnostics

Distinguish:

- Unsupported valid content.
- Approximation.
- Lossy conversion.
- Missing dependencies.
- Invalid data.
- Source-access conflict.
- Pending cleanup (retryable disposal of prepared or obsolete resources).
- Fatal failure.

Include binding, source path, property/asset identifier, severity, and fallback where applicable.

Aggregate repeated problems. Source/display diagnostics belong to a published generation or to the last attempt and are kept separate from any attempt history. Unresolved cleanup diagnostics also persist with pending-cleanup ownership information, so a later attempt cannot erase pending work. Report current cleanup status separately from historical attempt results and deduplicate by operation and resource. An unchanged refresh produces equivalent deduplicated source/display diagnostics. Current cleanup diagnostics may change with unresolved work under [Resource Stability](lifecycle.md#resource-stability); resolved cleanup diagnostics are removed rather than accumulated as history.

Each synchronization reports one result state, derived from its diagnostics:

- **Success:** no diagnostics in any category.
- **Completed with issues:** at least one unsupported, approximation, lossy-conversion, missing-dependency, invalid-data, or pending-cleanup diagnostic, but no fatal failure.
- **Fatal failure,** including a source-access conflict.

A completed synchronization with issues must be distinguishable from a fully supported result.

Never pass unsafe invalid geometry into Blender or silently present unsupported translation as exact.
