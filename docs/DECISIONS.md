# Decision Register

Milestones update this register when they settle a decision. Every in-scope requirement is traced in the requirement-to-test matrix created in M1, with high-risk entries marked separately. Settled contract decisions update their requirement rows and test/oracle coverage before implementation. Fixture IDs refer to [Named Contract Fixtures](testing/strategy.md#named-contract-fixtures).

| Decision | Owner | Chosen behavior / alternatives | Acceptance test |
|---|---|---|---|
| Dirty contributing layers on file-backed refresh | M3 | **Chosen:** fail with a source-access conflict. Rejected: evaluating in-process state with a divergence diagnostic. May upgrade to a private disk view if M1 proves it feasible. | `F-DIRTY-LAYER` |
| Private disk view feasibility | M1 | Open. | M1 feasibility record |
| Stage-level state reproduced for in-memory sources | M3 | Open: muted layers, population mask, resolver context, interpolation, session-layer opinions. | `F-PRIVATE-STAGE` |
| In-memory source key contract | M3 | Open (see [Source Identity](spec/source-access.md#source-identity)). | M3 reattachment tests |
| Copied bindings | M3 | **Chosen:** disabled pending repair. Canonical-candidate rule open. Rejected: automatic new identity; treat as detached. | `F-OWNERSHIP-AMBIGUITY` |
| Browsing universe and inspection metadata set | M2 | Open. | M2 contract tests |
| Partition unit | M4 | Open. | M4 decision record |
| Geometry sharing | M4 | **Chosen:** deduplicate wherever sharing preserves correct display; required distinct resources are permitted with recorded display reasons, correctness fixtures, and measured costs. Specific sharing criteria open. | M4 prototypes; M8/M10 sharing and appearance fixtures |
| Support cases for backend feasibility | M4 | **Chosen:** freeze concrete primvar/material cases before backend selection; later additions or changes affecting feasibility, sharing, or partitioning require renewed prototype validation before implementation. Specific cases open. | M4 prototypes and stress fixture; M8/M9 fixtures |
| Python-only implementation | M4 | **Current:** Python only. Revisit if measurements from M4 onward show Python cannot meet the budgets; any compiled components must support all three platforms. | M4 measurements |
| Post-publication retirement failure | M5 | **Chosen:** synchronization completes; leftovers tracked, noncanonical, retryable. | `F-RETIREMENT-FAILURE` |
| Pre-publication disposal failure | M5 | **Chosen:** attempt remains failed; published generation unchanged; prepared leftovers inactive, persistently tracked, and retryable. | `F-PREPARATION-CLEANUP-FAILURE` |
| Pending-cleanup tracking mechanism | M5 | Open: separate persistent ledger or pending-cleanup state in existing ownership records. M3 defines the persistence contract; M5 chooses and validates the mechanism. | `F-PREPARATION-CLEANUP-FAILURE`, `F-RETIREMENT-FAILURE` |
| Undo for failed synchronizations | M5 | **Chosen:** no undo step; last-attempt record and pending-cleanup tracking may change; binding configuration and published generation do not. | `F-FAILED-SETTINGS`, `F-PREPARATION-CLEANUP-FAILURE` |
| Undo memory cost | M5 | **Current:** one undo step per published synchronization. Clearing undo history is consistent but hostile to users. Revisit if measurements show unacceptable use. | M5 measurement |
| Interaction feasibility evidence | M4 | **Chosen:** headless functions only; viewport input assumptions recorded as risk. Rejected: manual viewport check. | M4, M12 headless suites |
| Primvar support matrix | M8 | Open; completed against M4's frozen cases before M8 implementation, with renewed prototype validation where required. | M8 fixtures |
| Material connection grammar | M9 | Open; completed against M4's frozen cases before M9 implementation, with renewed prototype validation where required. | M9 fixtures |
| Offline appearance | M9 | **Chosen:** geometry, materials, and inspection persist; textures stay external references. Rejected: packing assets; geometry-only promise. | `F-OFFLINE` |
| Detach contract and later refresh | M11 | **Chosen:** whole binding, surviving content as-is; remove binding-specific metadata and controls; no required baking or source reconstruction. Clear the published generation; next refresh behaves like a first synchronization. Subtree detach deferred. | `F-DETACH-SHARED`, `F-DETACH-AS-IS` |
| Lifecycle failure safety | M11 | **Chosen:** detach commits as a whole; cleanup/removal may report committed partial progress with persistent safe retry; pre-commit failure preserves starting state; binding removal never orphans disposal work. Staging, commit points, and removal retention strategy open for M11 planning, using M5's chosen tracking mechanism. | `F-LIFECYCLE-FAILURE`, `F-UNDO-AFTER-DAMAGE` |
| Bounds comparison contract and tolerances | M1 | Open; recorded in the acceptance specification. | Standard end-to-end checks |
| Churn budgets for replacement-affected resources | M13 | Open. | M14 qualification |
| Phase 2 performance targets | M13 | Open; derived from Phase 1 baselines. | M14 qualification |
