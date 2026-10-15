# M9 — Material translation and binding resolution

**Implements:** [Materials](../spec/support/materials.md), and texture handling in [Reopening](../spec/lifecycle.md#reopening).

**Depends on:** M4 (per-instance variation approach), M8 (UVs and primvars).

**Scope limits:** per-instance material variation is completed and tested in M10. M9 designs material inputs to accept per-instance data, following the M4 variation approach.

**Decisions and deliverables:**

- First, before implementation: complete the bounded connection grammar and `displayColor`/`displayOpacity` interaction rules against M4's frozen cases. Additions or changes affecting backend feasibility, sharing, or partitioning require rerunning the relevant M4 prototypes and revising the design as needed before implementation.
- Evaluation/planning: effective material bindings, translated networks, and material inputs that accept per-instance data. With M1b's Hydra core, networks come from Hydra's material network data. Bindings come from UsdShade's resolution, recorded by the core beside the chain: M1b found Hydra's flattened bindings wrong inside nested instances, without the allPurpose fallback, and blind to collections that reach into instances (OpenUSD #3690, worked around and labeled in the prototype). See the [M1b plan](../plans/M01b-evaluation-gate.md#phase-c-log); the connection grammar, Principled BSDF translation, and material purpose selection remain project work. Direct, inherited, collection-based, and face-subset precedence are verified against fixtures.
- Application: materials, nodes, images (as external file references), and assignments.
- Ownership and reuse rules for translated materials, images, node groups, and dependencies.

**Tests:**

- Display batching does not collapse distinct material assignments or attribute meanings.
- Material inputs accept per-instance data supplied through hand-constructed plans.
- Headless render assertions on controlled material fixtures.
- `F-SHARED-MATERIAL-FAILURE` and `F-OFFLINE`.

**Exit condition:** the material grammar works within the chosen display representation, and material and image failures leave the published generation unchanged.
