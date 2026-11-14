# `proscenium.ui.widget_resources`

What widgets register and draw with: the theme's colors, icons drawn in any color, badges, what a tree's rows draw alike, the arrow keys' watcher, and the clipboard operator. It's in the tier below the widgets' displays and above `columned_list/` ([import rules](../../README.md#import-rules)), and imports only `widget_model/` and `columned_list/` of the extension's units.

Each widget's display registers it with its own registration (`display_registration`), which registers it with the first widget and unregisters it with the last.

Its modules import each other in the order the table lists them, each only from those above it.

| Path | Holds |
|---|---|
| `__init__.py` | The package's exports: its modules. |
| `theme_colors.py` | The theme's colors widgets draw their own marks in (`ThemeColors`: the collection colors, named by `CollectionColor`, the list's text and pie menu's colors, and the colors Blender marks animated properties and keyframes in), read from the preferences once per list drawn; mixes of a color toward the list's text color, so it reads on the rows in any theme, plain or keeping the color's saturation; and, for the icons drawn in any color, a color rounded and named for an icon's name, and pixels of a color from how much of each it covers. |
| `tinted_icons.py` | Icons in any color, as preview icons drawn from masks, each the first time it's asked for in a color: Blender's own icons, from the masks in `blender_icons/`, and masks a widget makes itself (`mask_icon_id`). |
| `blender_icons/` | Masks of Blender's own row icons, which `tinted_icons.py` draws in colors; third-party artwork under CC BY-SA 4.0. |
| `keyframe_icons.py` | Keyframe icons for an animated property's row: a diamond outlined in the theme's keyframe border, filled in the color Blender gives an animated property's field, keyed on the current time code or only animated (`KeyframeFill`), drawn into a preview collection the first time each is asked for and again when the theme's colors change. |
| `badge_icons.py` | Badges' icons, drawn from strokes into a preview collection the first time each is asked for: a `BadgeLook`, a glyph (each arc's bold LIVRPS letter, in `ARC_LOOKS`, or an instance's two overlapping squares) in one of the theme's collection colors, on its piece (`BadgePlace`) of a dark block in the theme's pie menu color, greyed out or not; every icon drawn is drawn again when the theme's colors change. |
| `tree_rows.py` | What a tree's rows draw alike, in both widgets: the widths of an indent level, a chevron, the row's icon, its name's cell, and its badges; the chevron's icons; each indent level's guide line, a button of `TreeGuideLine`, the never-enabled operator it's drawn as; and `draw_badge_blocks`, a row's badges side by side on their blocks. |
| `list_keys.py` | Left and Right over widgets' lists: `WatchListKeys`, the modal operator that takes them, plain and with Shift, over a region showing a list, before its UIList does, and passes every other event on, one per window, started in every window once a widget adds its lists and in any window that draws a list whose running modal operators include none; each widget adds its lists as `KeyedLists`, each a `KeyedList` saying where it shows, whether the hovered row is its, whether a key steps it now, and how; and `item_name_holding`, which names the window manager's item a hovered property is in, so a widget can tell which of its lists is under the cursor. |
| `clipboard_operators.py` | `CopyUsdPath`, the internal operator a row's copy button runs, which puts a USD path on the clipboard. |
| `display_registration.py` | `register` and `unregister`: the shared classes (the guide line's, copy-path, and key-watching operators) and the badge, keyframe, and tinted icons' preview collections, kept while any widget is registered. |
