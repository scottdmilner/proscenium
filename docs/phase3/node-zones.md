# Node Zones

How Phase 3's stage editor could give its node tree zones like Geometry Nodes' simulation and for-each element zones: a begin node and an end node, the nodes between them, and an outline drawn around them. This is a design note, not a requirement ([Phase 3 notes](README.md)).

The proof of concept is in [`tools/feasibility/node_zones/`](../../tools/feasibility/node_zones/README.md). Its README lists each file and how to run it, and its findings section holds the measurements in full.

Evidence is marked as in the other notes:
- **Checked:** run on Blender 5.2.2 LTS on one macOS machine, either headless (`bench.py`) or in the Blender binary driven by simulated events (`--enable-event-simulate`) and screenshots (`demo.py`).
- **Not checked:** reasoned from documentation or memory of Blender's source, but not run here.

## Recommendation

- **Build zones ourselves.** Blender's API has no way to define a zone type, and its zone nodes can't be added to a custom tree.
- **Pair by uid, stored on the begin.** Each node gets a uid from a counter on the tree, and a begin stores its end's uid. The tree's `update` repairs pairs after a copy and unpairs a begin whose end is gone.
- **Work out what a zone holds from the links,** in code that doesn't import bpy, cached until the links or pairs change.
- **Draw each zone as a rounded convex hull from a `PRE_VIEW` draw handler,** which draws under the nodes, and cache each zone's hull until one of its nodes moves or resizes.
- **Keep the zone rules apart from the drawing,** so they test in `bpy_free`, and could move to the core if the editor's graph lives there.

## Blender's zones aren't open to add-ons

**Checked:**
- `nodes.new` refused every built-in zone node in a custom Python tree. Geometry trees took all four zone kinds, shader trees took repeat and closure, and compositor trees took none.
- `bpy.types.Node` has no zone properties or callbacks; `paired_output` and `pair_with_output` exist only on the built-in zone input nodes.
- A Python subclass of `GeometryNodeRepeatInput` registered as a plain custom node, with no sockets and no pairing, and a custom tree still refused it.

**Not checked:** Blender registers zone types in C++, from a fixed list in the node system, with nothing exposed to Python. A stage editor built on a Geometry Nodes tree could use the real zones, but would inherit Geometry Nodes' evaluation, its node types, and its modifier, so this note doesn't pursue it.

## Pairing

A begin stores its end's uid, as Blender's zone input nodes store their output's identifier. Names won't do, since renaming and duplicating change them.
- **Uids:** a counter on the tree hands each node its uid in `init`. Uids are properties on the nodes, so they're saved with the tree, and undo restores them with it.
- **Copies:** `copy` gives the copy a fresh uid and records the uid it was copied from. The tree's next `update` pairs a copied begin with the copy of its end if both were copied together, and unpairs it otherwise. **Checked:** Shift-D over a whole zone, with a zone nested in it, paired both copies with each other; Shift-D on a lone begin left the copy unpaired; copy and paste paired the pasted zone.
- **Deletion:** deleting either half of a zone deletes the other, as Geometry Nodes does (**Checked:** X on a Repeat Output also deleted its Repeat Input).
  - The prototype binds Blender's delete keys in zone trees to its own delete, which adds each selected begin's or end's partner to the selection and then runs Blender's delete, so both go in one undo step. **Checked:** X on an end deleted its begin, one Ctrl+Z restored both, Ctrl+Shift+Z deleted both again, and X still deleted nodes in a Geometry Nodes tree.
  - Other deletions, such as from Python, are caught by the nodes' `free` and the tree's `update`, which removes the partner. Its removal evidently lands after the delete's undo step: through it, one Ctrl+Z after X restored only the begin; it's a fallback, not the main path. **Checked:** removing a begin from Python removed its end.
  - **Not checked:** whether the Node menu's Delete entry, which runs `node.delete` itself, deletes the partner through the fallback.
- **Creating zones:** an Add menu entry per zone kind adds a begin and an end, paired and linked, as Blender's own zones are added. A pair operator pairs the active begin with a selected end of its kind, and refuses another kind (**Checked**).

`repaired_partners` in `zone_model.py` is the whole repair rule, as a pure function.

## What a zone holds

The prototype's rules, which `bench.py` checks:
1. Every node downstream of the begin, short of the end and anything downstream of the end.
2. Every node whose consumers are all already in the zone, repeated until nothing more joins, so a value used only inside a zone is drawn inside it.
3. Interface nodes, such as the tree's input and output, never join.
4. A zone is nested in another when its begin and end both lie in it; a node belongs to the innermost zone that holds it. A zone with only one of its two nodes in another overlaps it, and is reported as a problem.
5. A link is invalid when it leaves a zone other than through the zone's end, feeds back into the zone's begin, or takes the end's output back into the zone. Invalid links are drawn red by setting `NodeLink.is_valid`.

These rules are the prototype's. **Not checked:** how closely they match Geometry Nodes', which also has to decide, for example, where a node fed by both a zone and the outside belongs. The editor's own evaluation should decide them, since what a zone holds is what it runs per element.

**Checked:** Blender resets every link's validity after the tree's Python `update` returns, so invalid links have to be marked from a timer registered in `update`.

## Drawing

**Checked:**
- **Where to draw:** a `PRE_VIEW` handler on `SpaceNodeEditor` draws in the node editor's view space, over the grid and frames and under the nodes. `POST_VIEW` draws over the nodes.
- **Node rectangles:** a node's top-left corner is `location_absolute` times `preferences.system.ui_scale`, and its size is `dimensions`, which is already scaled. `dimensions` is the size from the node's last draw, so a node that just changed size is a frame behind in `PRE_VIEW`.
  - It reads 0 before a node's first draw, and for every node in the first draw after an undo. Reading it as is made a zone vanish after deleting a node and undoing, so the prototype keeps each node's last size by uid and uses it while `dimensions` reads 0.
  - A `POST_VIEW` handler compares the sizes the fill used with the current ones, and if they differ, redraws from a timer: a redraw tagged during the draw itself never happened.
- **Color:** a zone takes its begin node's custom color, else its end node's, else its kind's, which its nodes also start with. So a user recolors a zone by recoloring its begin in the sidebar, and the outline follows on the next draw.
- **The hull:** the convex hull of the padded corners of the zone's nodes, grown by a circle to round it. As in Geometry Nodes, its sides cut through the middle of the zone's begin and end, so only the begin's right half and the end's left half are inside. A nested zone's hull is grown again before its parent takes it in, and the parent takes the nested zone's begin and end whole, so the nested zone sits inside its parent with a margin. It is filled with a triangle fan, and outlined with the polyline shader, thicker while its begin or end is selected.

Convex hulls of two zones overlap whenever their nodes interleave on screen, as a duplicate dropped across the original did. A tighter outline, such as a hull per connected cluster or a concave hull, is still to be tried.

### Cost

**Checked:** medians of 30 draws in the binary, from four runs:

| Tree | Nothing changed | One node moved per draw | Every zone remade |
|---|---|---|---|
| 121 nodes, 10 zones | 0.3 ms | 0.6 ms | 2.5–2.7 ms |
| 881 nodes, 40 zones | 1.7–1.8 ms | 2.2 ms | 12.6–13.5 ms |

- Two caches make this:
  - The zone layout is worked out again only when nodes, pairs, or links change. The tree's `update` also runs when a node is moved from Python, so `update` compares the graph before dropping the layout.
  - Each zone's hull and GPU batches are remade only when a rectangle it takes changes: one of its own nodes', its nested zones' begins' and ends', or one inside a nested zone.
- With nothing changed, most of the cost is reading every node's location, size, and selection in Python on each draw.
- Working out the zones walks the graph once per zone: 0.3 ms for 138 nodes, 248 ms for 3,388 nodes in 500 zones (`bench.py`). That runs once per edit to the links, not per draw, but a large tree would want an incremental pass.
- A drag by mouse wasn't timed; the moves were `location` changes between `wm.redraw_timer` draws.

## Testing

- The zone rules, pair repair, and hull are plain Python, and `bench.py`'s checks would become `bpy_free` tests.
- Pairing through Blender's operators (duplicate, paste, delete, undo) needs the binary with simulated events. Operators called from a timer left no undo steps behind: `ed.undo` went back to the opened file. Keys sent with `event_simulate` worked.
- `screen.screenshot` saved the window as of one swap earlier, so a screenshot check must draw twice first.

## Open questions

- Should the stage editor's graph, and its zone rules, live in Python or in the core?
- Which zone kinds will the editor have (for each prim, for each variant, an edit target), and does each need its own rules for what it holds?
- What should happen when a user drags a node into a zone's outline without linking it? In the prototype nothing does: the outline only shows what the links make.
- Should zones also show in the editor's node interface, such as a begin's sockets matching its end's, as Geometry Nodes' zone items do?
