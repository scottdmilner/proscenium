# Visibility, Models, and Unsupported Content

Part of the supported scene state. Cross-cutting guarantees are summarized in [invariants.md](../invariants.md).

## Visibility and Purpose

Respect effective inherited visibility separately from purpose.

| Destination | Default included purposes |
|---|---|
| Viewport | `default`, `proxy` |
| Final render | `default`, `render` |

Exclude `guide` by default. Support both destinations from the same evaluated snapshot.

Do not traverse only currently visible prims: organization, render-only content, inherited state, and supported descendants may still be needed.

## Models and Unsupported Content

Expose model kind and available asset metadata. Preserve source model grouping in inspection and use applicable bounds information.

Support is decided **per behavior, not per prim type**. Transform, imageability, geometry, material binding, and inspection metadata are each evaluated independently, so one unsupported behavior does not short-circuit the others.

For unsupported geometry:

- Use a bounding-box placeholder when usable bounds are available.
- Otherwise create an empty marker and warn.
- Respect transforms, visibility, and purpose.
- Avoid expensive unsupported evaluation merely to obtain bounds.

## Deferred and Out of Scope

Deferred areas include point instancers, curves, NURBS patches, points, elementary geometry, cameras/lights, skeletal deformation, physics, unsupported custom-schema visualization, hole-face support, and `.usdz` packaging.

Additional shader systems, generated simplified proxies, export, round trips, and render equivalence are outside scope.
