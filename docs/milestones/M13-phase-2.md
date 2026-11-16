# M13 — Phase 2: performance targets and qualification

**Implements:** [Phase 2](../PROJECT.md#phase-2--performance-qualification), the churn budgets in [Affected Content](../spec/incremental.md#affected-content), and Phase 2 qualification in [Acceptance Criteria](../testing/acceptance.md).

**Depends on:** M12 (Phase 1, its incremental refresh, and its baselines).

**Decisions and deliverables:**

- Phase 2 performance target values for synchronization and the required interaction operations, derived from Phase 1's baselines, and churn budgets for replacement-affected resources (DECISIONS.md "Phase 2 performance targets", "Churn budgets for replacement-affected resources").
- Measurements against them, on ALab and the generated `updates-N` scenes, of every change-matrix case M7 to M11 refresh incrementally, and of the required interaction operations.
- The undo step and retirement measured again with incremental refresh ([M5 plan](../plans/M05-architecture.md), F1, F2): after a full rebuild a step held about the display's size, 1.2 GB on ALab, and 4.5 MB after moving one object (DECISIONS.md "Undo memory cost"); retirement costs about the datablocks removed times those left in the file, 5.0 s for a full rebuild on ALab.
- Manifest updates by entry measured with the refresh measurements (M7), and where they're over budget, a count of each resource's users and a persistent map in place of the copied entries.
- Where a target is missed, the work that meets it, within Phase 1's correctness.
- From M7 ([M7 plan](../plans/M07-application.md), Phase G; [runtime record](../feasibility/runtime-record.md#the-products-synchronizations-m7-phase-g)):
  - Narrowing the plan diff by the notices a capture read: it compares the whole plans, 0.5 ms on ALab and 3 ms at 30,001 copies, but each refresh's per-copy decision and its source paths grow with the plan.
  - Noted costs: the first refresh after a whole write, which groups the manifest's partitions from every entry, 44 ms of partition replacement on ALab and 222 ms at 30,001 objects; the held plans, up to the undo steps plus one per binding, about 4 MB each on ALab and 14 MB at 30,001 objects; a hide's undo push, 238 ms on ALab against 35 ms after a move, with the push evaluating the depsgraph; the second undo push after a synchronization, 13 MB on `updates-1000` with nothing changed, not explained; and retirement beside a replacement display (M11's note).

**Tests:**

- All Phase 2 fixture cases and assertions assigned by the requirement-to-test matrix, plus Phase 1 cases and assertions rerun as regression checks.
- The measurement harness's recorded runs against each target and budget (ARCH-08).

**Exit condition:** every Phase 2 requirement has a passing requirement-to-test matrix entry, and synchronization, incremental refresh, and the required interaction operations meet the recorded targets, with replacement-affected resources within the churn budgets. Missing requirement rows, fixtures, or test/oracle coverage block qualification.
