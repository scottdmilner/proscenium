# Geometry and Primvars

Part of the supported scene state. Cross-cutting guarantees are summarized in [invariants.md](../invariants.md). M4 settles the cases needed for representation feasibility; M8 completes the support matrix in this file before implementation.

## Supported Geometry

Support:

- Validated polygon topology and point positions.
- Authored normals and a documented generation fallback.
- Orientation/winding and documented double-sidedness behavior.
- Supported UV sets with their names and meaningful domains.
- `displayColor` and `displayOpacity`.
- Supported arbitrary primvars converted into native float, color, and vector attributes.
- Indexed and inherited primvars, and supported domain conversions.
- Face-level material assignments.
- Approximate subdivision, edge creases, and corner sharpness.
- Topology-changing snapshots, discarding obsolete topology-dependent data.

A UV set is a `texCoord2f[]` primvar. A binding's UV-set names, a list of globs, also make a UV set of a `float2[]` primvar with vertex, varying, or faceVarying interpolation whose whole name matches one of them, case-insensitively. The default is an empty list, so only `texCoord2f[]` primvars are UV sets. A list such as `st`, `st_*`, `*uv`, `uv*` covers common untyped UVs.

Validate topology and attribute sizes before passing data to Blender. Diagnose unsupported types, domains, lossy conversions, holes, and inexact subdivision mappings.

## Primvar Support Matrix

Settle the primvar support matrix **before implementation**. For each supported primvar category, record USD value types, interpolation modes, indexed handling, inheritance, Blender attribute domain, conversion rules, missing/invalid-value behavior, and name-collision rules.

Before choosing a display backend, M4 defines and freezes concrete cases for geometry sharing, named UVs, face-level material assignments, and primvars driving per-instance appearance. Record the relevant value types, interpolation modes, indexed handling, inheritance, domains, and how varying data reaches the display. M8 completes the full matrix against these cases. Additions or changes affecting backend feasibility, sharing, or partitioning require rerunning the relevant M4 prototypes before implementation and revising the decision record and affected milestones as needed.

### Representation Feasibility Cases

Cases whose display depends on the representation. M4 chooses the representation against them, M8's matrix includes them, and a change to one reruns its prototypes.

| Case | Primvars | Interpolation and indexing | Inheritance | Blender domain | Display |
|---|---|---|---|---|---|
| Shared prototype | none beyond points and topology | — | — | — | Every drawn copy of an instance prototype's mesh, whatever its transform, uses one geometry resource. |
| Equal content | `st`, `displayColor` | as authored | — | as authored | Meshes outside instances with equal topology, points, and primvars are equivalent uses and share one geometry resource. |
| Named UVs | `st` and `perfuv` as `texCoord2f[]`; `ST`, `offset`, and a constant `uv_shift` as `float2[]` | faceVarying, indexed and not; vertex; constant | none | corner for faceVarying, point for vertex | Each UV set displays as a UV map with its primvar's name, so a primvar reader selects it by name. With no UV-set names, no `float2[]` primvar is a UV set; with `st` and `uv*`, `ST` is one, and neither `offset` nor the constant `uv_shift` is. |
| Mesh display color | `displayColor` (`color3f[]`) and `displayOpacity` (`float[]`) authored on the mesh | constant, also indexed; uniform; vertex; faceVarying | none | per drawn copy for constant, face for uniform, point for vertex, corner for faceVarying | Without a material, the mesh shows its display color and opacity on its interpolation's domain. |
| Inherited display color | constant `displayColor` and `displayOpacity` on instance roots and their ancestors | constant | the nearest opinion: the mesh's own, then the inner instance root's, then the outer's | per drawn copy | Copies of one prototype show their own roots' values, through nested instances, without collapsing into one appearance. |
| Instance primvars for materials | `tint` (`color3f`) and `rough` (`float`) on instance roots | constant | as for display color | per drawn copy | A material that reads them through primvar readers shows each copy's own values (the connection cases in [Connection Grammar](materials.md#connection-grammar)). |
| Face assignments | GeomSubsets of family `materialBind` | `partition`, and `nonOverlapping` with unassigned faces | a subset belongs to its mesh, inside a prototype too | face | Each face shows its subset's bound material, and an unassigned face the mesh's own binding, which may be inherited from an instance root and differ per copy. |

Per drawn copy, the representation chooses where a value is stored, and records any distinct geometry resource that needs under [Geometry Sharing](instancing.md#geometry-sharing).

## Mesh Classification

Also classify, for each case, whether the mesh remains supported with an approximation, becomes a placeholder, or fails:

- Geometric primvars such as velocities when unused.
- Opacity interpretation.
- Normal generation and domain conversion.
- Degenerate but structurally valid faces.
- Nonfinite positions and transforms.
- Unsupported topology features on an otherwise supported mesh.
