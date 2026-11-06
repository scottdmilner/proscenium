"""Removing datablocks in one call where none fails (proscenium.synchronization.removal)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy

from proscenium.binding.runtime import state
from proscenium.synchronization import removal

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    import pytest


def _objects(count: int) -> list[bpy.types.Object]:
    return [bpy.data.objects.new(f"Removed {i}", None) for i in range(count)]


def _counted(monkeypatch: pytest.MonkeyPatch, fail: Callable[[Sequence[bpy.types.ID]], bool]) -> list[int]:
    """Count the calls removal makes, by length; one that fail accepts raises, having removed its first if it can."""
    remove = removal._batch_remove  # noqa: SLF001 - the module's one call into Blender
    calls: list[int] = []

    def counted(datablocks: Sequence[bpy.types.ID]) -> None:
        calls.append(len(datablocks))
        if fail(datablocks):
            remove([d for d in datablocks[:1] if not fail([d])])  # a failed call may have removed some
            raise RuntimeError("injected failure")
        remove(datablocks)

    monkeypatch.setattr(removal, "_batch_remove", counted)
    return calls


def test_datablocks_are_removed_in_one_call(monkeypatch: pytest.MonkeyPatch) -> None:
    objects = _objects(5)
    calls = _counted(monkeypatch, lambda _: False)
    assert removal.remove(objects) == {}
    assert calls == [5]
    assert not any(state.alive(obj) for obj in objects)


def test_a_failure_is_found_one_call_each(monkeypatch: pytest.MonkeyPatch) -> None:
    # The failed call removed the first; the rest are removed one call each, which finds the one that fails, and the
    # removed one is never passed again (Blender crashes on one).
    objects = _objects(4)
    failing = objects[2]
    calls = _counted(monkeypatch, lambda datablocks: failing in datablocks)
    failures = removal.remove(objects)
    assert list(failures) == [2]
    assert calls == [4, 1, 1, 1]
    assert [state.alive(obj) for obj in objects] == [False, False, True, False]
