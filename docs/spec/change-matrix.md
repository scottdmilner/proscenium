# Change Matrix

What each change to a binding's source, settings, or state affects, and what a refresh does about it, under [Change Discovery](incremental.md#change-discovery) and [Affected Content](incremental.md#affected-content). M7 lists the cases its content covers: drawn copies shown as objects, with their bounds meshes, shear parents, and animation data. Each later milestone adds the cases its content brings. Cross-cutting guarantees are summarized in [invariants.md](invariants.md).

## Actions

A refresh compares the new plan with the plan of the generation the destination shows ([DECISIONS.md](../DECISIONS.md) "Incremental refresh comparison"), and each difference takes one of these actions:

- **Local update:** a kept resource is changed in place: a drawn copy's world matrix, its shear parent's matrices, its hide flags, its cached keys removed, or its object pointed at a replacement bounds mesh. The resource keeps its identity and its Blender selection.
- **Partition rebuild:** the drawn copy's partition is prepared anew beside the published generation, and publication replaces the old one, which is retired.
- **Full rebuild:** every partition is prepared anew, as for a first synchronization.
- Local updates are made at publication, and publication undoes them if it fails.
- A resource that unmanaged content uses is never updated in place: its partition is rebuilt, and it is released intact.
- A refresh writes only what its actions name. A resource the comparison finds equal is not written. The generation record and the last attempt are written when what they record changes (the applied settings, the unit scale, the time code, or the source revision), even when no resource is.
- A bounds mesh whose content changed is replaced, and its kept object is pointed at the replacement.

## Cases

| Change | Source-affected | Dependency-affected | Action |
|---|---|---|---|
| A prim added, activated, or loaded through a payload | The prim and its subtree | None | A partition built for each new drawn copy |
| A prim removed, deactivated, or unloaded through a payload | The prim and its subtree | Their drawn copies' resources | Those partitions retired |
| A prim renamed or moved under another parent | The prim and its subtree, at both paths | The drawn copies at the old paths | The old partitions retired and new ones built, since a copy's identity includes its source path |
| A variant selection switched | The prims the switch recomposes | Their drawn copies | Each copy compared with the published one at its identity, and acted on by the cases below; an equal copy is not written |
| A gprim's type changed | The prim | Its drawn copy | A placeholder box becoming a marker, or a marker a box, rebuilds its partition; a box whose bounds changed has its bounds mesh replaced |
| A transform changed, on a prim or an ancestor | The prim | Every drawn copy beneath it whose world transform changed, inside native instances included | A local update of their world matrices; a copy whose shear appears or vanishes rebuilds its partition |
| Visibility changed, on a prim or an ancestor | The prim | Every drawn copy beneath it whose visibility changed | A local update of their hide flags |
| Purpose changed, on a prim or an ancestor | The prim | Every drawn copy beneath it whose participation changed | A local update of their hide flags; a copy that leaves both destinations is retired, and one that enters a destination is built |
| An untranslated gprim's bounds changed, appeared, or vanished | The prim | Its drawn copy | Changed bounds replace its bounds mesh; bounds that appear or vanish rebuild its partition |
| A prim made instanceable, or no longer instanceable | The instance root | The drawn copies beneath it, whose instance contexts change | Their partitions retired and new ones built, since a copy's identity includes its instance context |
| A prim inside a native instance's shared contents changed | The prim in its source | Its drawn copies in every instance | Each copy acted on by the cases above |
| A point instancer's points, ids, or prototypes changed | The instancer | The drawn copies of the points that changed | Each copy acted on by the cases above; with authored ids, the other points' copies are kept; without them, a point's index is its identity, so a point added or removed renumbers every later point, and each index's copy is compared with the one published at that index; one whose point now draws another prototype has another source path, so it is retired and another built |
| The time code synchronized changed | The prims whose values differ at it | The drawn copies whose planned content differs | Each copy acted on by the cases above; when no values differ, no resource is written |
| A generation with cached time codes synchronized again | None | Every kept drawn copy with cached keys | A local update removing its keys, and its animation data retired; a copy given a shear parent for a cached time code alone, or whose bounds were sampled, rebuilds its partition |
| The payload policy changed | The payloads loaded or unloaded | Their contents' drawn copies | As a prim loaded or unloaded through a payload |
| A destination's purposes changed | None | Every drawn copy whose participation changed | As a change of purpose |
| Coordinate conversion turned on or off, or the target scene's unit scale changed while it is on | None | Every drawn copy | A local update of every world matrix |
| The target scene's unit scale changed while coordinate conversion is off | None | None | No resource written |
| The representation version changed | None | Every managed resource | A full rebuild |
| A reload reread layers | The prims whose composed state the reread opinions changed | Their drawn copies | Each copy acted on by the cases above |
| A stage attached in place of another | The prims whose composed state differs | Their drawn copies | Each copy acted on by the cases above |
| An undo or redo restored another generation | None | The drawn copies that differ from the restored generation's plan | Each copy acted on by the cases above; without that generation's plan held, a full rebuild |
| A `.blend` reopened | None | Every managed resource | A full rebuild |
| A full rebuild requested | None | Every managed resource | A full rebuild |

## Discovery

Design note (settled by M7; see [DECISIONS.md](../DECISIONS.md) "Change discovery"): a binding's kept scene-index chain records Hydra's notices between captures, and its source-info filter's stage listener adds what Hydra doesn't dirty, so a capture re-copies only the prims they name. That covers edits to the attached stage, reloads, a stage attached over the same layers, and another payload policy, mask, muting, or interpolation matched on the evaluation stage. A capture is full when its chain is new: once the evaluation stage is dropped, as when another stage's layers are attached, after a capture that fails or is discarded, and on a requested full rebuild. Settings, unit scale, and the representation version are planning's inputs, not the capture's; they, and an undo or redo, are found by comparing with the generation record the destination holds. Whatever discovery proposes, comparing plans decides what is written.

## Owned by Later Milestones

- Geometry, topology, normals, and primvars, and a drawn copy moving between a batch and an object of its own: M8.
- Materials, networks, bindings, and their dependencies, including external assets changed without a USD edit: M9.
- Changes to shared instance contents' representation, and point instancers nested in point instancers: M10.
- Managed Blender content requiring repair: M11.
