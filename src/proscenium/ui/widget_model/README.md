# `proscenium.ui.widget_model`

What the widgets' models share, kept apart from drawing so it tests in `bpy_free`: matching a search's text, the composition arcs and key steps they use, and what a widget reads and says of a prim. It imports without `bpy` and may import only itself: it's in the lowest tier, below each widget's model ([import rules](../../README.md#import-rules)).

| File | Holds |
|---|---|
| `__init__.py` | The package's exports: the modules `text_matching`, `composition_arcs`, `list_steps`, `prim_details`, and `prim_detail_text`. |
| `text_matching.py` | `MatchMode`, what a search's text is matched against (a name or a path) and how (substring, glob, or regular expression), and `text_matcher`, a test of one name or path; `InvalidPatternError` for text its mode can't match. |
| `composition_arcs.py` | `CompositionArc`, the arcs widgets mark, in LIVRPS strength order. |
| `list_steps.py` | `StepDirection`, which way a widget's Left and Right keys step through its list: into a row, or out of it. |
| `prim_details.py` | What a widget reads of one prim: `RowDetails`, what a list row of it draws (its names, type, kind, child count, flags, and which arcs are authored), and `PrimDetails`, what only a tooltip, summary, or details panel says (its arcs' targets as composed, variant selections, prototype, and attribute count), read by `row_details_of` and `prim_details_of` uncached, for each widget to cache; and `CHILD_PREDICATE`, the children a widget lists, instance proxies included, and `child_count`. |
| `prim_detail_text.py` | What the widgets say about a prim alike, from those records: its badges (its instancing, and the `CompositionArc`s authored on it, each in effect or not), and its lines: what each badge marks, and what's unusual about it. The scene graph's row tooltip and the property viewer's summary both say them. |
