# Project Overview

This project is a Blender extension for reliable, repeatable, **one-way synchronization of composed OpenUSD stages into a managed Blender display representation**.

It serves as:

- A snapshot synchronizer for supported USD content.
- The scene-display layer for a future USD-native stage editor.

**USD is authoritative.** Phase 1 does not author USD, export USD, or translate Blender edits back into USD.

This document establishes project requirements and architectural direction. [SEQUENCE.md](SEQUENCE.md) details the implementation milestones (P1–P14) and references the requirements here. Where the two documents conflict, this document takes precedence. Milestones describe planned work, not implementation status. Inspect the repository before assuming a feature exists.

Decisions that are still open, and the behavior chosen for settled ones, are tracked in the [Decision Register](#decision-register).

## Core Architecture

**The Blender display structure does not need to mirror the USD scene graph.**

Keep three concepts separate:

1. **USD scene graph:** authoritative source hierarchy and scene semantics.
2. **Source inspection and selection model:** entities users browse, inspect, select, and eventually edit.
3. **Blender display representation:** resources used to display the evaluated stage.

Requirements:

- The USD hierarchy must remain accessible through source inspection, within the browsing universe defined in [Source Inspection and Interaction](#source-inspection-and-interaction).
- Blender objects, collections, and parenting need not reproduce that hierarchy.
- One source prim may produce multiple display elements.
- Multiple source prims may share a display representation.
- Organizational prims need not have individual Blender objects.
- Supported descendants must receive the correct ancestor state, including beneath unsupported ancestors.
- Source hierarchy and selection identities are independent of display partitioning.

The central architectural rule:

> **Tools address USD entities through the source selection model. The display layer resolves those entities to Blender resources; tools do not infer USD structure from Blender parenting or object names.**

That preserves freedom to optimize the display later without redesigning the editor's hierarchy, selection, or authoring model.

Objects, collection instancing, Geometry Nodes, batching, or a hybrid are implementation options. Geometry Nodes is not mandatory, and one large graph is not a goal in itself. Prefer the simplest representation that satisfies correctness, interaction, and performance needs. Keep the performance tests around for later so that we can adapt to updates to Blender's performance.

## Delivery Phases

### Phase 1A — Correct Snapshot Synchronization

Synchronize supported content at an **explicit USD time code supplied as a function parameter**. The USD default time code is permitted.

- Manual refresh is required.
- Full traversal and rebuilding are acceptable.
- Blender object identities need not survive refresh.
- Native geometry sharing must be preserved.
- Binding lifecycle, persistence, diagnostics, and failure safety are required.
- The ALab acceptance test (ALab v2.3.0, techvar assets v2.2.0, `entry.usda`) must pass at any time code under every payload policy, against the criteria in [Acceptance Criteria](#acceptance-criteria).

### Phase 1B — Incremental Synchronization

Preserve Phase 1A correctness while avoiding unnecessary work.

- Update affected representations and their dependencies.
- Leave unaffected representations untouched during ordinary incremental refresh, as defined in [Affected Content](#affected-content).
- Preserve source selections where their source identities remain valid.
- Maintain sharing and reclaim obsolete managed resources without breaking sharing or other owners.
- Establish and meet representative performance targets for synchronization and the required interaction operations.
- Support manual file-backed refresh and in-memory sources; do not rely exclusively on future editor-provided change hints.

See [Incremental Synchronization](#incremental-synchronization) for detailed requirements.

**Phase 1B must be complete before Phase 2 begins.**

### Phase 2 — USD Stage Editor

Tools author USD changes and use the synchronizer as their display layer. Actual USD authoring tools are outside Phase 1.

Automatic timeline synchronization is a stretch goal. The evaluation time code may change between any two synchronizations.

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
- Retire obsolete managed resources under the [Ownership and Lifecycle](#ownership-and-lifecycle) rules.
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

## Source Inspection and Interaction

Source/display correspondence is a first-class contract:

- Display selection resolves to a binding and source entity, including instance context where applicable.
- Source selection of a prim or subtree resolves to its associated display elements.
- Source inspection works independently of Blender parenting.
- Native instance roots are selectable and source-identifiable.
- Individually selectable native-instance descendants are not required. Adding them would be a deliberate scope expansion.
- Source correspondence survives any batching, reordering, or geometry partitioning.

The interaction contract must settle:

- The **browsing universe**: which of the populated composed hierarchy, instance-proxy descendants, inactive prims, unloaded payload roots, abstract prims, and composition provenance source inspection exposes. Not all are required; the set must be defined.
- The supported metadata set for inspection. Arbitrary USD metadata inspection is not implied.
- Source-path identification.
- The identity of persistent selection state.
- Viewport picking granularity.
- Selection highlighting and framing.
- Instance-root selection.
- Inspection and selection of organizational or non-geometric prims.
- Interfaces needed by future USD manipulation tools.
- Whether any ordinary Blender selection/manipulation behavior is required.

Do not assume every prim needs independent viewport picking or that standard Blender transform tools must become USD authoring tools.

Persist enough inspection and correspondence information to inspect the saved display without accessing an unavailable source. Distinguish the last synchronized snapshot from newly evaluated source state.

### Interaction Testing

Picking, highlighting, and framing normally need a window and a 3D viewport, which background Blender and the `bpy` module lack. The extension therefore exposes the logic behind interaction as plain functions that can be tested headless. Examples include mapping a picked object and instance to a source path, computing framing bounds for a source selection, and resolving highlight targets. The interaction contract is defined and tested in these terms.

Interaction feasibility and qualification are claimed **at the level of these headless functions**: given the inputs a viewport operation supplies, they produce the contracted result. The project does not verify that real viewport operations produce those inputs. For the chosen representation, P4 records what a real pick is assumed to supply as an accepted, unverified risk.

Interaction timings measure the cost of these headless interaction functions plus any Blender data updates they trigger, such as selection or highlight state changes.

**Future work:** the following are out of scope for this project:

- A windowed test suite that drives real viewport picking, highlighting, and framing.
- Measuring viewport drawing performance.

## Bindings and Source Access

A synchronization binding associates a source with a dedicated managed destination collection and settings. Each binding stores an explicit target scene and its own units and up-axis conversion settings. Together with the target scene's unit scale, these drive coordinate conversion.

Support:

- Root-layer files: `.usd`, `.usda`, `.usdc`.
- Caller-supplied in-memory stages without requiring file reopening.
- Load-all or load-no-payload policy.
- Explicit evaluation time code, including the USD default time code.
- Coordinate-conversion and purpose/display settings.
- Multiple independent bindings, including bindings using the same source.

The default scope is the entire available stage. Subtree selection and individual payload selection are not required.

Consume existing composition and variant selections. Do not author composition arcs or variant selections.

Binding configuration must not cross-contaminate other bindings. Opening or synchronizing must not save or modify source USD files.

Use durable identifiers and ownership metadata, not Blender display names or object hierarchy. Keep binding identity, source identity, and display-resource identity distinct.

Runtime indexes follow the rules in [Undo and Runtime State](#undo-and-runtime-state).

### Source Consistency

- Synchronization is synchronous and non-reentrant.
- The caller must not mutate an attached stage or its contributing layers during a synchronization.
- Where a source change during evaluation can be detected, the attempt is discarded before publication.

### Source Identity

Source identity is persisted separately from source availability. P3 defines the in-memory source key contract:

- Its uniqueness scope.
- Whether reattachment requires an exact key match.
- Whether the root-layer identifier is authoritative or only informative. A root-layer identifier alone cannot be the reattachment contract for anonymous or unsaved sources.
- Whether replacing the attached stage preserves existing source selections.
- Whether attaching a different stage under an existing key requires explicit confirmation.

### Copied Bindings

Custom properties can be copied by duplication; do not assume they guarantee uniqueness. A binding can be copied by duplicating its destination collection or scene, appending managed content from another `.blend`, or copying a binding record together with its manifest.

- A binding whose identity is not unique is **disabled pending repair**: it keeps its display, does not refresh, and reports the ambiguity until the user makes it a new binding or detaches it.
- A deterministic, documented rule decides which candidate remains canonical. If the rule cannot decide, all candidates are disabled.
- Copies are never automatically claimed, merged, or deleted.

### In-Memory Sources

Requirements:

- Do not author changes to a caller-supplied stage's layers or change its stage settings, including load state, population mask, layer muting, and edit target.
- Evaluate the caller's composed content as the caller's stage presents it, except that the binding's payload policy replaces the caller's load rules. P3 settles how each piece of stage-level state is reproduced: muted layers, population mask, resolver context, interpolation settings, and session-layer opinions.
- Multiple bindings on the same in-memory source may use different payload policies without affecting each other or the caller.
- If the caller releases the attached stage, the binding becomes unattached. Replacing it follows the [Source Identity](#source-identity) rules.
- After a `.blend` is reopened, an in-memory binding reports its source as unavailable until the caller attaches a stage. Refreshing an unattached binding produces a diagnostic and preserves the saved display.
- Define what an in-memory binding persists so a caller can reattach the correct stage.

Design note (suggested, not settled): open a private stage per binding over the caller's root and session layers, using the binding's payload policy. Shared layers would make unsaved caller edits visible without reopening files. Persist the source kind, a caller-chosen source key, and the root-layer identifier.

### File-Backed Refresh

Requirements:

- A file-backed refresh displays the source as it exists on disk.
- Refresh must not discard unsaved in-process edits made by other tools to layers it shares.
- **If any contributing layer has unsaved in-process edits, refresh fails** with a source-access conflict naming those layers and preserves the previous display.
- Refresh does not reuse a cached stage or otherwise share stage state with other bindings.
- Refresh may reload clean shared layers from disk. Other stages using those layers then see the current disk content. This is the only effect synchronization may have that other stages can observe; it never authors changes or alters another stage's settings.

USD shares opened layers across the whole process, so file-backed and in-memory bindings on the same files can see each other's layer state.

Design note (suggested, not settled): open the stage at each refresh outside any stage-cache context, check contributing layers for unsaved edits before evaluation, and reload the clean ones. If P1 shows that a private disk view can be built reliably without touching shared layers, P3 may replace the conflict failure with that view. That change only turns failures into successes.

## Ownership and Lifecycle

Generated content is USD-authoritative. Blender-side edits to managed content are not guaranteed to survive synchronization.

Keep these concepts separate in ownership records:

| Concept | Meaning |
|---|---|
| Resource identity | Which managed resource this is |
| Ownership | Which binding may replace or retire it |
| Source coverage | Which source entities it represents (possibly many) |
| Representation role | Why it exists |
| Usage and dependencies | Which other resources depend on it, managed or not |

A resource has one owning binding but may cover many source entities and have many users.

Required behavior:

- Renaming does not detach content.
- Deleting managed content does not delete its source; refresh restores required display content.
- Additional collection links do not detach managed content.
- Unrelated unmanaged content must not be modified or deleted.
- Refresh does not mutate a managed resource that unmanaged content uses. It creates a replacement, and the old resource is left intact and released from management.
- Content without sufficient ownership evidence is treated as unmanaged. Ambiguous candidates are reported, not automatically claimed or deleted.
- Successful refresh removes stale content and accidental duplicate canonical representations.
- Duplicates are defined by source coverage and representation role, not by assuming one Blender object per prim.
- Repeated unchanged refreshes must not accumulate resources or diagnostics.

Required lifecycle operations:

- **Cleanup:** remove duplicate or obsolete managed content and unused exclusively owned resources, and retry retirements left pending by earlier synchronizations.
- **Detach:** convert all of a binding's current managed content into independent, unmanaged content. Detach operates on a whole binding; detaching individual source prims or subtrees is deferred. The binding remains, and its next refresh behaves like a first synchronization, creating new managed content alongside the detached result.
- **Remove binding:** remove configuration and managed content while preserving detached and unrelated content.

Lifecycle operations must preserve resources still required by other owners, and must remain correct even when Blender objects do not correspond individually to USD prims.

The detached result preserves the appearance of the last published generation: geometry, transforms, and translated materials at the synchronized time code. It must not depend on resources that remain managed or on extension runtime state that could change it later. It may keep references to external image files. Detach may require materializing content whose display relies on managed shared resources or extension-specific mechanisms.

### Synchronization Transaction

Each synchronization is a transaction:

```text
Acquire source
    → Evaluate and validate
    → Plan
    → Prepare replacement resources
    → Publish
    → Retire obsolete resources
```

- **Before publication,** any failure preserves the previous published generation unchanged and cleans up prepared work. For a first synchronization, no untracked partial content remains.
- **Preparation** never mutates resources reachable from the published generation unless a complete rollback mechanism covers the mutation. Shared meshes, materials, images, and node groups are the main risk.
- **Publication** switches the whole generation together (see [Binding State](#binding-state)). It never leaves a silently mixed old/new result.
- **After publication,** retirement failures do not fail the synchronization. Obsolete resources that could not be removed stay tracked, become noncanonical, are excluded from the active display and correspondence, and are reported with retryable cleanup diagnostics.

Failure safety covers recoverable failures. Process termination, native crashes, and catastrophic allocation failure are not promised to be recoverable.

These guarantees apply equally to incremental mutations in Phase 1B.

Undo grouping is **not** a substitute for failure-safe staging or rollback.

### Undo and Runtime State

Undo restores previously published Blender display state and its metadata. It does not undo external USD changes or guarantee that the restored display matches the current source.

- Each synchronization that publishes is exactly one undo step. Synchronizations invoked through the Python API push the step explicitly; an operator that calls the API does not push a second one.
- A failed synchronization pushes no undo step. It changes only the last-attempt record.
- With global undo disabled or in background mode, synchronization behaves the same but pushes no step.
- All persistent state (see [Binding State](#binding-state)) lives in Blender data, so undo restores the display and its metadata together.
- When undo/redo restores an earlier display, mark the binding as possibly out of date relative to its source.
- In-memory stage attachments are runtime associations keyed by binding identity. Undo neither restores nor removes them; a binding that still exists after undo stays attached.
- Runtime code must not hold Blender datablock references across operator calls. This covers indexes, UI caches, callbacks, queued work, and retained plans. Runtime indexes are disposable caches keyed by persistent identifiers, rebuilt after file load, deletion, undo, and redo, and guarded by a generation counter so stale lookups fail loudly instead of returning dead references.

Detach, cleanup, and binding removal **must support undo/redo**, including consistent ownership and binding state.

## Persistence

### Binding State

Keep these distinct:

| State | Contents | Persisted |
|---|---|---|
| Binding configuration | Binding identity, source information, destination, target scene, and requested settings (time code, payload policy, conversion, purpose) | Yes |
| Published generation | Display resources, inspection snapshot, correspondence, ownership manifest, the settings and time code it was produced with, source revision information, its diagnostics, and persistent selection-resolution state | Yes |
| Last attempt | Settings attempted, result state, and diagnostics | Yes |
| Runtime source attachment | The caller's stage for an in-memory binding | No |
| Runtime indexes | Disposable caches keyed by persistent identifiers | No; rebuilt |

A binding can therefore report, for example: requested time 20 with load-none, displayed time 10 with load-all, last attempt failed. This applies equally to changed source paths, changed conversion settings, and undo restoring an older display.

Source information is the file path for file-backed bindings, or the reattachment information for in-memory bindings (see [Source Identity](#source-identity)).

### Reopening

On reopening a `.blend`:

- Restore metadata and indexes.
- Do not automatically synchronize. The extension does not access USD sources or external assets on its own initiative; Blender may still read image files referenced by translated materials.
- Refresh is explicit.
- An unavailable source must not erase the saved representation.
- Source unavailability must not automatically detach the binding.
- Detached content remains detached.

The saved display remains usable without its USD source: geometry, transforms, translated materials, inspection, and correspondence persist in the `.blend`. Image textures remain references to external files, so texture appearance requires those files to be reachable. Packing assets into the `.blend` is not a Phase 1 guarantee.

Serialization of arbitrary unsaved in-memory USD edits is not a Phase 1 guarantee.

### Schema Versions

Binding records, ownership manifests, inspection snapshots, and correspondence carry schema versions.

- Older supported schemas migrate on load.
- If migration fails or the schema is newer than the extension supports, preserve the display, disable refresh and lifecycle operations for that binding, and report why.
- Without the extension installed, the saved display remains ordinary Blender content.

## Supported Scene State

### Transforms and Time Codes

- Evaluate ordered transform operations, reset-transform-stack behavior, and transforms authored on meshes.
- Reconcile organizational relationships with reset-transform-stack behavior without requiring equivalent Blender parenting.
- Support matrix transforms, negative and nonuniform scale, and shear.
- Preserve evaluated placement rather than reconstructing editable USD transform-operation stacks.
- Diagnose approximations when exact representation is unavailable.
- Evaluate supported time-varying values at the supplied time code, including topology changes. The USD default time code is permitted.
- Do not assume a USD time code equals a Blender frame.
- Do not create Blender animation data or change frame rate/playback range.

#### Coordinate Conversion

- Units/up-axis conversion is configurable and **disabled by default**. When disabled, the correction matrix is the identity.
- Enabled conversion respects the target scene's unit scale without changing scene settings.
- Converted results are consistent for geometry, transforms, bounds, and instances.

Coordinate conversion is owned by **representation planning**:

- The evaluated snapshot keeps source units and up-axis, recording `metersPerUnit` and `upAxis` as stage metadata.
- At synchronization start, application captures the binding's target-scene unit scale into the planning context as a plain value. This keeps Blender references out of the snapshot.
- Planning builds one correction matrix and prefixes it to every world transform. Local geometry is unchanged; bounds and instances inherit the correction. Points are converted individually only when batching bakes geometry into world space.
- If the destination collection is linked into a scene whose unit scale differs from the target scene's, diagnose the mismatch rather than guessing.

```text
scale           = stage.metersPerUnit / target_scene.unit_settings.scale_length
C               = R_upaxis @ Scale(scale)    # R_upaxis = +90° about X for Y-up sources, identity for Z-up
M_blender_world = C @ M_usd_world            # Blender column-vector convention (transposed from USD row-vector matrices)
```

### Geometry and Primvars

Support:

- Validated polygon topology and point positions.
- Authored normals and a documented generation fallback.
- Orientation/winding and documented double-sidedness behavior.
- Supported UV sets with their names and meaningful domains.
- `displayColor` and `displayOpacity`.
- Supported arbitrary primvars converted into native float, color, and vector attributes.
- Indexed and inherited primvars, and supported domain conversions.
- Face-level material assignments.
- Approximate subdivision, edge creases, and corner sharpness.
- Topology-changing snapshots, discarding obsolete topology-dependent data.

Validate topology and attribute sizes before passing data to Blender. Diagnose unsupported types, domains, lossy conversions, holes, and inexact subdivision mappings.

Settle the primvar support matrix **before implementation**. For each supported primvar category, record USD value types, interpolation modes, indexed handling, inheritance, Blender attribute domain, conversion rules, missing/invalid-value behavior, and name-collision rules.

Also classify, for each case, whether the mesh remains supported with an approximation, becomes a placeholder, or fails:

- Geometric primvars such as velocities when unused.
- Opacity interpretation.
- Normal generation and domain conversion.
- Degenerate but structurally valid faces.
- Nonfinite positions and transforms.
- Unsupported topology features on an otherwise supported mesh.

### Native Instancing

Support:

- Native and nested native instances.
- Multi-mesh, multi-material instance contents.
- Shared underlying geometry.
- Effective instance transforms, visibility, and purpose.
- Instance-context correspondence.
- Updates to shared contents.
- Transitions between instanced and non-instanced representations.
- Instance-root selection and source inspection.
- Per-instance `displayColor`, inherited material assignments, and named primvars driving supported material inputs.

Per-instance appearance must not collapse into a single shared appearance. Preserve geometry sharing where shading variation does not require unique geometry.

### Materials

Translate the supported USD Preview Surface subset into Blender materials:

- Constant parameters.
- Base color, metallic, roughness, emission, opacity, and normal mapping.
- Common image-texture connections.
- Named UV selection and texture-coordinate transforms.
- Texture color spaces and UDIMs.
- Direct, inherited, collection-based, and face-subset bindings with applicable precedence.
- Required per-instance variation.
- Supported displacement signals through the material displacement path, without baking into mesh geometry.

Target the Principled BSDF subset usable in Eevee and Cycles, with documented displacement exceptions.

Display batching must not collapse distinct material assignments or attribute meanings.

Settle a bounded connection grammar **before implementation**:

- Supported shader and node identifiers.
- Supported input/output connections.
- Material purpose and render-context selection.
- Texture channels and scale/bias treatment.
- UV transformation conventions.
- Primvar-reader types.
- Normal-map conventions.
- Opacity behavior.
- Displacement behavior and engine exceptions.
- Fallback behavior for partially supported graphs.

Also settle how `displayColor` and `displayOpacity` interact with no material binding, a translated material, an unsupported material, and per-instance variation.

Document ownership and reuse rules for translated materials, images, node groups, and dependencies. Diagnose missing textures, unsupported networks, and incomplete translations. Do not silently substitute another UV set when the requested one is unavailable.

### Visibility and Purpose

Respect effective inherited visibility separately from purpose.

| Destination | Default included purposes |
|---|---|
| Viewport | `default`, `proxy` |
| Final render | `default`, `render` |

Exclude `guide` by default. Support both destinations from the same evaluated snapshot.

Do not traverse only currently visible prims: organization, render-only content, inherited state, and supported descendants may still be needed.

### Models and Unsupported Content

Expose model kind and available asset metadata. Preserve source model grouping in inspection and use applicable bounds information.

Support is decided **per behavior, not per prim type**. Transform, imageability, geometry, material binding, and inspection metadata are each evaluated independently, so one unsupported behavior does not short-circuit the others.

For unsupported geometry:

- Use a bounding-box placeholder when usable bounds are available.
- Otherwise create an empty marker and warn.
- Respect transforms, visibility, and purpose.
- Avoid expensive unsupported evaluation merely to obtain bounds.
- Do not discard supported descendants or otherwise supported behavior on the same prim.

Deferred areas include point instancers, curves, NURBS patches, points, elementary geometry, cameras/lights, skeletal deformation, physics, unsupported custom-schema visualization, hole-face support, and `.usdz` packaging.

Additional shader systems, generated simplified proxies, export, round trips, and render equivalence are outside scope.

## Diagnostics

Distinguish:

- Unsupported valid content.
- Approximation.
- Lossy conversion.
- Missing dependencies.
- Invalid data.
- Source-access conflict.
- Pending cleanup (retryable retirement failure).
- Fatal failure.

Include binding, source path, property/asset identifier, severity, and fallback where applicable.

Aggregate repeated problems without accumulating duplicates. Diagnostics belong to a published generation or to the last attempt, and are kept separate from any attempt history. An unchanged refresh produces an equivalent deduplicated diagnostic set and does not accumulate historical copies.

Each synchronization reports one result state, derived from its diagnostics:

- **Success:** no diagnostics in any category.
- **Completed with issues:** at least one unsupported, approximation, lossy-conversion, missing-dependency, invalid-data, or pending-cleanup diagnostic, but no fatal failure.
- **Fatal failure,** including a source-access conflict.

A completed synchronization with issues must be distinguishable from a fully supported result.

Never pass unsafe invalid geometry into Blender or silently present unsupported translation as exact.

## Implementation Sequence

Milestones are detailed in [SEQUENCE.md](SEQUENCE.md):

- **P1** — Runtime feasibility, workspace, and test infrastructure
- **P2** — Display, inspection, and interaction contracts
- **P3** — Binding model, source access, identity, and persistence schemas
- **P4** — Display representation and interaction feasibility prototypes
- **P5** — Synchronization architecture, diagnostics, and failure safety
- **P6** — Snapshot evaluation and representation planning
- **P7** — Blender application and source inspection UI
- **P8** — Validated mesh and primvar translation
- **P9** — Material translation and binding resolution
- **P10** — Complete native instancing
- **P11** — Ownership reconciliation, detach, and lifecycle operations
- **P12** — Complete and qualify Phase 1A
- **P13** — Incremental change discovery and dependency invalidation
- **P14** — Incremental application and Phase 1B qualification

Ordering constraints:

- The interaction contract is settled and display representations are prototyped before a display backend is committed.
- Evaluation/planning (P6) and application (P7) are deliberately separate milestones, and every later feature milestone extends both sides explicitly (see [Why the Boundary Is Enforced](#why-the-boundary-is-enforced)).
- Support matrices and grammars are settled at the start of the milestone that implements them, before implementation.
- Phase ordering follows [Delivery Phases](#delivery-phases).

## Incremental Synchronization

Discover changes from:

- File-backed manual refresh.
- In-memory stage edits.
- Evaluation time-code changes.
- Binding-setting changes.
- Managed display damage.

Handle changes to:

- Prim existence, activation, type, hierarchy, and variants.
- Transforms, geometry, topology, normals, and primvars.
- Visibility and purpose.
- Materials, networks, bindings, and dependencies, including external assets changed without any USD edit.
- Payload state.
- Instanced/non-instanced representation and shared contents.
- Evaluation time code and binding settings, including time changes that do not alter evaluated values.
- Target-scene unit scale and representation version.
- Managed Blender content requiring repair, distinguished from legitimate external users of managed resources.

Separate change discovery from dependency invalidation. Account for inherited/shared state, display partitions, and both old and new dependencies when structure or relationships change. Recover correctly from missed or coalesced change notifications.

Editor-provided change descriptions may be hints, but are not the sole correctness mechanism. Full traversal or snapshot comparison is acceptable for discovery if performance targets are met and unaffected Blender content is not unnecessarily rewritten.

### Affected Content

Distinguish three levels:

1. **Source-affected entities:** source state actually changed.
2. **Dependency-affected resources:** depend on changed state.
3. **Replacement-affected resources:** replaced only because they share an approved partition with affected content.

"Unaffected" means outside levels 1 and 2. Level 3 is permitted but bounded by churn and performance budgets, so partition choice cannot make the unaffected requirement meaningless. Untouched resources keep stable identities, and a no-op refresh performs no unnecessary Blender writes.

> **Change discovery proposes work; comparing evaluated content decides whether a resource actually requires replacement or mutation.**

This allows conservative discovery without unnecessary Blender writes.

## Compatibility and Development

- Minimum Blender version: **5.2 LTS**.
- Use the OpenUSD version bundled with the supported Blender distribution.
- Support macOS, Windows, and Linux.
- Prefer Python-only implementation.
- Do not require externally installed custom resolvers or schema plugins.
- If additional compiled components become necessary, all three platforms remain required.

Verify actual runtime capabilities rather than assuming Blender's embedded Python behaves like a normal `uv` environment. "Blender has USD support" and "the required USD Python API is available and can exchange stages with callers" are separate assumptions.

Planned tooling includes `uv`, `ruff`, `ty`, pre-commit hooks, extension packaging, and pytest-based tests. Keep development dependencies separate from distributable runtime dependencies; do not inadvertently bundle another OpenUSD build.

## Testing Strategy

Use:

- Small temporary USD fixtures for precise semantic tests.
- Snapshot/planning tests without Blender mutation, ideally without importing `bpy`.
- Application tests using hand-constructed display plans without USD access.
- End-to-end Blender tests.
- Save/reopen, undo/redo, and failure-injection tests.
- Representative large-scene acceptance and performance tests.

Cover repeated synchronization, all required change cases, transform edge cases, invalid geometry, materials, nested instancing, per-instance variation, visibility/purpose, unsupported ancestors, source correspondence, multiple bindings, lifecycle safety, and protection of unmanaged content.

Failure-injection tests assert that the entire published generation is unchanged, not merely that old objects still exist: materials, images, flags, correspondence, ownership metadata, inspection data, and selection resolution.

Named contract fixtures, each assigned to a milestone in SEQUENCE.md:

1. **Dirty-layer conflict:** disk changes and unsaved in-process changes coexist.
2. **Private-stage fidelity:** caller stage settings differ from defaults.
3. **Cached-stage isolation:** ambient stage reuse does not cross-contaminate bindings.
4. **Failed settings transition:** requested settings change; the published display remains old.
5. **Shared-material failure:** abort after preparing some material dependencies.
6. **Publication failure:** correspondence or inspection publication fails.
7. **Retirement failure:** the new display is active; obsolete resources remain tracked.
8. **Ownership ambiguity:** copied binding identities and missing resource tags.
9. **Unmanaged user of managed data:** refresh and removal preserve unrelated content.
10. **Detach with shared instance content:** a later refresh cannot mutate the detached result.
11. **Unavailable source and assets:** verifies the exact offline persistence promise.
12. **Nested instance plus shear plus appearance variation.**
13. **Texture edited in place:** no USD property changes.
14. **Same evaluated values at a different time:** no unnecessary display writes.
15. **Undo after partial external display damage.**
16. **No-op refresh:** stable counts and diagnostics; in Phase 1B, zero unnecessary writes.

For incremental synchronization:

- Compare results against a clean full rebuild.
- Separately assert that unaffected content was not unnecessarily rewritten.
- Check resource growth over repeated updates.
- Measure required interaction operations as well as synchronization (see [Interaction Testing](#interaction-testing) for what an interaction timing measures).

**Optimize the complete display-and-interaction workflow—not object count alone.**

## Acceptance Criteria

An acceptance specification records the fixture checksums, the sampled time-code set, and the bounds comparison contract. These criteria define what passing means. ALab is a representative fixture, not the sole definition of correctness; targeted semantic fixtures supplement it.

**ALab fixture:**

- ALab **v2.3.0** with techvar assets **v2.2.0**, opened through the primary `entry.usda` file.
- Record download checksums in the acceptance specification so the fixture is verifiable.
- ALab must pass **at any time code** and **under every payload policy** (load-all and load-no-payload).
- "Any time code" remains a behavioral guarantee; the sampled set is evidence, not exhaustive proof. It covers at least:
  - The stage's start and end time codes.
  - Interior samples, including a non-integer time code.
  - Selected authored sample times.
  - Samples around topology or visibility transitions, and midpoints between relevant samples.
  - Time codes before the start and after the end.
  - The USD default time code.
  - Deterministically seeded additional samples where practical.
- Run an inventory script for each payload policy that counts prim types, applied schemas, and shaders, including content inside native-instance prototypes together with its instance counts. Deferred content in ALab is then known in advance, and pass criteria are judged against the content that policy actually loads.

**Phase 1A pass criteria for ALab**, applied to every combination of sampled time code and payload policy:

- Synchronization completes without a fatal failure.
- Every supported mesh in that policy's inventory is accounted for in source/display correspondence, and its viewport and render participation match evaluated visibility and configured purpose inclusion.
- Deferred content types appear as placeholders or markers with aggregated diagnostics.
- World bounds of each model's display match USD-computed bounds under the bounds comparison contract.
- Geometry sharing is correct: expected uses reference the same geometry resource, required distinct geometry remains distinct, per-instance appearance does not force geometry copies, and separate bindings do not share or contaminate each other's resources. Unique mesh-data counts are recorded as an aggregate regression metric.
- An unchanged second synchronization adds no resources and produces an equivalent deduplicated diagnostic set.
- Save and reopen preserves the display and inspection state without accessing the source.
- Changing the time code or payload policy and resynchronizing gives the same result as a clean synchronization at the new settings.

**Bounds comparison contract.** The acceptance specification defines coordinate space (source or converted), the purpose set compared for viewport and render, treatment of invisible content, authored extent hints versus evaluated geometry bounds, treatment of placeholders and markers, subdivision approximation, displacement exclusions, absolute and relative tolerances, and empty or unknown bounds. Deferred content without usable bounds is excluded rather than compared against empty markers.

**Interior correctness.** Matching model bounds do not establish correctness inside a model. Targeted source-to-display checks and small semantic fixtures cover internal meshes, transforms within models, material assignments, UV selection, face winding, and per-instance appearance. Material fixtures use headless render assertions on controlled scenes, without requiring equivalence with USD renderers.

**Performance:**

- The reference hardware is an **M1 Max MacBook Pro**. The acceptance specification records its memory configuration, OS version, and Blender build.
- Record repeated-run statistics, not single timings.
- Measure separately: cold and warm source acquisition, evaluation, planning, Blender resource construction, publication and retirement, undo overhead, peak memory while old and new generations coexist, inspection-tree expansion, source-to-display lookup, selection and highlight updates, and framing calculations.
- Measure these scenarios: initial synchronization, unchanged manual refresh, single transform edit, shared geometry edit affecting many instances, single material parameter change, payload-policy switch, and topology-changing time step.
- P4 sets provisional budgets for comparing representations. Phase 1A records baselines on the reference hardware, not gates. Phase 1B targets are derived from those baselines (for example, "a single transform edit in ALab updates within a set time").
- Performance claims cover synchronization and interaction-function latency, not overall viewport responsiveness.

**Where it runs:** ALab runs as a manual or nightly job, not in ordinary CI. Ordinary CI uses a smaller generated fixture with similar structure: nested native instancing, multi-material assets, payloads, and deep organizational hierarchy.

## Decision Register

Milestones update this register when they settle a decision. High-risk guarantees are also traced in the requirement-to-test matrix created in P1.

| Decision | Owner | Chosen behavior / alternatives | Acceptance test |
|---|---|---|---|
| Dirty contributing layers on file-backed refresh | P3 | **Chosen:** fail with a source-access conflict. Rejected: evaluating in-process state with a divergence diagnostic. May upgrade to a private disk view if P1 proves it feasible. | Fixture 1 |
| Private disk view feasibility | P1 | Open. | P1 feasibility record |
| Stage-level state reproduced for in-memory sources | P3 | Open: muted layers, population mask, resolver context, interpolation, session-layer opinions. | Fixture 2 |
| In-memory source key contract | P3 | Open (see [Source Identity](#source-identity)). | P3 reattachment tests |
| Copied bindings | P3 | **Chosen:** disabled pending repair. Canonical-candidate rule open. Rejected: automatic new identity; treat as detached. | Fixture 8 |
| Browsing universe and inspection metadata set | P2 | Open. | P2 contract tests |
| Partition unit | P4 | Open. | P4 decision record |
| Post-publication retirement failure | P5 | **Chosen:** synchronization completes; leftovers tracked, noncanonical, retryable. | Fixture 7 |
| Undo for failed synchronizations | P5 | **Chosen:** no undo step; only the last-attempt record changes. | Fixture 4 |
| Undo memory cost | P5 | **Current:** one undo step per published synchronization. Clearing undo history is consistent but hostile to users. Revisit if measurements show unacceptable use. | P5 measurement |
| Interaction feasibility evidence | P4 | **Chosen:** headless functions only; viewport input assumptions recorded as risk. Rejected: manual viewport check. | P4, P12 headless suites |
| Primvar support matrix | P8 | Open; settled before P8 implementation. | P8 fixtures |
| Material connection grammar | P9 | Open; settled before P9 implementation. | P9 fixtures |
| Offline appearance | P9 | **Chosen:** geometry, materials, and inspection persist; textures stay external references. Rejected: packing assets; geometry-only promise. | Fixture 11 |
| Detach granularity and later refresh | P11 | **Chosen:** whole binding only; next refresh behaves like a first synchronization. Subtree detach deferred. | Fixture 10 |
| Bounds comparison contract and tolerances | P1 | Open; recorded in the acceptance specification. | ALab criteria |
| Churn budgets for replacement-affected resources | P13 | Open. | P14 qualification |
| Phase 1B performance targets | P13 | Open; derived from Phase 1A baselines. | P14 qualification |
