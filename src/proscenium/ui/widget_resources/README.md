# `proscenium.ui.widget_resources`

What widgets register and draw with: the theme's colors, icons drawn in any color, badges, and the clipboard operator. It's in the tier below the widgets' displays ([import rules](../../README.md#import-rules)), and imports only `widget_model/` of the extension's units.

Each widget's display registers it with its own registration (`display_registration`), which registers it with the first widget and unregisters it with the last.

Its modules import each other in the order the table lists them, each only from those above it.

| Path | Holds |
|---|---|
| `__init__.py` | The package's exports: its modules. |
| `theme_colors.py` | The theme's colors widgets draw their own marks in (`ThemeColors`, with the collection colors named by `CollectionColor`), read from the preferences once per list drawn; mixes of a color toward the list's text color, so it reads on the rows in any theme, plain or keeping the color's saturation; and, for the icons drawn in any color, a color rounded and named for an icon's name, and pixels of a color from how much of each it covers. |
| `tinted_icons.py` | Icons in any color, as preview icons drawn from masks, each the first time it's asked for in a color: Blender's own icons, from the masks in `blender_icons/`, and masks a widget makes itself (`mask_icon_id`). |
| `blender_icons/` | Masks of Blender's own row icons, which `tinted_icons.py` draws in colors; third-party artwork under CC BY-SA 4.0. |
| `badge_icons.py` | Badges' icons, drawn from strokes into a preview collection the first time each is asked for: a `BadgeLook`, a glyph (each arc's bold LIVRPS letter, in `ARC_LOOKS`, or an instance's two overlapping squares) in one of the theme's collection colors, on its piece (`BadgePlace`) of a dark block in the theme's pie menu color, greyed out or not; every icon drawn is drawn again when the theme's colors change. |
| `clipboard_operators.py` | `CopyUsdPath`, the internal operator a row's copy button runs, which puts a USD path on the clipboard. |
| `display_registration.py` | `register` and `unregister`: the shared classes and the badge and tinted icons' preview collections, kept while any widget is registered. |
