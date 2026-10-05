# M12 — Complete and qualify Phase 1

**Implements:** [Phase 1](../PROJECT.md#delivery-phases) and Phase 1 qualification in [Acceptance Criteria](../testing/acceptance.md).

**Depends on:** M1–M11.

**Decisions and deliverables:**

- Completed binding settings, manual-sync controls, inspection UI, and diagnostics UI, including requested/published/last-attempt display and current cleanup status with explicit retry controls.
- Completed support matrices and deployment documentation.
- Phase 1 baselines, as defined in Acceptance Criteria.

**Tests:**

- The Phase 1 acceptance suite: every fixture case and assertion assigned to Phase 1 qualification by the requirement-to-test matrix, including interior correctness, with successful synchronization cases using the standard end-to-end checks and bounds comparison contract, expected failures using the expected-failure checks, and lifecycle cases using their operation-specific checks; then the ALab production-scale validation. Phase 2 cases and assertions, including `F-SAME-VALUES`' no-unnecessary-writes requirement, do not gate M12.
- Agreed picking, highlighting, and framing behavior, exercised through the headless interaction functions.
- Correspondence after rebuilding or repartitioning.
- Inspection of saved displays with unavailable sources.
- Failures injected at every transaction boundary.
- The Phase 1 cases and assertions of `F-OFFLINE`, `F-NO-OP-REFRESH`, and every fixture assigned to earlier milestones.

**Exit condition:** every Phase 1 requirement has a matrix entry and passes on its bespoke fixtures under the applicable outcome checks, and ALab passes the standard end-to-end checks at production scale. Missing requirement rows, fixtures, or test/oracle coverage block qualification.
