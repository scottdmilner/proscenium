# `proscenium.ui`

The extension's user interface: widgets an add-on places in Blender's editors. A widget registers its own classes and properties, and never a panel: where it shows is its host's choice, so the same widget can show in several editors at once.

It holds two widgets for Phase 3's stage editor: the scene graph widget, a prim tree ([Scene Graph UI](../../../docs/phase3/scene-graph-ui.md)), and the property viewer widget, the properties of one prim, such as the one the scene graph selects ([Property Viewer UI](../../../docs/phase3/property-viewer-ui.md)). They read stages with Blender's bundled `pxr`, never selects through the source selection model, shows no edits through bindings, and pushes no undo steps ([DECISIONS.md](../../../docs/DECISIONS.md) "Phase 3 ordering").

| Path | Holds |
|---|---|
| `__init__.py` | The package. It imports none of its packages, so importing a bpy-free unit, which runs it first, never imports `bpy`. |
| `widget_model/` | What the widgets' bpy-free models share: matching a search's text, and the composition arcs they mark. The lowest tier. |
| `columned_list/` | A list with columns: the columns' layout, the header, and the column settings and the gear that opens them. The tier below `widget_resources/` and `search_box.py`. |
| `widget_resources/` | What widgets register and draw with: theme colors, tinted and badge icons, what a tree's rows draw alike (their widths, guide lines, and badges), and the copy-path operator. It lays out tree rows with `columned_list/`, so it's in the tier above it, below the widgets' displays. |
| `search_box.py` | A widget's search box, drawn from a property group's search fields: its text, its match mode (`match_mode_items`), a case toggle, and any toggles of a widget's own. It lays itself out with `columned_list/`, so it's in the tier above it, below the widgets' displays. |
| `text_wrapping.py` | Wrapping a label's text to its region's width, measured with `blf`, since a label too long for its region is shortened with an ellipsis: lines break after a slash, dot, colon, comma, or space, so a path breaks between its elements and shows whole. It measures widths with `columned_list/`, so it's in the tier above it, below the widgets' displays. |
| `widget_updates.py` | Updating a widget outside a draw: its timers, redrawing every area, and writing its properties from its model without their update callbacks. The tier below the widgets' displays. |
| `scene_graph_widget/` | The scene graph widget: its bpy-free model and its Blender display. |
| `property_viewer_widget/` | The property viewer widget: its bpy-free model and its Blender display. |
