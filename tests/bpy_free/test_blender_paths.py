"""tools/blender_paths.py: choosing the installed Blender for the locked release."""

from __future__ import annotations

from blender_paths import pick_release


def test_exact_release_preferred_over_newer_patch() -> None:
    installed = [("a", (5, 2, 3)), ("b", (5, 2, 2)), ("c", (5, 2, 2))]
    assert pick_release(installed, (5, 2, 2)) == "b"


def test_newest_patch_of_minor_without_exact() -> None:
    installed = [("a", (5, 2, 0)), ("b", (5, 2, 4)), ("c", (5, 3, 0)), ("d", None)]
    assert pick_release(installed, (5, 2, 2)) == "b"


def test_none_without_minor() -> None:
    assert pick_release([("a", (5, 0, 0)), ("b", (4, 5, 5)), ("c", None)], (5, 2, 2)) is None
