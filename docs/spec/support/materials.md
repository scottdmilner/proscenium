# Materials

Part of the supported scene state. Cross-cutting guarantees are summarized in [invariants.md](../invariants.md). M4 settles the cases needed for representation feasibility; M9 completes the connection grammar in this file before implementation. Offline texture behavior is defined in [Reopening](../lifecycle.md#reopening).

## Supported Materials

Translate the supported USD Preview Surface subset into Blender materials:

- Constant parameters.
- Base color, metallic, roughness, emission, opacity, and normal mapping.
- Common image-texture connections.
- Named UV selection and texture-coordinate transforms.
- Texture color spaces and UDIMs.
- Direct, inherited, collection-based, and face-subset bindings with applicable precedence.
- Required per-instance variation.
- Supported displacement signals through the material displacement path, without baking into mesh geometry.

Target the Principled BSDF subset usable in Eevee and Cycles, with documented displacement exceptions.

Display batching must not collapse distinct material assignments or attribute meanings.

## Connection Grammar

Settle a bounded connection grammar **before implementation**:

- Supported shader and node identifiers.
- Supported input/output connections.
- Material purpose and render-context selection.
- Texture channels and scale/bias treatment.
- UV transformation conventions.
- Primvar-reader types.
- Normal-map conventions.
- Opacity behavior.
- Displacement behavior and engine exceptions.
- Fallback behavior for partially supported graphs.

Also settle how `displayColor` and `displayOpacity` interact with no material binding, a translated material, an unsupported material, and per-instance variation.

Before choosing a display backend, M4 defines and freezes concrete connection cases for per-instance appearance, named UV selection and primvar readers, face-level assignments, and geometry sharing. Record the relevant shader/node identifiers, connections, reader types, and `displayColor`/`displayOpacity` interaction rules so prototypes test a defined contract. M9 completes the full grammar against these cases. Additions or changes affecting backend feasibility, sharing, or partitioning require rerunning the relevant M4 prototypes before implementation and revising the decision record and affected milestones as needed. A chosen backend does not authorize silently narrowing required support.

### Representation Feasibility Cases

Cases whose display depends on the representation. M4 chooses the representation against them, M9's grammar includes them, and a change to one reruns its prototypes.

| Case | Shaders and connections | `displayColor` and `displayOpacity` | Display |
|---|---|---|---|
| No material | a mesh with no bound material | the mesh's own or inherited values (the primvar cases in [Primvar Support Matrix](geometry.md#primvar-support-matrix)) | A copy with no bound material shows its display color and opacity. |
| Constant surface | `UsdPreviewSurface` with constant `diffuseColor`, `roughness`, `metallic`, `ior`, and `opacity` | ignored | A bound material shows its own inputs, whatever the mesh's display color. |
| Material per instance | one prototype whose instance roots bind different `UsdPreviewSurface` materials | ignored | Each copy shows the material its own instance root binds. |
| Primvar readers | `diffuseColor` from `UsdPrimvarReader_float3` reading `tint`, `roughness` from `UsdPrimvarReader_float` reading `rough`, and `diffuseColor` from `UsdPrimvarReader_float3` reading `displayColor`, each with a `fallback` input and a constant `varname` | read only through the reader | Each copy shows its own primvar values, and the reader's fallback where the copy has none. |
| Named UV texture | `UsdUVTexture` with `file`, `wrapS` and `wrapT` `repeat`, no `sourceColorSpace`, and `st` from `UsdPrimvarReader_float2` whose `varname` is `perfuv`, on a mesh with both `st` and `perfuv`; `rgb` to `diffuseColor` and `r` to `roughness` | ignored | The texture is sampled through the UV map the reader names, never another. |
| Face assignments | two materials bound to `materialBind` subsets and a third bound on the mesh, in a prototype whose instance roots bind different fallback materials | ignored | Each face shows its subset's material, and unassigned faces each copy's own fallback. |
| One material, many uses | one material bound to many meshes and copies, some differing only in primvars its readers read | read only through readers | Every use shows that material with its own primvar values; the representation records any additional material resource a use needs under [Geometry Sharing](instancing.md#geometry-sharing). |
| Purpose bindings | `material:binding:preview` and `material:binding:full` on one prim naming different materials | ignored | The viewport shows the preview binding's material and the final render the full binding's, each falling back to the all-purpose binding. |

## Ownership and Diagnostics

Document ownership and reuse rules for translated materials, images, node groups, and dependencies. Diagnose missing textures, unsupported networks, and incomplete translations. Do not silently substitute another UV set when the requested one is unavailable.
