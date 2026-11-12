"""Each F-EDIT-SEQUENCE step's refresh, against the change matrix (change-matrix.md; M7 plan, C7).

The steps are applied in order to one live stage, a refresh after each. Each refresh displays what a clean binding's
first synchronization of the same stage does (TINC-01, support/clean_rebuild.py), and acts on exactly the copies the
step lists, those depending on its source-affected prims (AFF-01, DISC-06): an updated copy keeps its object, and its
Blender selection (CHG-01, CHG-02); a rebuilt copy's resources are new and its old ones retired (CHG-03); a retired
copy's resources are gone, and a built copy's new. Every other copy keeps its resources and their manifest entries, none
of their transforms or geometry updated in the depsgraph, and a step acting on no copy writes no display resource, only
the generation record and last attempt, for the source revision it shows (CHG-07). Copies are told apart by source
entity, as the manifest names them; a step retiring and building at one path, as instanceable toggled does, replaces
that path's resources.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import bpy

from fixtures import edit_sequence
from proscenium.binding.persistence import id_property_records
from proscenium.binding.persistence.manifests import RepresentationRole
from proscenium.binding.results import ResultState
from proscenium.binding.runtime import ownership
from support.blender_writes import observed_writes
from support.clean_rebuild import clean_rebuild, display_state

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

    from proscenium.api.bindings import Bindings
    from proscenium.binding.persistence import manifests
    from proscenium.binding.source_access import BindingId

_GENERATION = re.compile(r"~(\d{6})\.")  # a managed name's generation (DECISIONS.md "Managed object names")


def _entries_by_source(binding_id: BindingId) -> dict[str, dict[str, manifests.ManifestEntry]]:
    """The manifest's copy entries, by entry key, grouped by their copy's source entity."""
    manifest = ownership.manifest(binding_id)
    assert isinstance(manifest, id_property_records.LoadedRecord)
    grouped: dict[str, dict[str, manifests.ManifestEntry]] = {}
    for key, entry in manifest.record.entries.items():
        if (identity := entry.identity) is not None:
            grouped.setdefault(identity.entity, {})[key] = entry
    return grouped


def _object(entries: dict[str, manifests.ManifestEntry]) -> bpy.types.Object:
    [obj] = [e.datablock for e in entries.values() if e.role is RepresentationRole.OBJECT]
    assert isinstance(obj, bpy.types.Object)
    return obj


def _datablocks(entries: dict[str, manifests.ManifestEntry]) -> list[bpy.types.ID]:
    return [e.datablock for e in entries.values() if e.datablock is not None]


def test_each_step_acts_on_exactly_its_copies(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # TINC-01, AFF-01, DISC-02, DISC-06, CHG-01 to CHG-03, CHG-07 to CHG-20 on F-EDIT-SEQUENCE.
    view_layer = bpy.data.scenes["Scene"].view_layers[0]
    with edit_sequence.edit_sequence(tmp_path) as scene:
        handle = bindings.create_binding(bpy.data.scenes["Scene"], name="Shot")
        assert handle.attach(scene.stage).state is not ResultState.FATAL_FAILURE
        assert handle.synchronize(0).state is not ResultState.FATAL_FAILURE
        for step in scene.steps:
            before = _entries_by_source(handle.binding_id)
            updated = {source for source, _ in step.updated}
            replaced = {source for source, _ in step.rebuilt | step.retired | step.built}
            untouched = before.keys() - updated - replaced
            # Every object selected, as Blender lets a shown one be, and an updated one active, so a refresh is seen
            # keeping both; Blender deselects an object the step hides.
            for entries in before.values():
                _object(entries).select_set(True)
            selected = {s for s, entries in before.items() if _object(entries).select_get(view_layer=view_layer)}
            active = _object(before[min(updated)]) if updated else None
            view_layer.objects.active = active
            odd_mesh = _object(before[edit_sequence.ODD]).data if edit_sequence.ODD in before else None
            step.edit(scene.stage)
            with observed_writes(monkeypatch) as observed:
                assert handle.synchronize(0).state is not ResultState.FATAL_FAILURE, step.name
            after = _entries_by_source(handle.binding_id)
            assert display_state(handle.binding_id) == clean_rebuild(bindings, scene.stage), step.name
            if not (updated or replaced):
                # No display resource written: only the records of the source revision it now shows.
                assert not observed.updated_ids and observed.created_id_count == 0, (step.name, observed)
                assert set(observed.record_writes) <= {"generation", "last attempt"}, (step.name, observed)
            written = set(observed.changed_ids)
            for source in untouched:
                assert after[source] == before[source], (step.name, source)
                for datablock in _datablocks(before[source]):
                    assert f"{type(datablock).__name__}:{datablock.name}" not in written, (step.name, datablock)
                assert _object(after[source]).select_get(view_layer=view_layer) == (source in selected), step.name
            for source in updated:
                obj = _object(after[source])
                assert obj == _object(before[source]), (step.name, source)
                if not obj.hide_viewport:
                    assert obj.select_get(view_layer=view_layer) == (source in selected), (step.name, source)
            if active is not None and not active.hide_viewport:
                assert view_layer.objects.active == active, step.name
            for source in replaced:
                old = _datablocks(before.get(source, {}))
                assert not any(id_property_records.alive(datablock) for datablock in old), (step.name, source)
                new = _datablocks(after.get(source, {}))
                assert all(datablock not in old for datablock in new), (step.name, source)
            assert after.keys() == (before.keys() - {s for s, _ in step.retired}) | {s for s, _ in step.built}
            if step.name == "bounds-changed":
                # CHG-08: Odd's object kept, pointed at a new mesh named for Odd in a later generation, the old one
                # retired.
                obj = _object(after[edit_sequence.ODD])
                assert isinstance(obj.data, bpy.types.Mesh) and odd_mesh is not None and obj.data != odd_mesh
                generation, mesh_generation = (_GENERATION.match(n) for n in (obj.name, obj.data.name))
                assert generation and mesh_generation and mesh_generation.group(1) > generation.group(1)
                assert obj.data.name.endswith(" Odd") and not id_property_records.alive(odd_mesh)
