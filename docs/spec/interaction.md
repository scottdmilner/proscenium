# Interaction

Source inspection, the interaction contract, and how interaction is tested. Cross-cutting guarantees are summarized in [invariants.md](invariants.md).

## Source Inspection and Interaction

Source/display correspondence is a first-class contract:

- Display selection resolves to a binding and source entity, including instance context where applicable.
- Source selection of a prim or subtree resolves to its associated display elements.
- Source inspection works independently of Blender parenting.
- Native instance roots are selectable and source-identifiable.
- Individually selectable native-instance descendants are not required. Adding them would be a deliberate scope expansion.
- Source correspondence survives any batching, reordering, or geometry partitioning.

The interaction contract must settle:

- The **browsing universe**: which of the populated composed hierarchy, instance-proxy descendants, inactive prims, unloaded payload roots, abstract prims, and composition provenance source inspection exposes. Not all are required; the set must be defined.
- The supported metadata set for inspection. Arbitrary USD metadata inspection is not implied.
- Source-path identification.
- The identity of persistent selection state.
- Viewport picking granularity.
- Selection highlighting and framing.
- Instance-root selection.
- Inspection and selection of organizational or non-geometric prims.
- Interfaces needed by future USD manipulation tools.
- Whether any ordinary Blender selection/manipulation behavior is required.

The draft [Interaction Contract](interaction-contract.md) settles these items. Callers browse and inspect the live stage through the USD API; the contract maps between source and display. Framing is not provided (see [Interaction Testing](#interaction-testing)).

Do not assume every prim needs independent viewport picking or that standard Blender transform tools must become USD authoring tools.

Interaction requires the live source stage. A saved display whose source is unavailable remains displayed, without inspection or selection. Distinguish the last synchronized snapshot from newly evaluated source state.

## Interaction Testing

Picking and highlighting normally need a window and a 3D viewport, which background Blender and the `bpy` module lack. The extension therefore exposes the logic behind interaction as plain functions that can be tested headless. Examples include mapping a picked object and instance to a source path, choosing a selection target, and resolving highlight targets. The interaction contract is defined and tested in these terms.

Interaction feasibility and qualification are claimed **at the level of these headless functions**: given the inputs a viewport operation supplies, they produce the contracted result. The project does not verify that real viewport operations produce those inputs. For the chosen representation, M4 records what a real pick is assumed to supply as an accepted, unverified risk.

Interaction timings measure the cost of these headless interaction functions plus any Blender data updates they trigger, such as selection or highlight state changes.

**Future work:** the following are out of scope for this project:

- A windowed test suite that drives real viewport picking and highlighting.
- Framing source selections.
- Measuring viewport drawing performance.
