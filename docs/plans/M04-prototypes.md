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
   - each case's values where the baseline stores them. Values that need translation (UV-set names, non-constant opacity, reader fallbacks, texture sampling) are M8's and M9's.
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
  - **Storage only:** each case's value is checked where the baseline stores it, against the fixtures and USD's APIs. Values that need translation are M8's and M9's: UV-set names, non-constant opacity, reader fallbacks, and which UV map a texture samples.
  - **Shear (XFORM-03), through a parent chain (with the user).** A Blender object holds only location, rotation, and scale. The plan's matrices were right, but in one ad hoc run every sheared copy the depsgraph evaluated lost its shear.
    - **The chain:** `apply.py` now splits a sheared copy's world transform by SVD into rotation, scale, and rotation. A parent empty takes the first rotation, the scale, and the translation, and the object the second rotation, so neither holds shear. A reflection moves into a negative scale.
    - **The parent:** it can't be selected, so a pick lands on the object. It records its copy's source as `proscenium_shear_of`, and has no `proscenium_element`, so the selection functions leave it alone.
    - **Cost:** one empty per sheared object. Mesh sharing is unchanged. The stress fixture has 12 sheared copies of 21.
    - **The check:** `isolated/test_baseline.py` reads every object's world transform once the depsgraph has evaluated it, with every object shown, since hidden ones aren't evaluated. It compares them with `UsdGeom` on both fixtures, and checks that exactly the sheared copies have a parent. With the chain disabled, the stress fixture fails (ad hoc).
    - **The shear test:** it runs on every object, so it uses `mathutils`. On 7,317 matrices, ALab's object count, it took 6.7 ms, against 129 ms for numpy (ad hoc, median of 5).
    - **Detach** keeps the parents, as ordinary Blender parenting (B7).
  - **Appearance values where the baseline stores them.** `isolated/test_baseline.py` checks each case against the fixtures' facts and USD. Values held once per copy are on the copy's object, so copies of one shared mesh keep their own values:
    - **Display color and opacity (PVAR-07, PVAR-08, GRAM-05):** a constant value is an ID property of the copy's object, and a constant color and opacity are also the object's color and alpha, which Solid shading's Object color shows. Any other interpolation is a mesh attribute on its domain, with USD's values. This includes inherited values through nested instances: the nearest opinion wins, the mesh's own, then the inner root's, then the outer's.
    - **Reader primvars (PVAR-09, GRAM-08, GRAM-11):** each copy's own `tint`, `rough`, or `displayColor`, inherited from its instance root, is an ID property of its object, which an Attribute node of type Object can read. A copy with none has no property. So the reader's fallback must come from M9's translated material, or be written per copy: which one is M9's to settle.
    - **Named UVs (PVAR-06, and GRAM-09's UV map):** each UV set is a UV map with its primvar's name and USD's value at every corner, indexed and vertex sets included. The texture's `perfuv` map is there; sampling through it is M9's.
    - **Stress copies:** each shows its own inherited constant color.
    - **Already covered by B1:** each copy's materials, per face and per destination: material per instance, face assignments, and purpose bindings (GRAM-07, GRAM-10, GRAM-12, PVAR-10).
    - **Known differences, recorded and not fixed:**
      - The baseline makes every `float2[]` primvar with a per-corner or per-point interpolation a UV map. This is `Untyped`'s `offset` and `ST`, where the default UV-set names take none (A3). The test pins this behavior until M8 implements the setting.
      - Nothing displays a non-constant opacity (M8). The baseline stores it as a float attribute, apart from the color attribute.
    - **The checks:** in an ad hoc mutation run of `apply.py`, each of five single changes failed a test. They were no constant-primvar properties, no object color, an object alpha of 1, no attributes, and attribute values reversed.
  - **Transforms in the plan, and OpenUSD #862 (with the user).** `isolated/test_baseline.py` compares every copy's world transform in the plan with `UsdGeom.XformCache`, on both fixtures. That covers shear, negative and nonuniform scale, and a reset stack inside instances (XFORM-01 to XFORM-03).
    - **The bug:** Hydra ignores a reset stack inside a native instance ([OpenUSD #862](https://github.com/PixarAnimationStudios/OpenUSD/issues/862), open). It applies the instance's transform anyway, and its flattening marks every transform as resetting the stack, so no consumer can tell. In the stress fixture, each `Pin` was placed by its instance root's transform.
    - **Whose behavior:** composition and `UsdGeom` in Blender's bundled USD honor the reset, and UsdImaging doesn't. In one ad hoc run, Blender's own USD importer didn't honor it either, in its own code, since it reads `UsdGeom`. The bridge follows `UsdGeom`, as the oracles do.
    - **The workaround:** the source-info filter records which prims reset the stack. The planner drops the instance's transform for a copy under a reset inside its prototype, and `Expand` does the same for an inner instance root.
    - **The checks:** a known-gap check asserts that Hydra's own composition is still wrong for exactly the copies under a reset inside an instance. With the workaround disabled, the transform check fails (ad hoc).
    - **Not exercised:** no fixture has a reset at or above an inner instance root inside an outer prototype, or an edit to `xformOpOrder` between captures.
- **B5, sharing criteria (with the user).** In the baseline, copies share a mesh exactly when their mesh content is equal, byte for byte: positions, corners, faces, each face's material slot and the slot count, the non-constant primvars as attributes, the subdivision scheme, and sidedness. Everything else that differs per drawn copy is on its object: the transform (with a sheared copy's parent empty), constant primvars with display color and opacity, the material in each slot for each destination (slots link to the object), visibility, and purpose. So per-copy appearance never needs a distinct mesh in this representation, and different content is the only distinct-resource case.
  - **The planner:** `mesh_sharing.h/.cpp` hashes each built mesh in the parallel pass, with `ArchHash64` over everything the content compares. `AddMesh` looks the hash up among the plan's meshes and reuses one only after comparing it byte for byte, skipping arrays that share one buffer. A collision would merge two displays, so a hash alone is never trusted. That reuse applies whatever prim and Hydra instancer a mesh comes from, which includes the copies Hydra's instance aggregation splits (B1).
    - **Its cost:** O(total bytes) of hashing, split across threads. Each mesh then takes an expected O(1) lookup and one serial comparison per true duplicate. The work is per Hydra mesh, not per copy, since copies within one instancer are already one mesh.
  - **The fixtures:** each of `F-APPEARANCE-CASES`'s sharing sets holds equivalent uses, which must share; a representation may share more where the display stays correct. So `EqualContent`'s `MeshC`, which differs only in a constant `displayColor`, shares the mesh of `MeshA` and `MeshB`. New meshes that differ from `MeshA` in one way each keep their own: `MeshD` only in its vertex `st` values, `MeshE` only in its subdivision scheme, and `MeshF` only in its sidedness. The appearance fixture's 43 copies use 15 meshes (39 without deduplication), from the ad hoc counts of 13 and 37 before `MeshE` and `MeshF`, each of which adds one copy and one mesh, and the stress fixture's 21 copies use 1 (14), since all its meshes are one quad.
  - **The check:** `isolated/test_baseline.py` asserts that each mesh's copies have equal content as USD computes it (points, topology, orientation, each face's slot from its materialBind subsets, non-constant primvars, normals, subdivision scheme, sidedness), that no two meshes hold equal content, and that each sharing set is one mesh. In an ad hoc mutation run of `mesh_sharing.cpp`, each of six single changes failed it: no deduplication, and positions, the slot partition, attribute values, the subdivision scheme, or sidedness ignored in both the hash and the comparison.
    - **Not caught:** a comparison that always agreed passed: only a hash collision reaches it, and no fixture has one.
  - **Cost on ALab** (the measurement entry point, three runs each, medians, ad hoc on one Mac): plan meshes fell from 3,945 to 3,360, and Blender's vertices from 7.62 million to 6.52 million. In paired runs, synchronization took 3.38 s against 3.80 s without deduplication, and peaked at 2,810 MB against 3,124 MB. Planning took 0.26 s against 0.28 s, so hashing costs less than the run-to-run spread. The final code, whose hash covers every compared field, also plans 3,360 meshes. Its sync took 3.33 s and peaked at 2,810 MB, against the matched importer's 3.24 s and 1,795 MB in the same runs: 1.03× in time and 1.57× in peak memory, within the provisional budgets. M1b's digest counted 3,369 distinct contents; the cause of the difference of 9 wasn't investigated.
  - **Not exercised:** equal values in another byte form (−0 and 0, or a NaN) keep two meshes, which is safe.
  - **A new mesh field:** `ContentHash` binds every field of `MeshData` by a structured binding, so adding a field fails to compile until the hash and `SameContent` cover it. A `sizeof` check would differ between standard libraries, and padding could absorb a new `bool`.
  - **Alternatives measured** (ad hoc, on ALab's plan without deduplication, one run each; the timings are medians of four in one process, from temporary instrumentation):
    - **By USD identity,** sharing among copies of one prim in a prototype: it merges no mesh, since every Hydra mesh already draws a distinct prim. All 585 duplicates are equal content from different prims, as with one asset referenced several times without instancing. Identity also can't meet PVAR-05, whose equal meshes outside instances are distinct prims.
    - **By shared buffers:** points share a buffer for 415 meshes, but no two meshes share their topology arrays, so comparing the builder's input buffers merges no mesh. Comparing the built arrays' buffers merges none either: the builder makes new ones.
    - **By content, before building** (not built): it would skip building at most 585 meshes, about 22 ms of the 149 ms mesh build, against 12 ms of hashing and 7 ms of comparison now. It would also lower planning's peak, since all built meshes are held until the merges, which follow the parallel build (freeing each duplicate at its merge left the peak unchanged, ad hoc). It wasn't adopted. Its key must cover every input the builder reads (points before conversion, topology, primvars and the rules that read them, subsets, sidedness), so an input left out merges meshes that build differently. Different inputs can build equal meshes, so it finds no more duplicates. Each skipped prim still needs its own material slots and diagnostics. In Blender, the duplicates cost about 0.25 s of construction, which both methods avoid.
- **B6, small updates (with the user: a prototype with its test, and both user policies measured).** `update.py` replaces one unit of an applied display: some objects, meshes, and materials by plan index. Change discovery is out of scope, so the caller names the unit, and the new plan must keep the display's objects, meshes, and materials in order. `apply()` now returns the `Display` it built, its objects, meshes, and materials in plan order.
  - **Preparation** builds the unit's new meshes, materials, and objects in a collection no scene links, so it changes nothing the display uses (TXN-05).
  - **Publication** links the new objects, with their shear parents, in place of the old ones in one call (TXN-06). Objects that use a replaced mesh or material are either repointed or replaced, by the caller's user policy:
    - **Repoint:** kept, with publication moving their data and slots onto the replacement and restoring both if a later step fails. TXN-05 allows that mutation, since the rollback covers it.
    - **Replace:** each becomes a new object.
  - **Retirement** removes the old objects, and the old meshes and materials nothing uses once the old objects are gone. One that an object outside the display still uses stays intact (OWN-08).
  - **The check:** `isolated/test_update.py` replaces each of `update.sample_units`' units from the same plan, on `F-APPEARANCE-CASES` and `F-NESTED-STRESS`: one object whose mesh others share, the most-used mesh and material under each policy, the floor with the most objects, everything, and the most-used mesh with an object outside the display using it. It asserts five things:
    - preparation leaves the display and its collection as they were;
    - afterward, the display holds the same values, meshes by plan index, and materials per slot;
    - from publication on, the collection holds exactly the published objects and their shear parents;
    - new data appears exactly where the unit and policy say, and kept objects are on their mesh's replacement;
    - nothing is left over, except the old mesh the outside object keeps, with its positions unchanged.

    In an ad hoc mutation run of `update.py`, each of seven single changes failed it: no mesh repointing, no slot repointing, the old objects left linked at publication, shear parents left behind, no data retired, data retired despite another user, and preparation into the published collection.
    - **Not exercised:** a publication that fails, so the restore path is untested; and an outside user of a material.
  - **Cost on ALab** (`measure/updates.py`; the bpy wheel in one process, three runs each, medians, ad hoc on one Mac). A full synchronization took 2.61 s: capture 0.57 s, planning 0.35 s, construction 1.60 s, and evaluation 0.09 s. Each replacement below includes the depsgraph evaluation after it:

    | Unit | Objects replaced | Objects repointed | Meshes and materials replaced | Prepare | Publish | Retire | Evaluate | Total |
    |---|---|---|---|---|---|---|---|---|
    | One object | 1 | 0 | 0 | 62 ms | 1 ms | 11 ms | 66 ms | 0.14 s |
    | Most-used mesh, repoint | 0 | 169 | 1 | 55 ms | 2 ms | 16 ms | 65 ms | 0.14 s |
    | Most-used mesh, replace | 169 | 0 | 1 | 143 ms | 2 ms | 135 ms | 78 ms | 0.36 s |
    | Most-used material, repoint | 0 | 244 | 1 | 49 ms | 3 ms | 18 ms | 70 ms | 0.14 s |
    | Most-used material, replace | 244 | 0 | 1 | 157 ms | 2 ms | 134 ms | 65 ms | 0.37 s |
    | Largest floor (an asset copy) | 113 | 0 | 113 and 2 | 151 ms | 1 ms | 91 ms | 54 ms | 0.29 s |
    | Everything | 7,018 | 0 | 3,360 and 806 | 7.53 s | 35 ms | 5.57 s | 151 ms | 13.06 s |

    - **One real edit:** a translation of `/root/stoat/backpack_M_hrc/GEO/leatherBelt_M_hrc/belt07_M_geo`, followed by an incremental capture (21 ms), planning (0.30 s), and the replacement of its viewport object (0.13 s), took 0.50 s in all. The prim has a second object, for the render, which the measurement left unreplaced (C1 found it); as with almost every ALab copy, its two destinations bind different materials (6,997 of 7,018 objects display in one destination only). That is 5.3 times faster than the full synchronization, short of the provisional ten times. Planning is most of it: the planner always plans the whole stage.
    - **Fixed costs:** these dominate small units (an ad hoc probe in the same setup):
      - reading the plan's records, which the prototype's bindings convert whole on every read: `plan.objects` 36 ms and `plan.meshes` 12 ms;
      - the depsgraph's evaluation after any link, unlink, or `obj.data` change, 54–55 ms, against 2 ms after a transform change;
      - about 20 ms for each `batch_remove`.
    - **Per object:** about 0.5 ms to prepare and 0.7 ms to retire (the most-used mesh's two policies, 169 objects apart). So repointing 169 users cost 2 ms where replacing them cost about 0.2 s. Repointing also keeps their identities, and with them selection and any outside references.
    - **The whole display as one unit:** its replacement took 5.0 times as long as the full synchronization. Preparation took 4.7 times construction's time in a scene that already holds the display, and retirement about 0.5 ms per removed ID. In the probe, colliding names didn't slow object creation (1,000 objects in 219 ms, against 333 ms for fresh names); the cause wasn't investigated further.
  - **For the partition unit (F1):**
    - Up to about a hundred objects, a unit's size matters less than its fixed costs: one object and an asset copy of 113 objects both cost under 0.3 s. Most of those fixed costs belong to this prototype: whole-stage planning, and the bindings' conversion of every record. Only the depsgraph's 55 ms belongs to Blender.
    - A unit as large as the display can't be replaced within any budget.
    - The users of a shared mesh or material needn't join its unit: repointing them is cheap and keeps their identities.
    - A transform change could be applied in place, with its old value kept for rollback, and skip the depsgraph's rebuild (ad hoc probe only; not built).
- **B7, the detach walkthrough.** `detach.py` releases an applied display under [Detach As-Is](../spec/lifecycle.md#detach-as-is). It works on what survives in the destination collection when it runs, Blender-side edits and deletions included, and reads no USD.
  - **What it removes:** the baseline ties Blender data to its binding only through ID properties, named in `apply.py`: each object's source, instance context, element, and placeholder type, each shear parent's source, and each material's sources. The baseline has no handlers, drivers, modifiers, node groups, or overlays. Its correspondence and selection associations live in the bridge's `Interaction` and plan, not in Blender data, so releasing them removes nothing from the file.
  - **What it keeps,** as ordinary Blender data that works without the binding:
    - meshes, shared where they were;
    - objects, with their transforms, visibility per destination, and object color;
    - constant primvars as ID properties, which an Attribute node reads without the binding;
    - shear parent empties, by ordinary parenting, still unselectable;
    - placeholders (with the user), as bounds boxes and empty markers: plain objects that keep the layout readable, though they no longer say which USD type they stood for;
    - materials in object-linked slots (a new object on a detached mesh shows no material until one is assigned, as in any Blender file);
    - collection links and the selection.

    So detaching the baseline changes no appearance, and DET-04 has nothing to report.
  - **The check:** `isolated/test_detach.py` applies `F-APPEARANCE-CASES`, `F-NESTED-STRESS`, and `F-UNIVERSE-MEMBERSHIP` (for its bounds placeholder and empty marker). It then deletes an object whose mesh others share, moves another, recolors a material, and detaches. It asserts that Blender's data afterward equals the data before, minus every `proscenium_` property, edits included, and that the counts detach reports match. It also asserts that the saved file reopens the same in a process without the bridge. In an ad hoc mutation run of `detach.py`, each of seven single changes failed it: nothing removed, every ID property removed, materials skipped, placeholders deleted, object colors reset, shear parents unparented, and an object unlinked.
  - **For M11 and the compatibility review (F3):** the baseline's properties name no binding. So with two bindings in one collection, or sharing a material, detach couldn't tell which properties are this binding's ("Remove only metadata and controls belonging to this binding"). M3's ownership manifests are keyed by binding identity. So the product finds a binding's content through its manifest, and any per-datablock metadata it keeps must name the binding or be derived from the manifest.
    - **Not exercised:** DET-05's later refresh or removal, since the baseline keeps no ownership records for one to consult; and DET-06, since it has no pending cleanup.
- **Q11, kinds outside a valid model hierarchy (with the user).** A kind level matches a prim's authored kind, whether or not the prim is in a valid model hierarchy (`UsdPrim::IsModel`). The rule is stated in [Selection](../spec/interaction-contract.md#selection), ICON-21's oracle, and the DECISIONS.md row "Browsing universe and inspection metadata set". So a component-level pick on a component nested in another selects the nested one, as the oracle and the bridge already did. Under the other rule, it would select the outer one.
  - **In ALab** (`entry.usda`, load-all, one ad hoc survey), 594 of 1,877 authored components are outside a valid hierarchy:
    - 413 under point-instancer prototypes;
    - 180 directly inside another component;
    - 1 under a Scope with no kind.

    12 of 60 groups are outside one too. ALab's light-rig kinds aren't registered, so no level matches them.
  - **The case:** `F-KIND-HIERARCHY` gains `Vase`, a component inside the component `Table`, and `Crate`, a component under `Debris`, which has no kind. The fixture names both, and `bpy_free/test_interaction_fixtures.py` checks that `IsModel` rejects them. With the valid-hierarchy rule planted in the bridge's C++, `kind_hierarchy`'s `select_targets` and `selection_from_blender` checks fail (ad hoc).

### Phase C — Budgets and measurements

1. **The plan diff,** in the bridge's C++, so refreshes and edits find what to replace, and an unchanged refresh changes nothing.
2. **Updates from a diff:** `update.py` adding and removing objects and renumbering meshes, for the payload switch, the topology step, and geometry edits that change content deduplication.
3. **Provisional budgets and the measurement harness,** extending the bridge's `measure/`: the budgets as settled above, recorded with the measurements that test them. The harness covers initial construction, unchanged refresh, a small update, each interaction function with its Blender updates, peak memory while two generations coexist, and `.blend` size, on ALab and on generated fixtures of controlled size, repeated in the Blender binary on the reference hardware (APERF-01, APERF-02, APERF-06).
4. **Interaction at scale (Q6, Q9):** the universe's size under each payload policy, `displayed` over a whole stage browser, expansion, and a kind-level selection over a whole assembly, with the kind promotion's share.
5. **The first ownership lookup after an undo at ALab scale,** with the baseline's manifest entries written through M3's runtime, against the interaction budget. If it is over, the revision-token option in the [M3 plan](M03-bindings.md), Phase E.

#### Phase C log

- **C1, the plan diff (with the user: a diff in C++; Hydra's notices narrow only the capture).** `plan_diff.h/.cpp` compares a new plan with the published one, and `_hydra_bridge.diff_plans(published, next)` returns it:
  - **Meshes** match by B5's content: the plan keeps each mesh's hash, and a match is confirmed byte for byte.
  - **Materials** match by everything the plan holds.
  - **Objects** match by identity: source, instance context, and the destinations they display in. So a copy that becomes hidden, or shows in another destination, is a new object.
  - A matched object is **changed** when anything `apply.py` sets differs, its mesh and materials compared through their matches; unmatched old objects are **removed**.

  Change discovery proposes work, and this comparison decides it ([Affected Content](../spec/incremental.md#affected-content)), so an unchanged refresh changes nothing. The incremental capture already re-copies only the prims named in Hydra's notices. Narrowing planning and the diff by those notices is Phase 2's (M13): the spec takes notices as hints only, and they miss binding-setting changes, undo, external assets, and a rebuilt imaging pipeline, so a full comparison remains the fallback.
  - **The check:** `isolated/test_plan_diff.py` edits the caller's stage through its session layer, recaptures incrementally, and diffs. What each edit changes comes from how the fixture is built:
    - on `F-APPEARANCE-CASES`:
      - no edit: everything matched, nothing changed;
      - a translation: only its prim's objects;
      - the prototype's `Body` points: one new mesh, and its three copies;
      - `Red`'s color: rebuilt materials only among those with `Red`'s sources, and exactly the meshes the fixture binds to `Red`;
      - a constant `displayColor`: its object;
      - hiding a prim: its object removed and a hidden one added;
      - a deactivated prim and an added copy of `MeshA`: removed and added objects, and no new mesh;
    - on `F-UNIVERSE-MEMBERSHIP`: unloading and reloading `/World/Payload` removes and adds its contents;
    - on `F-NESTED-STRESS`: no edit matches everything.

    It also checks that every match keeps its source. In an ad hoc mutation run of `plan_diff.cpp`, each of eight single changes failed it: identity without destinations (in the comparison and the hash), no mesh matches, materials compared by name, and the matrix, mesh, slots, or primvars ignored in the object comparison, and no removed objects.
  - **Cost on ALab** (ad hoc, the bpy wheel, five runs each in one process): the diff took a median of 38 ms unchanged (range 37–91 ms), and 40 ms after one translation (38–45 ms), which changed that prim's 2 objects. The incremental capture copied 1 prim. Phase C's harness measures it in the binary.
- **C2, updates from a diff (with the user: structural changes now).** `update.prepare` takes the new plan, its diff, and the published display, so an update can add and remove objects and renumber meshes, materials, and objects.
  - **What it builds:** every mesh and material the diff doesn't match, and every added or changed object, in the staging collection as before.
  - **Repointing:** the diff now also lists the **repointable** changed objects, those that differ only in their mesh or materials. Under repointing, they're kept and moved onto the rebuilt data at publication.
  - **Renumbering:** publication rewrites the element index of each kept object whose plan index changed, and restores it if publication fails.
  - **B6's units:** each becomes a diff (`update.unit_diff`), so there is one update path.
  - **The check:** `isolated/test_update.py` applies a fixture, then after each edit updates the display by the diff, under both user policies. It covers C1's edits on `F-APPEARANCE-CASES`, unloading and reloading the payload on `F-UNIVERSE-MEMBERSHIP`, and no edit on each fixture. After each update, it asserts that:
    - the display holds what a fresh application of the new plan does, with Blender's data counts equal;
    - each object's element index is its new plan index;
    - the display keeps exactly the meshes, materials, and objects the diff matches and doesn't rebuild;
    - with no edit, it prepares, repoints, renumbers, and retires nothing.

    In an ad hoc mutation run of `update.py`, each of eight single changes failed it: no renumbering, removed objects kept, no repointing of data or of slots, changed objects kept or unchanged ones rebuilt, no data retired, and an old mesh reused for a rebuilt one.
  - **On ALab** (`measure/updates.py`, ad hoc, the bpy wheel, three runs each): the real translation now replaces both of the prim's objects. Its incremental capture, planning, diff, and update took 23 ms, 0.36 s, 69 ms, and 0.14 s, 0.59 s in all, against a full synchronization of 2.56 s. Phase C's harness measures the scenarios in the binary.
    - **Not exercised:** a publication that fails, as in B6; and a topology-changing time step, which the harness measures.
- **C3, provisional budgets and the measurement harness.** `measure/run.py` gains update modes: a fresh synchronization in the Blender binary, then one scenario from `measure/scenarios.py`, then the capture, planning, diff, and update that follow, each stage sampled from outside. Every scene gets an unrecorded warmup run first, since dropping the OS file cache needs root (with the user). The scenarios are acceptance.md's: an unchanged refresh, a transform, shared geometry, a material parameter, a time step, and a payload switch each way. They run on ALab and on generated `updates-N` scenes of 301, 3,001, and 30,001 objects, which have instances behind a payload, unique meshes, and a mesh whose topology changes. The budgets are recorded against the results as baselines (APERF-03), in the [feasibility record](../feasibility/runtime-record.md#measurements-m4-phase-c) with the method and environment (APERF-01, APERF-02, APERF-06).
  - **Against the budgets:**
    - initial synchronization meets both on ALab (1.09× the matched importer's time, 1.56× its peak memory) and at 301 and 3,001 objects, but takes 4.37× its time at 30,001;
    - an unchanged refresh takes 0.03–0.15× of initial synchronization, and writes nothing to Blender;
    - small updates miss ten times faster than a full rebuild everywhere except one: 5.3–6.8× on ALab, 2.9–10.3× on the generated scenes.
  - **Why the small updates miss:**
    - on ALab, whole-stage planning (0.33–0.43 s) and the diff (76–123 ms) are most of each update, as in B6;
    - on the generated scenes, the depsgraph's evaluation after any link or repointing grows with the scene: 68 ms at 3,001 objects, 761 ms at 30,001.
  - **Why large scenes are slow to build:**
    - Blender inserts each new datablock into a list sorted by name, at a cost that grows with how far from the end it lands. The prototype's names come from prims, so 10,000 objects named `Body` pass the point where Blender's numbered names stop sorting in creation order. Names in creation order (ad hoc) cut construction at 30,001 objects from 6.68 s to 1.06 s.
    - Retiring many objects grows faster than their count, for a cause not investigated: 16.9 s for 20,001 IDs at 30,001 objects.
  - **For M6 (with the user):** objects must be created so that their names land at the end of the list, whatever names users see. This also applies to any batching, such as Geometry Nodes instancing, which changes which objects are created at all.
  - **For the partition unit (F1):**
    - an update's Blender cost has a part that grows with the whole scene (the depsgraph's evaluation), whatever the unit;
    - the transaction keeps a second generation only of what an update rebuilds: 19–62 MB on ALab's small updates and time step.
  - **An unchanged refresh writes nothing:** `update.py` creates its staging collection only when something is built, since creating and removing a collection is itself a Blender write that triggers the depsgraph's rebuild. The test checks it.
- **C4, interaction at scale (Q6, Q9).** `measure/run.py --modes interaction` times the baseline's interaction functions after a synchronization, in process, on ALab and the `updates-N` scenes, in the binary. `_hydra_bridge.rebuild_correspondence` derives a plan's correspondence again so its cost can be timed. The results are in the [feasibility record](../feasibility/runtime-record.md#interaction-at-scale-m4-phase-c). Phase F answers the questions; these are its inputs.
  - **Q6:**
    - ALab's universe is 2,020 prims with its payloads loaded, and none without them, since its payloads hold all its displayed content.
    - Deriving the universe takes 1.9 ms.
    - `displayed` over the whole stage browser takes 8.4 ms, or 135 ms over all 38,197 prims with instance proxies.
    - Expanding the widest prim (178 children) takes 0.8 ms.
    - A box selection over `/root` (1,886 elements) takes about 38 ms from Blender's selection back to Blender. Kind promotion is 1.9 ms of it at the component level and 4.5 ms at the assembly level.
  - **Q9:** on ALab, every function meets the provisional budgets, the slowest being `apply_selection` with its depsgraph update for a pick (12.3 ms of 50) and `highlight_targets` for the box selection (15.9 ms of 250).
  - **At scale:** mirroring a selection grows with the display, and a pick's `apply_selection` takes 129 ms at 30,001 objects. Blender's depsgraph update after one selection change is 102 ms of that (an ad hoc probe), and the baseline's walk over every managed object is 26 ms. So, with C3's evaluation after updates, past about 10,000 objects Blender's per-object costs alone exceed the interaction budget. That is a reason to weigh batching in Phase D, if scenes that large are in scope.
- **C5, the first ownership lookup after an undo (with the user: the revision token goes to M5).** `measure/run.py --modes ownership` applies each scene into a file binding's destination through M3's API and writes the display as its manifest with `runtime.set_manifest`. It then times the first `runtime.ownership()` after each undo and redo, which rebuilds the bindings' state from every manifest, in the binary. The results are in the [feasibility record](../feasibility/runtime-record.md#ownership-lookup-after-undo-m4-phase-c).
  - **Against the interaction budget (50 ms):**
    - ALab's 11,185 entries take a median of 43.9 ms, under it, but each run's worst lookup took 85–90 ms, which a full garbage collection during the rebuild mostly explains (ad hoc);
    - 30,006 entries take 158 ms.

    So the plan's condition for the revision token holds.
  - **For M5 (with the user):** a revision token in each manifest record, so an undo or redo rereads only the manifests whose token changed and keeps the cached ones, repaired as after a removal ([M3 plan](M03-bindings.md), notes for M4 and M5). In the measured case, an undo of an edit that touched no manifest, nothing would be reread. M5 owns the manifests' publication and is the next milestone to change the records' schema; Phase F's notes for M5 carry this. Until then, the rebuild's own allocations are worth keeping few, since a collection during it doubled a lookup.
  - **Undo itself** takes about 350 ms on ALab (an undo push 49 ms), the undo overhead C3 couldn't measure without global undo.

### Phase D — Targeted alternatives

Only for the requirements or costs Phases B and C found failing; this phase may be empty, and the log says so.

- Batching (such as Geometry Nodes instances of shared meshes) or a hybrid partitioned by asset or by independently updated subtree, prototyped as far as the failing question needs.
- Each alternative answers the same list as the baseline: multi-mesh, multi-material assets, per-instance shading, pick data (Q2), partial highlighting and mirroring (Q3, Q5), small updates, detach, and the interaction checks.

Phases B and C left one failing question a representation can answer: above about 10,000 objects, Blender's per-object costs (the depsgraph's evaluation after an update, a selection change, retirement) exceed the budgets. ALab's small updates miss theirs through whole-stage planning and the diff, which no representation changes; Phase F records that as a limitation (with the user). So this phase prototypes Geometry Nodes instancing, on `updates-10000` and checked on ALab:

1. **Batched application:** plan objects that differ only in transform and constant primvars become instances on one carrier object, held to the baseline's own checks.
2. **One object for both destinations:** whether a copy whose viewport and render objects differ only in their materials can be one object, whose Geometry Nodes switch materials by destination, and how many objects that saves.
3. **Interaction on the batched display (Q2, Q3, Q5):** a pick resolved to its instance's element, and `apply_selection` and `read_blender_selection` with instances.
4. **Updates and detach of the batched display.**
5. **Measurements:** the batched display in the harness, against the baseline and the budgets.

#### Phase D log

- **D1, batched application.** `batch.py` applies a plan with Geometry Nodes instancing. Plan objects that share a mesh, material slots, destinations, and object color, and whose constant primvars have the same names and kinds, are instances on one carrier object. A group of one, a placeholder, and a copy with a primvar no attribute holds stay objects, as `apply.py` builds them.
  - **Carrier:** a mesh with one point per instance. Its point attributes hold each instance's world transform as a 4x4 matrix, its element (`proscenium_element`), and its constant primvars by name, which reach the instance domain, where an Attribute node of type Instancer reads them. Its hide flags are the group's destinations, and one node group instances its prototype on every point.
  - **Prototype:** an object no scene links, on the shared mesh, with the group's object-linked materials and object color, which every instance shows.
  - **The check:** `isolated/test_baseline.py` runs every baseline check on both representations, reading the batched display from Blender's evaluated instances: each instance's world transform, its prototype's mesh and materials, its carrier's destinations, and its instance attributes, by the element the attributes name. The only difference it allows is that a sheared instance has no parent empty, since its 4x4 transform holds the shear.
    - `F-APPEARANCE-CASES`'s 46 objects become 18 instances on 8 carriers and 28 objects.
    - `F-NESTED-STRESS`'s 21 become 12 instances on 4 carriers (6 of them sheared) and 9 objects.
    - In an ad hoc mutation run of `batch.py`, each of eight single changes failed it: a transposed transform, one material for every slot, no primvar attributes, the first copy's primvars for all, elements out of order, and the mesh slots, destinations, or object color left out of the grouping.
  - **What batching changes:**
    - **Object color:** Solid shading's object color is the prototype's, so copies whose constant `displayColor` or `displayOpacity` differ are in separate groups, as in `F-NESTED-STRESS`.
    - **Constant primvars:** a material reads them through an Attribute node of type Instancer, not Object, which M9's translation must choose by representation. The check reads the evaluated attributes, not shading. A primvar no attribute type holds (a string, an array of more than one value) keeps its copy an object; no fixture has one.
    - **Correspondence:** an instance holds only its element, so its source and instance context are the plan's, by element.
  - **Ad hoc probes** (the Blender binary, one run each):
    - a ray cast that hits an instance returns the prototype and the instance's world matrix, but not its index, which Q2's pick resolution (D3) must recover;
    - a depsgraph instance's `persistent_id[1]` is its index on the carrier, which the check uses.
- **D2, one object for both destinations (with the user: a probe, not a prototype).** A copy has a viewport and a render object only when its preview and full materials differ (GRAM-12).
  - **How many:** 336 of ALab's 7,016 plan objects, so merging them would save 336 objects (4.8%). `F-APPEARANCE-CASES` has 3 such copies, and `F-NESTED-STRESS` and the `updates-N` scenes have none. In every pair, the two objects differ only in their material slots, one shown only in the viewport and the other only in the render. A scene saves one object per such copy, so the saving depends on how many it has. The generated scene at 30,001 objects has none, so merging can't change that measurement, and `batch.py` doesn't do it.
  - **That it works** (an ad hoc probe in the Blender binary, one run): a node group sets each slot's material through a Switch on Is Viewport, with the preview material when true and the full one when false. The viewport depsgraph showed the preview materials and the final render's depsgraph, read by a Python `RenderEngine`, the full ones. That held with the object's slots linked to the object or to the data, and on a prototype that a carrier instances. Viewport shading modes other than Solid weren't checked separately, since they evaluate in the same viewport depsgraph.
  - **What it would cost** (not tested): one Blender object would stand for two display elements, and the materials would live in modifier inputs, not in the object's slots, which detach (DET-03) and users' material edits would have to account for. M9 and M10 can adopt it if the object count warrants it.

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
