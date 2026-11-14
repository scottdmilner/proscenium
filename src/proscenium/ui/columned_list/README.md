# `proscenium.ui.columned_list`

A list with columns, as widgets draw one in a `UIList`: the layout of the columns after a row's leading one, the header above the list, and the columns' lines in a settings popover. It's in the tier below `widget_resources/` and `search_box.py` ([import rules](../../README.md#import-rules)), and imports only `widget_model/` of the extension's units. It registers nothing.

Its modules import each other in the order the table lists them, each only from those above it.

| File | Holds |
|---|---|
| `__init__.py` | The package's exports: its modules. |
| `column_layout.py` | `Column`, a column after a row's leading one: its title, the list properties that show it and set its width, or its fixed width, its header icon and alignment, and what draws its cell from a row's details, its width in UI units or its share of what those columns leave; and the widths the columns are laid out by: each shown column's (`column_widths`), the columns shown, a column's width, the leading column's share of a row, Blender's widget unit in pixels, a list row's width in units, a split's factor leaving a width, the columns' cells in a row, and a fixed-width row. |
| `column_header.py` | A list's header: counting the rows a list draws, to tell whether it scrolls, the header's row leaving a scrolling list's scrollbar blank, and each column's title over its cells. |
| `column_settings.py` | A list's settings popover: the gear at a row's end that opens it, and its line for each column: its eye, title, and width. |
