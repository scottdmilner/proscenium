# Native Instancing

Part of the supported scene state. Cross-cutting guarantees are summarized in [invariants.md](../invariants.md).

## Supported Instancing

Support:

- Native and nested native instances.
- Multi-mesh, multi-material instance contents.
- Shared underlying geometry.
- Effective instance transforms, visibility, and purpose.
- Updates to shared contents.
- Transitions between instanced and non-instanced representations.
- Per-instance `displayColor`, inherited material assignments, and named primvars driving supported material inputs.

Instance-root selection and instance-context correspondence follow the [interaction contract](../interaction.md#source-inspection-and-interaction).

## Geometry Sharing

Within a binding, deduplicate geometry whenever sharing preserves correct display. Per-instance appearance must not collapse into a single shared appearance. Distinct geometry resources are permitted when required to preserve geometry, attributes, material assignments, or per-instance appearance in the chosen representation. Uses with equivalent geometry-resource requirements remain shared, including equivalent variants within cases that require distinct resources. Separate bindings do not share managed geometry resources.

M4 records sharing criteria and the display state that requires each distinct-resource case, with a correctness fixture and measured resource cost. M8–M10 implement and validate those criteria. Reducing mesh-data counts never justifies an incorrect display.
