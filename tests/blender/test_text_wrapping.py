"""Wrapping a label's text to its region's width (proscenium.ui.text_wrapping), so a long path shows whole.

The wrapping is measured here by character count, a character a pixel, so each expected line is written from the
text; Blender's own measure needs a region, which the background wheel's context doesn't have.
"""

from __future__ import annotations

import bpy

from proscenium.ui import text_wrapping


def _characters(text: str) -> float:
    return float(len(text))


def test_a_path_breaks_between_its_elements() -> None:
    path = "/World/Geometry/Crates/Crate_Unique.xformOpOrder"
    assert text_wrapping.wrap_text(path, 24, _characters) == [
        "/World/Geometry/Crates/",
        "Crate_Unique.",
        "xformOpOrder",
    ]
    assert "".join(text_wrapping.wrap_text(path, 24, _characters)) == path  # nothing dropped


def test_words_break_at_spaces_which_the_lines_drop() -> None:
    assert text_wrapping.wrap_text("Opinions: 2, strongest in root.usda", 16, _characters) == [
        "Opinions: 2,",
        "strongest in",
        "root.usda",
    ]


def test_a_part_with_no_break_is_cut_where_it_fills_a_line() -> None:
    assert text_wrapping.wrap_text("abcdefghij", 4, _characters) == ["abcd", "efgh", "ij"]
    assert text_wrapping.wrap_text("ab", 0, _characters) == ["a", "b"]  # too narrow for one: a character a line


def test_text_that_fits_stays_one_line() -> None:
    assert text_wrapping.wrap_text("/World", 40, _characters) == ["/World"]
    assert text_wrapping.wrap_text("", 40, _characters) == [""]


def test_without_a_region_text_stays_whole() -> None:
    text = "/World/Geometry/Crates/Crate_Unique.xformOpOrder"
    assert text_wrapping.wrapped_lines(bpy.context, text) == [text]  # the background wheel has no region
