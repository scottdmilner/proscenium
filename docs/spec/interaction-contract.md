# Interaction Contract

The interaction contract that [Source Inspection and Interaction](interaction.md#source-inspection-and-interaction) requires: what source inspection exposes, how selections resolve, and how they reach Blender. M2 drafted it, and M4 finalized it with its answers to the [M2 plan](../plans/M02-contracts.md#feasibility-questions-for-m4)'s feasibility questions ([M4 plan](../plans/M04-prototypes.md), F2); M7, M8, and M10 implement it. Cross-cutting guarantees are summarized in [invariants.md](invariants.md).

The contract defines what the display layer provides, not its Blender structure. Each requirement is stated as the result of a headless function (see [Headless Functions](#headless-functions)), so it can be checked against any display representation.

## Two Layers and the Live Stage

Callers of the contract have the binding's live USD stage. They browse and inspect it through the USD API: hierarchy, prims, attributes, metadata, and composition. The contract provides no browsing or inspection functions of its own, only what the stage cannot answer: what is displayed, and how display and source map to each other. Two layers share that work:

- The **correspondence layer** says what is displayed and which source entity each displayed thing came from. The compiled core maintains it, from Hydra's scene indices and the composed stage, as part of planning; application only records which Blender resources realize each correspondence entry. It is persisted with the published generation, and after a `.blend` is reopened, the core loads it from Blender data once the binding has a live stage, without synchronizing. It resolves picks to source prims, says which prims are displayed, and shows a set of source prims as selected. It stores no inspection data.
- The **inspection layer** maps picked prims to selection targets by model kind on the live stage. It never reads the display, the plan, or the snapshot, and it is not needed to display anything or to select at the prim level.

The inspection layer is a C++ library that does not touch Blender. It does not depend on the compiled core: it shares no code with it, and uses none of the core's scene indices, snapshot, or plan. Its inputs are a USD stage, source paths, and model kinds. The core calls it; it has no Python bindings of its own.

The core's Python bindings expose the interaction functions, and the core routes each call to the correspondence and inspection layers internally, so paths never pass through Python between the layers. The only Python in interaction is the display component that reads and writes Blender's selection state.

The inspection layer is read-only. It never authors USD, loads or unloads payloads, changes the population mask, or changes any other stage setting.

A binding's live stage is its source stage ([Source Stages](source-access.md#source-stages)): the caller's attached stage, available as soon as it is attached, before any synchronization. An unattached binding has no live stage, including after release or reopening a `.blend`. Callers get a binding's live stage from the binding, which never places it in a stage cache. The caller may supply a stage it acquired from a stage cache.

The live stage may differ from the display once the source has changed since synchronization. Callers that need values matching the display read them at the time code it shows ([Transforms and Time Codes](support/transforms.md#transforms-and-time-codes)).

## Without a Live Stage

Interaction requires the binding's live stage. Without one, such as when a saved display is reopened with its source unavailable, the saved display remains displayed as ordinary Blender content, each of the core's interaction functions reports that the source is unavailable, and stored persistent selections are kept unchanged. The Python display component's functions read only display targets and Blender's state, not the source.

## Source Entities and Hierarchy

A source entity is a binding plus a USD prim path, with an instance context when the prim lies inside instance contents: a native instance's, or a point instancer's copies of its prototypes. Source paths are USD paths in the composed stage; Blender display names and parenting are never source identifiers.

A copy a point instancer draws is named by its point-instance path: the instancer's path, then an element naming the point, `__id_<id>` by its authored id (`__id_n<id>` for a negative one) or `__index_<index>` when the instancer authors no ids, then the prim's path below its prototype root's parent, so it begins with the root's name. No prim has that path. Its instance context is the native-instance roots enclosing the instancer, then the instancer, then the point, then any native-instance roots inside the prototype, outermost first.

The source hierarchy is the composed stage's: an entity's ancestors are the prefixes of its USD path, and model kinds are read from the live stage. Hydra may flatten, regroup, or omit prims, so Hydra paths and nesting are never used for grouping or selection expansion.

## Browsing Universe

The browsing universe of a published generation is every prim outside native-instance contents that has a viewport display element of its own, or has one beneath it in the source hierarchy, including through native instances and point instancers. Display elements include placeholders and empty markers for unsupported geometry. A source inspector browses the live stage and uses the universe to tell which prims are displayed and selectable.

- Membership uses the viewport destination's included purposes and evaluated visibility at the time code the display shows. Content displayed only in the final render destination is not in the universe.
- Ancestors of displayed content are in the universe, including organizational prims that Hydra does not keep.
- Prims with nothing displayed in their subtree are not in the universe: materials, shaders, empty organizational prims, and types without display support.
- Instance-proxy descendants, point-instance paths, unloaded payload roots, inactive prims, abstract prims, and composition provenance are not in the universe. A later scene-graph inspector (Phase 3) may expose them; this contract does not.
- The universe belongs to its published generation. It is derived from correspondence, not stored: the entities that display elements represent, outside instance contents (an element inside instance contents counts for its floor), plus the prefixes of their paths.

## Picking

A pick resolves to the binding and source entity of the display element hit, including its instance context when it lies inside instance contents. Resolution uses only the published generation's correspondence, never Blender names or parenting. A pick supplies what a ray cast returns: the object hit and its world matrix. For an object that shows one display element, the object names it; for an instance in a batch, the object is the batch's prototype, and the element is the instance whose world transform the matrix is. That a real viewport pick supplies this is assumed, not verified: an accepted risk ([Interaction Testing](interaction.md#interaction-testing)).

## Selection

Selection runs through both layers. The correspondence layer resolves a pick to a source prim, the inspection layer maps that prim to a selection target when a model kind is chosen, and the correspondence layer shows the target's subtree as selected.

The caller supplies a selection level: either the prim level or a model kind.

- The floor of an entity is the outermost native-instance root or point instancer enclosing it, or the entity itself when it is not inside instance contents. The correspondence layer derives it from the entity's instance context. Nothing inside instance contents is a selection target.
- At the prim level, the target is the floor.
- At a kind level, the inspection layer maps the floor to the nearest ancestor-or-self on the live stage whose kind is that kind or derives from it. A prim's kind is the one authored on it, whether or not its ancestors place it in a valid model hierarchy (`UsdPrim::IsModel`). When no such ancestor exists, or the floor is absent from the live stage, the target is the floor.

Selecting a target selects its subtree: the target and every entity in the universe beneath it in the source hierarchy. The display elements of a selection are those of its expanded entities, found through correspondence, independent of how Hydra or the display representation groups them.

Highlighting a source selection resolves to display targets that cover exactly the viewport display elements of its expanded entities: none outside it and none missing. No display object covers both selected and unselected viewport elements: a batch shows its instances through one object for each selection state they hold.

## Persistent Selection

A persistent selection is an ordered set of (binding identifier, USD path) entries plus an optional active entry, stored in Blender data per scene. It may hold entries from several bindings. It stores targets, not their expanded members.

- Resolution checks each entry against its binding's published generation, at the time code the display shows ([Transforms and Time Codes](support/transforms.md#transforms-and-time-codes)), and expands the entries that are in its universe.
- An entry whose path is not in that generation's universe stays stored and is reported unresolved. It resolves again when a later generation displays it.

## Blender Selection

A source selection is mirrored into Blender's selection state, in the active view layer, and into a view layer again when it becomes active:

- A managed display object whose source coverage lies entirely within the expanded selection is selected, and one covering none of it is deselected. None covers part of it (see [Selection](#selection)).
- When the active entry has exactly one display object, it is the active Blender object. When it has several, such as a component shown by several objects, all of them are selected and there is no active object.
- The selection state of unmanaged objects is never changed.

Selecting displayed content produces a source selection through a selection tool the extension provides: the targets, at the current selection level, of the source entities its pick or box identifies. A box identifies the viewport display elements whose world bounds' centers lie inside it. Blender's own selection tools don't select managed content: while another tool is active, managed objects are unselectable, and the source selection is mirrored back once the extension's tool is active again. `selection_from_blender` gives the source selection that Blender's selection of managed objects identifies.

Blender's transform tools are not USD authoring tools. Edits to managed content are not authoritative, and refresh restores the published representation.

## Headless Functions

Design note (names and signatures are settled by M3 and M7): the contract is checked through these functions, which take and return plain values so that they run without a window. Everything else a caller needs, it reads from the live stage.

Core bindings, which route to the correspondence and inspection layers internally:

| Function | Input | Result |
|---|---|---|
| `resolve_pick` | what a viewport pick supplies for the representation | the hit source entity, with instance context, and its floor |
| `select_targets` | resolved entities and a selection level | their selection targets: the floors at the prim level, or the inspection layer's mapping on the live stage at a kind level |
| `displayed` | source paths | whether each is in the browsing universe |
| `highlight_targets` | selection targets | the display targets covering exactly their expanded entities |
| `selection_from_blender` | the display-resource identities of Blender's selected and active managed objects, any pick data, and a level | the selection targets of the source entities they identify |

Python display component:

| Function | Input | Result |
|---|---|---|
| `apply_selection` | display targets, with those of the active entry marked | Blender's selection and active state, mirrored |
| `read_blender_selection` | Blender's selection state | the display-resource identities of the selected and active managed objects |

`displayed` serves both a stage browser, to mark displayed prims, and persistent-selection resolution.

## Interfaces for Future Tools

Future USD manipulation tools receive: the live stage, source/display resolution in both directions (`resolve_pick`, `displayed`, `highlight_targets`), getting and setting the source selection, notification when the source selection changes, the time code the display shows, and the published generation's settings. Phases 1 and 2 provide no authoring interfaces.
