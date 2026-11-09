# M13 — Phase 2: performance targets and qualification

**Implements:** [Phase 2](../PROJECT.md#phase-2--performance-qualification), the churn budgets in [Affected Content](../spec/incremental.md#affected-content), and Phase 2 qualification in [Acceptance Criteria](../testing/acceptance.md).

**Depends on:** M12 (Phase 1, its incremental refresh, and its baselines).

**Decisions and deliverables:**

- Phase 2 performance target values for synchronization and the required interaction operations, derived from Phase 1's baselines, and churn budgets for replacement-affected resources (DECISIONS.md "Phase 2 performance targets", "Churn budgets for replacement-affected resources").
- Measurements against them, on ALab and the generated `updates-N` scenes, of every change-matrix case M7 to M11 refresh incrementally, and of the required interaction operations.
- The undo step and retirement measured again with incremental refresh ([M5 plan](../plans/M05-architecture.md), F1, F2): after a full rebuild a step held about the display's size, 1.2 GB on ALab, and 4.5 MB after moving one object (DECISIONS.md "Undo memory cost"); retirement costs about the datablocks removed times those left in the file, 5.0 s for a full rebuild on ALab.
- Manifest updates by entry measured with the refresh measurements (M7), and where they're over budget, a count of each resource's users and a persistent map in place of the copied entries.
- Where a target is missed, the work that meets it, within Phase 1's correctness.

**Tests:**

- All Phase 2 fixture cases and assertions assigned by the requirement-to-test matrix, plus Phase 1 cases and assertions rerun as regression checks.
- The measurement harness's recorded runs against each target and budget (ARCH-08).

**Exit condition:** every Phase 2 requirement has a passing requirement-to-test matrix entry, and synchronization, incremental refresh, and the required interaction operations meet the recorded targets, with replacement-affected resources within the churn budgets. Missing requirement rows, fixtures, or test/oracle coverage block qualification.
