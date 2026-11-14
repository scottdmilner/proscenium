# UIList options demos

Blender scripts that each try one part of [What a UIList can show](../../../docs/phase3/scene-graph-ui.md#what-a-uilist-can-show), on every prim of `tests/fixtures/scenes/scene_graph/prim_kinds.usda`, for judging by hand which options suit the scene graph widget. They're evidence, not product code: they draw a flat, fully expanded list of prims, and leave the tree to the widget.

| File | Holds |
|---|---|
| `demo_prim_rows.py` | What every demo shares: the stage's prims as one row item each on the window manager, repeated to try a list at length, with payloads loaded or not, their tooltip, and the sidebar tab the demos' panels are on. |
| `list_controls_demo.py` | [Filter flags](../../../docs/phase3/scene-graph-ui.md#filter-flags): a `filter_items` that sets six of the list's own bits for each row, some from other rows, a `draw_item` that draws from them, and how long `filter_items` takes, computing the flags or returning them again. |
| `row_look_demo.py` | [A row's look](../../../docs/phase3/scene-graph-ui.md#a-rows-look): `active`, `enabled`, and `alert` tied to a chosen prim fact on the row, its name, or its buttons; the buttons' `emboss` and `depress`; and `scale_y`, `scale_x`, a fixed `ui_units_x`, and `alignment`. |
| `row_contents_demo.py` | [A row's contents](../../../docs/phase3/scene-graph-ui.md#a-rows-contents): each prim's state as a text glyph, a socket dot, a fixed-color icon, and a preview icon; type, kind, and large name icons; and columns of per-row properties (icon toggle, checkbox, enum, dynamic enum), `progress`, a color swatch, and a menu button that reads its row from the context; disclosure triangles, indentation by separators or guide glyphs, and column and row dividers. |
| `hover_and_menus_demo.py` | [Hover text and menus](../../../docs/phase3/scene-graph-ui.md#hover-text-and-menus): a row tooltip in three lengths, a tooltip of each other kind (an operator's `description`, a property's, and an enum's per-row items), the status bar written on hover, and items added to the button context menu, above or below Blender's, which read the right-clicked row from its layout's context. |
| `right_click_demo.py` | [The widget's right-click](../../../docs/phase3/scene-graph-ui.md#the-widgets-right-click): a watcher that takes right-clicks over its own list (`context.ui_list`), finds the row under the mouse with Blender's own list hit-testing (private functions called through `ctypes`, on verified builds only), and opens a menu of its own; and otherwise, items added to Blender's list item menu. |
| `redraw_benchmark.py` | Times the widget's sidebar redraws in a window, at a given row count: the widget as it is, with flags returned again, and with flags computed on each redraw ([Filter flags](../../../docs/phase3/scene-graph-ui.md#filter-flags)). |

## Running one

```sh
/Applications/Blender.app/Contents/MacOS/Blender --python tools/feasibility/uilist_options/list_controls_demo.py
```

In the 3D View, open the sidebar (N) and its **UIList Demo** tab. The benchmark runs one case and quits:

```sh
/Applications/Blender.app/Contents/MacOS/Blender --factory-startup \
    --python tools/feasibility/uilist_options/redraw_benchmark.py -- computed_flags 100000
```
