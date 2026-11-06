"""Removing managed datablocks nothing else uses, users first, in one call per level where none fails.

See proscenium.synchronization.removal.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy

from proscenium.binding.persistence import records
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
    assert not any(records.alive(obj) for obj in objects)


def test_a_failure_is_found_one_call_each(monkeypatch: pytest.MonkeyPatch) -> None:
    # The failed call removed the first; the rest are removed one call each, which finds the one that fails, and the
    # removed one is never passed again (Blender crashes on one).
    objects = _objects(4)
    failing = objects[2]
    calls = _counted(monkeypatch, lambda datablocks: failing in datablocks)
    failures = removal.remove(objects)
    assert list(failures) == [2]
    assert calls == [4, 1, 1, 1]
    assert [records.alive(obj) for obj in objects] == [False, False, True, False]


def _placeholder(name: str) -> tuple[bpy.types.Object, bpy.types.Mesh]:
    mesh = bpy.data.meshes.new(name)
    return bpy.data.objects.new(name, mesh), mesh


def test_users_are_removed_first_a_level_per_call(monkeypatch: pytest.MonkeyPatch) -> None:
    first, first_mesh = _placeholder("First")
    second, second_mesh = _placeholder("Second")
    calls = _counted(monkeypatch, lambda _: False)
    outcome = removal.remove_unused({"a": first_mesh, "b": first, "c": second_mesh, "d": second})
    assert outcome == removal.RemovalOutcome(removed={"a", "b", "c", "d"})
    assert calls == [2, 2]  # the objects, then the meshes they used


def test_what_something_else_uses_is_released_intact(monkeypatch: pytest.MonkeyPatch) -> None:
    # The mesh's key sorts before its object's, so it's decided after the object is released, in a later pass.
    obj, mesh = _placeholder("Kept")
    bpy.data.scenes["Scene"].collection.objects.link(obj)  # an unmanaged user
    calls = _counted(monkeypatch, lambda _: False)
    outcome = removal.remove_unused({"a": mesh, "b": obj})
    assert outcome == removal.RemovalOutcome(released={"a", "b"})
    assert calls == []
    assert obj.data == mesh


def test_a_holder_doesnt_keep_one_from_removal() -> None:
    obj, mesh = _placeholder("Staged")
    staging = bpy.data.collections.new("Staging")
    staging.objects.link(obj)
    outcome = removal.remove_unused({"object": obj, "mesh": mesh}, holders=[staging])
    assert outcome == removal.RemovalOutcome(removed={"object", "mesh"})


def test_a_failure_leaves_it_and_what_it_uses_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    obj, mesh = _placeholder("Failing")
    _counted(monkeypatch, lambda datablocks: obj in datablocks)
    outcome = removal.remove_unused({"object": obj, "mesh": mesh})
    assert outcome.removed == outcome.released == set()
    assert outcome.pending == {"object": "injected failure", "mesh": "a resource using it couldn't be removed"}
    assert records.alive(obj) and records.alive(mesh)


def test_one_already_gone_counts_as_removed() -> None:
    obj, mesh = _placeholder("Gone")
    bpy.data.objects.remove(obj)
    assert removal.remove_unused({"object": obj, "none": None, "mesh": mesh}) == removal.RemovalOutcome(
        removed={"object", "none", "mesh"}
    )
