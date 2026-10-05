# M14 — Incremental application and Phase 2 qualification

**Implements:** [Phase 2](../PROJECT.md#delivery-phases), incremental application in [Incremental Synchronization](../spec/incremental.md), incremental guarantees in [Synchronization Transaction](../spec/pipeline.md#synchronization-transaction), and the [Incremental Synchronization Tests](../testing/strategy.md#incremental-synchronization-tests).

**Depends on:** M13 (affected-resource sets, targets, and budgets).

**Decisions and deliverables:**

- A validated in-memory-stage integration interface.
- Incremental application, including repair of damaged content in individual partitions without a full rebuild.

**Tests:**

- All Phase 2 fixture cases and assertions assigned by the requirement-to-test matrix, plus Phase 1 cases and assertions rerun as regression checks.
- Repeated edits, topology changes, inherited changes, and repartitioning, for every change-matrix case.
- Failure injection during incremental mutation and disposal of its newly prepared resources, including persistent cleanup tracking and safe retry.
- `F-NO-OP-REFRESH` with zero unnecessary writes.

**Exit condition:** every Phase 2 requirement has a passing requirement-to-test matrix entry. For the change matrix, incremental results are semantically equivalent to clean rebuilds, preserve identities and avoid writes outside approved affected resources, survive failure injection, satisfy [Resource Stability](../spec/lifecycle.md#resource-stability) including cleanup recovery after disposal failures, and meet the recorded synchronization and interaction targets. Missing requirement rows, fixtures, or test/oracle coverage block qualification.
