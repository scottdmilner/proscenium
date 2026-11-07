# M9 — Material translation and binding resolution

**Implements:** [Materials](../spec/support/materials.md), and texture handling in [Reopening](../spec/lifecycle.md#reopening).

**Depends on:** M4 (per-instance variation approach), M8 (UVs and primvars).

**Scope limits:** per-instance material variation is completed and tested in M10. M9 designs material inputs to accept per-instance data, following the M4 variation approach.

**Decisions and deliverables:**

- First, before implementation: complete the bounded connection grammar and `displayColor`/`displayOpacity` interaction rules against M4's representation feasibility cases. Additions or changes affecting backend feasibility, sharing, or partitioning require rerunning the relevant M4 prototypes and revising the design as needed before implementation.
- Evaluation/planning: effective material bindings, translated networks, and material inputs that accept per-instance data. With M1b's Hydra core, networks come from Hydra's material network data. Bindings come from UsdShade's resolution, recorded by the core beside the chain: M1b found Hydra's flattened bindings wrong inside nested instances, without the allPurpose fallback, and blind to collections that reach into instances (OpenUSD #3690, worked around and labeled in the prototype). See the [M1b plan](../plans/M01b-evaluation-gate.md#phase-c-log); the connection grammar, Principled BSDF translation, and material purpose selection remain project work. Direct, inherited, collection-based, and face-subset precedence are verified against fixtures.
- Application: materials, nodes, images (as external file references), and assignments.
- From the bridge's binding resolution ([M1b plan](../plans/M01b-evaluation-gate.md#phase-c-log); the bridge's `copy_bindings`, `instancing` (`BoundMaterial`), and source-info filter):
  - The nested-instance binding bug has no upstream issue; M9 files one, so its workaround is labeled `WORKAROUND for OpenUSD #<issue>` with a known-gap check, as #3690's is.
  - The #3690 workaround's cost and limits ([record](../feasibility/runtime-record.md#collection-bindings-inside-instances-workaround-for-openusd-3690)): 0.185 s of a 0.209 s capture when a binding collection reaches 1,000 instances (21,000 copies), 0.044 s on ALab with none. It covers only USD's three material purposes, a path-expression collection sends every instance through per-copy resolution, and any binding or collection edit recomputes the whole result. It runs between the graph's advances, never alongside reads.
  - The source-info filter's binding facts are cached per prim and rebuilt only when what they depend on changes: the prim, an ancestor's binding, any collection, or one of a mesh's subsets (its family verdict). With one counter for every prim, the filter built 366 containers for 55 prims in the first capture alone; with per-prim dependencies, 56.
  - Bindings authored without `MaterialBindingAPI`: UsdShade honors them and posts its own warning whenever anything resolves one, so the filter reports the fact and each copy gets a `binding-without-api` warning on its source.
  - Each destination's materials are resolved only where the object displays there: resolving both made a proxy-only prim's `full` binding a material nothing displayed.
  - The Windows bpy wheel omits six USD plugins' resources, `usdShaders` among them (a Blender install rule), so any Sdr lookup of UsdPreviewSurface raises there; the binary is authoritative ([M1b plan](../plans/M01b-evaluation-gate.md#phase-a-log)).
- Ownership and reuse rules for translated materials, images, node groups, and dependencies.
- From M4 ([M4 plan](../plans/M04-prototypes.md)): a material reads a copy's constant primvars through an Attribute node of type Object for an object and Instancer for a batch's instance, so translation chooses it by representation (D1); a copy's own constant color is its object color, which Solid shading's Object color shows (D10, D13); and a reader's fallback comes from the translated material or is written per copy, also where a cached time code blocks the primvar (B4, F5).

**Tests:**

- Display batching does not collapse distinct material assignments or attribute meanings.
- Material inputs accept per-instance data supplied through hand-constructed plans.
- Headless render assertions on controlled material fixtures.
- `F-SHARED-MATERIAL-FAILURE` and `F-OFFLINE`.

**Exit condition:** the material grammar works within the chosen display representation, and material and image failures leave the published generation unchanged.
