# M1 — Runtime feasibility, workspace, and test infrastructure

**Implements:** [Compatibility and Development](../PROJECT.md#compatibility-and-development), [Testing Strategy](../testing/strategy.md) infrastructure, [Acceptance Criteria](../testing/acceptance.md) specification.

**Depends on:** nothing.

**Scope limits:** M1 is a stop/go gate. Runtime feasibility is verified before investing in tooling polish; if it fails, the implementation strategy is revisited before M2.

**Decisions and deliverables:**

- A runtime feasibility record for each platform:
  - Exact Blender build and version, embedded Python version, USD version, and available USD modules.
  - Runtime module paths and relevant USD plugin discovery.
  - Whether a supported distribution can exchange stage objects with caller code.
  - Extension packaging results.
- Verified runtime behaviors that later milestones depend on:
  - Post-load, post-undo, and post-redo handlers fire reliably, including in the test runner.
  - A synchronization invoked from the Python API can push its own undo step, and undo behavior with global undo disabled and in background mode.
  - Candidate approaches from the [In-Memory Sources](../spec/source-access.md#in-memory-sources) design note behave as expected.
  - Contributing layers with unsaved edits can be detected, and a fresh stage can be opened without reusing a cached one.
  - Whether a private disk view can be built without touching shared layers (see [File-Backed Refresh](../spec/source-access.md#file-backed-refresh)).
- Which USD imaging modules Blender's Python `pxr` exposes, and whether a compiled module can link against the bundled USD and exchange stages with Python. The macOS arm64 result is in the [compiled Hydra bridge record](../feasibility/runtime-record.md#compiled-hydra-bridge--macos-arm64); Windows and Linux are M1b's first deliverable and do not gate M1's exit.
- The extension layout, development environment, build script, lint/type-check hooks, and `AGENTS.md`.
  - `AGENTS.md` directs agents to read [PROJECT.md](../PROJECT.md) and [spec/invariants.md](../spec/invariants.md) before any work.
  - `AGENTS.md` instructs agents to keep `spec/invariants.md` in sync with the spec: any change to a guarantee in a spec file updates its statement in `invariants.md` in the same change, and vice versa. `invariants.md` stays a summary that links to and defers to the authoritative spec section; it never accumulates detail of its own.
- A minimal register/unregister extension.
- Test infrastructure:
  - Pure unit tests where possible.
  - Blender integration tests.
  - Generation of [bespoke fixtures](../testing/acceptance.md#bespoke-fixtures).
  - Save/reopen and undo/redo test support.
  - Cross-platform smoke tests.
  - Reused Blender test processes with explicit state reset, retaining isolated processes where necessary.
- The acceptance specification, the smaller generated CI fixture, and the ALab inventory for each payload policy, all as described in Acceptance Criteria.
- A requirement-to-test matrix covering every requirement applicable to Phases 1 and 2 in PROJECT.md, spec/, and testing/. Each row records a stable requirement ID, authoritative spec section, delivery milestone, bespoke fixture and test or oracle, and qualification milestone/phase. Mark high-risk entries separately. Invariant summaries reference the authoritative requirement ID rather than creating duplicate rows. Later contract decisions update the matrix before implementation.

**Exit condition:** the runtime feasibility record shows the required Blender/USD combination works on all three platforms (or the strategy has been revised), and a reproducible development/test/package workflow, acceptance specification, and complete initial requirement-to-test matrix exist.
