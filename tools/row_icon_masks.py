"""Make the scene graph widget's row icon masks from Blender's own icon SVGs.

    uv run --group icons python tools/row_icon_masks.py

For each icon a row can show, it fetches the SVG from the Blender release `uv.lock` pins, rasterizes it with resvg
(`resvg_py`, whose wheels hold the whole renderer) to PNG bytes, decodes them with pypng, and keeps how much of each
pixel the icon covers. Both are in the `icons` dependency group, kept out of `dev` since only this tool needs them.
The masks are written to `src/proscenium/ui/scene_graph_widget/display/blender_icons/row_icon_masks.npz`, where the
widget recolors them for instances and their proxies. The icons are licensed CC BY-SA 4.0 (that directory's
`LICENSE.txt`).
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

import numpy as np

try:  # only in the `icons` dependency group
    import png  # ty: ignore[unresolved-import]
    import resvg_py  # ty: ignore[unresolved-import]
except ImportError as error:
    sys.exit(f"{error}: run with `uv run --group icons`")

from proscenium.ui.scene_graph_widget.display.list_columns import name_column

ROOT = Path(__file__).resolve().parents[1]
MASKS_PATH = (
    ROOT / "src" / "proscenium" / "ui" / "scene_graph_widget" / "display" / "blender_icons" / "row_icon_masks.npz"
)
BLENDER_BRANCH = "blender-v5.2-release"  # the minor version uv.lock pins
SVG_URL = (
    f"https://projects.blender.org/blender/blender/raw/branch/{BLENDER_BRANCH}/release/datafiles/icons_svg/{{}}.svg"
)
MASK_SIZE_PIXELS = 64  # twice a row icon's 32 pixels at a UI scale of 2, so it stays sharp when Blender scales it
ICON_UNITS = 1600  # an icon's square, in its SVG's units: most of Blender's icon SVGs are 1600 by 1600


def rendered_pixels(svg: str, zoom: float) -> np.ndarray:
    """An SVG drawn at a zoom of its own size, as RGBA rows from 0 to 1, bottom row first, as preview pixels run."""
    # The icons have no text, so no fonts are needed.
    png_bytes = bytes(resvg_py.svg_to_bytes(svg_string=svg, zoom=zoom, skip_system_fonts=True))
    width, height, rows, _ = png.Reader(bytes=png_bytes).asRGBA8()
    pixels = np.array([list(row) for row in rows], dtype=np.float32).reshape(height, width, 4) / 255
    return pixels[::-1]  # PNG rows run top first


def coverage_mask(svg: str) -> np.ndarray:
    """How much of each pixel an icon covers, 0 to 255, bottom row first, as preview pixels run.

    The icons are drawn in units of an icon's square, ICON_UNITS on a side, and not every SVG fills it: DOT's is 600
    units, which Blender draws as a small dot, and others are narrower or shorter. Each is drawn at its size and
    centered in the mask, as Blender centers it in a row's icon square; one larger than the square fills the mask.
    resvg_py doesn't report an SVG's size, but drawn at a zoom, its image is that size times the zoom, so one larger
    than the mask is drawn again at the zoom that fits it.
    """
    zoom = MASK_SIZE_PIXELS / ICON_UNITS
    pixels = rendered_pixels(svg, zoom)
    if max(pixels.shape[:2]) > MASK_SIZE_PIXELS + 1:  # resvg rounds a zoomed size up, so a side can be one pixel over
        pixels = rendered_pixels(svg, zoom * MASK_SIZE_PIXELS / max(pixels.shape[:2]))
    pixels = pixels[:MASK_SIZE_PIXELS, :MASK_SIZE_PIXELS]
    height, width = pixels.shape[:2]
    # The icons are drawn white over transparency, a part's opacity in its alpha; Blender tints them by the theme.
    coverage = pixels[:, :, 3] * pixels[:, :, :3].mean(axis=2)
    mask = np.zeros((MASK_SIZE_PIXELS, MASK_SIZE_PIXELS), dtype=np.uint8)
    bottom, left = (MASK_SIZE_PIXELS - height) // 2, (MASK_SIZE_PIXELS - width) // 2
    mask[bottom : bottom + height, left : left + width] = np.round(coverage * 255).astype(np.uint8)
    return mask


def main() -> None:
    """Fetch, rasterize, and write every row icon's mask."""
    masks: dict[str, np.ndarray] = {}
    for name in name_column.row_icon_names():
        with urllib.request.urlopen(SVG_URL.format(name.lower())) as response:
            svg = response.read().decode()
        masks[name] = coverage_mask(svg)
        print(f"{name}: {int((masks[name] > 0).sum())} pixels covered")
    MASKS_PATH.parent.mkdir(exist_ok=True)
    np.savez_compressed(MASKS_PATH, allow_pickle=False, **masks)  # plain arrays, which np.load reads without pickle
    print(f"wrote {len(masks)} masks to {MASKS_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
