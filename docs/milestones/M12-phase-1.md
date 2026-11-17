# M12 — Complete and qualify Phase 1

**Implements:** [Phase 1](../PROJECT.md#delivery-phases) and Phase 1 qualification in [Acceptance Criteria](../testing/acceptance.md).

**Depends on:** M1–M11.

**Decisions and deliverables:**

- Completed binding settings, manual-sync controls, inspection UI, and diagnostics UI, including requested/published/last-attempt display and current cleanup status with explicit retry controls.
- Completed support matrices and deployment documentation.
- Phase 1 baselines, as defined in Acceptance Criteria.
- What earlier measurements set beside them:
  - M1b's adoption criterion 4 ([M1b plan](../plans/M01b-evaluation-gate.md#phase-f--decision)): at ALab scale against Blender's importer in its matched configuration, end-to-end time and peak memory each at most 2× the importer's, and the Hydra stages (capture, planning, and transfer) faster than Blender construction. M4's provisional budgets are 1.5× the importer's time and 2× its peak ([M4 plan](../plans/M04-prototypes.md#settled-with-the-user-2026-10-27)).
  - Blender's importer with scene instancing on drops materials bound at an instance root, so comparisons on instancing scenes use its expanded configuration, without scene instancing ([M1b plan](../plans/M01b-evaluation-gate.md#phase-e-log)).
  - The live heap is read only in the macOS binary: Blender's Linux and Windows release builds replace malloc with TBB's proxy, and their working-set and resident-set counters are unchecked against another tool ([record](../feasibility/runtime-record.md#measurements-m1b-phase-e)).
- Deployment documentation covers updating: the compiled module never unloads and its converters are process-global, so an in-session update reuses the old ones, and updating or uninstalling while loaded is untested ([M1b plan](../plans/M01b-evaluation-gate.md#native-build-and-boundary)).
- From M7's temporary UI ([M7 plan](../plans/M07-application.md), Phase F; `src/proscenium/interface/`), which M12 replaces, reaching the product only through `bindings/`:
  - The Source Select tool picks with a ray of its own against each visible, selectable object's bounds box, and an empty marker within a few pixels, since bounds meshes have no faces; its Python loop took 15 ms on ALab and 191 ms at 30,001 objects ([record](../feasibility/runtime-record.md#the-products-interaction-m7-phase-g)), until M8's meshes let `scene.ray_cast` do it.
  - Selections are undone through operators: picks and boxes declare UNDO, and the source inspector's tree pushes a step for a row that changes the source selection while synced. Selectability follows the active tool through message-bus subscriptions, and is recomputed after a load, an undo, and a redo, since an undo step may hold it from before the tool's activation.
  - The source inspector hosts the scene graph and property viewer widgets over the chosen binding's live stage, which neither holds, and its per-draw reads, the displayed line and the shown time code, cost under 1 ms on ALab with the binding's display kept.
  - A change of selection costs Blender's depsgraph update however few objects change, 106 ms at 30,001 objects and about 15 ms on ALab (ad hoc), so a pick there stays over M4's 50 ms budget; mirroring sets only what changes, so an unchanged selection mirrored again costs nothing more.

**Tests:**

- The Phase 1 acceptance suite: every fixture case and assertion assigned to Phase 1 qualification by the requirement-to-test matrix, including interior correctness, with successful synchronization cases using the standard end-to-end checks and bounds comparison contract, expected failures using the expected-failure checks, and lifecycle cases using their operation-specific checks; then the ALab production-scale validation. Phase 2 cases and assertions, the performance targets and churn budgets, do not gate M12.
- Agreed picking, selection, and highlighting behavior, exercised through the headless interaction functions.
- Correspondence after rebuilding or repartitioning.
- Incremental refresh for every change-matrix case, rerun across M7 to M11's content: results equal to clean rebuilds, identities kept and no writes outside the affected resources, through failure injection, under [Resource Stability](../spec/lifecycle.md#resource-stability).
- Saved displays with unavailable sources: the display remains, and interaction reports the source unavailable.
- Failures injected at every transaction boundary.
- The Phase 1 cases and assertions of `F-OFFLINE`, `F-NO-OP-REFRESH`, `F-SAME-VALUES`, and every fixture assigned to earlier milestones.

**Exit condition:** every Phase 1 requirement has a matrix entry and passes on its bespoke fixtures under the applicable outcome checks, and ALab passes the standard end-to-end checks at production scale. Missing requirement rows, fixtures, or test/oracle coverage block qualification.
