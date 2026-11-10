# Node zones proof of concept

Zones in a custom node tree, like Geometry Nodes' simulation and for-each element zones: a begin node paired with an end node, the nodes between them worked out from the links, and a rounded convex hull drawn around them with the `gpu` module. It explores Phase 3's stage editor ([node zones note](../../../docs/phase3/node-zones.md)). It is evidence, not product code.

| File | Contents |
|---|---|
| `zone_model.py` | The bpy-free zone rules: which begins and ends pair, what each zone holds, how zones nest, which links cross out, and how pairs are repaired after a copy |
| `zone_hull.py` | The bpy-free outline: a convex hull of each zone's node rectangles, rounded, with nested zones inset |
| `addon.py` | The add-on: a custom node tree and nodes that store their pairing, `_ZoneRuntimeState`, `_CachedZoneTopology`, and `_ZoneDrawData` for its caches, the draw handlers, link marking, an Add menu entry per zone kind, a pair operator, and a sidebar panel |
| `bench.py` | Headless checks of the zone rules, the pair repair, and the hull, and timings at scale |
| `demo.py` | A windowed run in the binary: a demo tree, duplicate, paste, delete and undo through Blender's own operators and keys, screenshots, and draw timings |

## Running it

Nodes store their paired end's identifier in `partner_uid`. Zone records use `begin_uid`, `end_uid`, and
`body_node_uids`; layouts expose `innermost_zone_by_node_uid` and `invalid_link_indices`.

```sh
/Applications/Blender.app/Contents/MacOS/Blender --python tools/feasibility/node_zones/addon.py
uv run python tools/feasibility/node_zones/bench.py
/Applications/Blender.app/Contents/MacOS/Blender --factory-startup --enable-event-simulate <blank.blend> \
    --python tools/feasibility/node_zones/demo.py -- <out_dir>
```

In Blender, open a node editor, pick **Zone Tree** as its tree type, make a new tree, and add a zone from **Add**: the two entries at the end of the menu add a paired begin and end. The sidebar's **Zones** tab shows the active node's zone and the tree's problems, and **Pair Zone Nodes** pairs the active begin with a selected end. The demo needs a `.blend` on its command line, because the splash screen would cover its screenshots.

## Findings

Measured on Blender 5.2.2 LTS on one macOS machine (UI scale 2.0). Draw timings are medians of 30 draws, from four runs that varied by under 1 ms; headless timings are single runs. Windowed checks drove the binary with `--enable-event-simulate` and screenshots.

- **No custom zones in the API.**
  - Blender's zone nodes (`GeometryNodeRepeatInput`, `GeometryNodeSimulationInput`, `GeometryNodeForeachGeometryElementInput`, `NodeClosureInput`, and their outputs) refused a custom tree: `nodes.new` raised "Cannot add node of type". Repeat and closure zones were accepted in a shader tree, all four in a geometry tree, none in a compositor tree.
  - `bpy.types.Node` has no zone properties or callbacks. `paired_output` and `pair_with_output` exist only on the built-in zone input nodes.
  - A Python subclass of `GeometryNodeRepeatInput` registered, but as a plain custom node: its `type` was `CUSTOM`, it had no sockets and no `paired_output`, and a custom tree still refused it.
  - **Not checked:** that zone types are registered only in C++. This is from memory of Blender's source, not read here.
- **Pairing.** Each node stores a uid from a counter on the tree; a begin stores its end's uid, as Blender's zone inputs store their output's identifier. `copy` gives the copy a fresh uid and records the uid it was copied from; the tree's `update` then pairs a copied begin with the copy of its end, or leaves it unpaired.
  - Shift-D over a whole outer zone paired both copies, the outer and the nested zone, with each other. Shift-D on a lone begin left the copy unpaired and the original paired. Copy and paste of a zone paired the pasted begin with the pasted end.
  - Deleting either half of a zone deletes the other, as in Geometry Nodes, where X on a Repeat Output also deleted its Repeat Input.
    - The add-on binds X, Delete, and Ctrl+X in the node editor to its own delete, which selects each selected begin's or end's partner and then runs Blender's `node.delete` (or `node.delete_reconnect`). X on an end deleted its begin; one Ctrl+Z brought both back, and Ctrl+Shift+Z deleted both again. Its poll passes only in a zone tree, and X still deleted nodes in a Geometry Nodes tree with the bindings registered.
    - Deleting some other way, such as `nodes.remove` from Python, is caught by the nodes' `free`, which records the deletion, and the tree's `update`, which removes the partner. Removing a begin from Python removed its end. That removal evidently lands after the delete operator's undo step: before the add-on had its own delete, one Ctrl+Z after X brought back only the begin, and a second the end. The Node menu's Delete entry, which runs `node.delete` itself, wasn't tried.
    - Undo replaces the tree's data without calling `update`, so the add-on drops its caches, and the deletions `free` recorded, in `undo_post` and `redo_post`.
  - The pair operator refused an end of another kind and paired one of the same kind.
- **What a zone holds.** Every node downstream of the begin, short of the end and what follows it, and every node whose consumers are all already inside, such as a value used only in the zone. Interface nodes never join. `bench.py` checks these rules, nesting, overlap, and the links that cross out. These rules are this prototype's; they weren't compared with Blender's.
- **Invalid links.** Setting a link's `is_valid` to False draws it red. Blender sets every link's validity after the tree's Python `update` returns, so marking links in `update` never showed; marking them from a timer registered in `update` stuck.
- **Drawing.**
  - A `PRE_VIEW` draw handler on `SpaceNodeEditor` draws in view space, over the grid and frames and under the nodes. `POST_VIEW` draws over the nodes. `BACKDROP` draws with a different projection, not looked into further.
  - A node's view-space rectangle is `location_absolute` times the UI scale (`preferences.system.ui_scale`) for its top-left corner, and `dimensions` for its size, which is already in view units. Rectangles drawn this way covered expanded nodes exactly, and hulls built from them enclosed collapsed nodes and nodes in frames in the screenshots.
  - `dimensions` is the size from the node's last draw: it read 0 before the first draw, and for every node in the first draw after an undo. So `PRE_VIEW`, which runs before the nodes draw, sees the previous frame's sizes.
    - Until the add-on remembered sizes, the first draw after deleting a node and undoing drew no zones, and none was drawn again until something else redrew the editor. The add-on now keeps each node's last size by its uid (uids and the tree's `session_uid` survived the undo), and uses it while `dimensions` reads 0; the first draw after undo then drew both zones.
    - A `POST_VIEW` handler compares the sizes the fill used with the current ones, and redraws if they differ. Tagging the region for a redraw from inside its draw drew nothing more; tagging it from a timer registered there did: a node just added drew without its size once, then with it.
  - The hull is the convex hull of the padded node corners, rounded by growing it with a circle. As in Geometry Nodes, its sides cut through the middle of the zone's begin and end, so it holds the begin's right half and the end's left half. A nested zone's hull is grown again before its parent takes it, and the parent also takes the nested zone's begin and end whole, so the nested zone sits inside with a margin. `bench.py` checks both, and the demo's screenshot showed the cuts on the outer and the nested zone. Hulls are filled with a triangle fan and outlined with `POLYLINE_UNIFORM_COLOR`, thicker while the zone's begin or end is selected.
  - A zone takes its color from its begin node's custom color, else its end node's, else its kind's, which is also the color its nodes start with. The fill is that color, and the outline the color lightened. Colors are read on every draw, so changing a node's color in the sidebar recolors its zone with no cache to drop. The demo's screenshot showed a begin recolored orange turn its zone orange, and a zone whose nodes had custom color turned off keep its kind's color.
  - Two zones' hulls overlap when their nodes interleave on screen, as a duplicated zone placed across the original did.
- **Draw cost.** The zone layout is cached and worked out again only when the tree's nodes, pairs, or links change. The tree's `update` also runs when a node is moved from Python: while `update` dropped the layout outright, one node moved per draw cost more than remaking every zone (22 ms at 881 nodes). Each zone's hull and batches are cached and remade when one of its nodes' rectangles changes.

  | Tree | Batches reused | One node moved per draw | Every zone remade |
  |---|---|---|---|
  | 121 nodes, 10 zones | 0.27–0.30 ms | 0.58–0.61 ms | 2.46–2.69 ms |
  | 881 nodes, 40 zones | 1.72–1.78 ms | 2.19–2.23 ms | 12.62–13.46 ms |

  - The draws were `wm.redraw_timer` draws, the move a `location` change between them. A drag by mouse wasn't timed.
  - Even reused, each draw reads every node's location, size, and selection in Python, which is most of the cost at 881 nodes.
  - Headless (`bench.py`), working out the zones took 0.3 ms for 138 nodes and 248 ms for 3,388 nodes in 500 zones, since each zone walks the graph.
- **Shutdown.** Batches still held when Blender quit were reported as unfreed memory; `unregister` drops them. After unregistering, a node editor still set to the tree type logged `tree_type` warnings.
- **Screenshots.** `screen.screenshot` saved the window as it was one swap earlier, so the demo draws twice before each.
- **Undo steps from scripts.** In the demo, `ed.undo` called from a timer went back to the opened file, past the tree the demo had built and the operators it had called, even after an `ed.undo_push`. Delete and undo sent as keys with `event_simulate`, after a select-all key, deleted and restored the end as a user's keys would.
