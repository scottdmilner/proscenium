# Transforms and Coordinate Conversion

Part of the supported scene state. Cross-cutting guarantees are summarized in [invariants.md](../invariants.md).

## Transforms and Time Codes

- Evaluate ordered transform operations, reset-transform-stack behavior, and transforms authored on meshes.
- Reconcile organizational relationships with reset-transform-stack behavior without requiring equivalent Blender parenting.
- Support matrix transforms, negative and nonuniform scale, and shear.
- Preserve evaluated placement rather than reconstructing editable USD transform-operation stacks.
- Diagnose approximations when exact representation is unavailable.
- Evaluate supported time-varying values at the time code synchronized and at each one cached, including topology changes.
- USD time code t is Blender frame t, its fraction a subframe, whatever the stage's time codes per second and the target scene's frame rate. Without a time code, synchronization uses the time code of the target scene's current frame, its subframe included.
- A display shows each time code cached in its generation ([Cached Time Codes](../pipeline.md#cached-time-codes)) at its frame, through Blender animation data, and at any other frame the latest cached time code before it, or before the earliest, the earliest. Interaction answers for the time code the display shows.
- Design note (settled by M4): the DECISIONS.md row "Time-sampled data representation" records the animation data used and why.
- Authored animation data and its caches are managed content under [Ownership and Lifecycle](../lifecycle.md#ownership-and-lifecycle).
- Do not change the target scene's frame rate or playback range.

## Coordinate Conversion

- Units/up-axis conversion is configurable and **disabled by default**. When disabled, the correction matrix is the identity.
- Enabled conversion respects the target scene's unit scale without changing scene settings.
- Converted results are consistent for geometry, transforms, bounds, and instances.

Coordinate conversion is owned by **representation planning**:

- The evaluated snapshot keeps source units and up-axis, recording `metersPerUnit` and `upAxis` as stage metadata.
- At synchronization start, application captures the binding's target-scene unit scale into the planning context as a plain value. This keeps Blender references out of the snapshot.
- Planning builds one correction matrix and prefixes it to every world transform. Local geometry is unchanged; bounds and instances inherit the correction. Points are converted individually only when batching bakes geometry into world space.
- If the destination collection is linked into a scene whose unit scale differs from the target scene's, diagnose the mismatch rather than guessing.

```text
scale           = stage.metersPerUnit / target_scene.unit_settings.scale_length
C               = R_upaxis @ Scale(scale)    # R_upaxis = +90° about X for Y-up sources, identity for Z-up
M_blender_world = C @ M_usd_world            # Blender column-vector convention (transposed from USD row-vector matrices)
```
