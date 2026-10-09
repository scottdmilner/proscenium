# M1b — Evaluation front end and core language gate

**Implements:** the compiled-component decision in [Compatibility and Development](../PROJECT.md#compatibility-and-development), and the choice between the [Hydra evaluation design note](../spec/pipeline.md#evaluated-source-snapshot) and direct USD evaluation.

**Depends on:** M1 (runtime feasibility record and the macOS [compiled Hydra bridge record](../feasibility/runtime-record.md#compiled-hydra-bridge--macos-arm64)).

**Scope limits:**

- M1b is a decision gate. Its prototype is not production code, and it does not choose the display representation (M4).
- It runs before M3 because M3 defines the identifier schemes and the source-side inspection snapshot format, which belong to the core. Settling the core's language first avoids writing those in one language and porting them.
- Requirements in PROJECT.md, spec/, and testing/ are unchanged by either outcome. Hydra is judged against them; it does not relax them.

**Decisions and deliverables:**

- **Cross-platform native loading.** Whether a compiled Python module links against the OpenUSD bundled with Blender 5.2 on macOS, Windows, and Linux, exchanges stages with Python `pxr`, and loads no second USD build, in both the wheel and the binary. Results go into the [feasibility record](../feasibility/runtime-record.md) per platform. The macOS arm64 bridge (`tools/feasibility/hydra_bridge/`) is the starting point; its CMake build is macOS-only today.
- **A thin end-to-end prototype:** Hydra scene-index capture → a display plan built in C++ → Python application into Blender. It exercises at least:
  - A mesh with GeomSubsets and indexed primvars.
  - An implicit shape converted to a mesh by a Hydra filter, and the approximation diagnostic when the conversion is inexact.
  - Nested native instances with differing inherited appearance, and the mapping from Hydra instancers and instance indices back to source entities with instance context.
  - A time-code change, a material parameter edit, and an unchanged refresh.
  - A Hydra prim type the prototype does not translate, such as basis curves, which must still produce a placeholder and diagnostic.
  - Handing large plan arrays to Blender without copying them in Python, for example through the buffer protocol and `foreach_set`.
  - **Time-sampled data detection:** whether the scene-index chain reports which values are time-varying (points, transforms, primvars, visibility, topology), and over what interval. A candidate is the sample-time query on Hydra's sampled data sources, such as `GetContributingSampleTimesForInterval`. Check it against authored samples and against direct USD (`UsdAttribute::ValueMightBeTimeVarying`), including values that become time-varying only after flattening, such as a static mesh under an animated ancestor.
- **Measurements**, kept separate: Hydra capture, C++ planning, the C++ → Python plan transfer, Blender construction, and peak memory. Compare against a direct-USD Python baseline on the same fixtures.
- **One recorded decision** in the [Decision Register](../DECISIONS.md) row "Evaluation front end and core language":
  - **Hydra adopted:** evaluation, the snapshot, planning, source-side diagnostics, and Phase 2 evaluated-content comparison are written in C++ as a compiled core. Everything that touches Blender stays in Python: application, the transaction and publication, persistence, lifecycle operations, undo handling, and UI. Extensions can reach Blender only through the Python `bpy` API, so this boundary is fixed. The display plan crosses it once, as an immutable object whose large arrays are exposed without copying.
  - **Hydra not adopted:** the core stays Python, evaluating USD directly, and the Python-only row continues under M4 measurement.
- If Hydra is adopted, the distribution design in the row "Native core distribution", and the follow-up updates listed below.
- **Time-sampled data findings**, recorded in the feasibility record whatever the front-end decision. They feed the open row "Time-sampled data representation", which compares per-time-code snapshots with animation-data representations: keyframes, mesh cache modifiers, and Geometry Nodes baking. [Transforms and Time Codes](../spec/support/transforms.md#transforms-and-time-codes) permits mapping time codes to frames and authoring animation data. A mesh cache modifier that reads the USD file must still settle these conflicts:
  - [Blender Application](../spec/pipeline.md#blender-application): a modifier that reads the USD file at depsgraph time is application querying USD.
  - [In-memory sources](../spec/source-access.md#in-memory-sources) and unsaved layers are invisible to a file reader.
  - [Reopening](../spec/lifecycle.md#reopening): a saved display must survive an unavailable source.
  - Source-semantic diagnostics must all exist before Blender is mutated.

  Settling the row is M4 work, because it is a representation choice. M1b only establishes whether the time-varying information is available.

**Follow-up updates if Hydra is adopted** (made in the same change as the decision):

- `AGENTS.md`: the compiled core's source location outside the extension directory, its build through `tools/build_extension.py`, C++ style and lint hooks (such as clang-format and clang-tidy), and how the core is tested.
- [PROJECT.md](../PROJECT.md#compatibility-and-development) and the affected milestone files (M3, M5, M6, M8–M10, M13), whose Hydra-conditional notes become settled scope.

**Tests:**

- The bridge's runtime checks pass in the wheel and the binary on all three platforms, with exactly one USD library loaded per process.
- Prototype results are checked against values from the spec or from how each fixture is built (for example, UsdGeom-computed transforms and visibility), never against Hydra's own output.
- Malformed input to the C++ core produces Python exceptions and diagnostics, not crashes. [Synchronization Transaction](../spec/pipeline.md#synchronization-transaction) does not promise recovery from native crashes, so a C++ core moves geometry validation to where a bug terminates Blender.

**Exit condition:** native loading is recorded for all three platforms, and a recorded decision on the evaluation front end and core language is backed by the end-to-end prototype's correctness results and separate measurements.

## Background

What Hydra offers and where it stops, from the 2026-10-07 investigation. Points marked *(tested)* were checked by the macOS bridge; the rest come from OpenUSD documentation and the v26.03 source, and are inputs for the prototype to verify.

**Why Hydra.** Hydra's scene-index API turns a composed stage into display-oriented data: USD imaging adapters expose prims as Hydra data, filtering scene indices transform it, and a consumer reads the result and receives change notices ([Hydra getting-started guide](https://openusd.org/release/api/_page__hydra__getting__started__guide.html)). A consumer that builds a snapshot fits Proscenium's pipeline without a render delegate, which would add renderer lifecycle machinery the snapshot does not need. Blender's own Hydra integration runs the other way (Blender scenes into Hydra renderers) and provides no Hydra-to-datablock translation.

**What the chain provides.**

- `UsdImagingStageSceneIndex` alone does not resolve inherited transforms, visibility, or native-instance aggregation. `UsdImagingCreateSceneIndices` builds the processed chain: native and point-instancer processing, material-binding resolution, selection, and optional draw-mode substitution. Its native-instance aggregation regroups instances whose inherited state differs from USD's prototypes.
- Inherited state through `HdFlatteningSceneIndex` *(tested: parent translation and ancestor visibility)*.
- Implicit surfaces to meshes through the implicit-surface scene index *(tested: cube; sphere configured but not exercised)*, and NURBS approximation into meshes and basis curves (untested).
- Material networks as nodes, connections, and terminals per render context, plus resolved bindings.
- Observer notices for added, removed, renamed, and dirtied prims *(tested: kinds and paths, not dirty-locator coverage)*. A dirty notice names data to re-read, not proof its value changed. The stage scene index exposes time changes and pending-update processing *(tested: time change dirties; same-time capture emits none)*.
- Hydra's sampled data sources can report the sample times that contribute to a value over an interval. Whether the processed chain reports these accurately for time-varying data, including after flattening, is untested (see time-sampled data detection above).
- `UsdImagingSelectionSceneIndex` maps USD paths, including paths inside native instances, into the processed scene. The reverse mapping from picks, and durable identities, remain Proscenium's.

**What Hydra does not do.**

- It does not reduce scenes to triangle meshes and one shader. Meshes keep subdivision settings, holes, indexed primvars, interpolation domains, and subsets; curves, points, volumes, and instancers stay distinct. Each needs support, conversion, or a diagnostic.
- It does not translate materials into Principled BSDF. The bounded Preview Surface grammar, UV conventions, color spaces, opacity, and displacement rules remain M9 work.
- Deformation is unverified: mesh points from Hydra are not proven to include skinning. A probe must read correct deformed points at several times before skeletal support is promised.
- Custom schemas get display data only through imaging adapters; Hydra does not infer what an installed schema should look like.
- It does not reduce Blender's own costs: object construction, depsgraph updates, undo storage, and old and new generations coexisting during publication.

**Runtime facts.** In both the uv environment and the Blender 5.2.2 binary (USD 0.26.3), `pxr.Hd`, `pxr.Hdsi`, `pxr.UsdImaging`, and `pxr.UsdSkelImaging` are absent from Python; `pxr.UsdImagingGL` and `pxr.UsdHydra` are present but do not expose scene indices. A Python-only Hydra pipeline is therefore not possible. The `release` documentation describes APIs newer than the bundled USD, so implementation is checked against v26.03 and Blender's actual build. The bridge record lists the build details: Blender's pinned dependency headers, the `pxrBlender_v26_03__pxrReserved__` namespace, and the import order tested.

**Effect on the milestones if adopted.**

| Milestone | Effect |
|---|---|
| M3 | Source access, identifiers, and persistence are unchanged in kind. A retained imaging pipeline adds a reason to review refresh strictness, and the bridge must not keep released stages alive. |
| M5 | The plan interface becomes the C++/Python boundary. |
| M6 | Imaging adapters and filters replace much custom display-semantic evaluation. Source inspection and validation remain. |
| M8 | Input comes from Hydra's mesh and primvar data. Blender domain conversion, safe construction, sharing, and approximation policy remain. |
| M9 | Binding resolution and network extraction come from Hydra. Blender shader translation remains. |
| M10 | Instance aggregation comes from Hydra. Blender representation, appearance variation, correspondence, and deduplication remain. |
| M13 | Observer notices become one discovery source. |
| M4, M7, M11 | Representation, application, publication, persistence, ownership, detach, and undo stay project work. |

**Editor direction.** For a Phase 3 editor the loop is: select a source entity, author an opinion through USD, process imaging changes, reconcile the Blender display. Authoring decisions (edit targets, layer strength, variants, instance restrictions, undo of opinions) stay USD decisions; a displayed world matrix does not say which transform op or layer to edit. A Hydra-rendered viewport is a separate option that would give up the promise of ordinary, persistent Blender content.
