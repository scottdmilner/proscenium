"""M5's stub application layer: preparing a plan's placeholders apart from the display (M5 plan, D3).

Plans come from the core on F-RETIREMENT-FAILURE's scene, which is synchronized at 0 and then 10; expected values come
from how the scene is built (fixtures/transaction.py).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy
import pytest
from pxr import Usd

from fixtures import transaction
from fixtures.transaction import EXTENT, ROLES_PER_PLACEHOLDER, translation
from proscenium.binding.persistence import CopyResourceIdentity, Manifest, RepresentationRole
from proscenium.binding.source_access import PayloadPolicy
from proscenium.core import _core
from proscenium.synchronization import application
from support.usd import open_fresh

if TYPE_CHECKING:
    from pathlib import Path

    from proscenium.synchronization.application import PreparedWork

CONTEXT = _core.PlanningContext(unit_scale=1.0, representation_version=1)


def _plan(stage: Usd.Stage, time_code: float) -> _core.Plan:
    return _core.plan(_core.SceneIndexChain(stage).capture(Usd.TimeCode(time_code)), CONTEXT)


def _prepared(plan: _core.Plan, published: Manifest | None = None) -> PreparedWork:
    prepared = application.new_prepared_work()
    application.prepare(plan, published or Manifest({}), prepared)
    return prepared


def _datablocks() -> set[bpy.types.ID]:
    return {*bpy.data.objects, *bpy.data.meshes, *bpy.data.collections}


def _values(objects: list[bpy.types.Object]) -> list[object]:
    """What a published object shows: its placement, its mesh's vertices, and its collections."""
    return [
        (
            obj.name,
            [row[:] for row in obj.matrix_world],
            [v.co[:] for v in obj.data.vertices],  # ty: ignore[unresolved-attribute] - a mesh object's
            sorted(c.name for c in obj.users_collection),
        )
        for obj in objects
    ]


def test_a_placeholder_per_partition_in_no_scene(tmp_path: Path) -> None:
    # TXN-05: an object drawing its bounds, and its bounds mesh, per drawn gprim, linked only in the staging collection.
    with transaction.retirement_failure(tmp_path) as scene:
        prepared = _prepared(_plan(scene.caller, 0.0))
        objects = list(prepared.staging.objects)
        assert len(objects) == len(transaction.DRAWN[PayloadPolicy.LOAD_ALL])
        assert not any(prepared.staging in s.collection.children_recursive for s in bpy.data.scenes)
        assert all(obj.users_collection == (prepared.staging,) for obj in objects)
        low, high = EXTENT
        corners = {(x, y, z) for x in (low[0], high[0]) for y in (low[1], high[1]) for z in (low[2], high[2])}
        for obj in objects:
            source = prepared.entries[_key(prepared, obj)].covers[0]
            assert obj.display_type == "BOUNDS"
            assert obj.matrix_world.translation[:] == pytest.approx(translation(source, 0.0))
            assert {v.co[:] for v in obj.data.vertices} == corners  # ty: ignore[unresolved-attribute]


def test_its_entries_are_the_plans_resources(tmp_path: Path) -> None:
    # Each prepared datablock has the entry a publication writes: its role, the source it covers, its place, and the
    # object using its own bounds mesh.
    with transaction.retirement_failure(tmp_path) as scene:
        prepared = _prepared(_plan(scene.caller, 0.0))
        assert len(prepared.entries) == transaction.resource_count(PayloadPolicy.LOAD_ALL)
        assert prepared.datablocks.keys() == prepared.entries.keys()
        for key, entry in prepared.entries.items():
            assert entry.datablock == prepared.datablocks[key]
            assert entry.role in ROLES_PER_PLACEHOLDER
            if entry.role is RepresentationRole.OBJECT:
                [used] = entry.uses
                assert entry.datablock.data == prepared.datablocks[used]  # ty: ignore[unresolved-attribute]
                bounds_mesh = CopyResourceIdentity(RepresentationRole.BOUNDS_MESH, entry.covers[0], 0)
                assert prepared.entries[used].identity == bounds_mesh
            assert entry.identity == CopyResourceIdentity(entry.role, entry.covers[0], 0)
        Manifest(prepared.entries)  # a whole manifest


def test_a_replacement_takes_the_published_keys_and_changes_nothing_published(tmp_path: Path) -> None:
    # ROLE-05: prepared resources with the published ones' identities take their keys. TXN-05: preparing them
    # changes nothing the published generation reaches.
    with transaction.retirement_failure(tmp_path) as scene:
        first, second = scene.time_codes
        published = _prepared(_plan(scene.caller, first))
        destination = bpy.data.collections.new("Shot")
        bpy.data.scenes["Scene"].collection.children.link(destination)
        objects = list(published.staging.objects)
        for obj in objects:  # what a publication links
            destination.objects.link(obj)
            published.staging.objects.unlink(obj)
        before = _values(objects)
        replacement = _prepared(_plan(scene.caller, second), Manifest(published.entries))
        assert replacement.entries.keys() == published.entries.keys()
        assert set(replacement.datablocks.values()).isdisjoint(published.datablocks.values())
        assert _values(objects) == before
        mover = next(o for o in replacement.staging.objects if "Mover" in o.name)
        assert mover.matrix_world.translation[:] == pytest.approx(translation("/World/Mover", second))


def test_only_the_same_identity_takes_a_published_key(tmp_path: Path) -> None:
    # Planned without the payloaded gprim, the others take their published keys, and its entries' go unused.
    with transaction.retirement_failure(tmp_path) as scene:
        published = _prepared(_plan(scene.caller, 0.0))
        unloaded = _plan(open_fresh(scene.root, PayloadPolicy.LOAD_NONE.load_set), 0.0)  # without /World/Payloaded
        drawn = transaction.DRAWN[PayloadPolicy.LOAD_NONE]
        kept = {key for key, entry in published.entries.items() if entry.covers[0] in drawn}
        replacement = _prepared(unloaded, Manifest(published.entries))
        assert replacement.entries.keys() == kept


def test_dispose_removes_what_was_prepared(tmp_path: Path) -> None:
    with transaction.retirement_failure(tmp_path) as scene:
        before = _datablocks()
        prepared = _prepared(_plan(scene.caller, 0.0))
        application.dispose(prepared)
        assert _datablocks() == before
        assert (prepared.datablocks, prepared.entries) == ({}, {})


def test_a_failure_partway_leaves_what_was_made_to_dispose_of(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A failure on the second placeholder's placement: the first placeholder and the second's mesh and object remain
    # in the prepared work, and disposing of it leaves the file as before.
    with transaction.retirement_failure(tmp_path) as scene:
        plan = _plan(scene.caller, 0.0)
        world = application._world  # noqa: SLF001
        calls = []

        def failing(matrix: object) -> object:
            calls.append(matrix)
            if len(calls) == 2:
                raise RuntimeError("injected")
            return world(matrix)  # ty: ignore[invalid-argument-type]

        monkeypatch.setattr(application, "_world", failing)
        before = _datablocks()
        prepared = application.new_prepared_work()
        with pytest.raises(RuntimeError, match="injected"):
            application.prepare(plan, Manifest({}), prepared)
        assert len(prepared.datablocks) == 4
        assert len(prepared.entries) == 2  # the first placeholder's; the second's entries come once it's placed
        application.dispose(prepared)
        assert _datablocks() == before


def _key(prepared: PreparedWork, datablock: bpy.types.ID) -> str:
    [key] = [k for k, d in prepared.datablocks.items() if d == datablock]
    return key
