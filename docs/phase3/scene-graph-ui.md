# Scene Graph UI

How Phase 3's stage editor shows a USD stage's prim hierarchy as a tree in Blender: which UI mechanism it's built on, where in Blender's UI it fits, what the keyboard, icons, tooltips, search, and selection can do, and how the widget in [`src/proscenium/ui/`](../../src/proscenium/ui/README.md) is arranged for a host to place it, and how its rows compare with usdview's and Solaris's. This is a design note, not a requirement ([Phase 3 notes](README.md)). The widget may exist alongside Phases 1 and 2 because it reads a stage its host gives it, and selects through no source selection model, shows no edits through bindings, and pushes no undo step ([DECISIONS.md](../DECISIONS.md) "Phase 3 ordering").

The measurements below were taken on a proof of concept, kept at commit `32b1b86ecc749a772a534a2d1f2d456c5c4f924f` in `tools/feasibility/scene_graph_ui/`. Its README there lists each file, how to run it, and its findings in full. Its row model, search, tooltip text, key watcher, and badge icons became the widget; its benchmarks (`bench.py`, `bench_watcher.py`) and the native tree (`native_tree.py`) stayed behind with it.

Evidence is marked as in the other notes:
- **Checked:** run on Blender 5.2.2 LTS (USD 0.26.3) on one macOS machine, either headless in the bpy wheel (`bench.py`) or in the Blender binary driven by simulated events (`--enable-event-simulate`) and screenshots. Everything but [Colors](#colors) ran in the proof of concept at that commit; Colors comes from a one-off probe that drew a `UIList` in the binary and was screenshotted.
- **Tested:** covered by the widget's tests, `tests/bpy_free/test_prim_tree*.py` and `tests/blender/test_scene_graph.py`, which run in the bpy wheel and draw nothing.
- **Not checked:** reasoned from documentation or code, or seen in another add-on, but not run here.

Timings are single runs unless stated, and varied by about 2× between runs. Windowed checks show behavior; only `bench_watcher.py` measured anything in a window.

## Recommendation

- **Build the tree as a virtualized `UIList`** over a model kept apart from drawing. Each visible row is an empty collection item, and `draw_item` reads that row from the model, so only the row count enters Blender's data. It got Blender's theme, scrolling, tooltips, and DPI scaling with nothing extra, and kept up at 100,000 rows in a group.
- **Register no panel in the widget.** The widget registers its classes and properties; a host, the add-on, registers the panels that place it and calls the widget's drawing from them ([The Widget](#the-widget)). The same widget can then show in several places at once, each place a view of its own.
- **Host it in two places, over one model and drawing:**
  - **The 3D View sidebar,** showing a binding's stage and selecting with the viewport ([Selection with the Viewport](#selection-with-the-viewport)). That's where the tree was checked.
  - **The node editor's sidebar,** beside the stage editor's node tree, showing its active Viewer's stage ([Node Tree](node-tree.md#viewer)). No binding displays that stage, so selecting a row there selects no Blender objects.

  A dedicated pane, an editor whose header is hidden and whose sidebar is dragged nearly full width, is the next candidate. The Properties editor, the toolbar, and the Tool Settings strip don't suit a tree.
- **Take Left and Right with one modal operator** that passes every other event on. Keymaps can't reach plain arrow keys over a list. A Python modal operator costs about 1.7 µs per event.
- **Search the whole stage, and show each match under its ancestors.** The UIList's own filter can't do that. At a million prims, a Python traversal is too slow for typing, and an index is the fix.
- **Keep the row model and the search independent of the drawing,** so they test in `bpy_free` and could move into the core.

## Approaches

Python can't register a new editor type, and `UILayout` has no general tree widget, so every approach borrows one of Blender's existing widgets or draws its own.

### UIList with virtualized rows: chosen

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

## The widget

`src/proscenium/ui/scene_graph_widget/` groups the widget's two units, by the [import rules](../../src/proscenium/README.md#import-rules): the model that holds the tree, and the display that draws it.
- **`prim_tree/`, the model, in the lowest tier,** imports nothing of Blender's: which children a tree lists (`prim_children`), the search (`prim_search`), the row model (`prim_tree`), what the tree says about a prim (`prim_descriptions`), and one tree as a widget shows it (`prim_tree_view.PrimTreeView`), with its selection, query, keyboard steps, and the stage changes it follows. The logic tests can reach is here.
- **`display/`, below the add-on,** only draws and forwards input to a `PrimTreeView`: a registry of views that knows nothing of Blender's data, the property groups a `UIList` draws from and everything that reads or writes them, the operators, icons, drawing, and key watcher above those, and the host's calls and registration at the top.

Each package's modules import each other in that order, each only from those before it, and a check in `tests/bpy_free/test_import_tiers.py` fails on any cycle among a unit's modules, type-only imports included.

### What a host does

The widget registers no panel and draws nowhere by itself. A host:
1. **Registers it** with `display.register()`, from `proscenium.ui.scene_graph_widget`: its classes, a collection on the window manager, its icons, its key watchers, and a load handler.
2. **Creates a view** per place it shows a tree, by name: `create_view(name, shows_in_region, on_selection_changed)`.
   - `shows_in_region(area, region)` says whether a region is showing that view now, such as a 3D View sidebar on the host's tab. The key watcher asks it, since only the host knows which panels draw which view.
   - `on_selection_changed(path)` hears the prim selected from the tree, by a click or the keys, and `None` when a new stage or the selected prim leaving the stage clears the selection. `select_prim(name, path)` selects from elsewhere, such as the viewport, and isn't reported back, so the two directions can't loop.
3. **Gives each view a stage** with `set_stage(name, stage)`, or `None`; giving it the stage it already shows keeps its expansion and selection.
4. **Draws it** by calling `draw_tree(layout, context, name)` and `draw_details(layout, name)` from its own panels' `draw`, and reads its selection with `selected_path(name)`.

A host holds only a view's name, never the view, so every change goes through these calls, which keep the view's properties and the host's callback in step.

The extension's add-on doesn't host it yet; the hosts above come with the work that needs them.

### How a view keeps its state

- **Each view is separate.** A view's rows, active row, and search fields are an item of the window manager's `proscenium_scene_graph_views`, named for it, and its `UIList` takes the view's name as its list ID, so each view has its own rows and scroll. **Tested:** expanding a row in one of two views on the same stage leaves the other's rows as they were.
- **The view holds no stage.** A tree holds its stage's prims, never the stage, and its change listener holds none either, so it never keeps a binding's stage alive after the binding releases it. **Tested:** once a stage's last owner drops it, the tree is expired; a view whose tree is expired draws "Stage closed". This matters for the 3D View host, since releasing an attached stage is the caller's ([Source Identity](../spec/source-access.md#source-identity)).
- **State is kept by path.** Expansion, cached row details, and search results are keyed by prim path, so they survive the stage recomposing, where a `Usd.Prim` from before may no longer be the prim at its path.
- **Stage edits reach the rows after the edit.** A `Usd.Notice.ObjectsChanged` arrives while the stage is being edited, so the notice only marks what to read again and starts a timer; the timer rebuilds the rows, or forgets the rows' details for a metadata change, and reruns an active search. **Tested:** a metadata change and added prims mark the view once until it's read, and reading them shows the added prims; a refresh also drops removed ones. Adding an attribute resyncs the attribute's path, not its prim's, so it marks nothing.
- **The selection is a prim on the stage.** It stays selected while a collapse or a search hides its row, and is cleared when its prim leaves the stage, as when it is removed or an ancestor is deactivated. Selecting a path the stage has no prim at selects nothing. **Tested:** in the model, and that the host hears `None` when its selected prim is removed.
- **The view owns its state; the properties mirror it.** The one exception is the search fields, which hold the query being edited: a pause after they last change, they're applied to the view, whose query is then the applied one.
- **Loading a file keeps the views.** The window manager's properties aren't saved, and a load replaces them, so the load handler makes each view's item again, with its search fields from the applied query, and syncs its rows. The views and their trees are the host's, and stay, and their timers survive the load, so a stage change marked before it is still read. **Tested:** after saving and opening a file, a view has its rows back as they were expanded; and a view with a search and an unread stage change shows the search in its fields, keeps its timer, and once the timer runs, shows the change still filtered by the search.

## The row model

`prim_tree.PrimTree` holds a stage's expansion state and its visible rows. Its shape carries over to any drawing:
- **Rows hold only a prim and a depth.** Expanding a prim splices its visible subtree into the list after its row, and collapsing it cuts that subtree out. Each costs the rows it adds or removes, not the list's length. After the stage's hierarchy changes, the rows are rebuilt from the expanded paths, which costs every visible row.
- **Finding a prim's row scans the visible rows,** as syncing the active row and revealing a prim do, so it costs the list's length, and the rows' storage grows with what is expanded.
- **Details are read when a row first draws.** A row's name, type, flags, and badges are read from the prim and cached, so a widget pays for the rows on screen.
- **Children are listed with instance proxies included.** The model uses `Usd.TraverseInstanceProxies(Usd.PrimAllPrimsPredicate)`, so inactive, unloaded, class, and over prims show, as do the contents of native instances.
- **Checking for children must not list them.** **Checked:** `GetFilteredChildrenNames` on a 250,000-child group cost about 20 ms per call. A `PrimRange` iterator that stops at the first descendant doesn't depend on the group's size.

**Checked** headless, on a group of 100,000 leaves:
- **Expanding:** about 100–235 ms in the model, plus 35–50 ms adding collection items.
- **Collapsing:** 12–19 ms.
- **First draw:** 40 rows' details took about 3 ms whatever the group's size.

At a million leaves, expanding took about 1.3 s in the model plus 0.45 s adding items. Neither drawing nor scrolling was timed. Those timings are of the proof of concept's model, which kept expansion by prim rather than by path.

## UIList mechanics

- **Empty items:** the collection holds one empty `PropertyGroup` item per visible row. Only the count changes on expand and collapse, and `draw_item` reads the model by the row's index.
- **Resizing:** **Checked:** removing items one at a time from the end is quadratic (35 s for 100,000), so shrinking clears the collection and adds items back.
- **Indentation:** **Checked:** one `separator(factor=2.0)` per level keeps rows even. One deep separator makes the row taller, because a separator's spacer is square. A blank icon per level cut deep names to a letter or two at sidebar width.
- **Guide lines:** **Checked** in the binary by one-off probes, then in the widget. The widget indents each level by a cell 0.6 units wide, the width `separator(factor=2.0)` took, holding a vertical line under the centre of the parent's chevron, so a line runs down from each open chevron to its last descendant, as in Solaris. Every ancestor of a visible row is expanded, so a row draws a line at every level of its indent, and the model works out nothing for them.
  - **A line is a disabled button** squeezed to 0.05 units, in fixed-width parts that fill the level. Disabled, it draws faint, and a simulated click on it, or on the indent beside it, selected its row; its operator never ran.
  - **The lines stay out of the dimming:** a row's contents are dimmed in a sub-layout of their own, so a line has one look down its length past inactive rows.
  - **The active row's highlight covers its lines.**
  - **Narrower icons:** the chevron's button is 0.6 units, narrower than an icon button's 1.0, and the type icon sits in a 0.8-unit cell with `separator(factor=1.0)` before the name, a narrower gap than a label's icon has. The list's own padding, about 5 points before the first chevron, has no Python setting, and a negative separator factor does nothing.
- **Columns:** a 72% name column with the type and badges right-aligned after it read in full at sidebar width.
- **Updating properties without callbacks:** **Checked:** in Blender 5, `bpy.props` values aren't dict-style ID properties, so `wm["prop"] = v` doesn't set a registered property. Moving the active row without running its update callback needs a guard flag.
- **No writes while drawing:** a panel's `draw` can't write the window manager's properties, so rows are synced from operators, timers, and handlers, never from drawing. A view drawn before the load handler has made its properties draws "Loading".
- **Header row:** a `UIList` has no column headers. **Checked:**
  - A row above the list, split at the same factor as each row, serves as one. The list's padding offsets its columns from the header's by a few pixels.
  - The header can hold controls, such as the eye that hides the type column.
- **No highlight beyond the active row:** a `UIList` highlights only its active row. Selecting several prims at once would need a mark per row, such as an icon or a highlighted button ([Colors](#colors)).

## Icons and tooltips

- **Custom icons:** **Checked:** `icon_value` takes any icon from a `bpy.utils.previews` collection, loaded from an image file or drawn from pixels (`icon_pixels_float`). Four badges drew in the binary: payload, references, variants, and instance.
  - They keep their own colors, while Blender's icons follow the theme.
  - Preview icons get `icon_id` 0 in the headless wheel, so they can only be seen in the binary.
- **Row tooltips:** `template_list`'s `item_dyntip_propname` names a string property on each item to use as that row's tooltip. A getter computes it on hover from the model, finding the view and row from the item's RNA path (`proscenium_scene_graph_views[0].rows[12]`). It shows the prim's path, type, specifier, and kind.
- **Badge tooltips:** labels can't have tooltips, so each badge is a borderless operator button. The operator's `description` classmethod writes each button's tooltip from that button's properties, such as "Payload (loaded): /_Crate". The disclosure triangle's tooltip says what a click does to that row and lists the keys.
- **Tested:** the tooltip text. **Not checked:** a tooltip appearing on screen. Simulated mouse moves highlighted the hovered row but brought up no tooltip, and screenshots in these runs never captured pop-ups.
- **Text only:** no Python API for richer tooltips, such as image previews, was found.
- **The widget's rows draw no badges for now,** so new row information starts from a clean row. The badges, their icons, their tooltips, and their buttons (`prim_descriptions.Badge`, `badge_icons`, `SceneGraphSelectRow`) are kept, unused, for when rows draw them again.

## Colors

What a row can do with the color of its text, background, and icons. **Checked:** a probe drew one `UIList` row per option in the binary's 3D View sidebar, under the default theme, and was screenshotted.

- **Text:** a label has no color argument. Three layout states change it, recoloring the row's text and its icons together:
  - `active = False` dims it grey, and the row still takes clicks. The tree uses it for inactive prims and rows that only hold search matches.
  - `enabled = False` dims it the same way, and its buttons stop taking clicks, though a click still selects the row ([A row's look](#a-rows-look)).
  - `alert = True` turns it red; with `active = False`, a dim red.

  Text has those four looks, and no others. Their colors are the theme's List Item colors (text, selected text, and backgrounds), and an add-on changing the theme would restyle every list in Blender and override the user's choice.
- **Background:** no arbitrary color either.
  - The active row has the theme's selection color, and only that row ([UIList Mechanics](#uilist-mechanics)).
  - A button that is on fills with the selection color: a toggled boolean (`prop(..., toggle=True)`), or an operator drawn with `depress=True`. A row-wide one could mark each of several selected prims, but clicks on it go to the button, not the list. `depress` shows nothing on a button drawn without emboss.
  - `alert` on a button colors its background red.
  - `layout.box()` draws a darker framed box, and makes the row taller.
  - Of the emboss styles, `PIE_MENU` gives a button a dark background; `PULLDOWN_MENU` and `NONE_OR_STATUS` give none.
- **Icons:** the one place a row has color of its own.
  - Blender's icons follow the theme, apart from a set of fixed colored ones: `COLLECTION_COLOR_01`–`08`, `STRIP_COLOR_01`–`09`, `COLORSET_01_VEC`–`20_VEC`, `LAYERGROUP_COLOR_01`–`08`, the `KEYTYPE_*_VEC` icons, `COLOR_RED`, `COLOR_GREEN`, `COLOR_BLUE`, and `ERROR`.
  - Preview icons, as the badges are ([Icons and Tooltips](#icons-and-tooltips)), take any colors and shapes, and keep them under any theme.
  - `template_node_socket(color=(r, g, b, a))` draws a small dot in any color, with no image: a per-row color marker.
  - A color property (`FloatVectorProperty(subtype="COLOR")`) drawn without text is a swatch in any color, but it opens a color picker when clicked, and disabling it dims it.
- **Lines:** `separator(type="LINE")` in a row drew a short horizontal line at the row's top edge, not a vertical one, so it can't draw tree guide lines; the widget draws them as thin disabled buttons ([UIList mechanics](#uilist-mechanics)).
- **Overlays:** the `gpu` module could paint any background or guide line over a list, but a list's rows have no reported positions. **Not checked.**

So a row can show state as dim, red, or highlighted, and color only through its icons: preview icons, Blender's colored icons, or socket dots.

## What a UIList can show

Every control a `UIList` gives over what it tells a user: the list's own, a row's look and contents, hover text, and what sits beside the list. Names and parameters are from the RNA of `UILayout` and `UIList` in the bpy 5.2 wheel. Items marked **Checked** ran in the proof of concept or the [Colors](#colors) probe; the rest are **Not checked**, read from the RNA only. The demos in [`tools/feasibility/uilist_options/`](../../tools/feasibility/uilist_options/README.md) draw them on the test stage, for trying by hand.

### The list

| Control | What it sets |
|---|---|
| `template_list(rows, maxrows)` | The list's default and minimum row count, and its default maximum. |
| `template_list(type)` | `DEFAULT` or `COMPACT`. The enum has no `GRID`, though `columns` remains a parameter. |
| `template_list(sort_reverse, sort_lock)` | The display order, and whether the user can change it. |
| `template_list(item_dyntip_propname)` | A string property of each item, used as that row's tooltip. **Checked**; the widget uses it. |
| `UIList.draw_item(..., index, flt_flag)` | Draws each shown row. `flt_flag` is the row's filter flags, whose lower 16 bits are the list's own, so `filter_items` can hand each row a state for drawing. |
| `UIList.draw_filter` | Anything under the list's bottom triangle. **Checked**; the widget draws the search's type and flags there. |
| `UIList.filter_items` → `filter_flags`, `filter_neworder` | Per row, flags and a new position. `bitflag_filter_item` marks a row shown, and `bitflag_item_never_show` leaves it out. |
| `use_filter_show`, `filter_name`, `use_filter_invert`, `use_filter_sort_alpha`, `use_filter_sort_reverse`, `use_filter_sort_lock` | The built-in filter and sort options. The widget's search stands in for them ([Search](#search)). |
| The active index | The one row highlighted ([UIList mechanics](#uilist-mechanics)). **Checked.** |

The widget's list is a `DEFAULT` list in the stage's order: a compact list shows one row, and a tree's rows can't be reordered, so `type`, `sort_reverse`, `sort_lock`, and `filter_neworder` stay unset. It defines no `filter_items` and sets no filter flags; a row's state comes from the model ([Filter flags](#filter-flags)). It uses row tooltips, the active index, and the filter drawer, which holds the search's options.

#### Filter flags

`filter_items` runs before the list draws, over every item, and returns one integer of flags per item. Blender reads the upper 16 bits: `bitflag_filter_item` shows a row, and `bitflag_item_never_show` leaves it out. The lower 16 bits are the list's own, and `draw_item` gets them back as `flt_flag`. So `filter_items`, which sees every row at once, can hand a row what its `draw_item`, which sees one, can't work out. **Checked** in the binary with `list_controls_demo.py`, on the test stage:
- **Bits from other rows:** each drew as expected:
  - "inside a payload", inherited from an ancestor's row;
  - "ancestor of the active row", which follows the selection;
  - "last sibling", from the rows after it, drawn as a `├` or `└` guide glyph;
  - a name mark, which marks matches and hides nothing.
- **Guide lines:** a row's own connector takes one bit. Full guide lines would take one bit per ancestor depth, saying whether that ancestor has a later sibling, so the 16 bits would bound how deep the lines go. **Not checked.**
- **Running on every redraw:** `filter_items` ran again on each redraw of the sidebar. Computing six bits in Python took 0.5 ms for 35 rows, 46 ms for 10,500, and 370–395 ms for 105,000, in two runs. Returning the same list again took 0.1 ms at 105,000.
- **The widget's whole list, per redraw:** **Checked** with `redraw_benchmark.py`, which redraws the widget's sidebar as fast as Blender's event loop runs, on one group of leaves expanded under `/World`, with 48 rows on screen. The median time of the panel's `draw`, in which `template_list` filters the list and draws its shown rows, over 4 seconds of redraws, in one run per cell:

  | Rows | The widget, no `filter_items` | Flags computed once, returned again | Flags computed each redraw (last sibling only) |
  |---|---|---|---|
  | 1,000 | 1.8 ms | 1.8 ms | 1.8 ms |
  | 10,000 | 1.8 ms | 1.8 ms | 3.5 ms |
  | 100,000 | 3.3 ms | 4.2 ms | 18.7 ms |

  A panel drawing one label took 0.01 ms, and a redraw tick took at least 8.3 ms, one frame of the display's 120 Hz. So even without `filter_items`, Blender's own filtering costs every row, about 1.5 ms per 100,000; returned flags add about 1 ms per 100,000, and computing even one bit in Python adds about 15 ms.
- **A label's width:** in an aligned row, a label takes an equal share of the row's width unless its sub-layout has a `ui_units_x`, as the guide glyph's has.

The flags carry a value from `filter_items` to `draw_item`; they hold nothing of their own. A list whose `draw_item` has only its item needs them to know about other rows. The widget's `draw_item` reads the model by the row's index, so it can already reach other rows, the selection, and the stage:
- **Facts about a prim**, such as being instanceable or time-varying, belong in the row's details, read when the row first draws ([The row model](#the-row-model)). Flags would compute them for every row on each change, and hold 16 bits.
- **Facts from other rows** come from the model for one row too: an ancestor of the selection is a prefix of the selected path, a last sibling is the last of its parent's listed children, and being inside a payload is a matter of the row's ancestors.

So the widget sets no bits of its own: flags it computed would cost every row on each change, where `draw_item` reading the model costs only the rows on screen.

### A row's look

Each is an attribute of a `UILayout`, so it applies to whatever sub-layout of a row it's set on.

| Attribute | Effect |
|---|---|
| `active`, `enabled`, `alert` | Dim; dim with unclickable buttons; red ([Colors](#colors)). **Checked.** The widget dims inactive prims and unmatched search ancestors alike, and turns an orphaned over (a prim nothing defines) red. |
| `emboss` | `NORMAL`, `NONE`, `PULLDOWN_MENU`, `PIE_MENU`, or `NONE_OR_STATUS`. `NONE` draws a button as its bare icon, as the badges are drawn. `NONE_OR_STATUS` colors a property by Blender's animated, keyed, and driven states, so only for properties that are. |
| `scale_x`, `scale_y` | Items' size along each axis. |
| `ui_units_x`, `ui_units_y` | Items' fixed size, so a column can keep one width on every row. |
| `alignment` | `EXPAND`, `LEFT`, `CENTER`, or `RIGHT`. **Checked**; the widget right-aligns its type column. |
| `use_property_split`, `use_property_decorate` | A property's label and value in two columns, and its keyframe decorator. |

**Checked** by hand in the binary with `row_look_demo.py`, on the test stage:
- **Dim and disabled look the same.** A disabled row can still be selected; only its buttons stop taking clicks. So the two can't mark different states.
- **Alert** turns a sub-layout's text and icons red.
- **Emboss:** `NORMAL` and `PIE_MENU` give a button a background; `PULLDOWN_MENU` shows one only while the button is depressed. Neither `PULLDOWN_MENU` nor `PIE_MENU` buttons turn red under `alert`.
- **`depress`** shows only on a button with a background: under emboss `NONE` it just brightens the text, too faintly to mark anything.
- **`scale_y`** on a row breaks the list's highlight of the active row, so rows keep their height.
- **`ui_units_x`** keeps a column one width on every row.

The theme's List Item colors (`outline`, `inner`, `inner_sel`, `item`, `text`, `text_sel`, `roundness`, and shading) can be read from the preferences, and writing them would restyle every list in Blender ([Colors](#colors)).

### A row's contents

| Item | What it can carry |
|---|---|
| `split(factor)`, `row`, `column`, `box`, `grid_flow`, `column_flow` | Columns. **Checked:** a split row above the list serves as their header ([UIList mechanics](#uilist-mechanics)). |
| `separator(factor, type)`, `separator_spacer` | Indentation, a `LINE` at the row's top edge ([Colors](#colors)), and space pushing later items right. |
| `label(text, icon, icon_value)` | Text and one icon. **Checked:** the UI font draws marker and box-drawing characters such as `◇ ○ × ◌ ▫ ◆ •` and `│ ├ └`. |
| `icon`, Blender's icons | Type and state icons, in the theme's colors, apart from the fixed colored set ([Colors](#colors)). |
| `icon_value`, a preview collection | Icons of any color and shape. **Checked**; the badges. |
| `template_icon(icon_value, scale)` | A larger icon, drawn from a preview's image rather than its icon. **Checked:** above a scale of 1 it overflows its row. |
| `template_node_socket(color)` | A dot in any color. **Checked.** |
| `prop(...)` | A property's value, which a click edits: a toggle, an icon, a checkbox (`invert_checkbox`), a slider, an expanded enum, or a text field, aligned with `text_align`. Columns such as visibility or active would be these, each a property with a getter and setter over the prim. |
| `prop_enum`, `prop_menu_enum`, `prop_with_menu`, `prop_with_popover` | A menu or popover per row, such as a variant set's selection or a draw mode. |
| `operator(..., depress, emboss, icon, icon_value)` | A button with its own tooltip. **Checked**; the disclosure triangle and the badges. |
| `operator_menu_hold`, `menu`, `popover` | A menu or popover from a button. |
| `progress(factor, type)` | A bar or a ring, for a fraction. |
| A color property drawn without text | A swatch in any color, which opens a picker when clicked ([Colors](#colors)). **Checked.** |
| `link(url, text)` | A link, such as to an asset's file. |

**Checked** in the binary with `row_contents_demo.py`, on the test stage, by screenshots and by hand:
- **Fixed-width columns:** a cell with a `ui_units_x` keeps its width only with its contents centered: under a row's `RIGHT` alignment, which a cell inherits, a label shrinks to its text and shifts the columns after it. `separator_spacer` before the columns misaligned the rows.
- **`LINE` separators** draw only horizontal lines, a little above a row's middle: several in a row merge into one line leading to what follows them, such as a disclosure triangle. None drew vertically, whether in an aligned or unaligned row, at any factor, or in a column, and none drew at all in a narrow cell or below a row's contents.
- **Guide glyphs** (`│`, `├`, `└`) worked out from the model draw in place of indentation, but break between rows and take a unit of width per level. A `│` in a cell narrower than a unit draws nothing.
- **Column and row dividers:** characters (`|`, `│`) break between rows, and boxes make rows taller. Collection Manager draws its column separators as a disabled button squeezed to `scale_x = 0.2`, so only its frame shows, which drew faintly and only some of the time here. What drew a grid of continuous lines, keeping each row's height and the active row's highlight:
  - **Between columns:** an enabled button with no text or icon, in a cell with `ui_units_x = 0.05`, before each column and in the header. A click on it does nothing.
  - **Between rows:** the row's contents in a column, at `scale_y = 1 - 0.075`, under a full-width button of the same kind at `scale_y = 0.075`, so the two keep one row's height. A row draws only inside itself, so the line sits at its top or bottom edge; at the top it lines up a little better with the columns' lines.
- **Clicks:** a click on a glyph, an icon, or a preview icon selects its row; a click on a `template_node_socket` dot doesn't.
- **Worth keeping:** columns of per-row properties, as an icon toggle, a checkbox, or a dropdown, and a menu button per row could each carry a prim's state or an action. A `progress` bar and a color swatch add nothing a stage editor's rows need.

### Hover text and menus

| Source | Per row? |
|---|---|
| `item_dyntip_propname`: a string property whose getter writes the row's tooltip | Yes, the whole row. **Checked**; the widget's path, type, specifier, and kind. |
| An operator's `description(context, properties)` | Yes, per button, from its properties. **Checked**; the badges and the triangle. |
| An operator's `bl_description`, or a property's `description` | No: fixed at registration. |
| The descriptions of an enum's items, from an `items` callback | Perhaps, per menu, for an enum drawn in each row. |
| A label | None: a label has no tooltip. |

Tooltips are text only ([Icons and tooltips](#icons-and-tooltips)). A `UIList` row has no right-click hook of its own, but a draw function appended to `UI_MT_button_context_menu` adds items to the menu a right-click on any button opens, and can read the button through the context.

**Checked** in the binary with `hover_and_menus_demo.py`, on the test stage:
- **Which row is hovered:** nothing reports it. A row tooltip's getter runs only when its tooltip is about to show, so writing the hovered path to the status bar from it left the status bar on the last path whose tooltip showed, changing only as the list scrolled.
- **The button context menu knows its row.** A row that sets itself in its layout's context with `context_pointer_set` reaches an appended draw function through that context, from a right-click on any part of it: the indent, a label, an operator button, or a property. A right-click on a label reports the list's own row button (`button_pointer` the list's properties, `button_prop` the active row index), so the menu also holds Blender's items for that property; on an operator or a property it reports that button. Blender opens the menu from its UI code, not a keymap item an add-on could replace. Its `popup_context_menu_for_button` (`interface_context_menu.cc`) lays out its own items first, such as Copy Data Path, keyframes, Add to Quick Favorites, Assign Shortcut, and Online Manual, and only then draws `UI_MT_list_item_context_menu`, when the click is on a list row, and `UI_MT_button_context_menu`. So an add-on's items always come after Blender's, whether added with `append` or `prepend`, which orders them only among add-ons' items; and none can remove Blender's. A draw function appended to `UI_MT_list_item_context_menu` ran, with its row in the context, on a right-click on each part of a row.
- **A modal operator can take the right-click.** A watcher in each window, as the key watcher is, that returns `RUNNING_MODAL` for a right mouse press over the sidebar stops Blender's menu from opening, and can open its own (`wm.call_menu`) in its place.
- **It can find the row from the hovered button.** In the watcher, with the context overridden to the sidebar's region, `context.property` names the hovered button's property, as the ID and a data path. Over a property of a row item that isn't text, such as the eye, the path names the row (`uilist_demo_rows.rows[4].is_visible`). Over a label, an unembossed text property such as the item's `name`, or the indent, it names the list's own row button (`active_row_index`), which doesn't say which row. The row's context member isn't there, and `UIList` reports no row positions.
- **So a row can be drawn as its item's properties.** Drawing the name, and the type, as an unembossed toggle with the prim's name as its text (`prop(item, "is_active_row", text=..., toggle=True, emboss=False, text_align="LEFT")`), whose getter says whether the row is active and whose setter selects it, let the watcher find the row from a right-click anywhere on it but a gap between buttons, and open its own menu for it; a left-click on the name still selected the row. Checked with simulated clicks; whether the list's other clicks (double-click to rename, Ctrl, drag) still work wasn't. A toggle centers its text, whatever its `text_align`; in a sub-row with `alignment = "LEFT"` it shrinks to its icon and text and looked like a label a few pixels to the right, and then a right-click on the indent or the space after the name finds only the list's row button. Empty toggles filling that space made the layout share the row's width unevenly, shortening indents and names.
- **Between the buttons, the row can be tracked.** The watcher also sees each mouse move, before Blender's UI does, so the hovered button it reads then is the one at the last move it saw; it notes that row and that move's window y. A right-click where nothing names a row takes the last noted row, offset by the mouse's distance from it over a row's height: measured from two noted rows, or else one UI unit, which is 20 / 26 of the editor header's height (Blender's `HEADERY`) whatever the interface scale and pixel size say. Scrolling clears what's noted. With simulated clicks, right-clicks in the space after a name found the row the mouse had passed over and rows two below it, before and after a second row was noted and a menu had opened and closed. Pairing a row with the event's own `mouse_prev_y` didn't work, since simulated moves report the same previous and current position. That scrolling clears it wasn't checked, and nor was any of it with a real mouse.
- **`context.ui_list` names the hovered list.** In the watcher, with the context overridden to the sidebar's region, it was the demo's `UIList` over every part of a row, so a watcher can take right-clicks over its own list only. But neither there nor in a menu opened from there (`wm.call_menu`) was the row's context member set, so a menu opened that way can act only on the active row.
- **Blender's own list hit-testing finds the hovered row,** called through `ctypes`. The executable exports, on macOS, the private C++ functions its UI uses (`interface_query.cc`): `listbox_find_mouse_over_ex` and `listrow_find_mouse_over` give the list and the row button under a window position, and `listrow_find_index` gives the row button for an item index, matching the index the row button holds (`hardmax`) that Python can't read. Comparing pointers gives the hovered row. With simulated clicks, on rows drawn as labels, it found the right row from a right-click anywhere on a row, the first right-click included, and after the list scrolled, searching only the 14 rows `draw_item` last drew; nothing crashed. What it costs:
  - **It isn't an API.** The names are mangled C++ (Itanium on macOS; MSVC's differ), the signatures can change in any release, and a mismatch crashes Blender, so it runs only on a build checked by platform, version, and build hash (here, macOS 5.2.2 `d13f752e3b9c`), and other builds need another way. **Checked**, in the official 5.2.2 downloads, whose checksums matched the published ones: only macOS exports them. The macOS arm64 executable exports about 132,000 symbols, these among them. The Linux x64 executable is stripped, and its 1,696 dynamic symbols are Python's C API and a few of the C++ standard library's, none in Blender's namespace. The Windows x64 `blender.exe` exports 10 names, Python modules' `PyInit_` functions and `NvOptimusEnablement`, and none of the DLLs beside it export these. Neither Windows arm64 nor any other release was looked at.
  - **Each index costs a scan.** `listrow_find_index` walks the region's buttons for every index it's given, so the candidates are only the rows on screen.
- **Nothing else names the hovered row** of a row drawn with labels. Blender skips its own items for the list's row button only when the button is disabled, which would stop it selecting, and adds Copy Data Path, Copy Full Data Path, and Online Manual for any property button (`popup_context_menu_for_button`).
- **Opening a menu from the list item menu's draw function** doesn't replace Blender's: checked by hand, both menus show, Blender's and the new one for the right row.

#### The widget's right-click

A right-click on a row opens a menu for the prim under the mouse, with rows drawn as they are:
- **On a verified build,** which can only be a macOS one, since only macOS exports the hit-testing functions, a watcher in each window takes a right-click over the widget's own list, which `context.ui_list` names in the region under the mouse, and leaves every other right-click to Blender. It finds the row with Blender's list hit-testing, among the rows on screen, and opens the widget's own menu for it, so Blender's menu doesn't open.
- **On any other build,** Windows and Linux included, Blender's menu opens, and the widget adds its items to `UI_MT_list_item_context_menu`, after Blender's own, for the row its layout's context names.
- **Verified builds** are an allowlist of platform, Blender version, and build hash, each checked by hand. A test in the `isolated` layer, on macOS only, checks that the pinned binary exports the three functions under their names, as the known-gap checks for OpenUSD workarounds do, so a release that drops or renames them fails it.

The watcher reads the hovered row only from Blender's hit-testing: tracking the mouse across buttons, or redrawing rows as their items' properties, was too fragile ([Hover text and menus](#hover-text-and-menus)). `right_click_demo.py` shows this design. **Checked** with simulated right-clicks on macOS 5.2.2 `d13f752e3b9c`: with the hit test, a right-click on a row's name, indent, the space after the name, or type opened the demo's menu for that row, and one in the 3D View went to Blender; without it, Blender's list item menu drew the demo's items for the row clicked. The probes of the approaches not taken weren't kept.

### Beside the list

- **The details panel** (`draw_details`): any text and buttons, for the active row.
- **The status line** above the list: a label, with `ERROR` as its icon for an invalid query.
- **`area.header_text_set` and `workspace.status_text_set`:** replace an editor's header text or the status bar's, such as with what's under the mouse.
- **A `gpu` draw handler:** anything over the region, without the rows' positions ([Colors](#colors)).

### For the widget's gaps

What each of [What the widget lacks](#what-the-widget-lacks) could be drawn with, none of it tried:
- **Unloaded payloads, what's in them, and instance proxies:** a badge or socket dot each, or Unicode bold and italic names ([Scene Graph Rows](scene-graph-rows.md), A4–A7).
- **Ancestors of the selection:** an icon or a socket dot, since a row's background can't be set.
- **Kind:** the kind's icon in place of the type's, and the fixed-color `ERROR` icon for an invalid kind.
- **Visibility, active, purpose, draw mode, and variants:** `prop` and `prop_enum` columns of fixed `ui_units_x`, with header toggles choosing which show.
- **Copy prim path, jump to enclosing model, and select bound material:** items appended to the button context menu, or a menu button per row.

## Keyboard

The tree's keys: Right expands the active row, or steps into it if it's already expanded. Left collapses it, or steps out to its parent. Shift with either does the whole subtree, and Up and Down move between rows. **Tested** in the model: each step moves the selection where it should.

**Checked** in the binary:
- **The list takes arrow keys first.** While the cursor is over a `UIList`, the list takes all four arrow keys itself, ahead of every keymap: Left and Up move to the previous row, Right and Down to the next. Its update callback sees only the active row change, not which key moved it.
- **The Frames keymap comes before the 3D View's.** In the 3D View sidebar, "Frames" is checked before "3D View Generic", so Shift+Right jumped frames instead of reaching a binding in "3D View Generic". An add-on item in "Frames" itself did win Shift+Right while its poll passed. Alt+arrows reached "3D View Generic".
- **A modal operator sees keys first.** Window modal handlers run before regions' handlers. The watcher (`widget_keys.py`):
  - runs in each window, one per window, tracked by the window it runs in; one starts in every window at registration, and drawing a view starts one in a window that has none;
  - takes plain and Shift Left/Right while the cursor is over a region whose host says it shows a view;
  - passes every other event on.

  With it, the tree expanded, stepped, and collapsed as expected. Up and Down stayed the list's, the frame didn't change over the sidebar, and Right over the viewport still stepped a frame. That was the proof of concept's watcher, which asked one fixed test for the tree's tab; the widget's asks each view's host instead.
- **Text fields keep their keys.** While a text field is being edited, the field gets keys before the watcher: typing `a`, Left, `b` in the search box gave `ba`, and the tree didn't move.

### Rules for modal operators

Phase 3 will likely have more than one modal operator, so these apply to all of them:
- **Run one per window, in every window.** Loading a file ends modal operators, and a window opened later has none, so the watcher tracks which windows have one and starts one in any window that draws a view and has none. It untracks a window in its `cancel`, and the `load_post` handler untracks every window. **Checked** with the demo in the binary: Left and Right moved the tree in the first window, in a window opened after registration, and after a file load; closing the new window removed its entry, which only the watcher's `cancel` does; and no entry was left for a window that no longer existed.
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
- **A shared watcher:** one modal operator dispatching to several features would pay the call into Python once. That is an inference from the table, not measured. The widget's watcher already serves every view.
- **Limits:** simulated mouse moves aren't merged the way the system's are, and the batches time event handling, not drawing.

## Search

The `UIList`'s own filter hides every row that doesn't match, and sees only the rows already expanded. A stage editor needs to find prims anywhere and see where they are. `prim_search.search` does that, and `PrimTree.set_search` shows the result. **Checked** in the binary, and **Tested**:
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
- **Python traversal:** about 5 µs per prim. That's 90–230 ms for 37,000 prims, and 3.1–5.3 s for a million with no match. A search stops at 10,000 matches, which bounds what it lays out but not its time: a query with few matches still traverses the whole stage, on Blender's main thread.
- **An index:** listing every prim's name once took 1.4 s for a million prims, and searching that list took about 35 ms a search. Keeping such an index current as the stage changes wasn't tried. The core, which already follows the stage's changes, is a natural owner for it.
- **Many matches under one parent:** 10,000 matches among a million siblings took 1.2–1.5 s to lay out, since the parent's children are filtered to the ones that lead to matches.

**Search performance needs work.** At these costs a search on a large stage stalls Blender for seconds, and every hierarchy change reruns an active search. Candidates are an index kept current with the stage's changes, a search that runs in steps or off the main thread, and a faster layout of many matches under one parent. None was tried.

## Selection with the viewport

The tree in the 3D View sidebar shows a binding's stage and selects with the viewport. The tree in the node editor's sidebar shows the Viewer's stage, which no binding displays, so it selects nothing ([Node Tree](node-tree.md#viewer)).

The widget gives the host both directions, `on_selection_changed` from the tree and `select_prim` into it ([What a Host Does](#what-a-host-does)); mapping between prims and Blender objects is the host's, and waits for Phase 2 (DECISIONS.md "Phase 3 ordering"). **Not checked:** neither mapping was built.
- **Tree to viewport:** the host maps the selected prim to its Blender objects and selects them. In Proscenium, that mapping goes through the inspection layer's selection targets ([interaction contract](../spec/interaction-contract.md#two-layers-and-the-live-stage)), so the tree and the viewport agree on instance contexts. Prims with no Blender object (unloaded, inactive, class, over) have nothing to select.
- **Viewport to tree:** Blender has no event for a selection change. Two ways to notice one:
  - A `depsgraph_update_post` handler can compare the selected objects with the last set it saw. The Hydra bridge's `tools/feasibility/hydra_bridge/select_tool.py` follows Blender's selection this way. The host would map the objects to prims and call `select_prim`.
  - A `bpy.msgbus` subscription to the active object fires only when the active object changes.
- **Things to handle:**
  - **Feedback loops:** `select_prim` doesn't call `on_selection_changed`, so a selection the host makes isn't reported back to it.
  - **Instances:** a pick inside a native instance resolves to an instance-proxy row, which the model already lists.
  - **Cost:** revealing a prim inside a large group pays that group's expand cost.

## Where the tree can go

- **3D View sidebar: works, and hosts a binding's stage.** **Checked.**
  - The tree's tab is its own.
  - The keys work over it.
  - The sidebar can be dragged wide.
- **Node editor sidebar: hosts the Viewer's stage,** beside the node tree. **Not checked:** a host's panel there takes the same drawing calls with another editor type, and whether the keys reach it as they do in the 3D View.
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
  - another editor's sidebar (Image, Graph), which takes the same drawing calls in a panel with a different editor type;
  - a panel opened by a hotkey (`wm.call_panel(..., keep_open=True)`);
  - an operator's dialog;
  - the file browser's sidebar in a bind operator's file dialog, where a prim tree beside the chosen USD file could suit choosing what to bind.
- **More than one place at once:** each view has its own rows and scroll, and several views can show the same stage (**Tested**, without drawing). Two panels drawing the same view would share its rows, its selection, and, since a `UIList` keeps its scroll per list ID, its scroll. **Not checked** in a window.

### Workspaces

A workspace that arranges editors around the tree can be built at run time or shipped.
- **Built at run time:** **Checked**, by copying the active workspace and changing its editors.
  - `workspace.duplicate` created the copy at once, in `bpy.data.workspaces`, and setting `window.workspace` switched to it.
  - On a screen that isn't showing, setting an area's type changed `area.type` but left the old editor's space in place. So the editors are changed from a timer, once the window shows the workspace.
  - `screen.area_move`, with the window, screen, and area overridden, dragged the edge between two editors.
- **Shipped:** in a .blend file the add-on appends, with editor types, sizes, and panel order already set. The Maya Workflow Kit adds its layouts this way. **Not checked.**

## Testing

- **Without Blender's UI:** the row model, the search, the view's steps and change notices, and the tooltip text have no `bpy`, so they test in `bpy_free` (`tests/bpy_free/test_prim_tree.py`, `test_prim_tree_search.py`, `test_prim_tree_view.py`), on `tests/fixtures/scenes/scene_graph/prim_kinds.usda`, a stage with one prim of each kind a row marks.
- **Blender's data, without a window:** `tests/blender/test_scene_graph.py` checks the widget's registration, its views' row items, the operators and their tooltips, the search fields, stage edits, and a file load, in the bpy wheel. Search and stage-change timers don't run without an event loop, so the tests call `apply_pending` as the timers would.
- **The binary's quirks:** the binary with `--enable-event-simulate` can drive the UI, but:
  - Each simulated event needs its own `x` and `y`. Without them, key events landed at the mouse position (0, 0).
  - Event and region coordinates are pixels; `window.width` and `window.height` are points.
  - A region's `active_panel_category` (its sidebar tab) is read-only, so a run moves its panels into the tab that shows.
  - Screenshots didn't capture tooltips or popovers.
- **What tests can cover:** windowed UI tests are out of the project's test scope, so the drawing code stays thin, and the model and search carry the logic tests can reach. Drawing, the key watcher, and the icons are checked by hand with `tools/scene_graph_demo.py`, which hosts two views of one stage, in the 3D View's sidebar and the node editor's, as the add-on will (`Blender --python tools/scene_graph_demo.py [-- stage.usda]`).

## Compared with usdview and Solaris

What two other scene graph trees show for each prim, beside what this widget's rows show. **Not checked:** read from documentation and source, not run. Solaris is from [Houdini's Scene Graph Tree page](https://www.sidefx.com/docs/houdini/ref/panes/scenegraphtree.html). usdview's columns and menu are from [NVIDIA's usdview Tree View page](https://docs.omniverse.nvidia.com/usd/latest/usdview/tree_view.html), which shows its legend only as an image, so its colors and fonts are from its source on OpenUSD's `release` branch (`pxr/usdImaging/usdviewq/primViewItem.py` and `common.py`).

### Name text

| State | usdview | Solaris | This widget |
|---|---|---|---|
| Has composition arcs | Dark yellow (222, 158, 46) | A style of its own, for inherits, references, or specializes | The details only |
| Loaded payload | The arcs color | Bold, light orange | The details only |
| Unloaded payload | The arcs color | Bold italic, dark orange | The details only |
| Inside an unloaded payload | — | Italic, in the unloaded color | Nothing |
| Instance | Light sky blue (135, 206, 250), ahead of the arcs color | Light blue, with the payload styles over it | The details only |
| Instance proxy | — | A style of its own, italic when the instance's payload is unloaded | The details only |
| Inside a prototype | Blue-violet (118, 136, 217) | — | Not listed: the tree reaches instances' contents through instance proxies |
| Inactive | Its color, darkened | A deactivated style | Dimmed |
| Specifier | The font: a def bold, an over light italic, a class normal weight | — | A class's name in Unicode italics, not its children's; an orphaned over, which nothing defines, red; the specifier in the tooltip |
| A search match's ancestor that doesn't match | — | — | Dimmed |
| An ancestor of the selection | A background of the selection color at 20% opacity | — | Nothing |

So usdview tells composition by color, activity by darkening, and the specifier by font, where this widget dims inactive prims and unmatched ancestors, turns orphaned overs red, and sets a class's name in Unicode italics. A row's text can't take a color here, beyond dim and red ([Colors](#colors)), so telling more states apart takes icons, badges, socket dots, or Unicode text styles.

### Icons and markers

- **Type icon:** Solaris shows the prim's kind's icon if it has a kind, and its type's otherwise. This widget shows a type icon only. usdview has none.
- **Badges:** neither has badges. This widget has payload, references, variants, and instance badges, each with a tooltip, but its rows don't draw them for now.
- **Override dots:** Solaris marks a prim red for an override in its viewport-only layer (visibility, draw mode, or active), blue for a post-layer override, and purple for both. The widget edits nothing, so has nothing to mark.
- **Warnings:** Solaris's Kind column marks an invalid kind with a warning icon. This widget marks no problem on a row.
- **Animated visibility:** Solaris shows an animated eye for visibility that has time samples.

### Columns

| Column | usdview | Solaris | This widget |
|---|---|---|---|
| Name | ✓, or `displayName` if set to show it | ✓ the path and name | ✓, or `displayName` where a prim has one, from a menu in the header |
| Type | ✓ | ✓ | ✓, and can be hidden |
| Visibility | ✓ V or I, bold italic when inherited; a click toggles it | ✓ inherited or hidden, and animated; a click toggles it | — |
| Guide visibility | ✓ | — | — |
| Draw mode | ✓ computed, italic when inherited | ✓ computed, for prims in a valid model hierarchy; an edit reaches descendants without their own | — |
| Kind | In the tooltip | ✓ with a warning icon when invalid | In the tooltip and details |
| Purpose | — | ✓ | — |
| Variants | — | ✓ a menu per variant set, which switches its selection | The details only |
| Material | — | ✓ the bound material's name, its path on hover, an arrow when inherited | — |
| Proxy path | — | ✓ | — |
| Populated (P) and Loaded (L) | — | ✓ each in four states: not, a child, from an ancestor, and explicit | Loaded only in the details |
| Active | In the context menu | ✓ a toggle | — |
| Solo | "Vis Only" in the context menu | ✓ in three states; lights and geometry solo separately | — |
| Selectable | — | ✓ inherited to descendants | — |

Solaris's gear menu chooses which columns show.

### Listing, search, and state

- **Which prims are listed:** Solaris's toolbar toggles show or hide inactive, invisible, over-only, and class prims, and its `/HoudiniLayerInfo` prim. usdview's Show menu chooses which prim types show; the NVIDIA page doesn't list its items. This widget lists every prim, instance proxies included, with no such toggles.
- **Which layer:** Solaris can show one sublayer, uncomposed, in place of the composed stage.
- **Search:** usdview searches names, with a find-next button. Solaris has selection rules: prim patterns that match as typed, show their search time, and can be saved, and a Collections sub-pane. This widget's search, with its text modes, type, and flags, and its matches shown under their ancestors ([Search](#search)), has no counterpart in either.
- **Kept state:** Solaris saves and restores the expansion, its viewport overrides, and its load masks on the LOP network, in the .hip file, and keeps a Favorites folder of prim shortcuts. This widget's expansion lasts the session.
- **Info:** Solaris opens a prim's info window on a middle-click. This widget has its tooltips and `draw_details`.
- **Context menu:** usdview's has jump to enclosing model, select bound preview or full material, make invisible, vis only, remove session visibility, load or unload the subtree's payloads, activate or deactivate, copy prim path, copy enclosing model path, open the asset in a new usdview, and set as active camera. This widget has no context menu.

### What the widget lacks

Showing only, from what a row's prim already gives:
- Distinct looks for an unloaded payload and what's inside it, and an instance proxy.
- The kind's icon, and a warning for an invalid model hierarchy.
- Marks for composition arcs, payloads, variants, and instances.
- Toggles for listing inactive, over, and class prims, and instance proxies.
- Copy prim path, jump to enclosing model, and select bound material.

What edits or overrides the stage, so waits on how Phase 3 edits it: visibility, active, draw mode, purpose, solo, and selectable columns; loading and unloading, with populated and loaded states; switching variants; override dots; and saving the expansion and favorites in the .blend file.

## Open questions

- Do tooltips and the Tool Settings popover show when hovered and clicked by hand?
- How fast is drawing and scrolling a `UIList` with thousands of rows? Only the model and the collection were timed.
- Does a hierarchy change in a stage with many visible rows rebuild them fast enough while editing, or should a change rebuild only the subtrees it resyncs?
- Can a dedicated pane's sidebar take the area's full width, and does the empty main area bother users?
- What should own the search index as the stage changes: the core, or a Python layer that listens to `Tf.Notice`?
- Where do the tree's own edits, such as visibility or active, go: a session layer, a viewport-only layer as in Solaris, or the edit target ([Compared with usdview and Solaris](#compared-with-usdview-and-solaris))?
- What does the widget's row menu hold, and should Ctrl+click add a row to a selection?
- How do multiple selected prims show in a list that highlights only one row: a highlighted button per selected row, which takes the row's clicks, or a marker icon ([Colors](#colors))?
