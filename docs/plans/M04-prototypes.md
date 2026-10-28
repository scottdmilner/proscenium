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
- **A6, M4 started.** Every M4 row has an oracle: the contract rows (XFORM-08, PVAR-02, SHARE-06, GRAM-03, ABND-01) name the decision record that settles each, and the process rows (ARCH-08, PVAR-03, GRAM-04, APERF-01 to APERF-03, APERF-06) what the measurement records and later reruns must show. M4 is in `started`, so the checker holds its rows to that from here on. Phase A is complete: the feasibility cases are settled in the spec and built as fixtures, and the risk matrix is marked, before any representation is prototyped.

### Phase B — The object baseline

The baseline is the bridge's representation, extended until it covers every case the milestone lists or a failure is recorded.

1. **The baseline, from M1b's `apply.py`:** objects per drawn copy, shared meshes, materials, viewport and render participation, placeholders and markers, with what changed from M1b in the decision log.
2. **Correspondence in the plan:** each display element's source entity with its instance context and floor, and the browsing universe derived from it (Q1, Q10's inputs).
3. **The headless interaction functions for the baseline,** with kind promotion in C++, and the reusable checks on `F-KIND-HIERARCHY`, `F-NESTED-SELECTION`, and `F-UNIVERSE-MEMBERSHIP`. Q11 gets its new case here.
4. **The feasibility cases and the stress fixture through the baseline,** checked against USD-derived expectations, interior correctness included, in three commits:
   - every copy's world transform in the plan;
   - shear in Blender, through a parent chain;
   - each case's values where the baseline stores them. Values that need translation (UV-set names, opacity, reader fallbacks, texture sampling) are M8's and M9's.
5. **Sharing criteria:** which display state forces a distinct mesh in this representation, each with its correctness case and measured cost, and content deduplication of the 576 duplicates.
6. **Small updates within a larger scene:** what replacing one object, one asset, or one shared mesh's users costs, as input to the partition unit.
7. **Detach walkthrough:** the baseline's binding-specific controls to remove and the ordinary Blender dependencies to keep, under [Detach As-Is](../spec/lifecycle.md#detach-as-is).

#### Phase B log

- **B1, the baseline.** The baseline is M1b's representation unchanged: the bridge's planner and `apply.py`. What's new is that it runs in the test suite. The `hydra_bridge` fixture in `tests/isolated/conftest.py` builds the bridge once per run (on Linux, CI builds it in the manylinux job beside the core). `isolated/test_baseline.py` applies `F-APPEARANCE-CASES` and `F-NESTED-STRESS` in a fresh wheel process and checks what Blender holds against the fixtures and `UsdGeom`/`UsdShade`:
  - one object for each drawn copy and destination it displays in, with its source and instance context, and one hidden object for a copy shown in neither (the stress fixture's guides);
  - each face's material in each destination, preview in the viewport and full in the final render (GRAM-12);
  - meshes shared only among copies of one prototype mesh.

  In an ad hoc mutation run, each of five single changes to the expectations failed a test: swapped material purposes, reversed instance context, swapped destinations, sharing by own path, and subsets ignored.
  - **Two destinations:** a copy whose viewport and render materials differ becomes two objects sharing one mesh, each hidden in the other destination. The appearance fixture's three `PurposeBindings` meshes do this, so its 40 drawn copies are 43 objects.
  - **Sharing:** the baseline shares a mesh among the copies of one Hydra instancer only. The appearance fixture's 40 copies of 25 geometries (prototype meshes and meshes outside instances) use 36 meshes, and the stress fixture's 21 copies of 6 use 14. The likely cause, not checked: Hydra's instance aggregation splits copies whose roots differ in bindings (M1b recorded this) or inherited primvars. B5 takes this up.
  - **Placeholders and markers:** unchanged, and neither fixture has an untranslated prim; M1b's `untranslated` case covers them.
  - Appearance values (transforms with shear, display color, shading) are B4's.
- **B2, correspondence in the plan.** Each plan object is one display element. Its source and instance context, which M1b's planner already gave it, are its source entity. The bridge's new `correspondence.h/.cpp` derives the rest when planning ends:
  - each object's floor, the first of its instance context or else its source;
  - the browsing universe: the floors of the viewport's objects and every prefix of them, sorted so each prim's subtree is one contiguous range for B3's expansion.

  Python reads them as each object's `floor` and the plan's `universe`. `isolated/test_correspondence.py` compares them with the M2 oracle on the three interaction fixtures and the two appearance fixtures, at every time code each publishes. The viewport's objects are exactly the oracle's display elements, every object's floor is the oracle's, and the universe is the oracle's. In an ad hoc mutation run of the C++, each of three single changes failed a test: render-only objects in the universe, the innermost instance root as the floor, and the universe built from sources rather than floors.
  - **Q1, for the baseline:** on these fixtures, correspondence reaches every displayed entity. That includes organizational prims Hydra doesn't keep (`F-KIND-HIERARCHY`), native instances Hydra aggregates (`F-NESTED-SELECTION`), and visibility animated between generations (`F-UNIVERSE-MEMBERSHIP`). It holds because the planner maps Hydra prims back to USD paths before anything else reads them, so nothing downstream sees Hydra's paths.
  - **Q10's inputs:** floors and the universe derive from each element's source, instance context, and viewport participation, with no stage. `apply.py` already writes the source and instance context onto each object, and Blender holds its viewport flag. So a reopened `.blend` could in principle rebuild the universe from its own data; that is an inference, not checked. Phase F answers Q10.
  - **Explicitly visible guides:** the spec shows a guide in the viewport when its effective visibility is explicitly visible ([Visibility and Purpose](../spec/support/visibility.md#visibility-and-purpose)), and so does the bridge. `support/interaction_oracle.py` now asks the same, through `ComputeEffectiveVisibility` for each prim's purpose, and `F-UNIVERSE-MEMBERSHIP` has a case for it: `VisibleGuide`, a guide subtree made visible by `guideVisibility` on its root (with the user). VIS-04 uses the fixture. The old rule, and the case with `guideVisibility` set to `inherited`, each failed tests (ad hoc).
- **C++ checks, before B3 (with the user).** B3 prototypes kind promotion in the bridge's C++ as a model of M7's inspection layer, so the bridge now meets the core's C++ rules.
  - **Hooks:** clang-format and clang-tidy run on the bridge as on the core. The bridge keeps the 4-space style it was written in (its own `.clang-format`) and shares the checks, in a `.clang-tidy` moved from the core to the repository root, where clang-tidy and editors find it for both. `tools/clang_tidy.py` checks both projects, one process per source in parallel (39 s for both on this Mac, one run).
  - **Checks added for both:** the C++ Core Guidelines group, among them owning memory, the rule of five, casts, pointer arithmetic, and non-const globals. Left out, with reasons in `.clang-tidy`: unchecked container access and constant array indices (they flag every subscript, though the code validates indices first), reference and const data members, magic numbers, easily swappable parameters, and the analyzer's leak check, which fires inside USD's `TfNotice::Register`. The core needed no change.
  - **Pointers:** no owning raw pointer remains but `TfCreateRefPtr(new ...)`. Vectors of never-null record pointers became `std::reference_wrapper`s (`PrimRefs`), the planner's nullable `slots` argument a reference whose empty value marks a placeholder, and the source-info filter's `const_cast` of `this` a weak self pointer set once in `New`. Each remaining raw pointer is a nullable lookup or optional argument whose declaration says what null means. AGENTS.md states the rule.
  - **The rest:** about 200 findings, fixed or, where the code needs the construct, marked with a `NOLINT` naming its check and reason (USD's reserved override names, a function address for `dladdr`, the stringizing macro, recursion bounded by `kMaxDepth`, two by-design globals).
  - **Unchanged behavior:** M1b's 42 loading, 20 prototype, and 131 correctness checks pass in the wheel and the binary, and on ALab (`entry.usda`, load-all) an order-free digest of the plan's 7,315 objects, 3,943 meshes, 806 materials, and 11,255 diagnostics is identical to the committed bridge's (ad hoc).
- **B3, the headless interaction functions for the baseline.**
  - **The checks** are in `tests/support/interaction_checks.py`, written once against the seven functions. A representation passes a `Display` adapter. The adapter publishes generations of a fixture's live stage, says what a pick on each Blender object supplies, and says which viewport elements each object and display target shows, by its own record of what it built. Each check names the matrix rows it covers:
    - picks (INSP-01, ICON-01, ICON-19), and picks after renaming and reparenting (ICON-17);
    - `displayed` over every composed prim and probe (ICON-11 to ICON-15);
    - `select_targets` at every level, and the fixtures' cases (ICON-18, ICON-20, ICON-21), including an absent floor;
    - a read-only stage (ICON-06);
    - exact highlighting of every path and of each level's targets (ICON-10, ICON-22, ICON-23, INSP-02);
    - mirroring into Blender (ICON-27 to ICON-29), and reading it back (ICON-30).

    Each check runs at every time code a fixture publishes, so `F-UNIVERSE-MEMBERSHIP`'s animated visibility checks membership per generation (ICON-25 and ICON-26's basis); resolving M3's stored persistent selection is not exercised.
  - **The baseline's core functions** are in the bridge's C++: `interaction.h/.cpp` over the plan's correspondence, bound as `_hydra_bridge.Interaction(stage, plan)`. Kind levels go to `inspection.h/.cpp`, which models M7's inspection layer: it reads only the stage it is given and includes nothing else of the bridge, so paths never pass through Python between the two. The correspondence now also holds the viewport's elements sorted by floor, so a target's expansion is one range, as in the universe.
  - **The Python display component** is the bridge's `selection.py`.
  - `isolated/test_interaction.py` runs each check on the three interaction fixtures in a fresh wheel process; `nested_selection` and `kind_hierarchy` have the absent-floor case, `universe_membership` doesn't. In an ad hoc mutation run, each of 14 single changes failed a test. The C++ changes were promotion from the floor alone, exact kind matching, promotion from the source, the innermost instance root as the floor, expansion without the target, expansion stopping at one element, a level-blind or active-blind `selection_from_blender`, and everything displayed. The Python changes were the active object kept with several display objects, unmanaged objects deselected, inverted selection, every managed object read as selected, and picks resolved by object name.
  - **What a pick supplies (Q2, for the baseline):** the object. The object names its display element, its plan index, which `apply.py` records as `proscenium_element`, and `resolve_pick` reaches the outermost instance root from it through the plan. That a real viewport pick yields the object is assumed, not checked: windowed tests are out of scope.
  - **Partial coverage (Q3, Q5, for the baseline):** none arises. Each object shows exactly one display element, so highlighting is exact, and each object is wholly in or out of a selection.
  - **Settled here for the baseline, for review:**
    - An object's coverage is the viewport elements it shows. A render-only object, such as one of a copy's two destination objects, covers none: it is never a display target, and `apply_selection` deselects it.
    - With no active entry, or one with no display object, no managed object stays active, and an unmanaged active object is kept.
  - **Element identities** are plan indices, which name elements within one generation only; a pick held across a republish could name another element. Production identities need M3's resource identities. Not checked.
  - **Without a live stage,** each of the five core functions raises `RuntimeError`. This was smoke-run once, ad hoc; `F-OFFLINE`'s checks (ICON-08, ICON-09) are M7's.
  - **Paths in and out (with the user).** The bridge takes paths as `Sdf.Path` or strings, through Sdf's converter, and returns strings.
    - **Why strings out:** Python stores paths only where strings are needed (Blender ID properties, JSON, M3's records, the interaction oracle), and the path algebra is in C++.
    - **Why not `Sdf.Path` out:** an `Sdf.Path` equals its string but hashes differently, so every set or dict mixing the two misses matches silently. Trying it, two of M1b's known-gap checks went vacuous until their paths were converted. The time cost was small: on ALab (ad hoc, one run, median of 5), `apply.py`'s conversions back to strings took 15 ms for 7,317 objects, and building `plan.objects` took the same 23–25 ms either way. M7 should weigh the hashing hazard before its bindings return `Sdf.Path`.
- **B4, the feasibility cases and the stress fixture through the baseline.** What B4 checks and how, settled with the user:
  - **Storage only:** each case's value is checked where the baseline stores it, against the fixtures and USD's APIs. Values that need translation are M8's and M9's: UV-set names, opacity, reader fallbacks, and which UV map a texture samples.
  - **Shear (XFORM-03), through a parent chain (with the user).** A Blender object holds only location, rotation, and scale. The plan's matrices were right, but in one ad hoc run every sheared copy the depsgraph evaluated lost its shear.
    - **The chain:** `apply.py` now splits a sheared copy's world transform by SVD into rotation, scale, and rotation. A parent empty takes the first rotation, the scale, and the translation, and the object the second rotation, so neither holds shear. A reflection moves into a negative scale.
    - **The parent:** it can't be selected, so a pick lands on the object. It records its copy's source as `proscenium_shear_of`, and has no `proscenium_element`, so the selection functions leave it alone.
    - **Cost:** one empty per sheared object. Mesh sharing is unchanged. The stress fixture has 12 sheared copies of 21.
    - **The check:** `isolated/test_baseline.py` reads every object's world transform once the depsgraph has evaluated it, with every object shown, since hidden ones aren't evaluated. It compares them with `UsdGeom` on both fixtures, and checks that exactly the sheared copies have a parent. With the chain disabled, the stress fixture fails (ad hoc).
    - **The shear test:** it runs on every object, so it uses `mathutils`. On 7,317 matrices, ALab's object count, it took 6.7 ms, against 129 ms for numpy (ad hoc, median of 5).
    - **For B7:** the parents are ordinary Blender parenting, which detach could keep.
  - **Transforms in the plan, and OpenUSD #862 (with the user).** `isolated/test_baseline.py` compares every copy's world transform in the plan with `UsdGeom.XformCache`, on both fixtures. That covers shear, negative and nonuniform scale, and a reset stack inside instances (XFORM-01 to XFORM-03).
    - **The bug:** Hydra ignores a reset stack inside a native instance ([OpenUSD #862](https://github.com/PixarAnimationStudios/OpenUSD/issues/862), open). It applies the instance's transform anyway, and its flattening marks every transform as resetting the stack, so no consumer can tell. In the stress fixture, each `Pin` was placed by its instance root's transform.
    - **Whose behavior:** composition and `UsdGeom` in Blender's bundled USD honor the reset, and UsdImaging doesn't. In one ad hoc run, Blender's own USD importer didn't honor it either, in its own code, since it reads `UsdGeom`. The bridge follows `UsdGeom`, as the oracles do.
    - **The workaround:** the source-info filter records which prims reset the stack. The planner drops the instance's transform for a copy under a reset inside its prototype, and `Expand` does the same for an inner instance root.
    - **The checks:** a known-gap check asserts that Hydra's own composition is still wrong for exactly the copies under a reset inside an instance. With the workaround disabled, the transform check fails (ad hoc).
    - **Not exercised:** no fixture has a reset at or above an inner instance root inside an outer prototype, or an edit to `xformOpOrder` between captures.
- **Q11, kinds outside a valid model hierarchy (with the user).** A kind level matches a prim's authored kind, whether or not the prim is in a valid model hierarchy (`UsdPrim::IsModel`). The rule is stated in [Selection](../spec/interaction-contract.md#selection), ICON-21's oracle, and the DECISIONS.md row "Browsing universe and inspection metadata set". So a component-level pick on a component nested in another selects the nested one, as the oracle and the bridge already did. Under the other rule, it would select the outer one.
  - **In ALab** (`entry.usda`, load-all, one ad hoc survey), 594 of 1,877 authored components are outside a valid hierarchy:
    - 413 under point-instancer prototypes;
    - 180 directly inside another component;
    - 1 under a Scope with no kind.

    12 of 60 groups are outside one too. ALab's light-rig kinds aren't registered, so no level matches them.
  - **The case:** `F-KIND-HIERARCHY` gains `Vase`, a component inside the component `Table`, and `Crate`, a component under `Debris`, which has no kind. The fixture names both, and `bpy_free/test_interaction_fixtures.py` checks that `IsModel` rejects them. With the valid-hierarchy rule planted in the bridge's C++, `kind_hierarchy`'s `select_targets` and `selection_from_blender` checks fail (ad hoc).

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
