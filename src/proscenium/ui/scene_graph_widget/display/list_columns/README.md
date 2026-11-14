# `proscenium.ui.scene_graph_widget.display/list_columns`

The scene graph list's columns, a module each, which `scene_graph_drawing.py` draws each row and the header from. The name column draws the tree; each column after it is a `columned_list.column_layout.Column`, which says how the header and the settings popover show it and draws its cell in a row from the row's `RowDetails`.

No column's module imports another of this package's modules. Of the display's other modules, they import only ones listed above `scene_graph_drawing.py` in the display's table; `__init__.py` imports the columns after the name. They draw with `columned_list/`'s layout and `widget_resources/`' icons and colors.

| File | Holds |
|---|---|
| `__init__.py` | `COLUMNS`, the columns after the name in the order they show, from the column modules; and `redraw_icons_if_theme_changed`, which reads the theme's colors and redraws the badge icons if they were drawn in others, once per view drawn. `scene_graph_drawing.py` imports them and `name_column.py`. |
| `name_column.py` | The name column: each row's indent and guide lines, dashed in the instancing colors under an instance, from a mask made here with its dashes timed to run evenly down a column of rows, its disclosure triangle, its type or kind icon, in those colors for an instance and its proxies, as are proxies' chevrons, its name, and a badge after the name for each composition arc on the prim and for an instance; `row_icon_names`, every icon a row can show; and the header's menu of which name the rows show. |
| `children_column.py` | The Children column: how many children a row's prim has, blank for a leaf. |
| `kind_column.py` | The Kind column: a row's prim's model kind, red where the model hierarchy makes it invalid. |
| `type_column.py` | The Type column: a row's prim's type name, or a dash. |
| `copy_path_column.py` | The Copy Path column: a button on each row, scaled wider than its icon, that copies its prim's path with the shared `CopyUsdPath`. |
