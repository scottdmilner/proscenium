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

## Ownership and Diagnostics

Document ownership and reuse rules for translated materials, images, node groups, and dependencies. Diagnose missing textures, unsupported networks, and incomplete translations. Do not silently substitute another UV set when the requested one is unavailable.
