# M8 — Validated mesh and primvar translation

**Implements:** [Geometry and Primvars](../spec/support/geometry.md), time-varying topology in [Transforms and Time Codes](../spec/support/transforms.md#transforms-and-time-codes), and correspondence through batching in [Source Inspection and Interaction](../spec/interaction.md#source-inspection-and-interaction).

**Depends on:** M6 (snapshot and planning), M7 (application layer).

**Decisions and deliverables:**

- First, before implementation: complete the primvar support matrix and mesh classification rules against M4's representation feasibility cases. Additions or changes affecting backend feasibility, sharing, or partitioning require rerunning the relevant M4 prototypes and revising the design as needed before implementation.
- Evaluation/planning: validated geometry and primvar data in the snapshot and plan. Since M1b adopted Hydra, the support matrix is written against Hydra's mesh and primvar data (topology, subdivision tags, indexed primvars, interpolation, subsets), and each Hydra filter conversion is classified as exact or approximate. The planning performance M1b's prototype leaves open (contention when meshes are built in parallel, and single large meshes) is in its [notes for production planning](../feasibility/runtime-record.md#for-production-planning-m8).
- M6's provisional mesh description, which M8 replaces ([M6 plan](../plans/M06-evaluation.md), C1, C8; [record](../feasibility/runtime-record.md#capture-and-planning-m6-phase-f)):
  - A `GeometryDescription` per mesh Hydra draws holds its source (its first copy's in source order), its local extent, and a content key, its source's path, so only a prototype mesh's copies share one. It gets no diagnostic, and the stub draws it as its bounds.
  - The snapshot copies only the schemas planning reads (`PlannedSchemas()` in `snapshot.cpp`), so M8 adds mesh topology and primvars to it. On ALab, the bridge's capture with them took 0.46 s against M6's 0.08 s, and its plan held 904 MB against M6's 6 MB.
  - Batch groups are keyed by the geometry description, provisional until M8's content key. On ALab they held up to 898 copies, where M4 found groups of up to 1,282 leaves of one prototype, which a key per Hydra mesh prim may split, not yet checked; ALab's 3,945 meshes held 3,369 distinct contents in M1b.
- Application: mesh data, attributes, and modifiers created from the plan.
- Geometry refreshes incrementally on M7's framework, from the bridge's reuse ([M4 plan](../plans/M04-prototypes.md), D9, E4):
  - Mesh build reuse (D9): a mesh prim's build is reused when its captured container and its subsets' are the ones it was built from, so Hydra's invalidation decides what is rebuilt. On ALab with its point instancers a batched transform update took 0.250 s against 0.493 s. What it leaves on every update is reading every prim's record and planning every object; reusing those needs a prim table that shares records with the previous plan's and dependency tracking for what an object takes from other prims (its frame, instance context, and materials).
  - Topology reuse (E4): a mesh rebuilt with the previous build's topology and point count takes its validation, left-out faces, corner and face buffers, equal material slots, and each attribute whose primvar matches in name, interpolation, role, values, and indices. Hydra hands an unchanged topology over as a new array, so it is compared by content. On ALab's frames it cut mesh building from 0.070–0.091 s to 0.019–0.022 s, and the frames' plans' heap from 6,673 MB to 4,247 MB.
- The support matrix starts from what the bridge's mesh builder settled, which M1b checked against USD ([M1b plan](../plans/M01b-evaluation-gate.md#phase-c-log); the bridge's `validate`, `mesh_builder`, `properties`, and `mesh_sharing` in [its sources](../../tools/feasibility/hydra_bridge/src/README.md)). Each is a starting point the matrix confirms or changes:
  - Hydra validates nothing, and an out-of-range index in C++ or Blender ends the process, so every index is checked before use. `PxOsdMeshTopology::Validate` checks counts, indices, holes, and tokens, but rejects USD's `none` scheme, so such meshes validate as bilinear; the core adds indices below the point count and counts within Blender's `int`.
  - Faces Blender's `Mesh.validate()` deletes (a face using a point twice, a later face on an earlier face's points in either winding) are valid USD: the planner leaves them out first, keeping the first of each set, with a `faces-left-out` warning, and per-face primvars, corners, and subsets follow the faces kept.
  - Hole faces are kept as ordinary faces with a `holes-ignored` warning, and faces aren't triangulated. A left-handed face is reversed keeping its first corner.
  - Normals become Blender's `custom_normal` on the domain of their interpolation; `primvars:normals` wins over `normals`, and a subdivision surface's authored normals are ignored (`ignored-normals`), as UsdGeomMesh specifies. Per-point `velocities` become `velocity`; `accelerations` stay generic (`no-blender-equivalent`).
  - A primvar with a name Blender gives a meaning of its own changes shading, creases, or seams, so it isn't transferred and is warned: `position`, `material_index`, `sharp_face`, `sharp_edge`, `crease_vert`, `crease_edge`, `uv_seam`, `custom_normal`, `bevel_weight_vert`, `bevel_weight_edge`, `freestyle_edge`, `freestyle_face`, and any name starting with `.`.
  - Constant primvars become ID properties on each object: integers outside 32 bits keep their low 32 bits with a `narrowed-primvar` warning, and names over 63 bytes, the `proscenium_` prefix, asset paths, quaternions, and arrays of matrices aren't transferred (`untransferred-primvar`). Strings are kept in the plan but never split a batch ([M4 plan](../plans/M04-prototypes.md), D5).
  - Color attributes are floats, not 8-bit: Blender converts each 8-bit element as it writes it, about 60 ns against 2 ns, which made building ALab 0.70 s slower batched and 1.44 s as objects ([M4 plan](../plans/M04-prototypes.md), D10). A held display color is part of its mesh's content, in both the hash and the equality check (D13).
  - Primvars with `elementSize > 1` fail validation, as the bridge doesn't read elementSize; texCoord3f and constant texCoords are untested ([record](../feasibility/runtime-record.md#limits-and-next-gates)).
  - `UsdGeomSubset::ValidateFamily` checks the default value as well as every sample, so a partition authored only as time samples is rejected. Overlapping materialBind subsets give a face to the first by name, with a warning; point-element subsets are ignored with one.
  - UsdSkelImaging images a Skeleton as a guide-purpose bone mesh, so the plan has a hidden object for it, and UsdSkel's primvars reach the plan: the geometry policy decides them.
  - What Hydra never flags as time-varying, so a time change never dirties it: mesh orientation, scheme, doubleSided, subdivision tags, and subset indices, which the source-info filter flags by hand ([M1b plan](../plans/M01b-evaluation-gate.md#phase-d-log)).
- From M4 ([M4 plan](../plans/M04-prototypes.md)):
  - UV-set names join the requested settings, with a migration of the binding record (A3, F3).
  - A primvar named `custom_normal` takes the name of Blender's custom normals, which alters what is written to it (Moore Lane, F2): the name-collision rules cover it.
  - A batch's instance is one mesh's copy, so a multi-mesh asset's copy spreads over a carrier per mesh and is never one active object (F2). Batching a whole copy as one instance would give it one, at the cost of grouping by whole assets, of copies whose meshes vary on their own leaving their batch, and of a pick resolving to the copy before its element.
  - Cached time codes: a mesh whose points vary caches position attributes, and one whose topology varies a mesh per sample (E4); a mesh's material slots could be the union over its cached time codes, a newly needed slot appended (F5, a suggestion).
  - The bounds comparison's subdivision and approximation cases (ABND-05, ABND-06, F4).

**Tests:**

- Focused invalid-data and edge-case fixtures, one per support-matrix row and classification case.
- Sharing assertions against M4's criteria: equivalent geometry and attribute requirements share resources; differing data remains correct where distinct resources are required.
- The M5 failure-injection tests, rerun with geometry writes.
- Incremental refresh of geometry changes: points, topology, normals, and primvars, each equal to a clean rebuild, rewriting only the affected meshes.
- M6's tests of the provisional mesh description, updated for the mesh content that replaces it ([M6 plan](../plans/M06-evaluation.md), C1, C8, D4):
  - `bpy_free/test_core_instancing.py` checks that copies share a description only among copies of one USD prototype mesh, its source their least and its content key that source's path. M8 shares meshes by content, as the bridge does, so copies of equal meshes share too.
  - `bpy_free/test_core_plan.py`, `test_core_placeholders.py`, `plan_checks.py`, and the plan contents `test_core_snapshot.py` and `plan_serialization.py` compare read a mesh's copy as a description with an extent and a content key, and its bounds as that extent. They read the mesh content M8 plans.
  - `bpy_free/test_core_batch_groups.py` groups copies by their description, the provisional batch content key; M8's key replaces it.
  - `blender/test_application.py` checks a mesh's copy drawn as its extent's bounding box, and `blender/test_time_varying.py` checks no bounds, since none of its fixtures' bounds vary. M8 checks the mesh drawn, and at each sampled time code its points and topology as USD gives them (XFORM-07).

**Exit condition:** safe supported geometry at any supplied time code, matching the support matrix, with source correspondence intact.
