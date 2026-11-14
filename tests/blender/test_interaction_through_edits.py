"""Interaction across F-EDIT-SEQUENCE's edits: selections through refreshes, and a display out of date.

PH2-02: a source selection holding a copy a step updates in place or rebuilds stays resolved after the refresh, and
Blender's selection mirrors it, while an entry for a path the step retires stays stored and unresolved. INSP-09: after
an edit and before its refresh, the binding reports it may be out of date and answers from the generation it shows,
not from the edited stage. Expected copies come from the fixture's steps, and whether a copy shows from its object's
viewport hide flag, the display's own record.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy
from pxr import Gf

from fixtures import edit_sequence
from proscenium.api.bindings import PersistentSelection, SelectionEntry
from proscenium.binding.persistence import binding_state, id_property_records, manifests
from proscenium.binding.results import ResultState
from support import interaction_oracle
from support.refresh_checks import copy_object, entries_by_source

if TYPE_CHECKING:
    from pathlib import Path

    from pxr import Usd

    from fixtures.edit_sequence import CopyIdentity
    from proscenium.api.bindings import BindingHandle, Bindings


def _scene() -> bpy.types.Scene:
    return bpy.data.scenes["Scene"]


def _binding(bindings: Bindings, stage: Usd.Stage) -> BindingHandle:
    handle = bindings.create_binding(_scene(), name="Shot")
    assert handle.attach(stage).state is not ResultState.FATAL_FAILURE
    assert handle.synchronize(0).state is not ResultState.FATAL_FAILURE
    return handle


def _floor(copy: CopyIdentity) -> str:
    path, context = copy
    return context[0] if context else path


def _shown_objects(handle: BindingHandle, floor: str) -> list[bpy.types.Object]:
    """The objects of the copies at or beneath floor that show in the viewport, by the manifest."""
    prefix = floor.rstrip("/") + "/"
    return [
        obj
        for source, entries in entries_by_source(handle.binding_id).items()
        if (source == floor or source.startswith(prefix)) and not (obj := copy_object(entries)).hide_viewport
    ]


def test_selections_survive_refreshes(bindings: Bindings, tmp_path: Path) -> None:
    # PH2-02 on F-EDIT-SEQUENCE: before each step, a selection of the floors of the copies it updates or rebuilds and of
    # the plain copies it retires; after the step's refresh, each kept copy's floor resolves while a copy beneath it
    # shows, and those objects are selected, and each retired path no copy is drawn at any longer stays stored and is
    # reported unresolved.
    view_layer = _scene().view_layers[0]
    with edit_sequence.edit_sequence(tmp_path) as scene:
        handle = _binding(bindings, scene.stage)
        drawn = set(scene.initial_copies)
        for step in scene.steps:
            kept = list(dict.fromkeys(_floor(c) for c in sorted(step.updated | step.rebuilt)))
            drawn = (drawn - step.retired) | step.built
            plain_after = {path for path, context in drawn if not context}
            gone = sorted(path for path, context in step.retired if not context and path not in plain_after)
            entries = tuple(SelectionEntry(handle.binding_id, p) for p in dict.fromkeys([*kept, *gone]))
            selection = PersistentSelection(entries, None)
            bindings.set_source_selection(_scene(), selection)
            step.edit(scene.stage)
            assert handle.synchronize(0).state is not ResultState.FATAL_FAILURE, step.name
            resolution = bindings.resolve_source_selection(_scene())
            assert bindings.source_selection(_scene()) == selection, step.name
            for floor in kept:
                shown = _shown_objects(handle, floor)
                assert (SelectionEntry(handle.binding_id, floor) in resolution.resolved) is bool(shown), (
                    step.name,
                    floor,
                )
                assert all(obj.select_get(view_layer=view_layer) for obj in shown), (step.name, floor)
            for path in gone:
                assert SelectionEntry(handle.binding_id, path) in resolution.unresolved, (step.name, path)


def _stored(handle: BindingHandle) -> tuple[object, object]:
    destination = bpy.data.collections["Shot"]
    return (
        id_property_records.stored(destination, binding_state.GENERATION_KEY),
        id_property_records.stored(destination, manifests.MANIFEST_KEY),
    )


def _correspondence(handle: BindingHandle, paths: list[str]) -> tuple[object, ...]:
    """Each object's pick, by name, and displayed and each path's highlighted objects over paths."""
    objects = sorted(bpy.data.collections["Shot"].all_objects, key=lambda o: o.name)
    picks = [
        (obj.name, handle.resolve_pick(obj, Gf.Matrix4d(*(v for row in obj.matrix_world for v in row))))
        for obj in objects
    ]
    highlights = [sorted(o.name for o in handle.highlight_targets([p])) for p in paths]
    return picks, handle.displayed(paths), highlights


def test_an_edit_leaves_the_display_and_its_correspondence_until_refreshed(bindings: Bindings, tmp_path: Path) -> None:
    # INSP-09 on F-EDIT-SEQUENCE: after each step's edit and before its refresh, the binding reports it may be out of
    # date, its generation record and manifest are as published, and its correspondence answers as before the edit over
    # the stage's paths before it, and a path only the edit made isn't displayed; after the refresh, it isn't reported
    # out of date.
    with edit_sequence.edit_sequence(tmp_path) as scene:
        handle = _binding(bindings, scene.stage)
        for step in scene.steps:
            assert not handle.possibly_out_of_date(), step.name
            paths = interaction_oracle.all_paths(scene.stage)
            stored, answered = _stored(handle), _correspondence(handle, paths)
            step.edit(scene.stage)
            assert handle.possibly_out_of_date(), step.name
            assert _stored(handle) == stored, step.name
            assert _correspondence(handle, paths) == answered, step.name
            made = sorted(set(interaction_oracle.all_paths(scene.stage)) - set(paths))
            assert not any(handle.displayed(made)), (step.name, made)
            assert handle.synchronize(0).state is not ResultState.FATAL_FAILURE, step.name
            assert not handle.possibly_out_of_date(), step.name
