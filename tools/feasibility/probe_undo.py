"""Probe 4: can a Python-API synchronization push its own undo step?

Records behavior with global undo on and off; every runtime here is background
mode (windowed undo is out of scope).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from _common import Probe

if TYPE_CHECKING:
    from bpy.stub_internal.rna_enums import OperatorReturnItems  # stub-only alias


def run() -> dict[str, Any]:
    import bpy

    p = Probe("undo")
    p.fact("background", lambda: bpy.app.background)
    for global_undo in (True, False):
        tag = "global_undo_on" if global_undo else "global_undo_off"
        p.fact(f"{tag}: undo_push from plain function", lambda g=global_undo: _plain_push(g))
        for undo_arg in (None, False, True):
            label = "no arguments" if undo_arg is None else f"('EXEC_DEFAULT', {undo_arg})"
            p.fact(
                f"{tag}: UNDO-flag operator called with {label}",
                lambda g=global_undo, u=undo_arg: _operator_push(g, u),
            )
    p.check("undo_push from plain function restores state (global undo on)", lambda: _plain_push(True)["undo_removes"])
    p.check("redo restores the synchronized state (global undo on)", lambda: _plain_push(True)["redo_restores"])
    p.check("one undo step per push", lambda: _plain_push(True)["second_undo_reaches_base"])
    for case in ("unchanged", "renamed", "removed by undo"):
        p.fact(f"python reference after undo: {case}", lambda c=case: _stale_reference(c))
    _reset(True)
    return p.result()


def _reset(global_undo: bool) -> None:
    import bpy

    bpy.ops.wm.read_factory_settings(use_empty=True)
    prefs = bpy.context.preferences
    assert prefs is not None
    prefs.edit.use_global_undo = global_undo


def _names() -> set[str]:
    import bpy

    return {o.name for o in bpy.data.objects}


def _plain_push(global_undo: bool) -> dict[str, Any]:
    """Two synchronizations, each pushing one step; undo and redo across them."""
    import bpy

    _reset(global_undo)
    bpy.ops.ed.undo_push(message="base")
    bpy.data.objects.new("Sync1", None)
    bpy.ops.ed.undo_push(message="sync 1")
    bpy.data.objects.new("Sync2", None)
    bpy.ops.ed.undo_push(message="sync 2")
    if not bpy.ops.ed.undo.poll():  # ty: ignore[missing-argument] - stubs declare poll(self)
        return {"undo_available": False}
    first = sorted(bpy.ops.ed.undo())
    after_undo = _names()
    redo = sorted(bpy.ops.ed.redo())
    after_redo = _names()
    bpy.ops.ed.undo()
    bpy.ops.ed.undo()
    after_two = _names()
    return {
        "undo_result": first,
        "redo_result": redo,
        "undo_removes": after_undo == {"Sync1"},
        "redo_restores": after_redo == {"Sync1", "Sync2"},
        "second_undo_reaches_base": after_two == set(),
    }


def _operator_push(global_undo: bool, undo_arg: bool | None) -> dict[str, Any]:
    """A registered operator with bl_options UNDO, invoked from Python.

    bpy.ops calls take optional (execution_context, undo); None calls with no arguments."""
    import bpy

    class PROSCENIUM_OT_probe_sync(bpy.types.Operator):
        bl_idname = "proscenium_probe.sync"
        bl_label = "Probe Sync"
        bl_options = {"REGISTER", "UNDO"}

        def execute(self, context: bpy.types.Context | None) -> set[OperatorReturnItems]:
            bpy.data.objects.new("OpSync", None)
            return {"FINISHED"}

    bpy.utils.register_class(PROSCENIUM_OT_probe_sync)
    try:
        _reset(global_undo)
        bpy.ops.ed.undo_push(message="base")
        if undo_arg is None:
            bpy.ops.proscenium_probe.sync()  # ty: ignore[unresolved-attribute] - registered above
        else:
            bpy.ops.proscenium_probe.sync("EXEC_DEFAULT", undo_arg)  # ty: ignore[unresolved-attribute]
        if not bpy.ops.ed.undo.poll():  # ty: ignore[missing-argument]
            return {"undo_available": False}
        bpy.ops.ed.undo()
        return {"undo_available": True, "undo_removes": "OpSync" not in _names()}
    finally:
        bpy.utils.unregister_class(PROSCENIUM_OT_probe_sync)


def _stale_reference(case: str) -> str:
    """What happens to a Python datablock reference held across undo."""
    import bpy

    _reset(True)
    held = bpy.data.objects.new("Held", None)
    bpy.ops.ed.undo_push(message="held")
    if case == "renamed":
        held.name = "Renamed"
    elif case == "removed by undo":
        held = bpy.data.objects.new("Later", None)
    else:
        bpy.data.objects.new("Other", None)
    bpy.ops.ed.undo_push(message="change")
    bpy.ops.ed.undo()
    try:
        name = held.name
    except ReferenceError as exc:
        return f"ReferenceError: {exc}"
    lookup = bpy.data.objects.get(name)
    return f"still readable as {name!r}; equals fresh lookup: {held == lookup}"
