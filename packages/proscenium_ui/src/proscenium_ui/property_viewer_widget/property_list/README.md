# `proscenium_ui.property_viewer_widget.property_list`

The property viewer widget's model: one prim's properties as the flat rows a list shows, kept apart from drawing (`display/` draws it) so it tests in `bpy_free` ([Property Viewer UI](../../../../../../docs/phase3/property-viewer-ui.md#the-model)). Its search uses `widget_model/`'s text matching. It imports without `bpy`, so `tests/bpy_free` imports it with Blender's modules blocked.

A list holds its prim and never its stage, so it never keeps a stage alive. Its view keeps the selection and the expansion by property name, so they carry over from one prim to the next.

Its modules import each other in the order the table lists them, each only from those above it.

| File | Holds |
|---|---|
| `__init__.py` | The package's exports: its modules, and the list and the view, `PropertyList` and `PropertyListView`. |
| `property_search.py` | `SearchQuery`, which properties a list shows: text matched against each property's name or path, as `widget_model.text_matching` matches it, and whether only authored ones show; and `matcher`, its test of one property. |
| `property_rows.py` | `PropertyList`: a prim's properties as rows, each a `PropertyRow` of a property, or of one of its targets (a relationship's targets, an attribute's connections) under it while it's expanded. A row's `PropertyDetails` are read when it first draws, at the list's time code, with where its value there comes from (`ValueSource`, which tells a schema's fallback from an authored default value), and a property's `PropertyMetadata`, what only the metadata panel shows, when first asked for; both are cached until the stage or time code changes. It is the package's one reader of a property. |
| `property_descriptions.py` | What the list says about a property: its value as text, written as a layer writes it and shortened to fit a row, its declaration (`custom uniform float3[]`, `rel`), what its keyframe icon marks (`AnimationMark`: a key at the time code, or between keys), whether a target is missing, the status line, the text of its row and disclosure-triangle tooltips, and the metadata panel's summary, worded from `PropertyDetails` and `PropertyMetadata` with no USD queries of its own. |
| `list_views.py` | `PropertyListView`: one list as a widget shows it, with its stage, the prim shown, its selected row, query, time code, and expanded properties. It follows the stage's `ObjectsChanged` notices, marking the list to read again and telling its owner, which reads it once the edit is over. |
