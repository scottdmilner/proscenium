# `proscenium.ui`

The extension's user interface: widgets an add-on places in Blender's editors. A widget registers its own classes and properties, and never a panel: where it shows is its host's choice, so the same widget can show in several editors at once.

Today it holds one widget, the scene graph widget, a prim tree for Phase 3's stage editor ([Scene Graph UI](../../../docs/phase3/scene-graph-ui.md)). It reads stages with Blender's bundled `pxr`, never selects through the source selection model, shows no edits through bindings, and pushes no undo steps ([DECISIONS.md](../../../docs/DECISIONS.md) "Phase 3 ordering").

| Path | Holds |
|---|---|
| `__init__.py` | The package. It imports none of its packages, so importing a bpy-free unit, which runs it first, never imports `bpy`. |
| `widget_model/` | What the widgets' bpy-free models share: matching a search's text, and the composition arcs they mark. The lowest tier. |
| `widget_resources/` | What widgets register and draw with: theme colors, tinted and badge icons, and the copy-path operator. The tier below the widgets' displays. |
| `columned_list/` | A list with columns: the columns' layout, the header, and the column settings. The tier below `search_box.py`. |
| `search_box.py` | A widget's search box, drawn from a property group's search fields: its text, its match mode (`match_mode_items`), a case toggle, and any toggles of a widget's own. It lays itself out with `columned_list/`, so it's in the tier above it, below the widgets' displays. |
| `widget_updates.py` | Updating a widget outside a draw: its timers, redrawing every area, and writing its properties from its model without their update callbacks. The tier below the widgets' displays. |
| `scene_graph_widget/` | The scene graph widget: its bpy-free model and its Blender display. |
