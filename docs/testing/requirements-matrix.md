# Requirement-to-Test Matrix

Generated from [requirements.yaml](requirements.yaml) by `tools/matrix.py render`; do not edit.
Each row quotes the requirement it traces; the linked section is authoritative.
Kinds: **behavior** rows are checked by bespoke fixture tests; **contract** rows by the decision record
of the milestone that settles them; **process** rows by tooling or CI. A row without fixtures or oracle
is filled in by its delivering milestone before implementation.

266 rows: 197 behavior, 19 contract, 50 process; milestones started: M1, M1b.

## PROJECT.md

| ID | Requirement | Kind | Delivery | Phase / qualified by | Fixtures | Test or oracle |
|---|---|---|---|---|---|---|
| [ARCH-01](../PROJECT.md#core-architecture) | The USD hierarchy must remain accessible through source inspection | behavior | M7 | 1 / M12 | — | Set by M7. |
| [ARCH-04](../PROJECT.md#core-architecture) | Supported descendants must receive the correct ancestor state, including beneath unsupported ancestors. | behavior | M6 | 1 / M12 | — | Set by M6. |
| [ARCH-05](../PROJECT.md#core-architecture) | Source hierarchy and selection identities are independent of display partitioning. | behavior | M7 | 1 / M12 | — | Set by M7. |
| [ARCH-06](../PROJECT.md#core-architecture) | Tools address USD entities through the source selection model. | contract | M2 | 1 / M4 | — | Set by M2. |
| [ARCH-08](../PROJECT.md#core-architecture) | Keep the performance tests around for later | process | M4 | 1 / M14 | — | Set by M4. |
| [PH1-01](../PROJECT.md#phase-1--correct-snapshot-synchronization) | Manual refresh is required. | behavior | M12 | 1 / M12 | — | Set by M12. |
| [PH1-02](../PROJECT.md#phase-1--correct-snapshot-synchronization) | The acceptance suite must pass | process | M12 | 1 / M12 | — | Set by M12. |
| [PH2-02](../PROJECT.md#phase-2--incremental-synchronization) | Preserve source selections where their source identities remain valid. | behavior | M14 | 2 / M14 | — | Set by M14. |
| [PH2-03](../PROJECT.md#phase-2--incremental-synchronization) | Maintain sharing and reclaim obsolete managed resources without breaking sharing or other owners. | behavior | M14 | 2 / M14 | — | Set by M14. |
| [PH2-04](../PROJECT.md#phase-2--incremental-synchronization) | Establish and meet representative performance targets | behavior | M14 | 2 / M14 | — | Set by M14. |
| [COMP-01](../PROJECT.md#compatibility-and-development) | Minimum Blender version: 5.2 LTS. | process | M1 | 1 / M12 | — | The manifest's blender_version_min is 5.2.0 and the built zip validates (tools/build_extension.py). |
| [COMP-02](../PROJECT.md#compatibility-and-development) | Use the OpenUSD version bundled with the supported Blender distribution. | process | M1 | 1 / M12 | — | Smoke tests find pxr inside Blender's bundle, and the extension zip contains no pxr or other USD build. |
| [COMP-03](../PROJECT.md#compatibility-and-development) | Support macOS, Windows, and Linux. | process | M1 | 1 / M12 | — | CI runs the full suite, including binary smoke tests, on macOS, Windows, and Linux. |
| [COMP-04](../PROJECT.md#compatibility-and-development) | Prefer Python-only implementation. | contract | M1b | 1 / M1b | — | The M1b decision record (DECISIONS.md "Evaluation front end and core language" and "Python-only implementation"), backed by the end-to-end prototype's correctness results and separate measurements. |
| [COMP-06](../PROJECT.md#compatibility-and-development) | Compiled components link only against the OpenUSD libraries bundled with each supported Blender distribution. | process | M1b | 1 / M12 | — | Per platform, in the bpy wheel and the Blender binary: the build audit finds the module importing USD symbols only from Blender's usd_ms library, with no embedded search path and no bundled USD, TBB, or Python library; at run time exactly one usd_ms image is loaded, it is the host's own, and it is the image that provides USD symbols to the module. *Applies to the M1b bridge; a compiled core adopted by M1b inherits the checks.* |
## spec/pipeline.md

| ID | Requirement | Kind | Delivery | Phase / qualified by | Fixtures | Test or oracle |
|---|---|---|---|---|---|---|
| [SNAP-08](../spec/pipeline.md#evaluated-source-snapshot) | This model must not contain Blender datablock references. | behavior | M6 | 1 / M12 | — | Set by M6. |
| [SNAP-10](../spec/pipeline.md#evaluated-source-snapshot) | Snapshot data cannot change during planning or application. | behavior | M6 | 1 / M12 | — | Set by M6. |
| [SNAP-11](../spec/pipeline.md#evaluated-source-snapshot) | The snapshot keeps alive whatever storage it lends out, such as shared arrays. | behavior | M6 | 1 / M12 | — | Set by M6. |
| [SNAP-13](../spec/pipeline.md#evaluated-source-snapshot) | Application does not retain borrowed buffers beyond the synchronization that supplied them. | behavior | M7 | 1 / M12 | — | Set by M7. |
| [SNAP-16](../spec/pipeline.md#evaluated-source-snapshot) | Conversions made by Hydra filters, such as implicit surfaces or NURBS turned into meshes, are reported as approximations where inexact. | behavior | M6 | 1 / M12 | — | Set by M6. *Applies if M1b adopts Hydra. M1b's prototype checks the case but is not production code, so M6 delivers it.* |
| [SNAP-17](../spec/pipeline.md#evaluated-source-snapshot) | Hydra prim types the core does not translate | behavior | M6 | 1 / M12 | — | Set by M6. *Applies if M1b adopts Hydra. M1b's prototype checks the case but is not production code, so M6 delivers it.* |
| [PLAN-08](../spec/pipeline.md#display-plan) | Planning is deterministic: the same snapshot, binding settings, and planning context yield the same plan. | behavior | M6 | 1 / M12 | — | Set by M6. |
| [PLAN-09](../spec/pipeline.md#display-plan) | Anything planning depends on must arrive through one of its three inputs. | behavior | M6 | 1 / M12 | — | Set by M6. |
| [APP-05](../spec/pipeline.md#blender-application) | Report failures that only application can detect as diagnostics | behavior | M7 | 1 / M12 | — | Set by M7. |
| [APP-06](../spec/pipeline.md#blender-application) | When a resource fails during application, abort the transaction unless the plan already authorized a fallback for that resource. | behavior | M7 | 1 / M12 | — | Set by M7. |
| [APP-08](../spec/pipeline.md#blender-application) | Application must not query USD to fill in unresolved source semantics. | behavior | M7 | 1 / M12 | — | Set by M7. |
| [BND-01](../spec/pipeline.md#why-the-boundary-is-enforced) | Every feature extends both evaluation/planning and application explicitly. | process | M5 | 1 / M12 | — | Set by M5. |
| [BND-02](../spec/pipeline.md#why-the-boundary-is-enforced) | All source-semantic diagnostics and known representation limitations exist before any Blender data is mutated. | behavior | M5 | 1 / M12 | — | Set by M5. |
| [BND-03](../spec/pipeline.md#why-the-boundary-is-enforced) | A synchronization that fails for source reasons fails before touching the existing display. | behavior | M5 | 1 / M12 | `F-FAILED-SETTINGS` | Set by M5. |
| [TXN-02](../spec/pipeline.md#synchronization-transaction) | Before publication, any failure preserves the previous published generation unchanged and attempts to dispose of prepared work. | behavior | M5 | 1 / M12 | `F-FAILED-SETTINGS`, `F-PUBLICATION-FAILURE`, `F-SHARED-MATERIAL-FAILURE` | Set by M5. |
| [TXN-03](../spec/pipeline.md#synchronization-transaction) | Failed disposal leaves leftovers persistently tracked as pending cleanup | behavior | M5 | 1 / M12 | `F-PREPARATION-CLEANUP-FAILURE` | Set by M5. |
| [TXN-04](../spec/pipeline.md#synchronization-transaction) | For a first synchronization, no untracked partial content remains. | behavior | M5 | 1 / M12 | `F-PUBLICATION-FAILURE`, `F-PREPARATION-CLEANUP-FAILURE` | Set by M5. |
| [TXN-05](../spec/pipeline.md#synchronization-transaction) | Preparation never mutates resources reachable from the published generation unless a complete rollback mechanism covers the mutation. | behavior | M5 | 1 / M12 | `F-SHARED-MATERIAL-FAILURE` | Set by M5. |
| [TXN-06](../spec/pipeline.md#synchronization-transaction) | Publication switches the whole generation together | behavior | M5 | 1 / M12 | `F-PUBLICATION-FAILURE` | Set by M5. |
| [TXN-07](../spec/pipeline.md#synchronization-transaction) | After publication, retirement failures do not fail the synchronization. | behavior | M5 | 1 / M12 | `F-RETIREMENT-FAILURE` | Set by M5. |
| [TXN-08](../spec/pipeline.md#synchronization-transaction) | Ownership tracking covers newly created prepared resources before subsequent fallible work | behavior | M5 | 1 / M12 | `F-PREPARATION-CLEANUP-FAILURE` | Set by M5. |
| [TXN-09](../spec/pipeline.md#synchronization-transaction) | Reused published resources remain protected by the existing manifest and are never disposal candidates. | behavior | M5 | 1 / M12 | `F-PREPARATION-CLEANUP-FAILURE` | Set by M5. |
| [TXN-10](../spec/pipeline.md#synchronization-transaction) | Deferred disposal does not permit failed preparation to become visible or substitute for restoring any mutated published state. | behavior | M5 | 1 / M12 | `F-PREPARATION-CLEANUP-FAILURE` | Set by M5. |
| [TXN-12](../spec/pipeline.md#synchronization-transaction) | These guarantees apply equally to incremental mutations in Phase 2. | behavior | M14 | 2 / M14 | — | Set by M14. |
| [DIAG-01](../spec/pipeline.md#diagnostics) | Unsupported valid content. | behavior | M5 | 1 / M12 | — | Set by M5. |
| [DIAG-02](../spec/pipeline.md#diagnostics) | Include binding, source path, property/asset identifier, severity, and fallback where applicable. | behavior | M5 | 1 / M12 | — | Set by M5. |
| [DIAG-03](../spec/pipeline.md#diagnostics) | Aggregate repeated problems. | behavior | M5 | 1 / M12 | — | Set by M5. |
| [DIAG-04](../spec/pipeline.md#diagnostics) | Source/display diagnostics belong to a published generation or to the last attempt and are kept separate from any attempt history. | behavior | M5 | 1 / M12 | `F-FAILED-SETTINGS` | Set by M5. |
| [DIAG-05](../spec/pipeline.md#diagnostics) | Unresolved cleanup diagnostics also persist with pending-cleanup ownership information, so a later attempt cannot erase pending work. | behavior | M5 | 1 / M12 | `F-PREPARATION-CLEANUP-FAILURE` | Set by M5. |
| [DIAG-06](../spec/pipeline.md#diagnostics) | Report current cleanup status separately from historical attempt results and deduplicate by operation and resource. | behavior | M5 | 1 / M12 | `F-PREPARATION-CLEANUP-FAILURE`, `F-RETIREMENT-FAILURE` | Set by M5. |
| [DIAG-07](../spec/pipeline.md#diagnostics) | An unchanged refresh produces equivalent deduplicated source/display diagnostics. | behavior | M5 | 1 / M12 | `F-NO-OP-REFRESH` | Set by M5. |
| [DIAG-08](../spec/pipeline.md#diagnostics) | resolved cleanup diagnostics are removed rather than accumulated as history. | behavior | M5 | 1 / M12 | `F-PREPARATION-CLEANUP-FAILURE` | Set by M5. |
| [DIAG-09](../spec/pipeline.md#diagnostics) | Success: no diagnostics in any category. | behavior | M5 | 1 / M12 | — | Set by M5. |
| [DIAG-10](../spec/pipeline.md#diagnostics) | Completed with issues: at least one unsupported, approximation, lossy-conversion, missing-dependency, invalid-data, or pending-cleanup diagnostic, but no fatal failure. | behavior | M5 | 1 / M12 | — | Set by M5. |
| [DIAG-11](../spec/pipeline.md#diagnostics) | Fatal failure, including a source-access conflict. | behavior | M5 | 1 / M12 | `F-DIRTY-LAYER` | Set by M5. |
| [DIAG-13](../spec/pipeline.md#diagnostics) | Never pass unsafe invalid geometry into Blender or silently present unsupported translation as exact. | behavior | M8 | 1 / M12 | — | Set by M8. |
## spec/source-access.md

| ID | Requirement | Kind | Delivery | Phase / qualified by | Fixtures | Test or oracle |
|---|---|---|---|---|---|---|
| [BIND-02](../spec/source-access.md#bindings-and-source-access) | Root-layer files: .usd, .usda, .usdc. | behavior | M3 | 1 / M12 | — | Set by M3. |
| [BIND-03](../spec/source-access.md#bindings-and-source-access) | Caller-supplied in-memory stages without requiring file reopening. | behavior | M3 | 2 / M14 | — | Set by M3. |
| [BIND-04](../spec/source-access.md#bindings-and-source-access) | Load-all or load-no-payload policy. | behavior | M3 | 1 / M12 | — | Set by M3. |
| [BIND-05](../spec/source-access.md#bindings-and-source-access) | Explicit evaluation time code, including the USD default time code. | behavior | M3 | 1 / M12 | — | Set by M3. |
| [BIND-06](../spec/source-access.md#bindings-and-source-access) | Coordinate-conversion and purpose/display settings. | behavior | M3 | 1 / M12 | — | Set by M3. |
| [BIND-07](../spec/source-access.md#bindings-and-source-access) | Multiple independent bindings, including bindings using the same source. | behavior | M3 | 1 / M12 | — | Set by M3. |
| [BIND-08](../spec/source-access.md#bindings-and-source-access) | The default scope is the entire available stage. | behavior | M3 | 1 / M12 | — | Set by M3. |
| [BIND-09](../spec/source-access.md#bindings-and-source-access) | Consume existing composition and variant selections. Do not author composition arcs or variant selections. | behavior | M3 | 1 / M12 | — | Set by M3. |
| [BIND-10](../spec/source-access.md#bindings-and-source-access) | Binding configuration must not cross-contaminate other bindings. | behavior | M3 | 1 / M12 | — | Set by M3. |
| [CONS-01](../spec/source-access.md#source-consistency) | Synchronization is synchronous and non-reentrant. | behavior | M5 | 1 / M12 | — | Set by M5. |
| [CONS-03](../spec/source-access.md#source-consistency) | Where a source change during evaluation can be detected, the attempt is discarded before publication. | behavior | M3 | 1 / M12 | — | Set by M3. |
| [SID-02](../spec/source-access.md#source-identity) | Its uniqueness scope. | contract | M3 | 2 / M3 | — | Set by M3. |
| [COPY-01](../spec/source-access.md#copied-bindings) | do not assume they guarantee uniqueness. | behavior | M3 | 1 / M12 | `F-OWNERSHIP-AMBIGUITY` | Set by M3. |
| [COPY-02](../spec/source-access.md#copied-bindings) | A binding whose identity is not unique is disabled pending repair | behavior | M3 | 1 / M12 | `F-OWNERSHIP-AMBIGUITY` | Set by M3. |
| [COPY-03](../spec/source-access.md#copied-bindings) | A deterministic, documented rule decides which candidate remains canonical. If the rule cannot decide, all candidates are disabled. | behavior | M3 | 1 / M12 | `F-OWNERSHIP-AMBIGUITY` | Set by M3. |
| [COPY-04](../spec/source-access.md#copied-bindings) | Copies are never automatically claimed, merged, or deleted. | behavior | M3 | 1 / M12 | `F-OWNERSHIP-AMBIGUITY` | Set by M3. |
| [COPY-05](../spec/source-access.md#copied-bindings) | until the user makes it a new binding or detaches it. | behavior | M11 | 1 / M12 | `F-OWNERSHIP-AMBIGUITY` | Set by M11. |
| [MEM-01](../spec/source-access.md#in-memory-sources) | Do not author changes to a caller-supplied stage's layers or change its stage settings | behavior | M3 | 2 / M14 | `F-PRIVATE-STAGE` | Set by M3. |
| [MEM-02](../spec/source-access.md#in-memory-sources) | Evaluate the caller's composed content as the caller's stage presents it, except that the binding's payload policy replaces the caller's load rules. | behavior | M3 | 2 / M14 | `F-PRIVATE-STAGE` | Set by M3. |
| [MEM-03](../spec/source-access.md#in-memory-sources) | M3 settles how each piece of stage-level state is reproduced | contract | M3 | 2 / M3 | `F-PRIVATE-STAGE` | Set by M3. |
| [MEM-04](../spec/source-access.md#in-memory-sources) | Multiple bindings on the same in-memory source may use different payload policies without affecting each other or the caller. | behavior | M3 | 2 / M14 | `F-PRIVATE-STAGE` | Set by M3. |
| [MEM-05](../spec/source-access.md#in-memory-sources) | If the caller releases the attached stage, the binding becomes unattached. | behavior | M3 | 2 / M14 | — | Set by M3. |
| [MEM-06](../spec/source-access.md#in-memory-sources) | After a .blend is reopened, an in-memory binding reports its source as unavailable until the caller attaches a stage. | behavior | M3 | 2 / M14 | — | Set by M3. |
| [FILE-01](../spec/source-access.md#file-backed-refresh) | A file-backed refresh displays the source as it exists on disk. | behavior | M3 | 1 / M12 | `F-DIRTY-LAYER` | Set by M3. |
| [FILE-02](../spec/source-access.md#file-backed-refresh) | Refresh must not discard unsaved in-process edits made by other tools to layers it shares. | behavior | M3 | 1 / M12 | `F-DIRTY-LAYER` | Set by M3. |
| [FILE-03](../spec/source-access.md#file-backed-refresh) | If any contributing layer has unsaved in-process edits, refresh fails with a source-access conflict naming those layers and preserves the previous display. | behavior | M3 | 1 / M12 | `F-DIRTY-LAYER` | Set by M3. |
| [FILE-04](../spec/source-access.md#file-backed-refresh) | Refresh does not reuse a cached stage or otherwise share stage state with other bindings. | behavior | M3 | 1 / M12 | `F-CACHED-STAGE` | Set by M3. |
| [FILE-05](../spec/source-access.md#file-backed-refresh) | Refresh may reload clean shared layers from disk. Other stages using those layers then see the current disk content. This is the only effect synchronization may have that other stages can observe. | behavior | M3 | 1 / M12 | `F-CACHED-STAGE`, `F-DIRTY-LAYER` | Set by M3. |
## spec/lifecycle.md

| ID | Requirement | Kind | Delivery | Phase / qualified by | Fixtures | Test or oracle |
|---|---|---|---|---|---|---|
| [OWN-01](../spec/lifecycle.md#ownership-and-lifecycle) | Keep these concepts separate in ownership records: | contract | M3 | 1 / M3 | — | Set by M3. |
| [OWN-04](../spec/lifecycle.md#ownership-and-lifecycle) | Renaming does not detach content. | behavior | M11 | 1 / M12 | — | Set by M11. |
| [OWN-05](../spec/lifecycle.md#ownership-and-lifecycle) | Deleting managed content does not delete its source; refresh restores required display content. | behavior | M11 | 1 / M12 | — | Set by M11. |
| [OWN-06](../spec/lifecycle.md#ownership-and-lifecycle) | Additional collection links do not detach managed content. | behavior | M11 | 1 / M12 | — | Set by M11. |
| [OWN-07](../spec/lifecycle.md#ownership-and-lifecycle) | Unrelated unmanaged content must not be modified or deleted. | behavior | M7 | 1 / M12 | `F-UNMANAGED-USER` | Set by M7. |
| [OWN-08](../spec/lifecycle.md#ownership-and-lifecycle) | Refresh does not mutate a managed resource that unmanaged content uses. | behavior | M7 | 1 / M12 | `F-UNMANAGED-USER` | Set by M7. |
| [OWN-09](../spec/lifecycle.md#ownership-and-lifecycle) | Content without sufficient ownership evidence is treated as unmanaged. Ambiguous candidates are reported, not automatically claimed or deleted. | behavior | M11 | 1 / M12 | `F-OWNERSHIP-AMBIGUITY` | Set by M11. |
| [OWN-10](../spec/lifecycle.md#ownership-and-lifecycle) | Successful refresh removes stale content and accidental duplicate canonical representations. | behavior | M11 | 1 / M12 | — | Set by M11. |
| [OWN-12](../spec/lifecycle.md#ownership-and-lifecycle) | Cleanup: remove duplicate or obsolete managed content and unused exclusively owned resources | behavior | M11 | 1 / M12 | `F-LIFECYCLE-FAILURE` | Set by M11. |
| [OWN-13](../spec/lifecycle.md#ownership-and-lifecycle) | Detach: release a whole binding's surviving managed content as-is into unmanaged Blender content | behavior | M11 | 1 / M12 | `F-DETACH-AS-IS`, `F-DETACH-SHARED` | Set by M11. |
| [OWN-14](../spec/lifecycle.md#ownership-and-lifecycle) | Remove binding: remove configuration and managed content while preserving detached and unrelated content. | behavior | M11 | 1 / M12 | `F-LIFECYCLE-FAILURE`, `F-UNMANAGED-USER` | Set by M11. |
| [OWN-15](../spec/lifecycle.md#ownership-and-lifecycle) | Lifecycle operations must preserve resources still required by other owners | behavior | M11 | 1 / M12 | `F-DETACH-SHARED`, `F-UNMANAGED-USER` | Set by M11. |
| [STAB-01](../spec/lifecycle.md#resource-stability) | Count active display resources and inactive pending-cleanup resources separately. | behavior | M7 | 1 / M12 | `F-NO-OP-REFRESH` | Set by M7. |
| [STAB-02](../spec/lifecycle.md#resource-stability) | Disposal failures may retain additional resources only as inactive, persistently tracked pending cleanup with ownership evidence. | behavior | M7 | 1 / M12 | `F-NO-OP-REFRESH`, `F-RETIREMENT-FAILURE` | Set by M7. |
| [STAB-03](../spec/lifecycle.md#resource-stability) | explicit cleanup retry must restore managed-resource counts to the clean baseline | behavior | M7 | 1 / M12 | `F-NO-OP-REFRESH`, `F-PREPARATION-CLEANUP-FAILURE` | Set by M7. |
| [STAB-04](../spec/lifecycle.md#resource-stability) | Resources that must be released intact to protect detached or external users are accounted for separately | behavior | M7 | 1 / M12 | `F-NO-OP-REFRESH`, `F-UNMANAGED-USER` | Set by M7. |
| [DET-01](../spec/lifecycle.md#detach-as-is) | Detach operates on the surviving Blender content at the time of the operation, including Blender-side edits and existing damage. | behavior | M11 | 1 / M12 | `F-DETACH-AS-IS` | Set by M11. |
| [DET-02](../spec/lifecycle.md#detach-as-is) | Remove the binding's ownership tags, source correspondence and selection associations, and binding-specific runtime controls, callbacks, and display helpers. | behavior | M11 | 1 / M12 | `F-DETACH-AS-IS` | Set by M11. |
| [DET-03](../spec/lifecycle.md#detach-as-is) | Keep ordinary geometry, transforms, materials, collection links, and Blender dependencies | behavior | M11 | 1 / M12 | `F-DETACH-AS-IS` | Set by M11. |
| [DET-04](../spec/lifecycle.md#detach-as-is) | Changes in appearance caused by removing binding-specific mechanisms are permitted and reported | behavior | M11 | 1 / M12 | `F-DETACH-AS-IS` | Set by M11. |
| [DET-05](../spec/lifecycle.md#detach-as-is) | Later refresh or removal must not mutate or delete the detached result. | behavior | M11 | 1 / M12 | `F-DETACH-AS-IS`, `F-DETACH-SHARED` | Set by M11. |
| [DET-06](../spec/lifecycle.md#detach-as-is) | Release this binding's surviving pending-cleanup resources intact as well | behavior | M11 | 1 / M12 | `F-DETACH-AS-IS` | Set by M11. |
| [LFS-01](../spec/lifecycle.md#lifecycle-failure-safety) | Lifecycle operations do not access USD and report success, completed with issues, or failure, distinguishing committed changes from work still pending. | behavior | M11 | 1 / M12 | `F-LIFECYCLE-FAILURE` | Set by M11. |
| [LFS-02](../spec/lifecycle.md#lifecycle-failure-safety) | Detach: release ownership, remove binding-specific controls and associations, and clear the published generation as one logical commit. | behavior | M11 | 1 / M12 | `F-LIFECYCLE-FAILURE` | Set by M11. |
| [LFS-03](../spec/lifecycle.md#lifecycle-failure-safety) | Cleanup: completed disposals may remain committed if a later disposal fails. | behavior | M11 | 1 / M12 | `F-LIFECYCLE-FAILURE` | Set by M11. |
| [LFS-04](../spec/lifecycle.md#lifecycle-failure-safety) | Remove binding: preserve detached and unrelated content. | behavior | M11 | 1 / M12 | `F-LIFECYCLE-FAILURE` | Set by M11. |
| [LFS-05](../spec/lifecycle.md#lifecycle-failure-safety) | M11 settles staging and rollback mechanisms, commit points | contract | M11 | 1 / M11 | `F-LIFECYCLE-FAILURE` | Set by M11. |
| [UNDO-01](../spec/lifecycle.md#undo-and-runtime-state) | All persistent state (see Binding State) lives in Blender data | behavior | M5 | 1 / M12 | — | Set by M5. |
| [UNDO-02](../spec/lifecycle.md#undo-and-runtime-state) | Each synchronization that publishes is exactly one undo step. | behavior | M5 | 1 / M12 | — | Set by M5. |
| [UNDO-03](../spec/lifecycle.md#undo-and-runtime-state) | A failed synchronization pushes no undo step. | behavior | M5 | 1 / M12 | `F-FAILED-SETTINGS`, `F-PREPARATION-CLEANUP-FAILURE` | Set by M5. |
| [UNDO-04](../spec/lifecycle.md#undo-and-runtime-state) | With global undo disabled or in background mode, synchronization behaves the same but pushes no step. | behavior | M5 | 1 / M12 | — | Set by M5. |
| [UNDO-05](../spec/lifecycle.md#undo-and-runtime-state) | When undo/redo restores an earlier display, mark the binding as possibly out of date relative to its source. | behavior | M5 | 1 / M12 | — | Set by M5. |
| [UNDO-06](../spec/lifecycle.md#undo-and-runtime-state) | In-memory stage attachments are runtime associations keyed by binding identity. | behavior | M3 | 2 / M14 | — | Set by M3. |
| [UNDO-07](../spec/lifecycle.md#undo-and-runtime-state) | Runtime code must not hold Blender datablock references across operator calls. | behavior | M3 | 1 / M12 | — | Set by M3. |
| [UNDO-08](../spec/lifecycle.md#undo-and-runtime-state) | Detach, cleanup, and binding removal must support undo/redo | behavior | M11 | 1 / M12 | `F-LIFECYCLE-FAILURE`, `F-UNDO-AFTER-DAMAGE` | Set by M11. |
| [STATE-01](../spec/lifecycle.md#binding-state) | Binding configuration \| Binding identity, source information, destination, target scene, and requested settings | behavior | M3 | 1 / M12 | — | Set by M3. |
| [STATE-02](../spec/lifecycle.md#binding-state) | Published generation \| Display resources, inspection snapshot, correspondence, ownership manifest | behavior | M5 | 1 / M12 | `F-FAILED-SETTINGS` | Set by M5. |
| [STATE-03](../spec/lifecycle.md#binding-state) | Last attempt \| Settings attempted, result state, and diagnostics | behavior | M5 | 1 / M12 | `F-FAILED-SETTINGS` | Set by M5. |
| [STATE-04](../spec/lifecycle.md#binding-state) | Pending cleanup \| Unresolved prepared or obsolete resources, ownership evidence | behavior | M5 | 1 / M12 | `F-PREPARATION-CLEANUP-FAILURE` | Set by M5. |
| [STATE-07](../spec/lifecycle.md#binding-state) | A binding can therefore report, for example: requested time 20 with load-none, displayed time 10 with load-all, last attempt failed. | behavior | M12 | 1 / M12 | `F-FAILED-SETTINGS` | Set by M12. |
| [PEND-01](../spec/lifecycle.md#pending-cleanup) | Persist sufficient ownership information to retry disposal of newly prepared or obsolete resources safely. | behavior | M5 | 1 / M12 | `F-PREPARATION-CLEANUP-FAILURE` | Set by M5. |
| [PEND-02](../spec/lifecycle.md#pending-cleanup) | Retries revalidate ownership and current users | behavior | M5 | 1 / M12 | `F-PREPARATION-CLEANUP-FAILURE`, `F-UNMANAGED-USER` | Set by M5. |
| [PEND-03](../spec/lifecycle.md#pending-cleanup) | Remove resolved tracking and current cleanup diagnostics rather than accumulating history. | behavior | M5 | 1 / M12 | `F-PREPARATION-CLEANUP-FAILURE` | Set by M5. |
| [PEND-04](../spec/lifecycle.md#pending-cleanup) | Unresolved work remains inactive; retries are explicit and do not require USD access. | behavior | M5 | 1 / M12 | `F-PREPARATION-CLEANUP-FAILURE` | Set by M5. |
| [PEND-05](../spec/lifecycle.md#pending-cleanup) | Undo/redo restores cleanup tracking consistently with resource ownership. | behavior | M5 | 1 / M12 | `F-PREPARATION-CLEANUP-FAILURE` | Set by M5. |
| [PEND-06](../spec/lifecycle.md#pending-cleanup) | M3 defines the persistence contract; M5 chooses and validates the mechanism | contract | M5 | 1 / M5 | `F-PREPARATION-CLEANUP-FAILURE` | Set by M5. |
| [PEND-07](../spec/lifecycle.md#pending-cleanup) | removing configuration must not orphan pending work. | behavior | M11 | 1 / M12 | `F-LIFECYCLE-FAILURE` | Set by M11. |
| [REOPEN-01](../spec/lifecycle.md#reopening) | Restore metadata, pending-cleanup tracking, and indexes. Do not automatically retry cleanup. | behavior | M3 | 1 / M12 | `F-PREPARATION-CLEANUP-FAILURE` | Set by M3. |
| [REOPEN-02](../spec/lifecycle.md#reopening) | Do not automatically synchronize. | behavior | M3 | 1 / M12 | — | Set by M3. |
| [REOPEN-04](../spec/lifecycle.md#reopening) | An unavailable source must not erase the saved representation. | behavior | M3 | 1 / M12 | `F-OFFLINE` | Set by M3. |
| [REOPEN-05](../spec/lifecycle.md#reopening) | Source unavailability must not automatically detach the binding. | behavior | M3 | 1 / M12 | `F-OFFLINE` | Set by M3. |
| [REOPEN-06](../spec/lifecycle.md#reopening) | Detached content remains detached. | behavior | M11 | 1 / M12 | `F-DETACH-AS-IS` | Set by M11. |
| [REOPEN-07](../spec/lifecycle.md#reopening) | The saved display remains usable without its USD source | behavior | M3 | 1 / M12 | `F-OFFLINE` | Set by M3. |
| [REOPEN-08](../spec/lifecycle.md#reopening) | Image textures remain references to external files | behavior | M9 | 1 / M12 | `F-OFFLINE` | Set by M9. |
| [SCHEMA-02](../spec/lifecycle.md#schema-versions) | Older supported schemas migrate on load. | behavior | M3 | 1 / M12 | — | Set by M3. |
| [SCHEMA-03](../spec/lifecycle.md#schema-versions) | If migration fails or the schema is newer than the extension supports | behavior | M3 | 1 / M12 | — | Set by M3. |
| [SCHEMA-04](../spec/lifecycle.md#schema-versions) | Unreadable or unsupported pending-cleanup records are preserved and never authorize disposal. | behavior | M3 | 1 / M12 | — | Set by M3. |
| [SCHEMA-05](../spec/lifecycle.md#schema-versions) | Without the extension installed, the saved display remains ordinary Blender content. | behavior | M3 | 1 / M12 | `F-OFFLINE` | Set by M3. |
## spec/interaction.md

| ID | Requirement | Kind | Delivery | Phase / qualified by | Fixtures | Test or oracle |
|---|---|---|---|---|---|---|
| [INSP-01](../spec/interaction.md#source-inspection-and-interaction) | Display selection resolves to a binding and source entity, including instance context where applicable. | behavior | M7 | 1 / M12 | — | Set by M7. |
| [INSP-02](../spec/interaction.md#source-inspection-and-interaction) | Source selection of a prim or subtree resolves to its associated display elements. | behavior | M7 | 1 / M12 | — | Set by M7. |
| [INSP-03](../spec/interaction.md#source-inspection-and-interaction) | Source inspection works independently of Blender parenting. | behavior | M7 | 1 / M12 | — | Set by M7. |
| [INSP-04](../spec/interaction.md#source-inspection-and-interaction) | Native instance roots are selectable and source-identifiable. | behavior | M10 | 1 / M12 | — | Set by M10. |
| [INSP-05](../spec/interaction.md#source-inspection-and-interaction) | Source correspondence survives any batching, reordering, or geometry partitioning. | behavior | M8 | 1 / M12 | — | Set by M8. |
| [INSP-06](../spec/interaction.md#source-inspection-and-interaction) | The browsing universe: which of the populated composed hierarchy | contract | M2 | 1 / M4 | — | Set by M2. |
| [INSP-08](../spec/interaction.md#source-inspection-and-interaction) | Persist enough inspection and correspondence information to inspect the saved display without accessing an unavailable source. | behavior | M7 | 1 / M12 | `F-OFFLINE` | Set by M7. |
| [INSP-09](../spec/interaction.md#source-inspection-and-interaction) | Distinguish the last synchronized snapshot from newly evaluated source state. | behavior | M7 | 1 / M12 | — | Set by M7. |
| [ITEST-02](../spec/interaction.md#interaction-testing) | Interaction feasibility and qualification are claimed at the level of these headless functions | contract | M2 | 1 / M4 | — | Set by M2. |
## spec/incremental.md

| ID | Requirement | Kind | Delivery | Phase / qualified by | Fixtures | Test or oracle |
|---|---|---|---|---|---|---|
| [DISC-01](../spec/incremental.md#change-discovery) | File-backed manual refresh. | behavior | M13 | 2 / M14 | — | Set by M13. |
| [DISC-02](../spec/incremental.md#change-discovery) | Prim existence, activation, type, hierarchy, and variants. | behavior | M13 | 2 / M14 | — | Set by M13. |
| [DISC-03](../spec/incremental.md#change-discovery) | including external assets changed without any USD edit. | behavior | M13 | 2 / M14 | `F-TEXTURE-IN-PLACE` | Set by M13. |
| [DISC-04](../spec/incremental.md#change-discovery) | including time changes that do not alter evaluated values. | behavior | M13 | 2 / M14 | `F-SAME-VALUES` | Set by M13. |
| [DISC-05](../spec/incremental.md#change-discovery) | Managed Blender content requiring repair, distinguished from legitimate external users of managed resources. | behavior | M13 | 2 / M14 | `F-UNMANAGED-USER` | Set by M13. |
| [DISC-06](../spec/incremental.md#change-discovery) | Separate change discovery from dependency invalidation. | behavior | M13 | 2 / M14 | — | Set by M13. |
| [DISC-07](../spec/incremental.md#change-discovery) | Recover correctly from missed or coalesced change notifications. | behavior | M13 | 2 / M14 | — | Set by M13. |
| [DISC-08](../spec/incremental.md#change-discovery) | Editor-provided change descriptions may be hints, but are not the sole correctness mechanism. | behavior | M13 | 2 / M14 | — | Set by M13. |
| [AFF-01](../spec/incremental.md#affected-content) | Source-affected entities: source state actually changed. | behavior | M13 | 2 / M14 | — | Set by M13. |
| [AFF-02](../spec/incremental.md#affected-content) | Level 3 is permitted but bounded by churn and performance budgets | behavior | M13 | 2 / M14 | — | Set by M13. |
| [AFF-03](../spec/incremental.md#affected-content) | Untouched resources keep stable identities, and a no-op refresh performs no unnecessary Blender writes. | behavior | M14 | 2 / M14 | `F-NO-OP-REFRESH` | Set by M14. |
## spec/support/transforms.md

| ID | Requirement | Kind | Delivery | Phase / qualified by | Fixtures | Test or oracle |
|---|---|---|---|---|---|---|
| [XFORM-01](../spec/support/transforms.md#transforms-and-time-codes) | Evaluate ordered transform operations, reset-transform-stack behavior, and transforms authored on meshes. | behavior | M6 | 1 / M12 | — | Set by M6. |
| [XFORM-02](../spec/support/transforms.md#transforms-and-time-codes) | Reconcile organizational relationships with reset-transform-stack behavior without requiring equivalent Blender parenting. | behavior | M6 | 1 / M12 | — | Set by M6. |
| [XFORM-03](../spec/support/transforms.md#transforms-and-time-codes) | Support matrix transforms, negative and nonuniform scale, and shear. | behavior | M6 | 1 / M12 | `F-NESTED-STRESS` | Set by M6. |
| [XFORM-05](../spec/support/transforms.md#transforms-and-time-codes) | Diagnose approximations when exact representation is unavailable. | behavior | M6 | 1 / M12 | — | Set by M6. |
| [XFORM-06](../spec/support/transforms.md#transforms-and-time-codes) | Evaluate supported time-varying values at the supplied time code, including topology changes. | behavior | M6 | 1 / M12 | — | Set by M6. |
| [XFORM-07](../spec/support/transforms.md#transforms-and-time-codes) | including topology changes. | behavior | M8 | 1 / M12 | — | Set by M8. |
| [XFORM-08](../spec/support/transforms.md#transforms-and-time-codes) | This is permitted, not preferred: M4 decides whether and where it is used, and records the time-code-to-frame mapping it uses. | contract | M4 | 1 / M4 | — | Set by M4. |
| [XFORM-09](../spec/support/transforms.md#transforms-and-time-codes) | Authored animation data and its caches are managed content | behavior | M7 | 1 / M12 | — | Set by M7. *Applies if M4 adopts animation data.* |
| [XFORM-10](../spec/support/transforms.md#transforms-and-time-codes) | Do not change the target scene's frame rate or playback range. | behavior | M7 | 1 / M12 | — | Set by M7. |
| [CONV-01](../spec/support/transforms.md#coordinate-conversion) | Units/up-axis conversion is configurable and disabled by default. When disabled, the correction matrix is the identity. | behavior | M6 | 1 / M12 | — | Set by M6. |
| [CONV-02](../spec/support/transforms.md#coordinate-conversion) | Enabled conversion respects the target scene's unit scale without changing scene settings. | behavior | M7 | 1 / M12 | — | Set by M7. |
| [CONV-03](../spec/support/transforms.md#coordinate-conversion) | Converted results are consistent for geometry, transforms, bounds, and instances. | behavior | M6 | 1 / M12 | — | Set by M6. |
| [CONV-07](../spec/support/transforms.md#coordinate-conversion) | If the destination collection is linked into a scene whose unit scale differs from the target scene's, diagnose the mismatch rather than guessing. | behavior | M7 | 1 / M12 | — | Set by M7. |
| [CONV-08](../spec/support/transforms.md#coordinate-conversion) | scale = stage.metersPerUnit / target_scene.unit_settings.scale_length | behavior | M6 | 1 / M12 | — | Set by M6. |
## spec/support/geometry.md

| ID | Requirement | Kind | Delivery | Phase / qualified by | Fixtures | Test or oracle |
|---|---|---|---|---|---|---|
| [GEOM-01](../spec/support/geometry.md#supported-geometry) | Validated polygon topology and point positions. | behavior | M8 | 1 / M12 | — | Set by M8. |
| [GEOM-02](../spec/support/geometry.md#supported-geometry) | Authored normals and a documented generation fallback. | behavior | M8 | 1 / M12 | — | Set by M8. |
| [GEOM-03](../spec/support/geometry.md#supported-geometry) | Orientation/winding and documented double-sidedness behavior. | behavior | M8 | 1 / M12 | — | Set by M8. |
| [GEOM-04](../spec/support/geometry.md#supported-geometry) | Supported UV sets with their names and meaningful domains. | behavior | M8 | 1 / M12 | — | Set by M8. |
| [GEOM-05](../spec/support/geometry.md#supported-geometry) | displayColor and displayOpacity. | behavior | M8 | 1 / M12 | — | Set by M8. |
| [GEOM-06](../spec/support/geometry.md#supported-geometry) | Supported arbitrary primvars converted into native float, color, and vector attributes. | behavior | M8 | 1 / M12 | — | Set by M8. |
| [GEOM-07](../spec/support/geometry.md#supported-geometry) | Indexed and inherited primvars, and supported domain conversions. | behavior | M8 | 1 / M12 | — | Set by M8. |
| [GEOM-08](../spec/support/geometry.md#supported-geometry) | Face-level material assignments. | behavior | M8 | 1 / M12 | — | Set by M8. |
| [GEOM-09](../spec/support/geometry.md#supported-geometry) | Approximate subdivision, edge creases, and corner sharpness. | behavior | M8 | 1 / M12 | — | Set by M8. |
| [GEOM-10](../spec/support/geometry.md#supported-geometry) | Topology-changing snapshots, discarding obsolete topology-dependent data. | behavior | M8 | 1 / M12 | — | Set by M8. |
| [GEOM-11](../spec/support/geometry.md#supported-geometry) | Validate topology and attribute sizes before passing data to Blender. | behavior | M8 | 1 / M12 | — | Set by M8. |
| [GEOM-12](../spec/support/geometry.md#supported-geometry) | Diagnose unsupported types, domains, lossy conversions, holes, and inexact subdivision mappings. | behavior | M8 | 1 / M12 | — | Set by M8. |
| [PVAR-01](../spec/support/geometry.md#primvar-support-matrix) | Settle the primvar support matrix before implementation. | contract | M8 | 1 / M8 | — | Set by M8. |
| [PVAR-02](../spec/support/geometry.md#primvar-support-matrix) | Before choosing a display backend, M4 defines and freezes concrete cases | contract | M4 | 1 / M4 | — | Set by M4. |
| [PVAR-03](../spec/support/geometry.md#primvar-support-matrix) | Additions or changes affecting backend feasibility, sharing, or partitioning require rerunning the relevant M4 prototypes | process | M4 | 1 / M12 | — | Set by M4. |
| [MCLS-01](../spec/support/geometry.md#mesh-classification) | Also classify, for each case, whether the mesh remains supported with an approximation, becomes a placeholder, or fails: | contract | M8 | 1 / M8 | — | Set by M8. |
| [MCLS-02](../spec/support/geometry.md#mesh-classification) | Geometric primvars such as velocities when unused. | behavior | M8 | 1 / M12 | — | Set by M8. |
## spec/support/instancing.md

| ID | Requirement | Kind | Delivery | Phase / qualified by | Fixtures | Test or oracle |
|---|---|---|---|---|---|---|
| [INST-01](../spec/support/instancing.md#supported-instancing) | Native and nested native instances. | behavior | M10 | 1 / M12 | `F-NESTED-STRESS` | Set by M10. |
| [INST-02](../spec/support/instancing.md#supported-instancing) | Multi-mesh, multi-material instance contents. | behavior | M10 | 1 / M12 | — | Set by M10. |
| [INST-04](../spec/support/instancing.md#supported-instancing) | Effective instance transforms, visibility, and purpose. | behavior | M10 | 1 / M12 | — | Set by M10. |
| [INST-05](../spec/support/instancing.md#supported-instancing) | Updates to shared contents. | behavior | M10 | 1 / M12 | — | Set by M10. |
| [INST-06](../spec/support/instancing.md#supported-instancing) | Transitions between instanced and non-instanced representations. | behavior | M10 | 1 / M12 | — | Set by M10. |
| [INST-07](../spec/support/instancing.md#supported-instancing) | Per-instance displayColor, inherited material assignments, and named primvars driving supported material inputs. | behavior | M10 | 1 / M12 | `F-NESTED-STRESS` | Set by M10. |
| [SHARE-01](../spec/support/instancing.md#geometry-sharing) | Within a binding, deduplicate geometry whenever sharing preserves correct display. | behavior | M8 | 1 / M12 | — | Set by M8. |
| [SHARE-02](../spec/support/instancing.md#geometry-sharing) | Per-instance appearance must not collapse into a single shared appearance. | behavior | M10 | 1 / M12 | — | Set by M10. |
| [SHARE-04](../spec/support/instancing.md#geometry-sharing) | Uses with equivalent geometry-resource requirements remain shared, including equivalent variants within cases that require distinct resources. | behavior | M10 | 1 / M12 | — | Set by M10. |
| [SHARE-05](../spec/support/instancing.md#geometry-sharing) | Separate bindings do not share managed geometry resources. | behavior | M10 | 1 / M12 | — | Set by M10. |
| [SHARE-06](../spec/support/instancing.md#geometry-sharing) | M4 records sharing criteria and the display state that requires each distinct-resource case | contract | M4 | 1 / M4 | — | Set by M4. |
## spec/support/materials.md

| ID | Requirement | Kind | Delivery | Phase / qualified by | Fixtures | Test or oracle |
|---|---|---|---|---|---|---|
| [MAT-01](../spec/support/materials.md#supported-materials) | Constant parameters. | behavior | M9 | 1 / M12 | — | Set by M9. |
| [MAT-02](../spec/support/materials.md#supported-materials) | Common image-texture connections. | behavior | M9 | 1 / M12 | — | Set by M9. |
| [MAT-03](../spec/support/materials.md#supported-materials) | Named UV selection and texture-coordinate transforms. | behavior | M9 | 1 / M12 | — | Set by M9. |
| [MAT-04](../spec/support/materials.md#supported-materials) | Texture color spaces and UDIMs. | behavior | M9 | 1 / M12 | — | Set by M9. |
| [MAT-05](../spec/support/materials.md#supported-materials) | Direct, inherited, collection-based, and face-subset bindings with applicable precedence. | behavior | M9 | 1 / M12 | — | Set by M9. |
| [MAT-06](../spec/support/materials.md#supported-materials) | Required per-instance variation. | behavior | M10 | 1 / M12 | — | Set by M10. |
| [MAT-07](../spec/support/materials.md#supported-materials) | Supported displacement signals through the material displacement path, without baking into mesh geometry. | behavior | M9 | 1 / M12 | — | Set by M9. |
| [MAT-08](../spec/support/materials.md#supported-materials) | Target the Principled BSDF subset usable in Eevee and Cycles, with documented displacement exceptions. | behavior | M9 | 1 / M12 | — | Set by M9. |
| [MAT-09](../spec/support/materials.md#supported-materials) | Display batching must not collapse distinct material assignments or attribute meanings. | behavior | M9 | 1 / M12 | — | Set by M9. |
| [GRAM-01](../spec/support/materials.md#connection-grammar) | Settle a bounded connection grammar before implementation | contract | M9 | 1 / M9 | — | Set by M9. |
| [GRAM-02](../spec/support/materials.md#connection-grammar) | Also settle how displayColor and displayOpacity interact with no material binding | contract | M9 | 1 / M9 | — | Set by M9. |
| [GRAM-03](../spec/support/materials.md#connection-grammar) | Before choosing a display backend, M4 defines and freezes concrete connection cases | contract | M4 | 1 / M4 | — | Set by M4. |
| [GRAM-04](../spec/support/materials.md#connection-grammar) | A chosen backend does not authorize silently narrowing required support. | process | M4 | 1 / M12 | — | Set by M4. |
| [MDIAG-01](../spec/support/materials.md#ownership-and-diagnostics) | Document ownership and reuse rules for translated materials, images, node groups, and dependencies. | contract | M9 | 1 / M9 | — | Set by M9. |
| [MDIAG-02](../spec/support/materials.md#ownership-and-diagnostics) | Diagnose missing textures, unsupported networks, and incomplete translations. | behavior | M9 | 1 / M12 | — | Set by M9. |
| [MDIAG-03](../spec/support/materials.md#ownership-and-diagnostics) | Do not silently substitute another UV set when the requested one is unavailable. | behavior | M9 | 1 / M12 | — | Set by M9. |
## spec/support/visibility.md

| ID | Requirement | Kind | Delivery | Phase / qualified by | Fixtures | Test or oracle |
|---|---|---|---|---|---|---|
| [VIS-01](../spec/support/visibility.md#visibility-and-purpose) | Respect effective inherited visibility separately from purpose. | behavior | M6 | 1 / M12 | — | Set by M6. |
| [VIS-02](../spec/support/visibility.md#visibility-and-purpose) | Viewport \| default, proxy | behavior | M6 | 1 / M12 | — | Set by M6. |
| [VIS-03](../spec/support/visibility.md#visibility-and-purpose) | Exclude guide by default. Support both destinations from the same evaluated snapshot. | behavior | M6 | 1 / M12 | — | Set by M6. |
| [MODEL-01](../spec/support/visibility.md#models-and-unsupported-content) | Expose model kind and available asset metadata. | behavior | M6 | 1 / M12 | — | Set by M6. |
| [MODEL-03](../spec/support/visibility.md#models-and-unsupported-content) | Support is decided per behavior, not per prim type. | behavior | M6 | 1 / M12 | — | Set by M6. |
| [MODEL-04](../spec/support/visibility.md#models-and-unsupported-content) | Use a bounding-box placeholder when usable bounds are available. | behavior | M6 | 1 / M12 | — | Set by M6. |
| [MODEL-05](../spec/support/visibility.md#models-and-unsupported-content) | Otherwise create an empty marker and warn. | behavior | M6 | 1 / M12 | — | Set by M6. |
| [MODEL-06](../spec/support/visibility.md#models-and-unsupported-content) | Respect transforms, visibility, and purpose. | behavior | M6 | 1 / M12 | — | Set by M6. |
| [DEFER-01](../spec/support/visibility.md#deferred-and-out-of-scope) | Deferred areas include point instancers, curves, NURBS patches, points, elementary geometry | behavior | M6 | 1 / M12 | — | Set by M6. |
## testing/strategy.md

| ID | Requirement | Kind | Delivery | Phase / qualified by | Fixtures | Test or oracle |
|---|---|---|---|---|---|---|
| [TLAY-01](../testing/strategy.md#test-layers) | Small temporary USD fixtures for precise semantic tests. | process | M1 | 1 / M12 | — | tests/README.md layers: bespoke fixtures in tmp_path, bpy_free planning tests, application tests from hand-constructed plans, blender and isolated end-to-end tests, save/reopen and undo helpers, and the ALab job exist. |
| [TLAY-02](../testing/strategy.md#test-layers) | Cover repeated synchronization, all required change cases | process | M12 | 1 / M12 | — | Set by M12. |
| [TLAY-03](../testing/strategy.md#test-layers) | Before-publication failure-injection tests assert that the entire published generation is unchanged | process | M5 | 1 / M12 | — | Set by M5. |
| [TMETA-01](../testing/strategy.md#metamorphic-tests) | They complement bespoke fixtures and never replace a fixture's own expected results. | process | M6 | 1 / M12 | — | Set by M6. |
| [TMETA-02](../testing/strategy.md#metamorphic-tests) | Each relation states the input change, the expected effect on the result, and the requirement that justifies it. | process | M6 | 1 / M12 | — | Set by M6. |
| [TMETA-03](../testing/strategy.md#metamorphic-tests) | The milestone that delivers a behavior chooses its relations. | process | M6 | 1 / M12 | — | Set by M6. |
| [TMETA-04](../testing/strategy.md#metamorphic-tests) | provided each generated input is reproducible from a recorded seed. | process | M6 | 1 / M12 | — | Set by M6. |
| [TFIX-01](../testing/strategy.md#named-contract-fixtures) | Each fixture is assigned to a milestone in milestones/ and referenced by ID. | process | M1 | 1 / M12 | — | tests/bpy_free/test_fixture_registry.py keeps tests/fixtures/registry.py in sync with this table and the milestone Tests sections. |
| [TINC-01](../testing/strategy.md#incremental-synchronization-tests) | Compare results against a clean full rebuild. | process | M14 | 2 / M14 | — | Set by M14. |
## testing/acceptance.md

| ID | Requirement | Kind | Delivery | Phase / qualified by | Fixtures | Test or oracle |
|---|---|---|---|---|---|---|
| [AFIX-01](../testing/acceptance.md#bespoke-fixtures) | The requirement-to-test matrix covers every requirement applicable to Phases 1 and 2 | process | M1 | 1 / M1 | — | tools/matrix.py check (completeness, quotes, invariants, references) passes in CI; coverage per phase is checked at M12 and M14. |
| [AFIX-07](../testing/acceptance.md#bespoke-fixtures) | Requirements that are not runtime behavior are covered without a fixture | process | M1 | 1 / M1 | — | matrix.py requires fixtures only on behavior rows; contract and process rows name their decision record or check. |
| [AFIX-02](../testing/acceptance.md#bespoke-fixtures) | Fixtures are small, generated by code, and deterministic. | process | M1 | 1 / M12 | — | Generators are code in tests/fixtures/; determinism is tested per generator (as for production_like). |
| [AFIX-03](../testing/acceptance.md#bespoke-fixtures) | Expected results come from the spec, not from recording the implementation's output. | process | M1 | 1 / M12 | — | Review rule in tests/README.md; generators yield the expected values they build. |
| [AFIX-04](../testing/acceptance.md#bespoke-fixtures) | Each fixture case declares its operation and expected outcome | process | M3 | 1 / M12 | — | Set by M3. |
| [AFIX-05](../testing/acceptance.md#bespoke-fixtures) | M12 qualifies only Phase 1 cases and assertions. M14 qualifies Phase 2 cases and assertions and reruns Phase 1 coverage as regression checks. | process | M12 | 1 / M12 | — | Set by M12. |
| [AFIX-06](../testing/acceptance.md#bespoke-fixtures) | Fixtures with time-varying content are evaluated at the sampled time codes. Fixtures with payloads run under both payload policies. | process | M6 | 1 / M12 | — | Set by M6. |
| [ASTD-01](../testing/acceptance.md#standard-end-to-end-checks) | Synchronization completes without a fatal failure. | process | M7 | 1 / M12 | — | Set by M7. |
| [ASTD-02](../testing/acceptance.md#standard-end-to-end-checks) | World bounds of each model's display match USD-computed bounds under the bounds comparison contract. | process | M7 | 1 / M12 | — | Set by M7. |
| [ASTD-03](../testing/acceptance.md#standard-end-to-end-checks) | Unique mesh-data counts are recorded as an aggregate regression metric | process | M7 | 1 / M12 | — | Set by M7. |
| [ASTD-04](../testing/acceptance.md#standard-end-to-end-checks) | Save and reopen preserves the display and inspection state without accessing the source. | process | M7 | 1 / M12 | — | Set by M7. |
| [AFAIL-01](../testing/acceptance.md#expected-failure-checks) | The attempt reports fatal failure with the expected categorized diagnostics | process | M5 | 1 / M12 | — | Set by M5. |
| [AFAIL-02](../testing/acceptance.md#expected-failure-checks) | Retirement failures after publication are completed-with-issues cases | process | M5 | 1 / M12 | — | Set by M5. |
| [AFAIL-03](../testing/acceptance.md#expected-failure-checks) | For disposal-failure cases before or after publication, repeat attempts with disposal still failing. | process | M5 | 1 / M12 | — | Set by M5. |
| [ALIFE-01](../testing/acceptance.md#lifecycle-checks) | Cleanup, detach, and binding removal cases assert their operation-specific requirements | process | M11 | 1 / M12 | — | Set by M11. |
| [AINT-01](../testing/acceptance.md#interior-correctness) | Matching model bounds do not establish correctness inside a model. | process | M8 | 1 / M12 | — | Set by M8. |
| [AINT-02](../testing/acceptance.md#interior-correctness) | Material fixtures use headless render assertions on controlled scenes | process | M9 | 1 / M12 | — | Set by M9. |
| [ATIME-01](../testing/acceptance.md#sampled-time-codes) | Synchronization must work at any time code. | process | M6 | 1 / M12 | — | Set by M6. |
| [ATIME-02](../testing/acceptance.md#sampled-time-codes) | Each time-varying fixture declares its topology and visibility transitions from how it is built | process | M6 | 1 / M12 | — | Set by M6. |
| [ABND-01](../testing/acceptance.md#bounds-comparison-contract) | M4 defines in this section, for the chosen representation: whether expected bounds come from evaluated geometry or authored extent hints | contract | M4 | 1 / M4 | — | Set by M4. |
| [ABND-02](../testing/acceptance.md#bounds-comparison-contract) | The bounds check reuses decisions made elsewhere rather than making its own. | process | M7 | 1 / M12 | — | Set by M7. |
| [AALAB-01](../testing/acceptance.md#production-scale-validation-alab) | A failure found in ALab is reproduced as a bespoke fixture before it is fixed. | process | M12 | 1 / M12 | — | Set by M12. |
| [AALAB-02](../testing/acceptance.md#production-scale-validation-alab) | ALab passes the standard end-to-end checks at every sampled time code and under every payload policy | process | M12 | 1 / M12 | — | Set by M12. |
| [AALAB-04](../testing/acceptance.md#production-scale-validation-alab) | The tree is pinned by alab/subtrees.sha256 and checked with tools/alab_checksums.py --check. | process | M1 | 1 / M1 | — | tools/alab_checksums.py --check passes on the tree (the alab-marked test in tests/bpy_free/test_alab_tools.py). |
| [AALAB-03](../testing/acceptance.md#production-scale-validation-alab) | Run an inventory script for each payload policy | process | M1 | 1 / M1 | — | tools/alab_inventory.py writes docs/testing/alab/inventory.md (full counts to build/alab/); the alab-marked test checks it is current. |
| [APERF-05](../testing/acceptance.md#performance) | The reference hardware is an M1 Max MacBook Pro. | process | M1 | 1 / M1 | — | The feasibility record's macOS environment table lists the machine, memory, OS build, and Blender build. |
| [APERF-06](../testing/acceptance.md#performance) | Measurements run in the Blender binary on AC power | process | M4 | 1 / M12 | — | Set by M4. |
| [APERF-01](../testing/acceptance.md#performance) | Record repeated-run statistics, not single timings. | process | M4 | 1 / M12 | — | Set by M4. |
| [APERF-02](../testing/acceptance.md#performance) | ALab provides production-scale numbers. Generated fixtures of controlled size show how each cost scales. | process | M4 | 1 / M12 | — | Set by M4. |
| [APERF-03](../testing/acceptance.md#performance) | M4 sets provisional budgets for comparing representations. Phase 1 records baselines on the reference hardware, not gates. | process | M4 | 1 / M12 | — | Set by M4. |
| [AWHERE-01](../testing/acceptance.md#where-it-runs) | Bespoke fixtures run in ordinary CI. | process | M1 | 1 / M1 | — | CI runs pytest -n auto on all three platforms. |
| [AWHERE-02](../testing/acceptance.md#where-it-runs) | A smaller generated fixture with production-like structure | process | M1 | 1 / M1 | — | tests/fixtures/production_like.py runs in CI (bpy_free and isolated tests). |
| [AWHERE-03](../testing/acceptance.md#where-it-runs) | ALab runs as a manual or nightly job, not in ordinary CI. | process | M1 | 1 / M12 | — | alab-marked tests are skipped without PROSCENIUM_ALAB_ROOT; the ALab workflow is manual or scheduled. |
