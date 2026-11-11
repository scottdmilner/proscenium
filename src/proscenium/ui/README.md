# `proscenium.ui`

The extension's user interface: widgets an add-on places in Blender's editors. A widget registers its own classes and properties, and never a panel: where it shows is its host's choice, so the same widget can show in several editors at once.

Today it holds the scene graph widget, a prim tree for Phase 3's stage editor ([Scene Graph UI](../../../docs/phase3/scene-graph-ui.md)). It reads stages with Blender's bundled `pxr`, never selects through the source selection model, shows no edits through bindings, and pushes no undo steps ([DECISIONS.md](../../../docs/DECISIONS.md) "Phase 3 ordering").

| Path | Holds |
|---|---|
| `__init__.py` | The package. It imports none of its packages, so importing a bpy-free unit, which runs it first, never imports `bpy`. |
| `scene_graph_widget/` | The scene graph widget: its bpy-free model and its Blender display. |
