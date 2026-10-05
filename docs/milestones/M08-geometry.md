# M8 — Validated mesh and primvar translation

**Implements:** [Geometry and Primvars](../spec/support/geometry.md), time-varying topology in [Transforms and Time Codes](../spec/support/transforms.md#transforms-and-time-codes), and correspondence through batching in [Source Inspection and Interaction](../spec/interaction.md#source-inspection-and-interaction).

**Depends on:** M6 (snapshot and planning), M7 (application layer).

**Decisions and deliverables:**

- First, before implementation: complete the primvar support matrix and mesh classification rules against M4's frozen cases. Additions or changes affecting backend feasibility, sharing, or partitioning require rerunning the relevant M4 prototypes and revising the design as needed before implementation.
- Evaluation/planning: validated geometry and primvar data in the snapshot and plan.
- Application: mesh data, attributes, and modifiers created from the plan.

**Tests:**

- Focused invalid-data and edge-case fixtures, one per support-matrix row and classification case.
- Sharing assertions against M4's criteria: equivalent geometry and attribute requirements share resources; differing data remains correct where distinct resources are required.
- The M5 failure-injection tests, rerun with geometry writes.

**Exit condition:** safe supported geometry at any supplied time code, matching the support matrix, with source correspondence intact.
