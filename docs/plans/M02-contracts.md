# M2 — Display, inspection, and interaction contracts: plan

How M2 will produce its draft contract, what has been settled so far, and the order of work. Requirements are in the [M2 milestone](../milestones/M02-contracts.md); where this plan and a requirement file disagree, the requirement file wins. Mechanisms named here are suggestions unless marked settled. Each phase gains a short decision log once work starts, in the style of the [M1 plan](M01-runtime.md).

M2 delivers three contract rows, all qualified by M4: ARCH-06 (tools address USD entities through the source selection model), INSP-06 (what the interaction contract must settle), and ITEST-02 (interaction is claimed at the level of headless functions). The contract is a **draft**: M4 answers the feasibility questions below and finalizes it, and M7, M8, and M10 implement it.

## Settled with the user (2026-10-15)

- **Browsing universe: displayed content only.** Selection and the universe cover only what the scene displays. Instance-proxy descendants, unloaded payload roots, inactive prims, abstract prims, and composition provenance are all excluded. A Phase 3 scene-graph inspector will expose them; that inspector is not part of this contract.
- **Selection level is chosen by the caller,** for example by model kind (pick a mesh, select its component or group). **Nothing inside a native instance is selectable**: a hit inside instance contents resolves no lower than its outermost instance root. The spec's scope limit on instance descendants stands.
- **Hierarchy comes from the stage, not from Hydra.** Hydra's flattening need not preserve prim hierarchies, and intermediate prims such as a group may have no Hydra counterpart. Selecting at a level finds the target prim on the live stage, then selects every displayed prim in its subtree too. Expansion uses USD paths, so it never depends on how Hydra regrouped prims. Their display elements are found through correspondence.
- **Blender selection is both output and input.** A source selection is mirrored into Blender's selection state, and selecting displayed content in Blender produces a source selection. Whether input goes through Blender's native selection tools or a selection tool the extension provides is open (feasibility question Q4).
- **Callers have the live stage.** They browse and inspect it through the USD API. The contract provides only what the stage can't answer: what is displayed, and how display and source map to each other.
- **Two layers.** A persisted correspondence layer, produced by synchronization through the Hydra pipeline, resolves picks, says which prims are displayed, and shows selections; it stores no inspection data. An inspection layer maps picked prims to selection targets by model kind on the live stage. Hydra is needed for display, not for inspection.
- **The inspection layer is C++, independent of the core.** It doesn't touch Blender, shares no code with the compiled core, and doesn't depend on its scene indices, snapshot, or plan. Chosen because a kind-level selection runs correspondence → inspection → correspondence, and a Python middle step would be GIL-bound per-path work between two compiled calls (DECISIONS.md "Inspection layer"). Correspondence is already compiled: since M1b the core maintains it from Hydra as part of planning, and application only records which Blender resources realize it. The inspection layer is a library the core calls, and the core's bindings expose the interaction functions, so paths never pass through Python between the layers. The only Python is the display component that reads and writes Blender's selection. Which stage is live for a file-backed binding, and whether it stays open, is left to M3.
- **Nothing interaction-related works without a live stage.** A saved display with its source unavailable is plain displayed content; interaction functions report the source unavailable, and stored selections are kept.
- **Framing is out of scope.** The contract provides no framing of source selections in Phases 1 and 2; it is recorded as future work in [Interaction Testing](../spec/interaction.md#interaction-testing).
- **Deliverable: the spec plus a contract test kit.** A spec section defines the contract as headless functions. Matrix rows trace the behavior it settles. A test suite, parametrized by a display adapter, checks any representation against the contract, so M4 can plug in each prototype.

## Draft contract

The contract is in [spec/interaction-contract.md](../spec/interaction-contract.md) (Phase A). The spec is authoritative; this plan records only the reasoning behind it.

## Phases

Each phase ends with a review by the user before the next starts.

### Phase A — Contract in the spec

- Write the contract into the spec, as a new `docs/spec/interaction-contract.md` marked draft until M4, linked from [interaction.md](../spec/interaction.md) and the PROJECT.md documentation map.
- Update `invariants.md` only if a cross-cutting guarantee changes.
- Update the DECISIONS.md row "Browsing universe and inspection metadata set" to **Draft (M2)**, with the settled choices and a pointer to M4 for finalization.

#### Phase A log

Produced [spec/interaction-contract.md](../spec/interaction-contract.md), linked from [interaction.md](../spec/interaction.md) and the PROJECT.md documentation map and glossary; rows ICON-01 to ICON-31 and INSP-10 in the matrix; the DECISIONS.md row "Browsing universe and inspection metadata set", now a draft, and a new row "Inspection layer"; and the inspection layer's place in AGENTS.md, M3, and M7.

- **A separate contract file.** `interaction.md` keeps the requirements the contract must meet; the contract is the draft answer, which M4 may rewrite.
- **Matrix rows in Phase A,** because a spec change updates the matrix in the same change. The rows carry delivery milestones (M7, with M3 for persisted selection and the in-memory live stage, and M10 for the instance-root floor); Phase B fills in their fixtures and oracles.
- **Selection levels are the prim level and model kinds.** The floor is already the outermost instance root, so an instance level would duplicate the prim level.
- **Framing out of scope** (with the user). It is listed under future work in [Interaction Testing](../spec/interaction.md#interaction-testing). M4, M7, M12, and the acceptance measurement list don't name it.
- **Selection rows are behavior,** so they get fixtures and tests when delivered. Only ARCH-06, INSP-06, and ITEST-02 are contract rows, checked by this decision record.
- **Inspection is the live stage's** (with the user). A future editor reads arbitrary attributes, which only the live stage has, so nothing persisted is a view of the stage:
  - Callers browse and inspect through the USD API. The contract has no metadata set and no browsing functions; that covers the spec's "supported metadata set" item, and [Models and Unsupported Content](../spec/support/visibility.md#models-and-unsupported-content)'s kind and asset metadata, through the prim.
  - The universe, parentage, and instance roots are derived from correspondence and the generation, not stored.
  - Kinds are read on the live stage by the inspection layer. A target is an ancestor of a displayed prim, so it is always in the universe.
- **The interaction functions:** five on the core's bindings (`resolve_pick`, `select_targets`, `displayed`, `highlight_targets`, `selection_from_blender`), which route to the correspondence and inspection layers internally, and two in the Python display component (`apply_selection`, `read_blender_selection`). Expansion and floors happen inside them, and the inspection layer's kind promotion is an internal call behind `select_targets`.
- **The inspection layer is C++, behind the core's bindings** (with the user). A kind-level selection runs correspondence, then inspection, then correspondence; a Python step in the middle would be GIL-bound per-path work between two compiled calls. Correspondence is the core's, maintained from Hydra since M1b, so pipeline.md's application duty is to record which Blender resources realize the plan's correspondence. The dependency is one-way: the core calls the inspection layer, which never calls the core.
- **No interaction without a live stage** (with the user). Nothing persisted describes the stage, so a saved display with its source unavailable is plain content.
  - INSP-08 (persist enough to inspect offline) is retired; INSP-10 states that interaction requires the live stage.
  - There is no inspection snapshot: the published generation and schema-version list in [lifecycle.md](../spec/lifecycle.md), M3, and the milestones README don't list one, and the offline-persistence, failure-injection, and publication text in lifecycle.md, pipeline.md, acceptance.md (ASTD-04), strategy.md, and M12 doesn't name inspection.
- **One invariant change:** the source-authority bullet says the inspection layer is read-only (ICON-06). The ARCH-06 invariant already covers addressing, and the hierarchy-from-stage rule restates the [Evaluated Source Snapshot](../spec/pipeline.md#evaluated-source-snapshot) design note.

### Phase B — Requirement matrix

- Add M2 to `started` and give ARCH-06, INSP-06, and ITEST-02 their oracle: the contract file and this plan's decision log.
- Fill in the fixtures and oracles of the ICON rows that the contract test kit checks (Phase A added the rows themselves, since spec changes update the matrix in the same change).
- Register the interaction fixtures in `tests/fixtures/registry.py`, and add them to [Named Contract Fixtures](../testing/strategy.md#named-contract-fixtures) if the registry test requires it.
- `tools/matrix.py check` and `render`.

#### Phase B log

Added M2 to `started`; ARCH-06, INSP-06, and ITEST-02 name the draft contract and the Phase A log as their decision record. Registered three stub fixtures, `F-KIND-HIERARCHY`, `F-NESTED-SELECTION`, and `F-UNIVERSE-MEMBERSHIP`, in `tests/fixtures/registry.py` and the [Named Contract Fixtures](../testing/strategy.md#named-contract-fixtures) table. Phase C writes their scenes and generators.

- **Placeholders and empty markers are universe cases,** in `F-UNIVERSE-MEMBERSHIP`, since what they test is membership. The fixture also animates visibility, so an entry can be unresolved in one generation and resolve again in another (ICON-26).
- **Oracles on the rows the kit checks,** although their delivery milestones (M3, M7, M10) haven't started: each states what the check asserts. Rows the kit can't check through the headless functions are left to their milestone: ICON-01 (a summary), ICON-02, ICON-03, and ICON-16 (what is stored and what each layer reads, checked by M7 in the implementation), ICON-07 and ICON-24 (M3's binding and storage), and ICON-31 (M7's tool interfaces). ICON-04 and ICON-05 are process rows for M7.
- **Active object** (with the user). An active entry may be shown by several display objects, such as a component, and Blender has one active object per view layer. With exactly one, it is active; with several, all are selected and no object is active. `apply_selection` receives the active entry's display targets, since the Python component never sees source paths.
- **Milestone Tests sections name the fixtures,** as the registry test requires: M2 (the kit against its reference adapter and broken variants), M4 (each prototype's adapter), M7 (the real display), and M10 (instance-root floors). M2's deliverables list the kit.

### Phase C — Contract test kit

- **Fixture scenes** (`.usda` with purpose comments, under `tests/fixtures/scenes/interaction/`):
  - `F-KIND-HIERARCHY`, a kind hierarchy: assembly > group > component > meshes, plus a mesh under no model. Its intermediate Xforms and groups carry nothing Hydra needs to keep, so a check catches hierarchy taken from Hydra.
  - `F-NESTED-SELECTION`, nested native instances, with the same prototype used inside and outside an outer instance, and a component kind on an instance root.
  - `F-UNIVERSE-MEMBERSHIP`, universe membership: invisible subtrees, guide- and render-only prims, inactive and abstract prims, an unloaded payload, a materials scope, an organizational Xform with nothing displayed beneath, an unsupported gprim (placeholder) and an empty marker case, and visibility animated so a prim is displayed at one time code and not another.
- **Oracle**, from USD APIs only: hierarchy and kinds from the composed stage (`Usd.ModelAPI`, `Kind.Registry`); universe membership from `UsdGeomImageable.ComputeVisibility`/`ComputePurposeInfo` and instance traversal.
- **Adapter protocol and checks** in `tests/support/interaction/`: each check takes an adapter and a fixture and compares against the oracle. M4 supplies an adapter per prototype. The Blender-layer checks (`apply_selection`, `read_blender_selection`) run only against adapters that create Blender data.
- **Reference adapter** (bpy-free): a minimal display model of one element per displayed gprim copy, built by a plain stage traversal that is independent of the oracle's code. It shows the checks run.
- **Kind-selection checks** go through `select_targets` at a kind level: targets match the oracle (including a kind derived from the requested one, no matching ancestor, and a floor absent from the stage), and the stage's layers, load set, and population mask are unchanged. The core's bindings arrive with M7, so in M2 the checks run against a minimal Python reference and its broken variants.
- **Offline checks:** with no live stage, every function reports the source unavailable and stored selections are unchanged.
- **Every check must be able to fail**: a test runs each check against a deliberately broken variant of the reference adapter and asserts that it fails. Examples: a target inside an instance, a subtree expanded from a flattened hierarchy, an extra highlight target, or a render-only prim in the universe.

### Phase D — Feasibility questions for M4

Finalize the list below, link it from the [M4 milestone](../milestones/M04-prototypes.md), and close M2's decision log.

## Feasibility questions for M4 (draft)

- **Q1 — Reverse mapping under Hydra.** Do Hydra-processed paths, including aggregated native instances regrouped by inherited state, map back to source entities with their instance context for every candidate representation? Does correspondence reach every displayed source entity when Hydra drops or flattens intermediate prims? M1b's frame mapping passed nested cases; `HdxPrimOriginInfo` is deferred until Blender's USD has the `cdata()` fix ([M1b plan, Phase B log](M01b-evaluation-gate.md#phase-b-log)).
- **Q2 — Pick data.** For each representation, what does a real viewport pick supply: an object only, or also an instance or element index (Geometry Nodes instances, merged meshes)? Can `resolve_pick` reach the outermost instance root from that? M4 records the assumption as an accepted risk (ITEST-02).
- **Q3 — Partial highlighting.** Can one instance, or one model's content, be highlighted inside a shared or batched display resource without highlighting the others? Blender selection is per object.
- **Q4 — Selection input.** Native Blender selection observed through a handler, or a selection tool the extension provides? Compare what each can deliver: the instance or element under the cursor, level promotion, box and lasso selection, and cost.
- **Q5 — Mirroring partial coverage.** When one display object covers both selected and unselected entities, what does `apply_selection` set, and is the result acceptable?
- **Q6 — Universe and inspection cost at scale.** On ALab, how large is the universe under each payload policy, and how fast are deriving it from correspondence, `displayed` over a whole stage browser, and expansion? How fast is a kind-level selection end to end for a large selection, such as a box select over a whole assembly, and how much of that is the inspection layer's kind promotion?
- **Q7 — Time-varying universe.** Animated visibility changes the universe between time codes. Is per-generation membership, with unresolved selection entries kept, acceptable in use?
- **Q8 — Selection scope.** Blender selection is per view layer. Is a per-scene persistent selection compatible with mirroring into several view layers?
- **Q9 — Interaction budgets.** Provisional budgets for `resolve_pick`, `select_targets`, `displayed`, `highlight_targets`, `selection_from_blender`, `apply_selection`, and `read_blender_selection` on ALab ([Interaction Testing](../spec/interaction.md#interaction-testing)).
- **Q10 — Correspondence after reopening.** A reopened `.blend` never synchronizes, so how does the core get the published generation's correspondence back once a live stage is available: loaded from Blender data, or rebuilt from the live stage without a resync? That decides what persisted correspondence contains (M3, M5).

## Notes for M3

- Persistent selection entries need no instance context, but display-to-source correspondence still does ([M3](../milestones/M03-bindings.md): "USD paths plus instance context").
- There is no inspection snapshot format: the correspondence layer stores no inspection data, and the universe is derived from correspondence (M5, M7). Inspection is the caller's, on the live stage.
- Callers need a live stage per binding. For a file-backed binding, M3 decides which one, and whether the stage from the last synchronization stays open, with the row "Strictness of the file-backed refresh contract".

## Working agreements

- Work happens on branch `m02-contracts`. The user stages, commits, and pushes.
- Planning docs state requirements; mechanisms are suggestions for the milestone that settles them.
