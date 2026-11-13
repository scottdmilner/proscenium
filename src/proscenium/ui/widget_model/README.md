# `proscenium.ui.widget_model`

What the widgets' models share, kept apart from drawing so it tests in `bpy_free`. It imports without `bpy` and may import only itself: it's in the lowest tier, below each widget's model ([import rules](../../README.md#import-rules)).

| File | Holds |
|---|---|
| `__init__.py` | The package's exports: the modules `text_matching` and `composition_arcs`. |
| `text_matching.py` | `MatchMode`, what a search's text is matched against (a name or a path) and how (substring, glob, or regular expression), and `text_matcher`, a test of one name or path; `InvalidPatternError` for text its mode can't match. |
| `composition_arcs.py` | `CompositionArc`, the arcs widgets mark, in LIVRPS strength order. |
