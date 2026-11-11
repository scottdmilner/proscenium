# `proscenium.ui.scene_graph_widget.prim_tree`

The scene graph widget's model: a stage's prim hierarchy as the flat rows a tree shows, kept apart from drawing (`display/` draws it) so it tests in `bpy_free` ([Scene Graph UI](../../../../../docs/phase3/scene-graph-ui.md#the-row-model)). It imports without `bpy` and may import only itself; `tests/bpy_free` imports it with Blender's modules blocked.

A tree holds its stage's prims and never the stage, so it never keeps a stage alive: once the stage's owner releases it, the tree is expired and shows nothing. Expansion, details, and search results are kept by path, so they survive the stage recomposing.

Its modules import each other in the order the table lists them, each only from those above it.

| File | Holds |
|---|---|
| `__init__.py` | The package's exports: the modules `prim_children`, `prim_search`, and `prim_descriptions`, and the names `PrimTree`, `TreeRow`, `PrimTreeView`, and `StepDirection`. |
| `prim_children.py` | `CHILD_PREDICATE`, which lists every child a stage editor shows, instance proxies included, and `has_children`, which checks for one without listing them. |
| `prim_search.py` | `search`: the prims a `SearchQuery` matches over the whole stage (text by name, path, glob, or regular expression; a schema type, with `IsA`; and `SearchFlag`s), and the ancestors that show them in place, as a `SearchResult`. |
| `prim_tree.py` | `PrimTree`: a stage's expansion state and the rows it makes visible, each a `TreeRow` of a prim and its depth. Expanding splices a subtree's rows in and collapsing cuts them out; a row's `RowDetails` are read when it first draws. Also the keys' steps (`expand_or_enter_row`, `collapse_or_select_parent`), `reveal`, the search filter, and `refresh` after the stage changes. |
| `prim_descriptions.py` | What the tree says about a prim: a row's name (`row_name`, which sets a class in Unicode italics) and `Badge`s, and the text of its row, badge, and disclosure-triangle tooltips and its details. |
| `prim_tree_view.py` | `PrimTreeView`: one tree as a widget shows it, with its selected prim, query and `SearchStatus`, and keyboard steps. It follows the stage's `ObjectsChanged` notices, marking what to read again (`PendingChange`) and telling its owner, which reads it once the edit is over. |
