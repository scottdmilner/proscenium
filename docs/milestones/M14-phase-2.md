# M14 — Incremental application and Phase 2 qualification

**Implements:** [Phase 2](../PROJECT.md#delivery-phases), incremental application in [Incremental Synchronization](../spec/incremental.md), incremental guarantees in [Synchronization Transaction](../spec/pipeline.md#synchronization-transaction), and the [Incremental Synchronization Tests](../testing/strategy.md#incremental-synchronization-tests).

**Depends on:** M13 (affected-resource sets, targets, and budgets).

**Decisions and deliverables:**

- A validated in-memory-stage integration interface.
- Incremental application, including repair of damaged content in individual partitions without a full rebuild.
- Manifest updates by entry, measured with the refresh measurements: an update copies the manifest's entries and, with removals, scans every entry's uses ([M3 plan](../plans/M03-bindings.md), D8), and reads the manifest unless its caller passes the one it read (`published`, [M5 plan](../plans/M05-architecture.md), F3). If that's over budget, a count of each resource's users and a persistent map in place of the copied entries would make an update cost only what it changes.
- The undo step and retirement measured again with incremental updates ([M5 plan](../plans/M05-architecture.md), F1, F2): after a full rebuild a step held about the display's size, 1.2 GB on ALab, and 4.5 MB after moving one object (DECISIONS.md "Undo memory cost"); retirement costs about the datablocks removed times those left in the file, 5.0 s for a full rebuild on ALab.

**Tests:**

- All Phase 2 fixture cases and assertions assigned by the requirement-to-test matrix, plus Phase 1 cases and assertions rerun as regression checks.
- Repeated edits, topology changes, inherited changes, and repartitioning, for every change-matrix case.
- Failure injection during incremental mutation and disposal of its newly prepared resources, including persistent cleanup tracking and safe retry.
- `F-NO-OP-REFRESH` with zero unnecessary writes.

**Exit condition:** every Phase 2 requirement has a passing requirement-to-test matrix entry. For the change matrix, incremental results are semantically equivalent to clean rebuilds, preserve identities and avoid writes outside approved affected resources, survive failure injection, satisfy [Resource Stability](../spec/lifecycle.md#resource-stability) including cleanup recovery after disposal failures, and meet the recorded synchronization and interaction targets. Missing requirement rows, fixtures, or test/oracle coverage block qualification.
