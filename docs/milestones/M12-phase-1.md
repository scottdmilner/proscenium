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

**Tests:**

- The Phase 1 acceptance suite: every fixture case and assertion assigned to Phase 1 qualification by the requirement-to-test matrix, including interior correctness, with successful synchronization cases using the standard end-to-end checks and bounds comparison contract, expected failures using the expected-failure checks, and lifecycle cases using their operation-specific checks; then the ALab production-scale validation. Phase 2 cases and assertions, the performance targets and churn budgets, do not gate M12.
- Agreed picking, selection, and highlighting behavior, exercised through the headless interaction functions.
- Correspondence after rebuilding or repartitioning.
- Incremental refresh for every change-matrix case, rerun across M7 to M11's content: results equal to clean rebuilds, identities kept and no writes outside the affected resources, through failure injection, under [Resource Stability](../spec/lifecycle.md#resource-stability).
- Saved displays with unavailable sources: the display remains, and interaction reports the source unavailable.
- Failures injected at every transaction boundary.
- The Phase 1 cases and assertions of `F-OFFLINE`, `F-NO-OP-REFRESH`, `F-SAME-VALUES`, and every fixture assigned to earlier milestones.

**Exit condition:** every Phase 1 requirement has a matrix entry and passes on its bespoke fixtures under the applicable outcome checks, and ALab passes the standard end-to-end checks at production scale. Missing requirement rows, fixtures, or test/oracle coverage block qualification.
