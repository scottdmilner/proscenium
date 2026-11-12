# `proscenium.ui.scene_graph_widget.display/list_columns`

The scene graph list's columns, a module each, which `widget_drawing.py` draws each row and the header from. The name column draws the tree; each column after it is a `Column`, which says how the header and the settings popover show it and draws its cell in a row from the row's details.

Each column's module imports, of this package's modules, only `column_layout.py`, and no column imports another. Of the display's other modules, they import only ones listed above `widget_drawing.py` in the display's table; `__init__.py` imports the columns after the name, and `badge_icons.py` and `widget_colors.py`.

| File | Holds |
|---|---|
| `__init__.py` | `COLUMNS`, the columns after the name in the order they show, from the column modules; and `redraw_icons_if_theme_changed`, which reads the theme's colors and redraws the badge icons if they were drawn in others, once per view drawn. `widget_drawing.py` imports them, `column_layout.py`, and `name_column.py`. |
| `column_layout.py` | `Column`, a column after the name: its title, the view properties that show it and set its width, or its fixed width, its header icon and alignment, and what draws its cell; and the widths the columns are laid out by: a column's width, Blender's widget unit in pixels, a list row's width in units, a split's factor leaving a width, the columns' cells in a row, and a fixed-width row. |
| `name_column.py` | The name column: each row's indent and guide lines, dashed in the instancing colors under an instance, its disclosure triangle, its type or kind icon, in those colors for an instance and its proxies, as are proxies' chevrons, its name, and a badge after the name for each composition arc on the prim and for an instance; `row_icon_names`, every icon a row can show; and the header's menu of which name the rows show. |
| `children_column.py` | The Children column: how many children a row's prim has, blank for a leaf. |
| `kind_column.py` | The Kind column: a row's prim's model kind, red where the model hierarchy makes it invalid. |
| `type_column.py` | The Type column: a row's prim's type name, or a dash. |
| `copy_path_column.py` | The Copy Path column: a button on each row, scaled wider than its icon, that copies its prim's path. |
