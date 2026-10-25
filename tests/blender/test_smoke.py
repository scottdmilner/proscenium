"""Cross-platform smoke tests in the bpy wheel: pxr, extension registration, save/reopen, undo."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

import bpy

from proscenium import addon
from proscenium.persistence import records
from support import undo
from support.blend import save_and_reopen

from .state import handler_lists

if TYPE_CHECKING:
    from collections.abc import Callable
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


class _Registrations(NamedTuple):
    handlers: dict[str, list[str]]  # the extension's handlers by event
    namespaces: list[str]  # the ID types with the records' namespace
    classes: list[str]  # the extension's classes registered with Blender


def _registrations() -> _Registrations:
    """What the extension has added to Blender."""
    return _Registrations(
        {
            e: names
            for e, fns in handler_lists().items()
            if (names := [getattr(f, "__name__", repr(f)) for f in fns if _ours(f)])
        },
        [t.__name__ for t in addon.RECORD_TYPES if hasattr(t, records.NAMESPACE)],
        [c.__name__ for c in addon.CLASSES if "bl_rna" in vars(c)],  # registering gives a class its bl_rna
    )


def _ours(fn: Callable[..., object]) -> bool:
    return getattr(fn, "__module__", None) == addon.__name__


def test_extension_registers_and_unregisters(extension: ModuleType) -> None:
    registered = _registrations()
    assert {"load_pre", "load_post", "undo_pre", "undo_post", "redo_pre", "redo_post"} <= registered.handlers.keys()
    assert registered.namespaces == [t.__name__ for t in addon.RECORD_TYPES]
    assert registered.classes == [c.__name__ for c in addon.CLASSES]
    extension.unregister()
    assert _registrations() == _Registrations({}, [], [])


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
