# Scene graph UI proof of concept

A USD prim tree in Blender's 3D View sidebar, as a virtualized UIList, with the same stage drawn by Blender's own tree view for comparison. It explores Phase 3's stage editor ([Phase 3 notes](../../../docs/phase3/README.md)). It is evidence, not product code, and reads the stage with Blender's bundled `pxr` directly, not through the core.

| File | Contents |
|---|---|
| `tree_model.py` | The bpy-free model: the expansion state of a stage's hierarchy and the flat rows it makes visible. `expand_or_enter_row` and `collapse_or_select_parent` implement keyboard navigation. Rows are spliced in and out on expand and collapse, each row's flags are read only when it is first drawn, and a search result filters the rows |
| `tree_search.py` | The bpy-free search: a query (text by name, path, glob, or regex, a schema type, flags), the prims it matches, and the ancestors that show them in place |
| `prim_text.py` | The bpy-free text of the row and badge tooltips and the details panel |
| `addon.py` | The add-on: the UIList tree with its header and search box, a details panel, and operators to open, generate, and find stages |
| `tree_keys.py` | The modal operator that takes Left and Right over the tree before the UIList does |
| `badge_icons.py` | Custom badge icons, drawn from pixels into a preview collection, for payloads, references, variants, and instances |
| `native_tree.py` | The node-interface tree: Blender's own tree view, through a hidden custom node tree's interface |
| `demo_stage.usda` | A one-file stage with one prim of each kind a row marks: class, over, inactive, payload, variant set, instances and instance proxies |
| `bench.py` | A headless check of the trees, the search, and the keys' steps on the demo stage, and timings at scale in the bpy wheel |
| `bench_watcher.py` | A windowed benchmark, in the binary, of what the key watcher and other modal operators cost per event |

## Running it

```sh
/Applications/Blender.app/Contents/MacOS/Blender --python tools/feasibility/scene_graph_ui/addon.py
uv run python tools/feasibility/scene_graph_ui/bench.py
/Applications/Blender.app/Contents/MacOS/Blender --factory-startup --enable-event-simulate \
    --python tools/feasibility/scene_graph_ui/bench_watcher.py
```

In Blender, open the sidebar (N) and its **USD Tree** tab. **Demo** opens `demo_stage.usda`, **Open** any USD file, **Generate** a synthetic stage, and the magnifier finds a prim by name and reveals it.
- **Mouse:** click a triangle to expand a prim, or Shift-click it for its whole subtree. Hover a row or a badge for its tooltip.
- **Keys:** with the cursor over the tree's sidebar tab, Right expands the active row or steps into it, and Left collapses it or steps out to its parent. Shift does the whole subtree. Up and Down are the list's own.
- **Search:** type in the search box; it runs a quarter second after the last keystroke. The dropdown picks what the text matches, and **Aa** matches case. The list's own options, under its bottom triangle, add a schema type (matched with `IsA`, so `Gprim` finds meshes and curves) and flags (has a payload, variants, is an instance, inactive).

## Findings

Measured on Blender 5.2.2 LTS (USD 0.26.3) on one macOS machine. Timings are single runs and varied by about 2× between runs. Windowed checks drove the 5.2.2 binary with `--enable-event-simulate` and screenshots; they show behavior and measured nothing.

- **No generic tree view in Python.** `UILayout` in 5.2.2 has no template for a tree an add-on defines. Its tree templates are each tied to one kind of Blender data: bone collections, Grease Pencil layers, shape keys, light linking, and the node tree interface. Only the last takes a data argument, and it is the loophole `native_tree.py` uses.
- **UIList tree.** The collection holds empty items, one per visible row, and `draw_item` reads the row from the model by index, so only the row count crosses into RNA. Expanding a group of 100,000 leaves took about 100–235 ms in the model plus 35–50 ms adding collection items. Collapsing it took 12–19 ms. A first draw of 40 rows took about 3 ms whatever the group's size. The headless runs time neither drawing nor scrolling.
  - Indent with one small separator per level (`separator(factor=2.0)`), not one large one: a separator's spacer is square, so a deep one makes its row taller. A blank icon per level also keeps rows even, but its width left deep names a letter or two in a sidebar.
  - `has_children` must not list a prim's children: `GetFilteredChildrenNames` on a 250,000-child group cost about 20 ms per call.
  - Shrinking the collection one `remove` at a time from the end is quadratic (35 s for 100,000 items); `clear` then `add` isn't.
  - In Blender 5, `bpy.props` values aren't dict-style ID properties, so `wm["prop"] = v` doesn't set a registered property and can't bypass its update callback; a flag does.
- **Custom icons and tooltips.**
  - `icon_value` takes any preview's icon from `bpy.utils.previews`, loaded from an image file or, as here, drawn from pixels (`icon_pixels_float`). The windowed run drew the four badges. They keep their own colors, unlike Blender's icons, which the theme recolors. Preview icons get `icon_id` 0 in the headless wheel, so they need the binary.
  - A row's tooltip comes from `template_list`'s `item_dyntip_propname`, a string property on the item. Here it's a getter, computed on hover from the model, using the item's index in its RNA path.
  - Labels can't have tooltips, so each badge is a borderless operator button, and the operator's `description` classmethod writes the tooltip from that button's properties. Clicking a badge selects its row.
  - The bench checks the tooltip text. Neither windowed run showed a tooltip on screen: one moved the cursor with `cursor_warp`, the other with simulated mouse moves, which did highlight the hovered row. Hovering by hand is still to be checked.
- **Header row.** A UIList has no column headers, so the header is a row above the list, split at the same factor as each row. The list's padding offsets its columns from the header's by a few pixels. The header can hold controls; here an eye toggles the type column.
- **Keys.** Keymaps can't give the tree plain Left and Right, but a modal operator can (`tree_keys.py`). The windowed runs found:
  - While the cursor is over the list, the UIList takes the plain arrow keys itself, before any keymap: Left and Up move the active row to the previous one, Right and Down to the next. Its update callback sees only the active row change, not which key changed it.
  - In the sidebar, the "Frames" keymap comes before "3D View Generic", so Shift+Right jumped frames instead of reaching a binding in "3D View Generic". An add-on item in the "Frames" keymap itself did win Shift+Right over the frame jump while its poll passed. Alt+Left/Right, which neither the list nor "Frames" takes, did reach "3D View Generic" bindings.
  - A modal operator's handler runs before the regions' handlers, so it sees each key before the list does. Running in each window and passing every other event on, it took plain and Shift Left/Right while the cursor was over the sidebar showing the tree's tab: the tree expanded, stepped, collapsed, and expanded and collapsed whole subtrees as the bench's checks of `expand_or_enter_row`, `collapse_or_select_parent`, and `set_expanded` expect. Up and Down still moved the list's active row, the frame didn't change, and Right over the viewport still stepped a frame.
  - While a text field is being edited, the field gets keys before the watcher: typing `a`, Left, `b` in the search box gave `ba`, and the tree didn't move.
  - A modal operator ends when a file loads, so the watcher restarts from `load_post`. Unregistering the add-on while a watcher ran, then sending 20 mouse moves and a key, raised no error and Blender kept running.
  - A modal operator that ends by returning `CANCELLED` consumes the event it ends on, so the modal operators after it don't see it. Returning `{"CANCELLED", "PASS_THROUGH"}` passes it on.
  - The disclosure triangle's tooltip (its operator's `description`) says what a click does to that row and lists the keys.
- **Watcher cost.** `bench_watcher.py` times batches of 2,000 simulated mouse moves over the 3D View, with stand-in modal operators that pass every event on at once, and with the tree's watcher among them. Two runs of 7 trials each, medians:

  | Modal operators | µs per event | Added µs per event |
  |---|---|---|
  | None | 1.5 | 0 |
  | 1 stand-in | 3.3 | 1.8 |
  | 1 stand-in and the tree's watcher | 4.6–4.8 | 3.1–3.3 |
  | 10 stand-ins | 18.3–18.5 | 16.8–16.9 |
  | 10 stand-ins and the tree's watcher | 19.9 | 18.3–18.4 |
  | 50 stand-ins | 86.1 | 84.5–84.7 |

  - Each Python modal operator adds about 1.7 µs to every event, and the cost adds up linearly. The watcher's own code ran in 0.26–0.27 µs a call; the rest is Blender calling into Python.
  - Simulated mouse moves aren't merged the way real ones are, and the batches time event handling only, not drawing.
  - A counting stand-in checked that each batch's timer ran after all 2,000 events.
- **Properties editor: not recommended.** A windowed run drew the tree in a Properties editor's Scene tab, in a workspace that copied the current one with its Outliner turned into that editor. The keys stepped the tree there, but the editor doesn't suit it:
  - An add-on can't add a Properties tab, so the tree shares the Scene tab with Blender's panels, and shows in every Properties editor on that tab.
  - `bl_order` can't go below 0, Blender's own Scene panels' order, and panels of equal order are listed in the order they were registered, so the tree came after Blender's Scene panels. Only registering Blender's Scene panel classes again after the tree's put it at the top, which changes classes Blender owns.
  - Changing an area's type on a screen that isn't showing changed `area.type` but left the old space in place, so arranging a new workspace has to wait until it shows.
- **3D View toolbar and Tool Settings.** A windowed probe registered the tree's panel in both regions:
  - In the toolbar (`TOOLS`), the panel drew inside its strip of tool icons, 113 pixels wide, too narrow for rows.
  - The Tool Settings strip (`TOOL_HEADER`) is one row high and draws panels only as popovers. A popover button appended to its header drew there, and clicking it called the panel's draw. The popover itself never showed in a screenshot, as tooltips didn't either. A popover closes when the cursor leaves it, so the tree would close whenever the cursor went back to the viewport.
- **Search.** The UIList's own filter hides every row that doesn't match, and sees only the rows already visible. This search runs over the whole stage, then shows each match under all its ancestors, expanded to reach it, with the ancestors that don't match greyed and their other children hidden. A match's own children all show when it is expanded. Clearing the search restores the expansion from before it and reveals the selected prim.
  - The text box updates on every keystroke (`options={"TEXTEDIT_UPDATE"}`), and a timer runs the search after a pause; the windowed run showed the timer's search filter the tree.
  - The list's `draw_filter`, the options under its bottom triangle, can draw anything, so it holds the search's options instead of the list's own name filter.
  - Each flag is its own boolean toggle. An expanded `ENUM_FLAG` property sets one item per click (Shift-click adds or removes one), so once one flag was set, a click couldn't clear them all.
  - A search traverses the stage in Python at about 5 µs per prim: 130–230 ms for 37,000 prims, 5.3 s for a million with no match. Listing every prim's name once (1.4 s for a million) and searching that list took about 35 ms a search; keeping such an index current as the stage changes wasn't tried.
  - Showing many matches under one parent filters that parent's children: 10,000 matches among a million siblings took 1.5 s to lay out.
- **Node-interface tree.** Panels nest, and the tree draws with Blender's own tree view, so collapsing, drag and drop, renaming, and an active item come with it. But:
  - It reorders children: within a panel, sockets (leaf prims) come before panels (prims with children). `/World`'s children `Geometry, Looks, Camera, Sun, Scatter` show as `Camera, Sun, Scatter, Geometry, Looks`.
  - Building it costs more than linearly: 2,000 prims in about 125–320 ms, 10,000 in 4.4–10 s. Every prim is built up front; nothing loads when a panel opens.
  - The node group is an ID: it is saved in the .blend file and its edits are undo steps. Drag and drop and renaming change the interface, not the stage, so a real tool would have to turn them into USD edits or undo them.
  - Leaves draw as socket rows, with a socket's dot and none of the row's own icons or badges.
  - Panels built with `default_closed=True` still showed expanded in the tree in the windowed run; that flag is the node's, not the tree view's.
