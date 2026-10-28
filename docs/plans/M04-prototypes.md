# M4 — Display representation and interaction feasibility prototypes: plan

How M4 will choose a display representation and partition unit, finalize the interaction contract, and record the evidence for both, and the order of work. Requirements are in the [M4 milestone](../milestones/M04-prototypes.md); where this plan and a requirement file disagree, the requirement file wins. Mechanisms named here are suggestions unless marked settled. Each phase gains a short decision log once work starts, in the style of the [M3 plan](M03-bindings.md).

M4 delivers the matrix rows whose `delivery` is M4: ARCH-08, XFORM-08, PVAR-02, PVAR-03, SHARE-06, GRAM-03, GRAM-04, ABND-01, and the Performance process rows (APERF-01 to APERF-03, APERF-06). It qualifies M2's contract rows ARCH-06, INSP-06, and ITEST-02, and settles the DECISIONS.md rows it owns or co-owns: "Partition unit", "Geometry sharing", "Support cases for backend feasibility", "Time-sampled data representation", "Bounds comparison contract and tolerances", "Interaction feasibility evidence", "Browsing universe and inspection metadata set" (finalization), and the M4 measurements named by "Inspection layer" and "Python-only implementation".

## Starting point

- **M1b's bridge already is a first object baseline.** `tools/feasibility/hydra_bridge/apply.py` builds one Blender object per drawn copy, with meshes shared per prototype geometry and material variant, and no collection instances. On ALab it built 3,946 meshes and 7,018 objects in 3.50 s and 3,112 MB, against the matched importer's 3.24 s and 1,798 MB ([record](../feasibility/runtime-record.md#measurements-m1b-phase-e)). Its plan holds 576 meshes whose content duplicates another's. On instances-1000 it kept per-instance materials with 2 meshes for 10,000 objects, which the importer's scene instancing drops.
- **The bridge's planner already names each object's sources:** the gprim and its native-instance roots, outermost first. That is most of the correspondence the interaction functions need.
- **The product core has no evaluation yet.** `src/proscenium/core/` holds the stage handle and source access; M6 builds evaluation and planning. M3's manifests, ownership index, and persistent selection exist in `src/` and can hold a prototype's entries.
- **The interaction fixtures and oracle exist** (`tests/fixtures/interaction.py`, `tests/support/interaction_oracle.py`). `F-NESTED-STRESS` is a registered stub owned by M10.

## Settled with the user (2026-10-27)

1. **Prototypes extend the M1b bridge in `tools/feasibility/`.** They are evidence, not product code (the milestone's first scope limit), and the bridge already captures, plans, and applies every case M4 needs. M6 and M7 write the product versions from the decisions M4 records.
2. **The headless interaction checks are written once, against the seven functions.** A reusable module in `tests/support/` takes an implementation of `resolve_pick`, `select_targets`, `displayed`, `highlight_targets`, `selection_from_blender`, `apply_selection`, and `read_blender_selection`, and checks it against the M2 oracle on each interaction fixture. M4's tests pass each prototype's adapter; M7 and M10 pass the real display. The tests that run native prototype code go in `isolated/`.
3. **Correspondence and kind promotion are prototyped in the bridge's C++,** so Q6 and Q9 measure compiled code, as the inspection layer will be. M7 builds the inspection layer itself as its own library.
4. **Provisional budgets** (Phase C), from M1b's measurements: initial synchronization on ALab within 1.5× the matched importer's time and 2× its peak memory; where the representation can't reach either, the log records the measured ratio and what it would take, and the user decides. M1b's bridge measured 1.08× in time and 1.73× in peak memory. The other budgets: an unchanged refresh no slower than the initial synchronization, a small update in ALab at least ten times faster than a full rebuild, and each interaction function, with the Blender updates it triggers, within 50 ms for a single pick or entry and 250 ms for a whole-assembly selection on ALab. Phase 1 records these as baselines, not gates (APERF-03).
5. **Alternatives only where the baseline fails.** Geometry Nodes batching or a hybrid is prototyped only for a requirement the baseline fails or a measured cost over budget, and only as far as that question needs.

## Phases

Each phase ends with a review by the user before the next starts. Each phase lists its commits in order. Every commit is one feature and passes `pre-commit` and the test suite on its own:

- A spec change lands with its matrix rows, its `invariants.md` bullet, and its DECISIONS.md row.
- A new fixture lands with its registry entry, its Named Contract Fixtures row, its mention in the milestone's Tests section, and a row that uses it.
- Code lands with its tests.
- A decision lands with its line in the phase's decision log.

If a commit grows past one feature, it splits, and this list is updated in the same commit.

### Phase A — Representation feasibility cases and the risk matrix

The milestone freezes the support cases before any backend is chosen, so this phase writes no prototype code.

1. **The M4 plan:** this file.
2. **The risk matrix.**
   - A `risk: high` field on matrix rows, which `tools/matrix.py` validates and renders as a column, as the comment at the top of `requirements.yaml` anticipates.
   - The risk matrix in this plan: each high-risk requirement, why the representation could fail it, and which phase tests it. Candidates: per-instance appearance under sharing (SHARE), nested instancing with shear and negative determinants (XFORM), viewport and render participation from one snapshot (visibility and purpose), correspondence surviving batching (INSP), partial highlighting and mirroring (ICON), whole-generation publication and replacement (TXN-05, TXN-06), managed resources with unmanaged users (OWN-08), detach with shared content (DET), resource stability (STAB), runtime references across undo (UNDO-07), and ALab scale.
3. **Primvar feasibility cases** in [Primvar Support Matrix](../spec/support/geometry.md#primvar-support-matrix): geometry sharing, named UVs, face-level material assignments, and primvars driving per-instance appearance, each with its value types, interpolation, indexing, inheritance, Blender domain, and how varying data reaches the display. New PVAR rows, and the DECISIONS.md row "Support cases for backend feasibility".
4. **Connection feasibility cases** in [Connection Grammar](../spec/support/materials.md#connection-grammar): per-instance appearance, named UV selection and primvar readers, face-level assignments, and sharing, with shader identifiers, connections, reader types, and the `displayColor`/`displayOpacity` rules. New GRAM rows, and the same DECISIONS.md row.
5. **Fixtures for the feasibility cases.** A new appearance fixture (`F-APPEARANCE-CASES`) for the cases in items 3 and 4, including a multi-mesh, multi-material asset; and the `F-NESTED-STRESS` generator, which M4 co-owns with M10: shear, negative determinants, nonuniform scale, reset transform stacks inside instances, nested instances with differing appearance, and separate viewport and render purposes. Each with its rows and an oracle from USD.
6. **Oracles on M4's rows, and M4 started:** every M4 row gets its oracle, M4 joins `started`, then `tools/matrix.py render`.

#### Phase A log

- **A1, the plan,** with the five choices settled with the user above.
- **A2, the risk matrix.** Rows take an optional `risk: high`; `tools/matrix.py` refuses any other value, renders a Risk column, and counts the marked rows in the view's summary. The marked rows are grouped in the [Risk matrix](#risk-matrix) below by why a representation could fail them, with the step that tests each. The field holds no reason, so the reasons stay in one place. It is a label: nothing checks that a marked row was tested (with the user).
- **A3, primvar feasibility cases.** Seven cases in [Representation Feasibility Cases](../spec/support/geometry.md#representation-feasibility-cases), rows PVAR-04 to PVAR-10, each delivered by the milestone that displays it (M8 for one mesh, M10 where instances are involved). Each case states what the display shows; for a value per drawn copy, where it is stored is the representation's choice, recorded with the sharing criteria (B5). Chosen from an ad hoc survey of ALab under load-all, through instance proxies (7,484 meshes):
  - **UVs:** `st` as indexed faceVarying `texCoord2f[]` on 6,984 meshes, `perfuv` likewise on 5,725, and `st` as `float2[]` on 308 and as vertex on 162. Every `UsdPrimvarReader_float2` names `st` (845) or `perfuv` (422) by a constant `varname`, so named UV selection is in production use.
  - **Display color:** on meshes only, constant (3,708, 41 of them indexed), uniform (1,497), vertex (341), and faceVarying (72); `displayOpacity` likewise.
  - **Not in ALab:** GeomSubsets (none on any mesh) and primvars on instance roots, so face assignments and per-instance appearance come from fixtures only.
  - **UV-set names (with the user).** By USD's typing a `float2[]` primvar is not a UV set, so a binding setting decides: a list of globs, matched case-insensitively against whole names, that also take `float2[]` primvars with vertex, varying, or faceVarying interpolation. The default, an empty list, keeps USD's typing; `st`, `st_*`, `*uv`, `uv*` covers ALab without `st*`'s matches such as `stretch`. It joins the payload policy in the requested settings (BIND-11, GEOM-13, GEOM-14, and the API-03 and STATE-01 lists), and DECISIONS.md has a row "UV-set names". M8 implements it; the binding records gain the field then, with a migration, and Phase F's compatibility review lists it.
- **A4, connection feasibility cases.** Eight cases in [Representation Feasibility Cases](../spec/support/materials.md#representation-feasibility-cases), rows GRAM-05 to GRAM-12. Shader graphs alone (normal maps, scale and bias, texture transforms, displacement) don't bear on the representation and stay M9's. From the same survey:
  - **Textures:** every `UsdUVTexture` (3,409) takes `st` from a `UsdPrimvarReader_float2`, wraps `repeat`, and leaves `sourceColorSpace` unauthored; 422 author `scale` and `bias`.
  - **Surface inputs:** textures feed `diffuseColor` (1,266, from `rgb`) and `roughness`, `metallic`, `occlusion`, `ior` (422 each, from `r`), `normal` (422), and `opacity` (32); constant inputs are `ior` and `roughness` (844 each).
  - **Bindings by purpose:** 3,287 `material:binding:preview` and 1,853 `material:binding:full`, almost all on Xforms, and 3 all-purpose. So the viewport and the final render can show different materials on one prim, which a representation with one material per object slot can't show without a second object or mechanism. The case settles which binding each destination shows: preview in the viewport, full in the final render, each falling back to the all-purpose binding as `UsdShade` resolves purposes.
- **A5, fixtures for the feasibility cases.** `F-APPEARANCE-CASES` (`tests/fixtures/appearance.py`, `scenes/appearance/appearance.usda`) has one subtree of `/World` per case, a two-mesh, two-material prototype among them, and lists every mesh's material so none goes unchecked. `F-NESTED-STRESS`, which M4 now co-owns with M10, has three copies of one prototype under a shear matrix, a negative nonuniform scale, and a rotation inside a nonuniform scale, each holding a reset transform stack, nested instances whose mesh mirrors again, and proxy, render, and guide meshes. Both generators yield their facts written out by hand; `bpy_free/test_appearance_fixtures.py` checks them against USD's own APIs, with UV sets by the spec's rule. In an ad hoc mutation run, each of ten single changes to a fact or a scene (a face's material, a reader's fallback, a UV set, a purpose binding, a sharing set, the reset stack, an inner root's color, a primvar's type, a reader's `varname`, a mesh's purpose) failed a test. The fixtures join the rows of their cases (PVAR-04 to PVAR-10, GRAM-05 to GRAM-12, GEOM-13, GEOM-14; XFORM-02 and VIS-03 for the stress fixture) and the M4 milestone's Tests section. They have no cases yet: their rows' delivering milestones (M8 to M10) declare them.

### Phase B — The object baseline

The baseline is the bridge's representation, extended until it covers every case the milestone lists or a failure is recorded.

1. **The baseline, from M1b's `apply.py`:** objects per drawn copy, shared meshes, materials, viewport and render participation, placeholders and markers, with what changed from M1b in the decision log.
2. **Correspondence in the plan:** each display element's source entity with its instance context and floor, and the browsing universe derived from it (Q1, Q10's inputs).
3. **The headless interaction functions for the baseline,** with kind promotion in C++, and the reusable checks on `F-KIND-HIERARCHY`, `F-NESTED-SELECTION`, and `F-UNIVERSE-MEMBERSHIP`. Q11 gets its new case here.
4. **The feasibility cases and the stress fixture through the baseline,** checked against USD-derived expectations, interior correctness included.
5. **Sharing criteria:** which display state forces a distinct mesh in this representation, each with its correctness case and measured cost, and content deduplication of the 576 duplicates.
6. **Small updates within a larger scene:** what replacing one object, one asset, or one shared mesh's users costs, as input to the partition unit.
7. **Detach walkthrough:** the baseline's binding-specific controls to remove and the ordinary Blender dependencies to keep, under [Detach As-Is](../spec/lifecycle.md#detach-as-is).

### Phase C — Budgets and measurements

1. **Provisional budgets,** as settled above, recorded with the measurements that test them.
2. **The measurement harness,** extending the bridge's `measure/`: initial construction, unchanged refresh, a small update, each interaction function with its Blender updates, peak memory while two generations coexist, and `.blend` size, on ALab and on generated fixtures of controlled size, repeated in the Blender binary on the reference hardware (APERF-01, APERF-02, APERF-06).
3. **Interaction at scale (Q6, Q9):** the universe's size under each payload policy, `displayed` over a whole stage browser, expansion, and a kind-level selection over a whole assembly, with the kind promotion's share.
4. **The first ownership lookup after an undo at ALab scale,** with the baseline's manifest entries written through M3's runtime, against the interaction budget. If it is over, the revision-token option in the [M3 plan](M03-bindings.md), Phase E.

### Phase D — Targeted alternatives

Only for the requirements or costs Phases B and C found failing; this phase may be empty, and the log says so.

- Batching (such as Geometry Nodes instances of shared meshes) or a hybrid partitioned by asset or by independently updated subtree, prototyped as far as the failing question needs.
- Each alternative answers the same list as the baseline: multi-mesh, multi-material assets, per-instance shading, pick data (Q2), partial highlighting and mirroring (Q3, Q5), small updates, detach, and the interaction checks.

### Phase E — Time-sampled data

1. **Per-time-code snapshots against animation data:** keyframed transforms, mesh cache modifiers, and Geometry Nodes baking, on the bridge's animation case and a scaled fixture. Playback, construction, memory, and `.blend` size are measured separately.
2. **The decision** in the row "Time-sampled data representation" (XFORM-08), with the time-code-to-frame mapping for any approach adopted and how it meets the requirements in that row. A mesh cache modifier that reads the USD file first reconciles the requirements listed in M1b.

### Phase F — Decisions and finalization

1. **The partitioning decision record:** the partition unit, what a partition owns, and how it is replaced as a whole, in DECISIONS.md "Partition unit" and the Glossary.
2. **Answers to Q1–Q11** and the finalized [interaction contract](../spec/interaction-contract.md), with its draft notice removed, its rows, and its invariant if a guarantee changes. The pick-data assumption is recorded as an accepted risk (ITEST-02).
3. **Compatibility review of M3's identifiers and schemas** against the finalized contract and the partition unit, with any required change made before M5 starts. The requested settings' new UV-set names are listed for M8 (A3).
4. **The bounds comparison contract** in [acceptance.md](../testing/acceptance.md#bounds-comparison-contract) (ABND-01), using M1's finding on `BBoxCache` under rotation.
5. **Limitations and fallbacks,** and the "Python-only implementation" row's measurements.
6. **Notes for M5 to M10** in their milestone files, and the close of this plan.

## Risk matrix

The requirements a display representation is most likely to fail, each marked `risk: high` in [requirements.yaml](../testing/requirements.yaml). Every evaluated representation is tested against all of them; the phase column names where the baseline is.

| Risk | Rows | Why a representation could fail it | Tested in |
|---|---|---|---|
| Sharing against per-instance appearance | SHARE-01, SHARE-02, SHARE-04, INST-07, MAT-06, MAT-09, PVAR-08, PVAR-09, GRAM-07, GRAM-08, GRAM-10 | Deduplicating meshes puts appearance on objects or materials; a primvar that drives a material input per instance must reach the shader without a distinct mesh per instance, and batching must keep distinct assignments apart. | B4, B5 |
| Nested, multi-mesh, multi-material instances | INST-01, INST-02 | Each drawn copy of nested contents needs its own transform, visibility, and inherited bindings, at ALab's scale of copies. | B4, C2 |
| Transforms objects can't hold | XFORM-02, XFORM-03, CONV-03 | A Blender object's transform is location, rotation, and scale, so shear may need parenting or baked geometry (to be checked); reset transform stacks inside instances and the correction matrix must still reach every copy. | B4 (`F-NESTED-STRESS`) |
| Two destinations from one snapshot | VIS-03, GRAM-12 | Viewport and render participation differ per prim and purpose, and the viewport and final render may show different materials on one prim, while a Blender object has one visibility per destination and one material per slot. | B1, B4 |
| Correspondence and selection | INSP-01, INSP-02, INSP-04, INSP-05, ICON-23, ICON-27, ICON-30 | Batching and merged meshes hide which instance or element a pick hit, and per-object selection can't highlight part of a shared resource exactly (Q2, Q3, Q5). | B3, D |
| Publication and replacement | TXN-05, TXN-06 | Preparing a generation beside the published one, and switching it whole, depends on what a partition owns and how it is replaced. | B6, F1 |
| Managed resources with unmanaged users | OWN-08 | An unmanaged object using a shared mesh or material forces replacement instead of an in-place change. | B6 |
| Detach | DET-03, DET-05 | Binding-specific mechanisms, such as node groups or drivers, may not survive detach as ordinary Blender data. | B7 |
| Bounds and reopening | ASTD-02, ASTD-04 | Bounds must be comparable per model in world space, and the saved display and correspondence must reopen without the source, at a `.blend` size that holds up. | B4, C2, F4 |
| Time-varying content | XFORM-06 | Per-time-code snapshots and animation data trade construction, playback, memory, and `.blend` size differently. | E |
| Phase 2 churn and performance | AFF-02, AFF-03, PH2-04 | The partition unit bounds how much an edit replaces and whether untouched resources keep their identities. | B6, C2 |

## Working agreements

- Work happens on branch `m04-prototypes`. The user stages, commits, and pushes.
- Planning docs state requirements; mechanisms are suggestions for the milestone that settles them.
- Evidence claims only what a check tested; single runs and inferences are labeled.
