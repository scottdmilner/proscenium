# `proscenium.ui.scene_graph_widget`

The scene graph widget: a stage's prim hierarchy as a tree a host places in Blender's editors ([Scene Graph UI](../../../../docs/phase3/scene-graph-ui.md#the-widget)). It has two units, by the [import rules](../../README.md#import-rules): `prim_tree/`, the model, which holds the tree's state and imports nothing of Blender's, and `display/`, which draws it in Blender and forwards input to it.

| Path | Holds |
|---|---|
| `__init__.py` | The package. It imports none of its units, so importing `prim_tree/`, which runs it first, never imports `bpy`. |
| `prim_tree/` | The model: a stage's hierarchy as the rows a tree shows, its search, its selection and keyboard steps, the stage changes it follows, and what it says about each prim. The lowest tier. |
| `display/` | The display: the prim tree drawn as a virtualized UIList, with its views, properties, operators, key watcher, and badge icons, and what a host calls to place it. Tier 6. |
