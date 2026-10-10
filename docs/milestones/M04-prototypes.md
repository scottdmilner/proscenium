# M4 — Display representation and interaction feasibility prototypes

**Implements:** the representation options in [Core Architecture](../PROJECT.md#core-architecture), the prototyping constraint in [Ordering Constraints](README.md#ordering-constraints), the sharing criteria in [Geometry Sharing](../spec/support/instancing.md#geometry-sharing), and the representation feasibility cases in [Primvar Support Matrix](../spec/support/geometry.md#primvar-support-matrix) and [Connection Grammar](../spec/support/materials.md#connection-grammar). M8–M10 complete and implement the full support contracts.

**Depends on:** M2 (draft contract and feasibility questions), M3 (source-entity identity).

**Scope limits:**

- Prototypes are not production code.
- Interaction feasibility is established through the headless interaction functions only (see [Interaction Testing](../spec/interaction.md#interaction-testing)).
- Not every approach needs an equally complete prototype.

**Decisions and deliverables:**

- Before backend selection: concrete, frozen primvar and material cases in the support specs, covering per-instance appearance, named UVs and primvar readers, face assignments, and geometry sharing, with the relevant types, domains, inheritance/indexing behavior, connections, and display-color/opacity rules.
- A simple object/collection baseline, tested against a risk matrix of the highest-risk requirements. Those requirements are marked high-risk in the requirement-to-test matrix.
- Targeted prototypes of batching (such as Geometry Nodes) or a hybrid partitioned by assets or independently updated subtrees, only where the baseline fails a requirement or its measured costs justify the alternative.
- A stress fixture combining shear, negative-determinant transforms, nonuniform scale, reset transform stacks inside instances, nested instances with differing appearance, and separate viewport/render purposes. The question is whether the representation supports these in combination under the Geometry Sharing contract.
- Each evaluated representation also exercises:
  - Multi-mesh, multi-material assets.
  - Required per-instance shading variation.
  - Source lookup from pick data.
  - Highlighting and framing source selections.
  - Small updates within larger scenes.
  - Detaching a whole binding under [Detach As-Is](../spec/lifecycle.md#detach-as-is): identify binding-specific controls to remove and ordinary Blender dependencies to retain, without requiring baking or source reconstruction.
- Provisional performance budgets, and measurements of initial construction, refresh, interaction, and resource costs against them. Interaction costs are defined in [Interaction Testing](../spec/interaction.md#interaction-testing).
- Answers to every M2 feasibility question and the finalized interaction contract, including a compatibility review and any required updates to M3's identifiers and persistence schemas before M5 begins.
- For the chosen representation, a record of what a real viewport pick is assumed to supply, as an accepted risk.
- A partitioning decision record:
  - The partition unit, such as one per model or per prototype.
  - What a partition owns.
  - How a partition is replaced as a whole.
- Recorded limitations and fallbacks.
- Prototypes use the evaluation front end and core language chosen in M1b. A decision in the row "Time-sampled data representation", using M1b's findings on time-sampled data detection. Compare per-time-code snapshots against keyframed transforms, mesh cache modifiers, and Geometry Nodes baking. Baking is expected to perform better at the cost of higher memory use, so measure playback, construction, memory, and `.blend` size separately. Record the time-code-to-frame mapping for any approach adopted, and how it meets the requirements listed in that row.
- Sharing criteria and any cases requiring distinct geometry resources for correct display, with correctness fixtures and measured resource costs.
- The [bounds comparison contract](../testing/acceptance.md#bounds-comparison-contract) for the chosen representation, recorded in that section.

Later milestones build on the partitioning decision and frozen support cases. Changes affecting backend feasibility, sharing, or partitioning require rerunning the relevant prototypes before implementation, revising the decision record, and listing the affected milestones.

**Exit condition:** a display design that passes the frozen support cases, risk matrix, and stress fixture, validated against the finalized interaction contract at the level of the headless interaction functions, with compatible M3 identifiers and persistence schemas and a recorded partitioning decision—not merely a fast static-scene prototype.
