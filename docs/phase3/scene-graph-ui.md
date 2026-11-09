# Scene Graph UI

How Phase 3's stage editor could show a USD stage's prim hierarchy as a tree in Blender: which UI mechanism to build it on, where in Blender's UI it fits, and what the keyboard, icons, tooltips, search, and selection can do. This is a design note, not a requirement ([Phase 3 notes](README.md)).

The proof of concept is in [`tools/feasibility/scene_graph_ui/`](../../tools/feasibility/scene_graph_ui/README.md). Its README lists each file and how to run it, and its findings section holds the measurements in full. The PoC reads stages with Blender's bundled `pxr` directly, not through the core.

Evidence is marked as in the other notes:
- **Checked:** run on Blender 5.2.2 LTS (USD 0.26.3) on one macOS machine, either headless in the bpy wheel (`bench.py`) or in the Blender binary driven by simulated events (`--enable-event-simulate`) and screenshots.
- **Not checked:** reasoned from documentation or code, or seen in another add-on, but not run here.

Timings are single runs unless stated, and varied by about 2× between runs. Windowed checks show behavior; only `bench_watcher.py` measured anything in a window.

## Recommendation

- **Build the tree as a virtualized `UIList`** in a sidebar, over a model kept apart from drawing. Each visible row is an empty collection item, and `draw_item` reads that row from the model, so only the row count enters Blender's data. It got Blender's theme, scrolling, tooltips, and DPI scaling with nothing extra, and kept up at 100,000 rows in a group.
- **Host it in two places, over one model and drawing:**
  - **The 3D View sidebar,** showing a binding's stage and selecting with the viewport ([Selection with the Viewport](#selection-with-the-viewport)). That's where the tree was checked.
  - **The node editor's sidebar,** beside the stage editor's node tree, showing its active Viewer's stage ([Node Tree](node-tree.md#viewer)). No binding displays that stage, so selecting a row there selects no Blender objects.

  A dedicated pane, an editor whose header is hidden and whose sidebar is dragged nearly full width, is the next candidate. The Properties editor, the toolbar, and the Tool Settings strip don't suit a tree.
- **Take Left and Right with one modal operator** that passes every other event on. Keymaps can't reach plain arrow keys over a list. A Python modal operator costs about 1.7 µs per event.
- **Search the whole stage, and show each match under its ancestors.** The UIList's own filter can't do that. At a million prims, a Python traversal is too slow for typing, and an index is the fix.
- **Keep the row model and the search independent of the drawing,** so they test in `bpy_free` and could move into the core.

## Approaches

Python can't register a new editor type, and `UILayout` has no general tree widget, so every approach borrows one of Blender's existing widgets or draws its own.

### UIList with virtualized rows: recommended

A flat list of the visible rows, each with its depth, drawn with indentation and disclosure triangles. The Maya Workflow Kit builds its Outliner the same way, as a `UIList` in the 3D View sidebar (**Not checked** here beyond reading its source). It gives up drag and drop and a native tree's guide lines. The rest of this note is about this approach.

### Blender's own tree view, through a node tree's interface: rejected

**Checked:** `UILayout` in 5.2.2 has tree templates only for particular Blender data: bone collections, Grease Pencil layers, shape keys, light linking, and the node tree interface. Only `template_node_tree_interface` takes data an add-on can define. Drawing a hidden custom node tree's interface panels (prims with children) and sockets (leaves) shows the stage in Blender's C++ tree view, with collapsing, drag and drop, renaming, and an active item. It doesn't suit a stage editor:
- **Reordered children:** within a panel, sockets come before panels, so a prim's leaf children are listed before its children that have children. `/World`'s `Geometry, Looks, Camera, Sun, Scatter` showed as `Camera, Sun, Scatter, Geometry, Looks`.
- **Slow builds, built up front:** 2,000 prims took 125–320 ms and 10,000 took 4.4–10 s, more than linear. Nothing loads lazily when a panel opens.
- **Blender data, not the stage:**
  - The node group is an ID: it's saved in the .blend file, and its edits are undo steps.
  - Drag and drop and renaming change the interface, not the stage.
  - Leaves draw as socket rows, with no room for type icons or badges.
  - `default_closed=True` still showed panels expanded, since the flag is the node's, not the tree view's.

### Custom drawing with the `gpu` module: not pursued

`bl_ui_widgets` draws its own panels and buttons with `gpu` and `blf` from a draw handler, and receives input through a modal operator that runs all the time. That would give full control: drawing straight from the model, drag and drop, connector lines. But it also means rebuilding everything Blender's UI gives: theme colors, DPI scaling, tooltips, text input with IME, focus, and undo. **Not checked:** none of this was built.

The Maya Workflow Kit uses `gpu` for decoration over native widgets: about 50 draw handlers mark up Blender's own editors, such as joint markers drawn over the real Outliner. That remains an option for what a `UIList` can't draw, such as tree guide lines. **Not checked:** no overlay was drawn over a `UIList` here.

### Other options

- **Overlaying Blender's Outliner** could add USD badges to the managed collection's objects. It can't show prims with no Blender object (unloaded payloads, inactive prims, classes, overs, prototypes), so it can't be the stage editor. **Not checked.**
- **A custom node tree in the node editor** is the wrong shape for a hierarchy. It could suit a view of the layer stack and composition arcs, with panning, links, and selection built in. **Not checked.**
- **An external window** (Qt or a web view) is ruled out: it means bundling Qt, an event loop alongside Blender's, and reaching Blender other than through `bpy`.

## The row model

`tree_model.py` holds a stage's expansion state and its visible rows, with no `bpy`. Its shape carries over to any drawing:
- **Rows hold only a prim and a depth.** Expanding a prim splices its visible subtree into the list after its row, and collapsing it cuts that subtree out. Each costs the rows it adds or removes, not the list's length.
- **Details are read when a row first draws.** A row's name, type, flags, and badges are read from the prim and cached, so a widget pays for the rows on screen.
- **Children are listed with instance proxies included.** The model uses `Usd.TraverseInstanceProxies(Usd.PrimAllPrimsPredicate)`, so inactive, unloaded, class, and over prims show, as do the contents of native instances.
- **Checking for children must not list them.** **Checked:** `GetFilteredChildrenNames` on a 250,000-child group cost about 20 ms per call. A `PrimRange` iterator that stops at the first descendant doesn't depend on the group's size.

**Checked** headless, on a group of 100,000 leaves:
- **Expanding:** about 100–235 ms in the model, plus 35–50 ms adding collection items.
- **Collapsing:** 12–19 ms.
- **First draw:** 40 rows' details took about 3 ms whatever the group's size.

At a million leaves, expanding took about 1.3 s in the model plus 0.45 s adding items. Neither drawing nor scrolling was timed.

## UIList mechanics

- **Empty items:** the collection holds one empty `PropertyGroup` item per visible row. Only the count changes on expand and collapse, and `draw_item` reads the model by the row's index.
- **Resizing:** **Checked:** removing items one at a time from the end is quadratic (35 s for 100,000), so shrinking clears the collection and adds items back.
- **Indentation:** **Checked:** one `separator(factor=2.0)` per level keeps rows even. One deep separator makes the row taller, because a separator's spacer is square. A blank icon per level cut deep names to a letter or two at sidebar width.
- **Columns:** a 72% name column with the type and badges right-aligned after it read in full at sidebar width.
- **Updating properties without callbacks:** **Checked:** in Blender 5, `bpy.props` values aren't dict-style ID properties, so `wm["prop"] = v` doesn't set a registered property. Moving the active row without running its update callback needs a guard flag.
- **Header row:** a `UIList` has no column headers. **Checked:**
  - A row above the list, split at the same factor as each row, serves as one. The list's padding offsets its columns from the header's by a few pixels.
  - The header can hold controls, such as the eye that hides the type column.
- **No highlight beyond the active row:** a `UIList` highlights only its active row. Selecting several prims at once would need a mark per row, such as an icon. **Not checked.**

## Icons and tooltips

- **Custom icons:** **Checked:** `icon_value` takes any icon from a `bpy.utils.previews` collection, loaded from an image file or drawn from pixels (`icon_pixels_float`). The PoC's four badges drew in the binary: payload, references, variants, and instance.
  - They keep their own colors, while Blender's icons follow the theme.
  - Preview icons get `icon_id` 0 in the headless wheel, so they can only be seen in the binary.
- **Row tooltips:** `template_list`'s `item_dyntip_propname` names a string property on each item to use as that row's tooltip. A getter computes it on hover from the model, finding the row's index from the item's RNA path. The PoC's shows the prim's path, type, specifier, and kind.
- **Badge tooltips:** labels can't have tooltips, so each badge is a borderless operator button. The operator's `description` classmethod writes each button's tooltip from that button's properties, such as "Payload (loaded): /_Crate". The disclosure triangle's tooltip says what a click does to that row and lists the keys.
- **Checked** headless: the tooltip text. **Not checked:** a tooltip appearing on screen. Simulated mouse moves highlighted the hovered row but brought up no tooltip, and screenshots in these runs never captured pop-ups.
- **Text only:** no Python API for richer tooltips, such as image previews, was found.

## Keyboard

The tree's keys: Right expands the active row, or steps into it if it's already expanded. Left collapses it, or steps out to its parent. Shift with either does the whole subtree, and Up and Down move between rows.

**Checked** in the binary:
- **The list takes arrow keys first.** While the cursor is over a `UIList`, the list takes all four arrow keys itself, ahead of every keymap: Left and Up move to the previous row, Right and Down to the next. Its update callback sees only the active row change, not which key moved it.
- **The Frames keymap comes before the 3D View's.** In the 3D View sidebar, "Frames" is checked before "3D View Generic", so Shift+Right jumped frames instead of reaching a binding in "3D View Generic". An add-on item in "Frames" itself did win Shift+Right while its poll passed. Alt+arrows reached "3D View Generic".
- **A modal operator sees keys first.** Window modal handlers run before regions' handlers. The PoC's watcher (`tree_keys.py`):
  - runs in each window;
  - takes plain and Shift Left/Right while the cursor is over a region that shows the tree;
  - passes every other event on.

  With it, the tree expanded, stepped, and collapsed as expected. Up and Down stayed the list's, the frame didn't change over the sidebar, and Right over the viewport still stepped a frame.
- **Text fields keep their keys.** While a text field is being edited, the field gets keys before the watcher: typing `a`, Left, `b` in the search box gave `ba`, and the tree didn't move.

### Rules for modal operators

Phase 3 will likely have more than one modal operator, so these apply to all of them:
- **Restart after loading a file.** Loading a file ends modal operators, so each restarts from a `load_post` handler, and in each window. **Checked.**
- **Pass on the ending event.** **Checked:** an operator that ends by returning `CANCELLED` consumes the event it ends on, so modal operators after it never see that event. Return `{"CANCELLED", "PASS_THROUGH"}`.
- **Unregistering while running looked safe.** **Checked:** unregistering the add-on while the watcher ran, then sending 20 mouse moves and a key, raised no error, and Blender kept running. That Blender removed the handler, rather than skipping it, wasn't observed.
- **Return early.** Return at once from every event that isn't yours: every mouse move reaches every modal operator.

### Cost

**Checked** with `bench_watcher.py`. It times batches of 2,000 simulated mouse moves over the 3D View. Stand-in modal operators that pass every event on at once take the place of other add-ons' operators. Two runs of 7 trials each, medians:

| Modal operators | µs per event | Added µs per event |
|---|---|---|
| None | 1.5 | 0 |
| 1 stand-in | 3.3 | 1.8 |
| 1 stand-in and the tree's watcher | 4.6–4.8 | 3.1–3.3 |
| 10 stand-ins | 18.3–18.5 | 16.8–16.9 |
| 10 stand-ins and the tree's watcher | 19.9 | 18.3–18.4 |
| 50 stand-ins | 86.1 | 84.5–84.7 |

- **Mostly the call into Python:** each Python modal operator added about 1.7 µs to every event, and the cost added up linearly. The watcher's own code ran in 0.26–0.27 µs a call.
- **A shared watcher:** one modal operator dispatching to several features would pay the call into Python once. That is an inference from the table, not measured.
- **Limits:** simulated mouse moves aren't merged the way the system's are, and the batches time event handling, not drawing.

## Search

The `UIList`'s own filter hides every row that doesn't match, and sees only the rows already expanded. A stage editor needs to find prims anywhere and see where they are. `tree_search.py` (no `bpy`) does that, and `StageTree.set_search` shows the result. **Checked** headless and in the binary:
- **Matches in place:** the search runs over the whole stage. Each match shows under all its ancestors, expanded to reach it. Ancestors that don't match draw greyed, and their other children are hidden.
- **Exploring from a match:** a match's own children all show when it is expanded.
- **Clearing:** clearing the search restores the expansion from before it, and reveals the selected prim.
- **Query:**
  - text, matched by name, path, glob, or regular expression, with a case toggle;
  - a schema type, matched with `IsA`, so `Gprim` finds meshes and curves;
  - flags: has a payload, has variants, is an instance, inactive.

  The flags combine.
- **Typing:** the text box updates on every keystroke (`options={"TEXTEDIT_UPDATE"}`), and a timer runs the search a quarter second after the last one.
- **Where the options go:** the list's `draw_filter`, the options under its bottom triangle, can draw anything, so it holds the type and flags. The text options sit beside the box.
- **Flags as toggles:** each flag is its own boolean toggle. An expanded `ENUM_FLAG` property sets one item per click (Shift-click adds or removes one), so once a flag was set, no click could clear them all.

Cost, **Checked** headless:
- **Python traversal:** about 5 µs per prim. That's 90–230 ms for 37,000 prims, and 3.1–5.3 s for a million with no match. A search stops at 10,000 matches.
- **An index:** listing every prim's name once took 1.4 s for a million prims, and searching that list took about 35 ms a search. Keeping such an index current as the stage changes wasn't tried. The core, which already follows the stage's changes, is a natural owner for it.
- **Many matches under one parent:** 10,000 matches among a million siblings took 1.2–1.5 s to lay out, since the parent's children are filtered to the ones that lead to matches.

## Selection with the viewport

The tree in the 3D View sidebar shows a binding's stage and selects with the viewport. The tree in the node editor's sidebar shows the Viewer's stage, which no binding displays, so it selects nothing ([Node Tree](node-tree.md#viewer)).

Possible in both directions. **Not checked:** neither direction was built.
- **Tree to viewport:** the active row's update callback maps the prim to its Blender objects and selects them. In Proscenium, that mapping goes through the inspection layer's selection targets ([interaction contract](../spec/interaction-contract.md#two-layers-and-the-live-stage)), so the tree and the viewport agree on instance contexts. Prims with no Blender object (unloaded, inactive, class, over) have nothing to select.
- **Viewport to tree:** Blender has no event for a selection change. Two ways to notice one:
  - A `depsgraph_update_post` handler can compare the selected objects with the last set it saw. The Hydra bridge's `tools/feasibility/hydra_bridge/select_tool.py` follows Blender's selection this way. The tree would map the objects to prims and reveal them.
  - A `bpy.msgbus` subscription to the active object fires only when the active object changes.
- **Things to handle:**
  - **Feedback loops:** each direction triggers the other, and a guard flag stops the loop, as the PoC's row sync uses.
  - **Instances:** a pick inside a native instance resolves to an instance-proxy row, which the model already lists.
  - **Cost:** revealing a prim inside a large group pays that group's expand cost.

## Where the tree can go

- **3D View sidebar: works, and hosts a binding's stage.** **Checked.**
  - The tree's tab is its own.
  - The keys work over it.
  - The sidebar can be dragged wide.
- **Node editor sidebar: hosts the Viewer's stage,** beside the node tree. **Not checked:** it takes the same panel class as the 3D View's sidebar with another editor type, and whether the keys reach it as they do there.
- **A dedicated pane: the next candidate.** **Not checked.**
  - The idea: an editor whose header is hidden (`space.show_region_header = False`) and whose sidebar shows the tree, dragged nearly full width. A Text Editor costs little to draw, and its sidebar has one tab of Blender's own.
  - Its main area stays, mostly unused, beside the sidebar.
  - **Checked:** a region's `width` is read-only from Python, so the width comes from the user's drag, or from a workspace shipped in a .blend file.
  - **Not checked:** whether the sidebar can be dragged to the area's full width.
- **Properties editor: not recommended.** **Checked**, in a workspace built for it. The keys worked, but:
  - **No tab of its own:** an add-on can't add a Properties tab, so the tree shares one (Scene) with Blender's panels, and shows in every Properties editor on that tab.
  - **Order fixed only by a hack:** `bl_order` can't go below 0, which is Blender's own Scene panels' order. Panels of equal order are listed in the order they registered, so the tree came after Blender's. Only registering Blender's Scene panel classes again, after the tree's, put it at the top, and that changes classes Blender owns.
- **The 3D View's toolbar and Tool Settings strip: not suitable.** **Checked:**
  - The toolbar (`TOOLS`) drew the panel inside its 113-pixel strip of tool icons.
  - The Tool Settings strip (`TOOL_HEADER`) is one row high and shows panels only as popovers. A popover button there drew, and clicking it called the panel's draw. The popover itself didn't show in a screenshot.
  - A popover closes when the cursor leaves it, so the tree would close whenever the cursor went back to the viewport.
- **Other places, Not checked:**
  - another editor's sidebar (Image, Graph), which takes the same panel class with a different editor type;
  - a panel opened by a hotkey (`wm.call_panel(..., keep_open=True)`);
  - an operator's dialog;
  - the file browser's sidebar in a bind operator's file dialog, where a prim tree beside the chosen USD file could suit choosing what to bind.
- **More than one place at once:** **Not checked.** A `UIList` keeps its scroll position per list ID, so the same tree could show in several places.

### Workspaces

A workspace that arranges editors around the tree can be built at run time or shipped.
- **Built at run time:** **Checked**, by copying the active workspace and changing its editors.
  - `workspace.duplicate` created the copy at once, in `bpy.data.workspaces`, and setting `window.workspace` switched to it.
  - On a screen that isn't showing, setting an area's type changed `area.type` but left the old editor's space in place. So the editors are changed from a timer, once the window shows the workspace.
  - `screen.area_move`, with the window, screen, and area overridden, dragged the edge between two editors.
- **Shipped:** in a .blend file the add-on appends, with editor types, sizes, and panel order already set. The Maya Workflow Kit adds its layouts this way. **Not checked.**

## Testing

- **Without Blender's UI:** the row model, the search, and the tooltip text have no `bpy`, so they test in `bpy_free` from fixtures with known hierarchies, as `bench.py` checks them headless.
- **The binary's quirks:** the binary with `--enable-event-simulate` can drive the UI, but:
  - Each simulated event needs its own `x` and `y`. Without them, key events landed at the mouse position (0, 0).
  - Event and region coordinates are pixels; `window.width` and `window.height` are points.
  - A region's `active_panel_category` (its sidebar tab) is read-only, so a run moves its panels into the tab that shows.
  - Screenshots didn't capture tooltips or popovers.
- **What tests can cover:** windowed UI tests are out of the project's test scope, so the drawing code stays thin, and the model and search carry the logic tests can reach.

## Open questions

- Do tooltips and the Tool Settings popover show when hovered and clicked by hand?
- How fast is drawing and scrolling a `UIList` with thousands of rows? Only the model and the collection were timed.
- Can a dedicated pane's sidebar take the area's full width, and does the empty main area bother users?
- Can `gpu` overlays draw tree guide lines over a `UIList`, given that a list's rows have no reported positions?
- What should own the search index as the stage changes: the core, or a Python layer that listens to `Tf.Notice`?
- How do multiple selected prims show in a list that highlights only one row?
