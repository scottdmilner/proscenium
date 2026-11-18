# `proscenium_ui.property_viewer_widget`

The property viewer widget: one prim's properties as a list a host places in Blender's editors, usually beside the scene graph widget, showing the properties of the prim the scene graph selects ([Property Viewer UI](../../../../../docs/phase3/property-viewer-ui.md)). It has two parts: `property_list/`, the model, which holds the list's state, and `display/`, which draws it in Blender and forwards input to it.

| Path | Holds |
|---|---|
| `__init__.py` | The package. It imports none of its units, so importing `property_list/`, which runs it first, never imports `bpy`. |
| `property_list/` | The model: a prim's properties as the rows a list shows, with each expanded property's targets under it, its search, its selection, its time code, the stage changes it follows, and what it says about each property. |
| `display/` | The display: the property list drawn as a virtualized UIList, with its views, properties, operator, and columns, and what a host calls to place it and its metadata summary. |
