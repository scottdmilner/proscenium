"""Cross-platform smoke tests in the bpy wheel: pxr, extension registration, save/reopen, undo."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import bpy

from proscenium import addon
from support import undo
from support.blend import save_and_reopen

if TYPE_CHECKING:
    from types import ModuleType


def test_blender_modules_importable() -> None:
    # The bpy_free layer's blocker must not leak into this layer; a blocked import raises.
    import importlib

    importlib.import_module("bmesh")


def test_pxr_is_the_one_bundled_with_blender() -> None:
    from pxr import Usd

    # resource_path("LOCAL") is Blender's versioned install dir (bpy/5.2 in the wheel).
    local = Path(bpy.utils.resource_path("LOCAL")).resolve()
    assert local in Path(Usd.__file__).resolve().parents


def test_extension_registers_and_unregisters(extension: ModuleType) -> None:
    assert addon.is_registered()
    extension.unregister()
    assert not addon.is_registered()


def test_save_and_reopen_keeps_data(tmp_path: Path) -> None:
    # Linked to the scene: datablocks without users are not written to the file.
    scene = bpy.context.scene
    assert scene is not None
    scene.collection.objects.link(bpy.data.objects.new("Kept", None))
    save_and_reopen(tmp_path / "roundtrip.blend")
    assert "Kept" in bpy.data.objects
    assert Path(bpy.data.filepath) == tmp_path / "roundtrip.blend"


def test_undo_and_redo_one_step() -> None:
    undo.require_global_undo()
    undo.push("base")
    bpy.data.objects.new("Step", None)
    undo.push("add Step")
    undo.undo()
    assert "Step" not in bpy.data.objects
    undo.redo()
    assert "Step" in bpy.data.objects
