# `proscenium.ui.scene_graph_widget.display`

The scene graph widget's display: the `prim_tree/` model drawn in Blender as a virtualized `UIList`, for a host to place ([Scene Graph UI](../../../../../docs/phase3/scene-graph-ui.md#the-widget)). It registers no panel. A host registers it, creates named views, gives each a stage, and calls `draw_tree` and `draw_details` from its own panels' `draw`; it says, for the key watcher, which regions are showing each view, and may hear each view's selection changes. A host holds only a view's name, and changes and reads it through the package's functions.

Each view's state is a `prim_tree.PrimTreeView`, and the UIList draws from an item of the window manager's `proscenium_scene_graph_views` collection named for the view: one empty row item per visible row, the active row, and the search fields. The item mirrors the view, apart from the search fields, which hold the query being edited until it's applied to the view. The window manager's properties aren't saved, so a load handler makes the items again after each load, from the views.

Its modules import each other in the order the table lists them, each only from those above it; `tests/bpy_free/test_import_tiers.py` fails on any cycle among a unit's modules.

| File | Holds |
|---|---|
| `__init__.py` | The package's exports: the names hosts use, `register`, `unregister`, `create_view`, `remove_view`, `set_stage`, `select_prim`, `selected_path`, `draw_tree`, `draw_details`, `apply_pending`, and `ViewNotFoundError`. |
| `widget_views.py` | The views by name, each a `SceneGraphView`: its `PrimTreeView`, and what its host said about where it shows and who hears its selection. It knows nothing of Blender's data, and hosts never see it. |
| `widget_properties.py` | The property groups a view is drawn from, `SceneGraphViewProperties` (one view's rows, active row, and search fields) and `SceneGraphRow` (a row item with only a computed tooltip), with their update callbacks, the window manager's collection of them, and everything that reads or writes them: making a view's item from the view, syncing its row items with its tree, reading its search fields, and `apply_pending`, which the views' timers call to run a search a pause after the fields last change and to read stage changes once an edit is over. |
| `widget_operators.py` | The rows' buttons: `SceneGraphToggleRow`, the disclosure triangle, and `SceneGraphSelectRow`, a badge, each with its tooltip from its `description`. Both internal, pushing no undo step. |
| `badge_icons.py` | The badge icons, drawn from pixels into a preview collection. |
| `widget_keys.py` | `SceneGraphWatchKeys`, the modal operator that takes Left and Right, plain and with Shift, over a region showing a view, before its UIList does, and passes every other event on; one per window, tracked by window, started in every window at registration and in any window that draws a view without one. |
| `widget_drawing.py` | `SceneGraphList`, the UIList, which draws rows indented, with disclosure triangles, type icons, badges, and a type column; `draw_tree`, with the search box, status, and header row, which also starts a key watcher in its window if it has none; and `draw_details`. |
| `widget_hosting.py` | What a host calls: `create_view`, `remove_view`, `set_stage`, `select_prim`, and `selected_path`. |
| `widget_registration.py` | `register` and `unregister`: the classes, the window manager's collection, the badge icons, the key watchers, and the load handler that makes each view's properties again and untracks the watchers the load ended. |
