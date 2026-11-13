"""Updating a widget outside a draw: its timers, redrawing every area, and writing its properties from its model.

A widget's model owns its state, and its properties mirror it, so writing them from the model must not run their
update callbacks, which apply a user's change to the model. Blender 5 keeps `bpy.props` apart from dict-style ID
properties, so only a flag can stop the callbacks: each checks `is_writing_from_model` first.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

import bpy

if TYPE_CHECKING:
    from collections.abc import Callable, Generator


class _WidgetUpdatesState:
    is_writing_from_model = False  # set while properties are written from a model, so no update callback runs


@contextmanager
def writing_from_model() -> Generator[None]:
    """Mark properties as being written from their widget's model while the block runs."""
    _WidgetUpdatesState.is_writing_from_model = True
    try:
        yield
    finally:
        _WidgetUpdatesState.is_writing_from_model = False


def is_writing_from_model() -> bool:
    """Whether properties are being written from their widget's model, so an update callback should do nothing."""
    return _WidgetUpdatesState.is_writing_from_model


def schedule(timer: Callable[[], None], delay_seconds: float) -> None:
    """Run a timer after a delay, restarting the delay if it's already waiting; a file load doesn't cancel it."""
    unschedule(timer)
    # A widget's timer may read changes its model marked pending once, so a lost timer would stop its updates.
    bpy.app.timers.register(timer, first_interval=delay_seconds, persistent=True)


def unschedule(timer: Callable[[], None]) -> None:
    """Cancel a timer if it's waiting."""
    if bpy.app.timers.is_registered(timer):
        bpy.app.timers.unregister(timer)


def redraw_all_areas() -> None:
    """Redraw every window's areas: hosts draw widgets wherever they like."""
    wm: Any = bpy.context.window_manager
    if wm is None:
        return
    for window in wm.windows:
        for area in window.screen.areas:
            area.tag_redraw()
