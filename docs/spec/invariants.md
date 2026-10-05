# Invariants

Cross-cutting guarantees that every milestone must preserve, whatever feature it is building. Each statement summarizes a requirement; **the linked section is authoritative** for details and edge cases. When a guarantee changes, update this file and the linked section in the same change. Terms are defined in the [Glossary](../PROJECT.md#glossary).

## Source Authority

- USD is authoritative. Synchronization never authors USD, saves or modifies source files, authors composition arcs or variant selections, or changes a caller's stage settings. → [Bindings and Source Access](source-access.md#bindings-and-source-access), [In-Memory Sources](source-access.md#in-memory-sources)
- Tools address USD entities through the source selection model, never by inferring USD structure from Blender parenting or names. → [Core Architecture](../PROJECT.md#core-architecture)
- Bindings never cross-contaminate each other's configuration, stage state, or resources. → [Bindings and Source Access](source-access.md#bindings-and-source-access)
- Synchronization is synchronous and non-reentrant. → [Source Consistency](source-access.md#source-consistency)
- A file-backed refresh fails with a source-access conflict if any contributing layer has unsaved in-process edits. It never discards those edits and never reuses a cached stage. Reloading clean shared layers is its only effect visible to other stages. → [File-Backed Refresh](source-access.md#file-backed-refresh)

## Layer Boundaries

- The evaluated snapshot contains no Blender datablock references, and its data cannot change during planning or application. → [Evaluated Source Snapshot](pipeline.md#evaluated-source-snapshot)
- Planning is deterministic over its three inputs: snapshot, binding settings, and planning context. → [Display Plan](pipeline.md#display-plan)
- Application never queries USD to resolve source semantics. → [Blender Application](pipeline.md#blender-application)
- All source-semantic diagnostics and known representation limitations exist before any Blender data is mutated. Application reports only resource-consumption, runtime, and state-change failures, and aborts unless the plan authorized a fallback; it never invents a semantic fallback. → [Why the Boundary Is Enforced](pipeline.md#why-the-boundary-is-enforced), [Blender Application](pipeline.md#blender-application)
- Every feature extends both evaluation/planning and application explicitly. → [Why the Boundary Is Enforced](pipeline.md#why-the-boundary-is-enforced)

## Synchronization Transaction

- A failure before publication leaves the entire published generation unchanged and leaves no untracked partial content. → [Synchronization Transaction](pipeline.md#synchronization-transaction)
- Preparation never mutates resources reachable from the published generation unless a complete rollback mechanism covers the mutation. → [Synchronization Transaction](pipeline.md#synchronization-transaction)
- Publication switches the whole generation together; there is never a silently mixed old/new result. → [Synchronization Transaction](pipeline.md#synchronization-transaction)
- Retirement failures after publication do not fail the synchronization; leftovers stay tracked, noncanonical, and retryable. → [Synchronization Transaction](pipeline.md#synchronization-transaction)
- Failed disposal before publication leaves inactive, persistent, retryable cleanup work; the attempt remains failed and the published generation is unchanged. → [Synchronization Transaction](pipeline.md#synchronization-transaction), [Pending Cleanup](lifecycle.md#pending-cleanup)
- These guarantees apply equally to Phase 2 incremental mutations. Undo grouping is not a substitute for them. → [Synchronization Transaction](pipeline.md#synchronization-transaction)

## Ownership

- Unrelated unmanaged content is never modified or deleted. → [Ownership and Lifecycle](lifecycle.md#ownership-and-lifecycle)
- A managed resource that unmanaged content uses is never mutated by refresh; it is replaced, and the old resource is released intact. → [Ownership and Lifecycle](lifecycle.md#ownership-and-lifecycle)
- Content without sufficient ownership evidence is treated as unmanaged. Ambiguous candidates and copied bindings are reported or disabled, never automatically claimed, merged, or deleted. → [Ownership and Lifecycle](lifecycle.md#ownership-and-lifecycle), [Copied Bindings](source-access.md#copied-bindings)
- Ownership uses durable identifiers, never Blender display names or object hierarchy, and never assumes custom properties are unique. Ownership, source coverage, representation role, and usage are recorded separately. → [Ownership and Lifecycle](lifecycle.md#ownership-and-lifecycle), [Copied Bindings](source-access.md#copied-bindings)
- Lifecycle operations preserve resources still required by other owners. → [Ownership and Lifecycle](lifecycle.md#ownership-and-lifecycle)
- Detach releases surviving content as-is, removing binding-specific metadata and controls without source reconstruction or required baking. Later refresh and cleanup preserve the detached result. → [Detach As-Is](lifecycle.md#detach-as-is)
- Lifecycle failures preserve pre-commit state or report committed partial progress with consistent ownership and persistent retry information; binding removal never orphans disposal work. → [Lifecycle Failure Safety](lifecycle.md#lifecycle-failure-safety)
- Repeated unchanged refreshes keep active display resources and source/display diagnostics stable. Disposal failures permit only inactive, tracked cleanup leftovers; successful cleanup restores managed-resource counts while preserving protected users. → [Resource Stability](lifecycle.md#resource-stability)

## Runtime State, Undo, and Persistence

- Runtime code never holds Blender datablock references across operator calls, including in indexes, UI caches, callbacks, queued work, and retained plans. Runtime indexes are disposable caches keyed by persistent identifiers and guarded by a generation counter. → [Undo and Runtime State](lifecycle.md#undo-and-runtime-state)
- All persistent state lives in Blender data. Requested settings, the published generation, the last attempt, and pending cleanup are logically distinct. → [Binding State](lifecycle.md#binding-state)
- Each synchronization that publishes is exactly one undo step; a failed synchronization pushes none. → [Undo and Runtime State](lifecycle.md#undo-and-runtime-state)
- Each lifecycle invocation that commits changes has one undo step, including partial progress; failures before commit have none. Undo/redo restores ownership and pending-cleanup tracking with content and binding state, subject to the global-undo/background-mode rules. → [Undo and Runtime State](lifecycle.md#undo-and-runtime-state)
- Reopening a `.blend` never synchronizes automatically. An unavailable source never erases the saved display or detaches the binding. → [Reopening](lifecycle.md#reopening)
- Unreadable or newer persistent schemas disable refresh and lifecycle operations for that binding, but preserve its display. → [Schema Versions](lifecycle.md#schema-versions)

## Diagnostics and Support

- Never pass unsafe invalid geometry into Blender, or silently present unsupported translation as exact. → [Diagnostics](pipeline.md#diagnostics)
- Deduplicate geometry wherever sharing preserves correct display; required distinct resources follow recorded, tested sharing criteria. → [Geometry Sharing](support/instancing.md#geometry-sharing)
- Every synchronization reports one result state (success, completed with issues, or fatal failure) derived from categorized diagnostics, aggregated without duplicates. → [Diagnostics](pipeline.md#diagnostics)
- Support is decided per behavior, not per prim type. One unsupported behavior never discards supported behavior or supported descendants. → [Models and Unsupported Content](support/visibility.md#models-and-unsupported-content)
- A USD time code is never assumed to be a Blender frame; synchronization never creates animation data or changes frame rate or playback range. → [Transforms and Time Codes](support/transforms.md#transforms-and-time-codes)
