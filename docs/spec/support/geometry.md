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

Validate topology and attribute sizes before passing data to Blender. Diagnose unsupported types, domains, lossy conversions, holes, and inexact subdivision mappings.

## Primvar Support Matrix

Settle the primvar support matrix **before implementation**. For each supported primvar category, record USD value types, interpolation modes, indexed handling, inheritance, Blender attribute domain, conversion rules, missing/invalid-value behavior, and name-collision rules.

Before choosing a display backend, M4 defines and freezes concrete cases for geometry sharing, named UVs, face-level material assignments, and primvars driving per-instance appearance. Record the relevant value types, interpolation modes, indexed handling, inheritance, domains, and how varying data reaches the display. M8 completes the full matrix against these cases. Additions or changes affecting backend feasibility, sharing, or partitioning require rerunning the relevant M4 prototypes before implementation and revising the decision record and affected milestones as needed.

## Mesh Classification

Also classify, for each case, whether the mesh remains supported with an approximation, becomes a placeholder, or fails:

- Geometric primvars such as velocities when unused.
- Opacity interpretation.
- Normal generation and domain conversion.
- Degenerate but structurally valid faces.
- Nonfinite positions and transforms.
- Unsupported topology features on an otherwise supported mesh.
