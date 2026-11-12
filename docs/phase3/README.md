# Phase 3 Notes

Findings and design notes for [Phase 3 — USD Stage Editor](../PROJECT.md#phase-3--usd-stage-editor), kept for Phase 3 work, some of which may proceed alongside Phases 1 and 2 ([DECISIONS.md](../DECISIONS.md) "Phase 3 ordering"). Nothing here is a requirement: requirements are in [PROJECT.md](../PROJECT.md), [spec/](../spec/invariants.md), and [testing/](../testing/strategy.md), and where a note conflicts with them, they win. A note that becomes a requirement moves into the spec, with its matrix rows.

| File | Contents |
|---|---|
| [scene-graph-ui.md](scene-graph-ui.md) | A prim tree for the stage editor: a virtualized UIList over a model kept apart from drawing, where it fits in Blender's UI, and its keys, icons, tooltips, search, and selection, and the widget in `src/proscenium/ui/` that a host places, with the proof of concept's measurements |
| [scene-graph-rows.md](scene-graph-rows.md) | Every piece of data a scene graph row could carry and every control a `UIList` row has over its look, for pairing the two |
| [node-zones.md](node-zones.md) | Zones in the editor's node tree, like Geometry Nodes' simulation and for-each zones: why Blender's can't be used, pairing begin and end nodes by uid, what a zone holds, and drawing its outline with the `gpu` module, from the proof of concept in `tools/feasibility/node_zones/` |
| [node-tree.md](node-tree.md) | The stage editor's node tree for its first feature set: the tree as the source of truth for the layers it authors, layers flowing along links, socket types and their USD types, and the nodes that read, author, compose, and write layers |
| [usd-asset-library.md](usd-asset-library.md) | Offering USD assets through Blender's asset system: an asset library of stand-in assets, catalogs, and an asset shelf whose operators create bindings |
