# M2 — Display, inspection, and interaction contracts

**Implements:** the contracts required by [Core Architecture](../PROJECT.md#core-architecture), [Source Inspection and Interaction](../spec/interaction.md#source-inspection-and-interaction), and [Interaction Testing](../spec/interaction.md#interaction-testing). M2 defines these contracts; M4, M7, M8, and M10 implement them.

**Depends on:** M1 (headless test infrastructure).

**Scope limits:**

- Produces a **draft** contract. M4 answers its feasibility questions and finalizes it.
- The contract defines what the display layer must provide without prescribing its Blender structure.

**Decisions and deliverables:**

- A draft interaction contract covering everything Source Inspection and Interaction says the contract must settle, expressed as headless-testable functions. This includes the browsing universe, the supported inspection metadata set, and the identity of persistent selection state.
- A list of feasibility questions that depend on what Blender can actually do, such as whether individual instances inside a batched representation can be resolved from pick data. If M1b adopts Hydra, include whether Hydra-processed paths, including aggregated native instances, map back to source entities with their instance context. The contract itself stays independent of the evaluation front end.

**Exit condition:** a draft contract of testable inspection and interaction requirements that can be evaluated against different display implementations, plus a list of open feasibility questions for M4.
