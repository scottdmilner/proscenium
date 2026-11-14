# `proscenium.ui.widget_resources/blender_icons`

Blender's own row icons, as masks `tinted_icons.py` draws in colors, as the scene graph does for instances and their instance proxies. They're third-party artwork under CC BY-SA 4.0, not this extension's license; `LICENSE.txt`, which ships in the extension's zip, gives the attribution. Regenerate them with `uv run --group icons python tools/row_icon_masks.py` when a widget's row icons or the pinned Blender release change.

| File | Holds |
|---|---|
| `row_icon_masks.npz` | Each icon a widget's row can show, by Blender's icon name: a 64-by-64 array of how much of each pixel the icon covers, 0 to 255, bottom row first, rasterized from Blender 5.2's `icons_svg`. |
| `LICENSE.txt` | The icons' source, authors, and license, CC BY-SA 4.0, and how the masks were changed from them. |
