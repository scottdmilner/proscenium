"""Incremental refresh: a synchronization replaces only the partitions whose plan changed (M7 plan, C6).

Against the plan of the generation the destination shows, held since this session published it: on F-NO-OP-REFRESH, a
refresh with nothing changed writes nothing, and so does one after an undo or redo restores a held generation (AFF-03);
after reopening, or an undo past the held plans, a refresh rebuilds every partition, as a clean one does (AFF-04). On
F-EDIT-SEQUENCE, each step's refresh displays what a clean binding's first synchronization of the same stage does
(TINC-01), the copies the step doesn't touch or updates in place keep their objects, and a box whose bounds changed
keeps its object, pointed at a new mesh of a later generation. A sheared copy moves in place, and a publication failing
after local updates leaves every kept copy as it was. What a refresh writes is observed through the depsgraph, the
record writes, and the IDs made (support/blender_writes.py).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import bpy
import pytest
from pxr import Gf, UsdGeom

from fixtures import edit_sequence, incremental
from proscenium.api import bindings as api
from proscenium.binding.persistence import id_property_records, manifests
from proscenium.binding.persistence.manifests import RepresentationRole
from proscenium.binding.results import DiagnosticCode, ResultState
from proscenium.binding.runtime import ownership
from proscenium.synchronization import transaction
from support import undo
from support.blend import save_and_reopen
from support.blender_writes import observed_writes
from support.displayed_copies import displayed_copies

if TYPE_CHECKING:
    from pathlib import Path

    from pxr import Usd

    from proscenium.api.bindings import BindingHandle, Bindings
    from support.bounds_check import DisplayedCopy

_GENERATION = re.compile(r"~(\d{6})\.")  # a managed object name's generation (DECISIONS.md "Managed object names")


def _binding(bindings: Bindings, stage: Usd.Stage, name: str = "Shot") -> BindingHandle:
    handle = bindings.create_binding(bpy.data.scenes["Scene"], name=name)
    assert handle.attach(stage).state is not ResultState.FATAL_FAILURE
    return handle


def _synchronize(handle: BindingHandle) -> None:
    assert handle.synchronize(0).state is not ResultState.FATAL_FAILURE


def _shown(handle: BindingHandle) -> list[DisplayedCopy]:
    return sorted(displayed_copies(handle.binding_id), key=lambda copy: (copy.source_path, copy.world_vertices))


def _clean(bindings: Bindings, stage: Usd.Stage) -> list[DisplayedCopy]:
    """What a clean binding's first synchronization of stage displays; the binding is released after."""
    clean = _binding(bindings, stage, "Clean")
    _synchronize(clean)
    shown = _shown(clean)
    bindings.release(clean.binding_id)
    return shown


def _objects_by_source(handle: BindingHandle) -> dict[str, bpy.types.ID]:
    """Each copy's object, by its source path, from the manifest."""
    manifest = ownership.manifest(handle.binding_id)
    assert isinstance(manifest, id_property_records.LoadedRecord)
    return {
        identity.entity: e.datablock
        for e in manifest.record.entries.values()
        if (identity := e.identity) is not None and identity.role is RepresentationRole.OBJECT and e.datablock
    }


def _generations(handle: BindingHandle) -> set[str]:
    """The generations in the names of the binding's objects."""
    return {m.group(1) for obj in _objects_by_source(handle).values() if (m := _GENERATION.match(obj.name))}


@pytest.fixture
def pushing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Push undo steps as Blender with global undo on, outside background mode, would."""
    undo.require_global_undo()
    monkeypatch.setattr(api, "_undo_steps_enabled", lambda: True)


def test_an_unchanged_refresh_writes_nothing(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # AFF-03 on F-NO-OP-REFRESH "unchanged": no record, no ID made, nothing the depsgraph sees, and every object kept.
    with incremental.no_op_refresh(tmp_path) as scene:
        handle = _binding(bindings, scene.stage)
        _synchronize(handle)
        before = {source: obj.session_uid for source, obj in _objects_by_source(handle).items()}
        with observed_writes(monkeypatch) as observed:
            _synchronize(handle)
        assert observed.wrote_nothing, observed
        assert {source: obj.session_uid for source, obj in _objects_by_source(handle).items()} == before


def test_a_full_rebuild_is_seen_writing(bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The observation the zero-write tests rely on sees each of its three kinds of write in a full rebuild.
    with incremental.no_op_refresh(tmp_path) as scene:
        handle = _binding(bindings, scene.stage)
        _synchronize(handle)
        with observed_writes(monkeypatch) as observed:
            assert handle.synchronize(0, full_rebuild=True).state is not ResultState.FATAL_FAILURE
        assert observed.updated_ids and observed.record_writes and observed.created_id_count > 0


def test_a_refresh_after_an_undo_or_redo_writes_nothing(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pushing: None
) -> None:
    # AFF-03, CHG-30, UNDO-10 on F-NO-OP-REFRESH "after-undo": the render's purposes without render take RenderOnly
    # out of the second generation; an undo restores the first, whose plan is held, and a refresh of it writes nothing
    # and pushes no undo step, so a redo restores the second, whose refresh writes nothing either.
    with incremental.no_op_refresh(tmp_path) as scene:
        handle = _binding(bindings, scene.stage)
        undo.push("base")
        _synchronize(handle)
        first = _shown(handle)
        assert handle.set_settings(render_purposes=["default"]).state is ResultState.SUCCESS
        _synchronize(handle)
        second = _shown(handle)
        assert second != first
        for restore, shown in ((undo.undo, first), (undo.redo, second)):
            restore()
            with observed_writes(monkeypatch) as observed:
                _synchronize(handle)
            assert observed.wrote_nothing, (restore.__name__, observed)
            assert _shown(handle) == shown


def test_a_refresh_after_reopening_rebuilds_everything(bindings: Bindings, tmp_path: Path) -> None:
    # AFF-04, CHG-31 on F-NO-OP-REFRESH "after-reopen": no plan is held, so every object is of a new generation, and
    # the display is a clean binding's.
    with incremental.no_op_refresh(tmp_path) as scene:
        handle = _binding(bindings, scene.stage)
        _synchronize(handle)
        published = _generations(handle)
        save_and_reopen(tmp_path / "reopened.blend")
        [handle] = bindings.in_scene(bpy.data.scenes["Scene"])
        assert handle.attach(scene.stage).state is not ResultState.FATAL_FAILURE
        _synchronize(handle)
        assert len(_generations(handle)) == 1 and _generations(handle).isdisjoint(published)
        assert _shown(handle) == _clean(bindings, scene.stage)


def test_a_refresh_past_the_held_plans_rebuilds_everything(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pushing: None
) -> None:
    # AFF-04 on F-NO-OP-REFRESH: holding one plan, an undo restores a generation whose plan isn't held, so the
    # refresh rebuilds every partition, as a clean binding's first synchronization does.
    monkeypatch.setattr(transaction, "_held_plan_bound", lambda: 1)
    with incremental.no_op_refresh(tmp_path) as scene:
        handle = _binding(bindings, scene.stage)
        undo.push("base")
        _synchronize(handle)
        assert handle.set_settings(render_purposes=["default"]).state is ResultState.SUCCESS
        _synchronize(handle)
        undo.undo()
        shown = _generations(handle)
        _synchronize(handle)
        assert len(_generations(handle)) == 1 and _generations(handle).isdisjoint(shown)
        assert _shown(handle) == _clean(bindings, scene.stage)


def test_each_step_replaces_only_what_it_changes(bindings: Bindings, tmp_path: Path) -> None:
    # TINC-01, DISC-01, AFF-01, CHG-08 on F-EDIT-SEQUENCE: after each step's refresh, the display is a clean
    # binding's, and each copy the step neither rebuilds, retires, nor builds keeps its object, the updated ones
    # included; a box whose bounds changed has a new mesh named for its prim in a later generation than its object's,
    # the old one retired.
    with edit_sequence.edit_sequence(tmp_path) as scene:
        handle = _binding(bindings, scene.stage)
        _synchronize(handle)
        for step in scene.steps:
            before = _objects_by_source(handle)
            before_uids = {source: obj.session_uid for source, obj in before.items()}
            meshes = {source: obj.data for source, obj in before.items() if isinstance(obj, bpy.types.Object)}
            step.edit(scene.stage)
            _synchronize(handle)
            assert _shown(handle) == _clean(bindings, scene.stage), step.name
            replaced = {source for source, _ in step.rebuilt | step.retired | step.built}
            after = _objects_by_source(handle)
            after_uids = {source: obj.session_uid for source, obj in after.items()}
            kept = (before_uids.keys() & after_uids.keys()) - replaced
            assert {s: after_uids[s] for s in kept} == {s: before_uids[s] for s in kept}, step.name
            if step.name == "bounds-changed":
                [(odd, _)] = step.updated
                obj, old = after[odd], meshes[odd]
                assert isinstance(obj, bpy.types.Object) and obj.data is not None
                assert obj.data != old
                generation, mesh_generation = (_GENERATION.match(n) for n in (obj.name, obj.data.name))
                assert generation and mesh_generation and mesh_generation.group(1) > generation.group(1)
                assert obj.data.name.endswith(" Odd")
                assert old is not None and not id_property_records.alive(old)


def test_a_sheared_copy_moves_in_place(bindings: Bindings, tmp_path: Path) -> None:
    # CHG-14: A, sheared by the fixture's step, then translated, keeps its object and shear parent, and the display
    # is a clean binding's.
    with edit_sequence.edit_sequence(tmp_path) as scene:
        shear = next(step for step in scene.steps if step.name == "shear-introduced")
        shear.edit(scene.stage)
        handle = _binding(bindings, scene.stage)
        _synchronize(handle)
        obj = _objects_by_source(handle)[edit_sequence.A]
        assert isinstance(obj, bpy.types.Object) and obj.parent is not None
        parent = obj.parent
        scene.stage.GetAttributeAtPath(f"{edit_sequence.A}.xformOp:translate").Set(Gf.Vec3d(0, 0, 3))
        _synchronize(handle)
        assert _objects_by_source(handle)[edit_sequence.A] == obj and obj.parent == parent
        assert _shown(handle) == _clean(bindings, scene.stage)


def _state(obj: bpy.types.Object) -> tuple[object, ...]:
    """What a local update sets on a kept object: its transform's components, hide flags, and data."""
    return (obj.location[:], obj.rotation_euler[:], obj.scale[:], obj.hide_viewport, obj.hide_render, obj.data)


def test_a_failed_publication_undoes_its_local_updates(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # CHG-05 on F-EDIT-SEQUENCE: Odd moved, its bounds grown, and made invisible, then the manifest's write failing:
    # Odd's object has its transform, hide flags, and mesh as before, the replacement mesh is disposed of, and the
    # published records are as they were.
    with edit_sequence.edit_sequence(tmp_path) as scene:
        handle = _binding(bindings, scene.stage)
        _synchronize(handle)
        obj = _objects_by_source(handle)[edit_sequence.ODD]
        assert isinstance(obj, bpy.types.Object)
        before, meshes = _state(obj), set(bpy.data.meshes)
        manifest = ownership.manifest(handle.binding_id)
        odd = scene.stage.GetPrimAtPath(edit_sequence.ODD)
        scene.stage.GetAttributeAtPath(f"{edit_sequence.ODD}.xformOp:translate").Set(Gf.Vec3d(7, 0, 0))
        UsdGeom.Boundable(odd).GetExtentAttr().Set([Gf.Vec3f(0, 0, 0), Gf.Vec3f(2, 2, 2)])
        UsdGeom.Imageable(odd).MakeInvisible()

        def failing(*_args: object) -> None:
            raise RuntimeError("injected manifest failure")

        monkeypatch.setattr(manifests, "write_manifest_entries", failing)
        result = handle.synchronize(0)
        assert result.state is ResultState.FATAL_FAILURE
        assert DiagnosticCode.PUBLICATION_FAILED in [d.code for d in result.diagnostics]
        assert _state(obj) == before
        assert set(bpy.data.meshes) == meshes
        assert ownership.manifest(handle.binding_id) == manifest


def test_synchronizing_a_cached_generation_again_removes_its_keys(bindings: Bindings, tmp_path: Path) -> None:
    # CHG-22 on F-EDIT-SEQUENCE "cached-again": the keyed copies' objects hold no animation once synchronized
    # again at 0, the display a clean binding's, and the actions gone from the manifest.
    with edit_sequence.edit_sequence(tmp_path) as scene:
        handle = _binding(bindings, scene.stage)
        _synchronize(handle)
        assert handle.cache(scene.cached_time_codes).state is not ResultState.FATAL_FAILURE
        _synchronize(handle)
        objects = _objects_by_source(handle)
        for source, _ in scene.keyed_copies:
            obj = objects[source]
            assert isinstance(obj, bpy.types.Object)
            assert obj.animation_data is None or obj.animation_data.action is None
        manifest = ownership.manifest(handle.binding_id)
        assert isinstance(manifest, id_property_records.LoadedRecord)
        assert all(e.role is not RepresentationRole.ACTION for e in manifest.record.entries.values())
        assert _shown(handle) == _clean(bindings, scene.stage)


def test_a_deleted_object_is_rebuilt(bindings: Bindings, tmp_path: Path) -> None:
    # A managed object the user deleted leaves its entry naming nothing, so the refresh rebuilds its partition.
    with edit_sequence.edit_sequence(tmp_path) as scene:
        handle = _binding(bindings, scene.stage)
        _synchronize(handle)
        bpy.data.batch_remove([_objects_by_source(handle)[edit_sequence.A]])
        _synchronize(handle)
        assert edit_sequence.A in _objects_by_source(handle)
        assert _shown(handle) == _clean(bindings, scene.stage)


def test_replacement_meshes_take_names_of_their_own(bindings: Bindings, tmp_path: Path) -> None:
    # DECISIONS.md "Managed object names": Odd's bounds grown twice, a refresh after each replacing only its mesh, gives
    # each replacement a managed name of a later generation, which no other mesh had, so Blender added no suffix.
    with edit_sequence.edit_sequence(tmp_path) as scene:
        handle = _binding(bindings, scene.stage)
        _synchronize(handle)
        obj = _objects_by_source(handle)[edit_sequence.ODD]
        assert isinstance(obj, bpy.types.Object)
        extent = UsdGeom.Boundable(scene.stage.GetPrimAtPath(edit_sequence.ODD)).GetExtentAttr()
        names = []
        for size in (2, 3):
            extent.Set([Gf.Vec3f(0, 0, 0), Gf.Vec3f(size, size, size)])
            _synchronize(handle)
            assert _objects_by_source(handle)[edit_sequence.ODD] == obj and obj.data is not None
            names.append(obj.data.name)
        assert all(re.fullmatch(r"~\d{6}\.\d{7} Odd", name) for name in names), names
        assert names[0] < names[1]
