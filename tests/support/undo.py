"""Undo/redo support for background-mode tests.

What works in background mode is recorded in docs/feasibility/runtime-record.md#undo:
- With global undo on, `ed.undo_push` steps can be undone and redone.
- With global undo off, `ed.undo` fails its poll, so undo cannot be exercised.

Push a base step before the change under test; the first undo returns to it.
"""

from __future__ import annotations

import bpy
import pytest


def global_undo_enabled() -> bool:
    prefs = bpy.context.preferences
    assert prefs is not None
    return prefs.edit.use_global_undo


def require_global_undo() -> None:
    """Skip the calling test when global undo is off, where background-mode undo is unavailable."""
    if not global_undo_enabled():
        pytest.skip("global undo is off: ed.undo fails its poll in background mode (runtime-record.md#undo)")


def push(message: str) -> None:
    """Record an undo step for the current state."""
    bpy.ops.ed.undo_push(message=message)


# The stubs declare each operator as a class (the call is __new__), so ty sees
# poll() as unbound; at runtime bpy.ops.ed.undo is an instance and poll() takes no arguments.


def undo(steps: int = 1) -> None:
    """Undo `steps` steps, failing the test if one is not available."""
    for _ in range(steps):
        assert bpy.ops.ed.undo.poll(), "no undo step available"  # ty: ignore[missing-argument]
        bpy.ops.ed.undo()


def redo(steps: int = 1) -> None:
    """Redo `steps` steps, failing the test if one is not available."""
    for _ in range(steps):
        assert bpy.ops.ed.redo.poll(), "no redo step available"  # ty: ignore[missing-argument]
        bpy.ops.ed.redo()
