"""M5's stub application layer: preparing a plan's drawn copies apart from the display (M5 plan, D3 and D4).

Plans come from the core on the transaction scenes; expected values come from how the scene is built
(fixtures/transaction.py). Each preparation is a binding's, and its prepared work holds what it makes; only what
disposal fails to remove enters the ledger.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import bpy
import pytest
from mathutils import Matrix
from pxr import Usd

from fixtures import evaluation, transaction
from fixtures.transaction import EXTENT, ROLES_PER_PLACEHOLDER, translation
from proscenium.binding import runtime
from proscenium.binding.persistence.cleanup_ledgers import OriginatingOperation
from proscenium.binding.persistence.manifests import CopyResourceIdentity, Manifest, RepresentationRole
from proscenium.binding.results import DiagnosticCode
from proscenium.binding.source_access.binding_settings import PayloadPolicy
from proscenium.core import _core
from proscenium.synchronization import application, datablock_removal, preparation_resources
from support.blend import save_and_reopen
from support.usd import open_stage_without_cache

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from pxr import Gf

    from proscenium.api.bindings import Bindings
    from proscenium.binding.persistence.cleanup_ledgers import LedgerEntry
    from proscenium.binding.source_access import BindingId
    from proscenium.synchronization.preparation_resources import PreparationResources

CONTEXT = _core.PlanningContext(unit_scale=1.0, representation_version=1)
SETTINGS = _core.PlanSettings(evaluation.VIEWPORT_PURPOSES, evaluation.RENDER_PURPOSES)  # the defaults


def _plan(stage: Usd.Stage, time_code: float) -> _core.Plan:
    return _core.plan(_core.SceneIndexChain(stage).capture(Usd.TimeCode(time_code)), SETTINGS, CONTEXT)


def _binding(bindings: Bindings) -> BindingId:
    return bindings.create_binding(bpy.data.scenes["Scene"]).binding_id


def _work(binding_id: BindingId) -> PreparationResources:
    return preparation_resources.new_preparation_resources(binding_id, OriginatingOperation.SYNCHRONIZE)


def _prepared(binding_id: BindingId, plan: _core.Plan, published: Manifest | None = None) -> PreparationResources:
    work = _work(binding_id)
    application.prepare(plan, published or Manifest({}), work)
    return work


def _ledger() -> dict[str, LedgerEntry]:
    ledger = runtime.pending_cleanup.ledger()
    return {} if ledger is None else dict(ledger.record.entries)  # ty: ignore[unresolved-attribute] - not refused


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


def _records() -> list[object]:
    """The records on the scene and the collections, as stored."""
    return [{k: v.to_dict() for k, v in id_.items()} for id_ in (*bpy.data.scenes, *bpy.data.collections)]


def test_a_drawn_copy_per_partition_in_no_scene(bindings: Bindings, tmp_path: Path) -> None:
    # TXN-05: an object drawing its bounds, and its bounds mesh, per drawn gprim, linked only in the staging collection.
    with transaction.retirement_failure(tmp_path) as scene:
        work = _prepared(_binding(bindings), _plan(scene.caller, 0.0))
        objects = list(work.staging_collection.objects)
        assert len(objects) == len(transaction.DRAWN[PayloadPolicy.LOAD_ALL])
        assert not any(work.staging_collection in s.collection.children_recursive for s in bpy.data.scenes)
        assert all(obj.users_collection == (work.staging_collection,) for obj in objects)
        low, high = EXTENT
        corners = {(x, y, z) for x in (low[0], high[0]) for y in (low[1], high[1]) for z in (low[2], high[2])}
        for obj in objects:
            source = work.manifest_entries[_key(work, obj)].source_entity_paths[0]
            assert obj.display_type == "BOUNDS"
            assert obj.matrix_world.translation[:] == pytest.approx(translation(source, 0.0))
            assert {v.co[:] for v in obj.data.vertices} == corners  # ty: ignore[unresolved-attribute]


def test_its_entries_are_the_plans_resources(bindings: Bindings, tmp_path: Path) -> None:
    # Each prepared datablock has the entry a publication writes: its role, the source it covers, its place, and the
    # object using its own bounds mesh.
    with transaction.retirement_failure(tmp_path) as scene:
        work = _prepared(_binding(bindings), _plan(scene.caller, 0.0))
        assert len(work.manifest_entries) == transaction.resource_count(PayloadPolicy.LOAD_ALL)
        assert work.datablocks.keys() == work.manifest_entries.keys()
        for key, entry in work.manifest_entries.items():
            assert entry.datablock == work.datablocks[key]
            assert entry.role in ROLES_PER_PLACEHOLDER
            if entry.role is RepresentationRole.OBJECT:
                [used] = entry.dependency_entry_keys
                assert entry.datablock.data == work.datablocks[used]  # ty: ignore[unresolved-attribute]
                bounds_mesh = CopyResourceIdentity(RepresentationRole.BOUNDS_MESH, entry.source_entity_paths[0], 0)
                assert work.manifest_entries[used].identity == bounds_mesh
            assert entry.identity == CopyResourceIdentity(entry.role, entry.source_entity_paths[0], 0)
        Manifest(work.manifest_entries)  # a whole manifest


def test_world_transforms_cross_in_blenders_layout(bindings: Bindings, tmp_path: Path) -> None:
    # The plan's copy_world_matrices holds Blender's layout, so foreach_set writes it directly, and the stub's objects
    # get the same. Expected values are UsdGeom's, transposed, on F-TRANSFORMS' rotated, scaled, mirrored, and sheared
    # copies. Blender's objects hold no shear, so foreach_set loses it, and the stub's sheared copy shows it through its
    # unselectable shear parent, as Blender composes them from what each stores.
    with evaluation.transforms(tmp_path) as scene:
        plan = _plan(scene.stage, 0.0)
        expected = {
            p: Matrix([[w[r, c] for c in range(4)] for r in range(4)]).transposed()
            for p, w in scene.world_matrices_by_source.items()
        }
        sources = [c.source_path for c in plan.correspondence]
        made = [bpy.data.objects.new(f"copy-{copy:04}", None) for copy in range(plan.copy_count)]
        assert list(bpy.data.objects) == made  # in copy order, so foreach_set's buffer lines up
        bpy.data.objects.foreach_set("matrix_world", plan.copy_world_matrices)
        work = _prepared(_binding(bindings), plan)
        prepared = {
            work.manifest_entries[key].source_entity_paths[0]: obj
            for obj in work.staging_collection.objects
            if work.manifest_entries[key := _key(work, obj)].role == RepresentationRole.OBJECT
        }
        for source, obj in zip(sources, made, strict=True):
            shown = prepared[source]
            if source not in scene.sheared_paths:
                assert _close(obj.matrix_world, expected[source]), source
                assert (shown.parent, _close(shown.matrix_world, expected[source])) == (None, True), source
                continue
            parent = shown.parent
            assert parent is not None and parent.hide_select, source
            assert shown.matrix_parent_inverse == Matrix.Identity(4), source
            assert _close(parent.matrix_world @ shown.matrix_basis, expected[source]), source


def test_each_copy_is_hidden_where_it_does_not_display(bindings: Bindings, tmp_path: Path) -> None:
    # The plan's participation as Blender's hide flags, on F-VISIBILITY-PURPOSE: an invisible copy hidden in both.
    with evaluation.visibility_purpose(tmp_path) as scene:
        plan = _plan(scene.stage, 0.0)
        work = _prepared(_binding(bindings), plan)
        hidden = {
            work.manifest_entries[_key(work, obj)].source_entity_paths[0]: (obj.hide_viewport, obj.hide_render)
            for obj in work.staging_collection.objects
        }
        assert hidden == {
            path: (
                not scene.displays(path, 0.0, evaluation.VIEWPORT_PURPOSES),
                not scene.displays(path, 0.0, evaluation.RENDER_PURPOSES),
            )
            for path, purpose in scene.purpose.items()
            if purpose != "guide"  # never explicitly visible, so not planned
        }
        assert hidden["/World/Hidden/Child"] == (True, True)


def test_each_provisional_mesh_copy_draws_its_extent(bindings: Bindings, tmp_path: Path) -> None:
    # On F-UNITS-UP-AXIS' Z-up stage in meters: each mesh's copy, the one inside a native instance included, is an
    # object at its world transform drawing the mesh's authored extent, its provisional geometry description's.
    with evaluation.units_up_axis(tmp_path) as scene:
        work = _prepared(_binding(bindings), _plan(scene.stages["z-up-m"], 0.0))
        shown = _shown(work)
        assert shown.keys() == scene.world_matrices_by_source.keys()
        for path, world in scene.world_matrices_by_source.items():
            assert _close(shown[path].matrix_world, _blender(world)), path
            assert _vertices(shown[path]) == pytest.approx(_box(scene.bounds)), path


def test_an_empty_marker_is_an_object_holding_no_data(bindings: Bindings, tmp_path: Path) -> None:
    # MODEL-05 on F-UNSUPPORTED-CONTENT: the volume without usable bounds; every placeholder with bounds draws its box,
    # the authored extent or USD's computed one, at its world transform.
    with evaluation.unsupported_content(tmp_path) as scene:
        work = _prepared(_binding(bindings), _plan(scene.stage, 0.0))
        shown = _shown(work)
        for path, expected in scene.placeholders.items():
            assert _close(shown[path].matrix_world, _blender(expected.world_matrix)), path
            if expected.local_bounds is None:
                assert shown[path].data is None, path
            else:
                assert _vertices(shown[path]) == pytest.approx(_box(expected.local_bounds), rel=1e-6), path


def test_objects_are_named_to_land_at_the_end_of_the_object_list(bindings: Bindings, tmp_path: Path) -> None:
    # DECISIONS.md "Managed object names": a tilde, the generation, and the object's ordinal in the plan's order, then
    # its prim's name, so each new object sorts after every existing one, the display it replaces' included; its bounds
    # mesh shares its name. A sheared copy's shear parent takes the next ordinal after its object. On F-TRANSFORMS,
    # beside a user's objects.
    with evaluation.transforms(tmp_path) as scene:
        plan = _plan(scene.stage, 0.0)
        for name in ("Chair", "zebra", "~zzz user"):  # the last sorts after every managed name
            bpy.data.objects.new(name, None)
        binding_id = _binding(bindings)
        first, second = _prepared(binding_id, plan), _prepared(binding_id, plan)
        for generation, work in enumerate((first, second)):
            made = [d for d in work.datablocks.values() if isinstance(d, bpy.types.Object)]
            names = sorted(o.name for o in made)
            expected_count = sum(1 for r in plan.resources if r.role in ("object", "shear parent"))
            assert len(names) == expected_count
            assert names == [
                f"~{generation:06d}.{ordinal:07d} {name.split(' ', 1)[1]}" for ordinal, name in enumerate(names)
            ]
        # In the plan's order: each object's prim, then a shear parent's after its object.
        resources = plan.resources
        prims = [
            r.source_entity_path.rsplit("/", 1)[-1] + (" shear" if r.role == "shear parent" else "")
            for r in resources
            if r.role in ("object", "shear parent")
        ]
        assert [n.split(" ", 1)[1] for n in sorted(o.name for o in first.staging_collection.objects)] == prims
        # The managed objects follow the user's, but for the one named to sort after them, the second generation's after
        # the first's.
        managed = [o.name for o in (*first.staging_collection.objects, *second.staging_collection.objects)]
        assert [o.name for o in bpy.data.objects] == ["Chair", "zebra", *sorted(managed), "~zzz user"]
        assert max(o.name for o in first.staging_collection.objects) < min(
            o.name for o in second.staging_collection.objects
        )
        for obj in (*first.staging_collection.objects, *second.staging_collection.objects):
            assert obj.data is None or obj.data.name == obj.name, obj.name


def _close(shown: Matrix, expected: Matrix) -> bool:
    return all(abs(shown[r][c] - expected[r][c]) <= 1e-5 for r in range(4) for c in range(4))


def test_each_prepared_resource_is_held(bindings: Bindings, tmp_path: Path) -> None:
    # TXN-08: the prepared work holds each with its entry key and role, and preparing writes no record, the ledger's
    # included (STATE-04).
    with transaction.preparation_cleanup_failure(tmp_path) as scene:
        binding_id = _binding(bindings)
        before = _records()
        work = _prepared(binding_id, _plan(scene.caller, 0.0))
        assert {(key, work.roles[key], d) for key, d in work.datablocks.items()} == {
            (key, entry.role, entry.datablock) for key, entry in work.manifest_entries.items()
        }
        assert _ledger() == {}
        bpy.data.batch_remove([work.staging_collection])  # which holds no records
        assert _records() == before


# Preparation's fallible steps after a resource is made, by the function each runs: its call-th call fails.
_STEPS = [("_corners", call) for call in range(1, 5)] + [("_matrix_from_buffer", call) for call in range(1, 5)]


@pytest.mark.parametrize(("step", "call"), _STEPS)
def test_a_failure_after_a_resource_is_made_finds_it_held(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, step: str, call: int
) -> None:
    # TXN-08 on F-PREPARATION-CLEANUP-FAILURE: every resource made before the failure is held, and disposing of the
    # work leaves the file as before, writing no ledger entry.
    with transaction.preparation_cleanup_failure(tmp_path) as scene:
        binding_id = _binding(bindings)
        plan = _plan(scene.caller, 0.0)
        _fail_on_call(monkeypatch, step, call)
        before = _datablocks()
        work = _work(binding_id)
        with pytest.raises(RuntimeError, match="injected"):
            application.prepare(plan, Manifest({}), work)
        made = _datablocks() - before - {work.staging_collection}
        assert made == set(work.datablocks.values())
        assert len(made) == 2 * call - (step == "_corners")  # a placeholder's mesh is made before its corners
        assert preparation_resources.dispose(work) == ()
        assert _datablocks() == before
        assert _ledger() == {}


def test_a_replacement_takes_the_published_keys_and_changes_nothing_published(
    bindings: Bindings, tmp_path: Path
) -> None:
    # ROLE-05: prepared resources with the published ones' identities take their keys. TXN-05: preparing them
    # changes nothing the published generation reaches. TXN-09: none of the published resources is held.
    with transaction.retirement_failure(tmp_path) as scene:
        binding_id = _binding(bindings)
        first, second = scene.time_codes
        published = _prepared(binding_id, _plan(scene.caller, first))
        objects = _publish(published)
        before = _values(objects)
        replacement = _prepared(binding_id, _plan(scene.caller, second), Manifest(published.manifest_entries))
        assert replacement.manifest_entries.keys() == published.manifest_entries.keys()
        assert set(replacement.datablocks.values()).isdisjoint(published.datablocks.values())
        assert _values(objects) == before
        assert _ledger() == {}
        mover = next(o for o in replacement.staging_collection.objects if "Mover" in o.name)
        assert mover.matrix_world.translation[:] == pytest.approx(translation("/World/Mover", second))


def test_only_the_same_identity_takes_a_published_key(bindings: Bindings, tmp_path: Path) -> None:
    # Planned without the payloaded gprim, the others take their published keys, and its entries' go unused.
    with transaction.retirement_failure(tmp_path) as scene:
        binding_id = _binding(bindings)
        published = _prepared(binding_id, _plan(scene.caller, 0.0))
        unloaded = _plan(
            open_stage_without_cache(scene.root_layer_path, PayloadPolicy.LOAD_NONE.load_set), 0.0
        )  # without /World/Payloaded
        drawn = transaction.DRAWN[PayloadPolicy.LOAD_NONE]
        kept = {key for key, entry in published.manifest_entries.items() if entry.source_entity_paths[0] in drawn}
        replacement = _prepared(binding_id, unloaded, Manifest(published.manifest_entries))
        assert replacement.manifest_entries.keys() == kept


def test_dispose_removes_what_was_prepared_and_writes_no_ledger_entry(bindings: Bindings, tmp_path: Path) -> None:
    with transaction.retirement_failure(tmp_path) as scene:
        binding_id = _binding(bindings)
        before = _datablocks()
        work = _prepared(binding_id, _plan(scene.caller, 0.0))
        assert preparation_resources.dispose(work) == ()
        assert _datablocks() == before
        assert (work.datablocks, work.roles, work.manifest_entries) == ({}, {}, {})
        assert _ledger() == {}


def test_a_failed_disposal_leaves_tracked_inactive_leftovers(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # F-PREPARATION-CLEANUP-FAILURE: preparation fails once four resources are made, and disposal fails for an object
    # and a bounds mesh. They stay, linked in no collection, each retryable in the ledger with a cleanup diagnostic
    # naming its ledger key; the rest are removed, with no entry.
    with transaction.preparation_cleanup_failure(tmp_path) as scene:
        binding_id = _binding(bindings)
        plan = _plan(scene.caller, 0.0)
        _fail_on_call(monkeypatch, "_matrix_from_buffer", 2)
        before = _datablocks()
        work = _work(binding_id)
        with pytest.raises(RuntimeError, match="injected"):
            application.prepare(plan, Manifest({}), work)
        assert len(work.datablocks) == scene.prepared_before_failure
        failing = _fail_disposal(monkeypatch, work, scene.failed_disposals)
        diagnostics = preparation_resources.dispose(work)
        assert _datablocks() - before == failing
        assert all(not d.users_collection for d in failing if isinstance(d, bpy.types.Object))
        ledger = _ledger()
        assert {e.datablock for e in ledger.values()} == failing
        assert {e.diagnostic for e in ledger.values()} == set(diagnostics)
        assert {(d.code, d.binding_id, d.pending_resource_key, d.role) for d in diagnostics} == {
            (DiagnosticCode.DISPOSAL_FAILED, binding_id, ledger_key, entry.role) for ledger_key, entry in ledger.items()
        }


def test_a_leftover_survives_save_and_reopen_through_its_pointer(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The ledger's pointer is the leftover's only user, so it's saved, and found again after reopening.
    with transaction.preparation_cleanup_failure(tmp_path) as scene:
        work = _prepared(_binding(bindings), _plan(scene.caller, 0.0))
        [leftover] = _fail_disposal(monkeypatch, work, (RepresentationRole.BOUNDS_MESH,))
        name = leftover.name
        [diagnostic] = preparation_resources.dispose(work)
        save_and_reopen(tmp_path / "leftover.blend")
        [(ledger_key, entry)] = _ledger().items()
        assert entry.datablock == bpy.data.meshes[name]
        assert (ledger_key, entry.diagnostic) == (diagnostic.pending_resource_key, diagnostic)


def _publish(work: PreparationResources) -> list[bpy.types.Object]:
    """Link work's objects into a destination, as a publication does; the objects."""
    destination = bpy.data.collections.new("Shot")
    bpy.data.scenes["Scene"].collection.children.link(destination)
    objects = list(work.staging_collection.objects)
    for obj in objects:
        destination.objects.link(obj)
        work.staging_collection.objects.unlink(obj)
    return objects


def _fail_disposal(
    monkeypatch: pytest.MonkeyPatch, work: PreparationResources, roles: tuple[str, ...]
) -> set[bpy.types.ID]:
    """Make disposal fail for the first held datablock of each role; those datablocks."""
    failing = {next(d for key, d in work.datablocks.items() if work.roles[key] == role) for role in roles}
    remove = datablock_removal._batch_remove  # noqa: SLF001

    def failing_remove(datablocks: Sequence[bpy.types.ID]) -> None:
        if any(d in failing for d in datablocks):  # a call removing one fails, the batch's included
            raise RuntimeError("disposal injected")
        remove(datablocks)

    monkeypatch.setattr(datablock_removal, "_batch_remove", failing_remove)
    return {d for d in failing if d is not None}


def _fail_on_call(monkeypatch: pytest.MonkeyPatch, step: str, call: int) -> None:
    """Make application's function step raise on its call-th call."""
    original = getattr(application, step)
    calls = []

    def failing(*args: object) -> object:
        calls.append(args)
        if len(calls) == call:
            raise RuntimeError("injected")
        return original(*args)

    monkeypatch.setattr(application, step, failing)


def _key(work: PreparationResources, datablock: bpy.types.ID) -> str:
    [key] = [k for k, d in work.datablocks.items() if d == datablock]
    return key


def _shown(work: PreparationResources) -> dict[str, bpy.types.Object]:
    """The prepared copies' objects, by the source each shows."""
    return {
        work.manifest_entries[key].source_entity_paths[0]: obj
        for obj in work.staging_collection.objects
        if work.manifest_entries[key := _key(work, obj)].role == RepresentationRole.OBJECT
    }


def _blender(matrix: Gf.Matrix4d) -> Matrix:
    """USD's row-vector matrix as Blender's column-vector one."""
    return Matrix([[matrix[r, c] for c in range(4)] for r in range(4)]).transposed()


def _box(bounds: evaluation.Bounds) -> list[float]:
    """The eight corners of (min, max), sorted, flattened for pytest.approx."""
    low, high = (cast("Sequence[float]", corner) for corner in bounds)
    corners = sorted((x, y, z) for x in (low[0], high[0]) for y in (low[1], high[1]) for z in (low[2], high[2]))
    return [value for corner in corners for value in corner]


def _vertices(obj: bpy.types.Object) -> list[float]:
    """The vertices of obj's bounds mesh, sorted, flattened as _box's."""
    mesh = obj.data
    assert isinstance(mesh, bpy.types.Mesh)
    return [value for vertex in sorted(v.co[:] for v in mesh.vertices) for value in vertex]
