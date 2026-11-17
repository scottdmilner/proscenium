"""A binding's correspondence built from its manifest and Blender data (DECISIONS.md "Persisted correspondence").

The display elements are the objects the manifest names in a drawn copy's object role, each in the viewport when its
hide flag shows it at the frame shown; instance contexts come from the held plan, or from the live stage without one.
Expected values come from the interaction fixtures and F-TIME-VARIATIONS, and from USD's own APIs
(support/interaction_oracle.py). support/interaction_checks.py checks the interaction functions through bindings/.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy
import pytest
from pxr import Gf, Sdf, Usd

from fixtures import interaction, time_variations
from proscenium_sync.bindings import BindingHandle
from proscenium_sync.interaction import display_correspondence
from proscenium_sync.persistence import binding_state, id_property_records
from proscenium_sync.persistence.manifests import RepresentationRole
from proscenium_sync.results import ResultState
from proscenium_sync.runtime import held_plans, ownership
from proscenium_sync.source_access.binding_settings import PayloadPolicy
from support import interaction_oracle
from support.blend import save_and_reopen
from support.usd import open_stage_without_cache

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractContextManager
    from pathlib import Path

    from proscenium_sync import planner
    from proscenium_sync.bindings import Bindings
    from proscenium_sync.source_access import BindingId

IDENTITY = Gf.Matrix4d(1.0)
SCENES: dict[str, Callable[[Path], AbstractContextManager[interaction.InteractionScene]]] = {
    "F-KIND-HIERARCHY": interaction.kind_hierarchy,
    "F-NESTED-SELECTION": interaction.nested_selection,
    "F-UNIVERSE-MEMBERSHIP": interaction.universe_membership,
}

type Answers = tuple[dict[str, tuple[str, tuple[str, ...], str]], set[str], dict[str, set[str]]]


def _attached(
    bindings: Bindings, stage: Usd.Stage, payload_policy: PayloadPolicy = PayloadPolicy.LOAD_ALL
) -> BindingHandle:
    handle = bindings.create_binding(bpy.data.scenes["Scene"], payload_policy=payload_policy, name="Shot")
    assert handle.attach(stage).state is not ResultState.FATAL_FAILURE
    return handle


def _elements(binding_id: BindingId) -> display_correspondence.DisplayElements:
    elements = display_correspondence.display_elements(binding_id)
    assert elements is not None
    return elements


def _object_entries(binding_id: BindingId) -> dict[str, tuple[bpy.types.ID | None, str]]:
    """Each object-role entry's datablock and source entity, by entry key."""
    manifest = ownership.manifest(binding_id)
    assert isinstance(manifest, id_property_records.LoadedRecord)
    return {
        key: (e.datablock, e.source_entity_paths[0])
        for key, e in manifest.record.entries.items()
        if e.role is RepresentationRole.OBJECT
    }


def _answers(
    elements: display_correspondence.DisplayElements, correspondence: planner.Correspondence, stage: Usd.Stage
) -> Answers:
    """What the correspondence answers, by entry key: each element's entity, the universe, and each prim's highlight."""
    picks = {}
    for index, key in enumerate(elements.entry_keys):
        entity = correspondence.resolve_pick(index, IDENTITY)
        assert entity is not None
        picks[key] = (entity.source_path, entity.instance_context, entity.floor)
    paths = interaction_oracle.all_paths(stage)
    shown = memoryview(correspondence.displayed(paths)).tolist()
    universe = {p for p, displayed in zip(paths, shown, strict=True) if displayed}
    highlights = {
        target: {elements.entry_keys[i] for i in memoryview(correspondence.highlight_targets([target])).tolist()}
        for target in universe
    }
    return picks, universe, highlights


@pytest.mark.parametrize("fixture", SCENES)
def test_the_elements_are_the_manifests_objects(bindings: Bindings, tmp_path: Path, fixture: str) -> None:
    # ICON-11 to ICON-15 on the display: synchronized at each of the fixture's time codes, the elements are the objects
    # the manifest names in the object role, with their entry keys and source entities; with the held plan's contexts
    # and with the live stage's, each element resolves to the same entity and the fixture's floor, displayed is true
    # exactly for the universe, and a prim's highlight is the viewport elements whose floors are at or beneath it.
    with SCENES[fixture](tmp_path) as scene:
        # F-UNIVERSE-MEMBERSHIP's payload stays unloaded, as the caller's stage has it, only under that policy.
        handle = _attached(bindings, scene.stage, PayloadPolicy.LOAD_NONE)
        for time in scene.times:
            assert handle.synchronize(time).state is not ResultState.FATAL_FAILURE
            elements = _elements(handle.binding_id)
            entries = _object_entries(handle.binding_id)
            assert set(elements.entry_keys) == entries.keys()
            for key, obj, path in zip(elements.entry_keys, elements.objects, elements.source_paths, strict=True):
                assert entries[key] == (obj, path)
            in_viewport = {k for k, v in zip(elements.entry_keys, elements.visible_in_viewport, strict=True) if v}
            answers = []
            for plans in (bindings.published_plans, held_plans.HeldPlans()):
                correspondence = display_correspondence.correspondence(elements, scene.stage, plans)
                picks, universe, highlights = _answers(elements, correspondence, scene.stage)
                assert universe == scene.universe[time], time
                for path, _, floor in picks.values():
                    assert floor == scene.floors.get(path, path), path
                for target, covered in highlights.items():
                    beneath = {k for k, (_, _, floor) in picks.items() if Sdf.Path(floor).HasPrefix(Sdf.Path(target))}
                    assert covered == beneath & in_viewport, (time, target)
                answers.append(picks)
            assert answers[0] == answers[1], time  # the live stage gives the held plan's contexts


def test_correspondence_is_the_same_after_reopening(bindings: Bindings, tmp_path: Path) -> None:
    # ICON-35, ICON-16 on F-NESTED-SELECTION: saved and reopened, with the stage attached again, nothing synchronized,
    # and no plan held, the correspondence built from Blender data answers as before saving, by entry key, and the
    # generation record is unchanged.
    with interaction.nested_selection(tmp_path) as scene:
        handle = _attached(bindings, scene.stage)
        assert handle.synchronize(0.0).state is not ResultState.FATAL_FAILURE
        elements = _elements(handle.binding_id)
        before = _answers(
            elements,
            display_correspondence.correspondence(elements, scene.stage, bindings.published_plans),
            scene.stage,
        )
        record = elements.generation
        save_and_reopen(tmp_path / "correspondence.blend")
        restored = BindingHandle(handle.binding_id)
        stage = open_stage_without_cache(scene.root_layer_path)
        assert restored.attach(stage).state is not ResultState.FATAL_FAILURE
        assert bindings.published_plans.plan_for(record) is None
        elements = _elements(handle.binding_id)
        assert elements.generation == record
        after = _answers(
            elements, display_correspondence.correspondence(elements, stage, bindings.published_plans), stage
        )
        assert after == before
        destination = bpy.data.collections["Shot"]
        stored = binding_state.read_generation(destination)
        assert isinstance(stored, id_property_records.LoadedRecord)
        assert stored.record == record


def _set_frame(time_code: float) -> None:
    bpy.data.scenes["Scene"].frame_set(int(time_code))


def test_interaction_answers_for_the_time_code_shown(bindings: Bindings, tmp_path: Path) -> None:
    # XFORM-14 on F-TIME-VARIATIONS: synchronized at 0 and cached at the fixture's time codes, at the frame showing 15
    # Blink is outside the universe and Scatter's highlight covers its third point's copy, which the cache call built;
    # at the frame showing 0, the reverse.
    third_point = f"{time_variations.SCATTER}/__index_2/Pebble"
    with time_variations.time_variations(tmp_path) as scene:
        handle = _attached(bindings, scene.stage)
        assert handle.synchronize(scene.synchronized).state is not ResultState.FATAL_FAILURE
        [call] = scene.cache_groupings[0]
        assert handle.cache(call).state is not ResultState.FATAL_FAILURE
        for frame, blink_displayed, third_covered in ((15.0, False, True), (0.0, True, False)):
            _set_frame(frame)
            elements = _elements(handle.binding_id)
            correspondence = display_correspondence.correspondence(elements, scene.stage, bindings.published_plans)
            assert memoryview(correspondence.displayed([time_variations.BLINK])).tolist() == [blink_displayed], frame
            covered = memoryview(correspondence.highlight_targets([time_variations.SCATTER])).tolist()
            assert (third_point in {elements.source_paths[i] for i in covered}) is third_covered, frame
            assert third_point in elements.source_paths  # an element at both frames, in the viewport at one


def test_a_copys_second_object_is_an_element(bindings: Bindings, tmp_path: Path) -> None:
    # Flicker, a box from 10 until 20 and a marker otherwise, has two objects once cached: both are elements resolving
    # to Flicker, and its highlight covers the one its hide flag shows at each frame.
    with time_variations.time_variations(tmp_path) as scene:
        handle = _attached(bindings, scene.stage)
        assert handle.synchronize(scene.synchronized).state is not ResultState.FATAL_FAILURE
        [call] = scene.cache_groupings[0]
        assert handle.cache(call).state is not ResultState.FATAL_FAILURE
        for frame in (0.0, 15.0):
            _set_frame(frame)
            elements = _elements(handle.binding_id)
            correspondence = display_correspondence.correspondence(elements, scene.stage, bindings.published_plans)
            flicker = [i for i, path in enumerate(elements.source_paths) if path == time_variations.FLICKER]
            assert len(flicker) == 2
            for index in flicker:
                entity = correspondence.resolve_pick(index, IDENTITY)
                assert entity is not None
                assert entity.source_path == time_variations.FLICKER
            shown = [i for i in flicker if elements.visible_in_viewport[i]]
            assert len(shown) == 1, frame
            covered = set(memoryview(correspondence.highlight_targets([time_variations.FLICKER])).tolist())
            assert covered == set(shown), frame


def test_elements_read_no_source(bindings: Bindings, tmp_path: Path) -> None:
    # INSP-10's display half: with the live stage released, the display elements are still read from Blender data,
    # and the planner's correspondence reports the source unavailable.
    from proscenium_sync import planner

    with interaction.kind_hierarchy(tmp_path) as scene:
        handle = _attached(bindings, scene.stage)
        assert handle.synchronize(0.0).state is not ResultState.FATAL_FAILURE
        handle.release()
        elements = _elements(handle.binding_id)
        assert len(elements.objects) == len(scene.elements[0.0])
        with pytest.raises(planner.SourceUnavailableError):
            display_correspondence.correspondence(elements, handle.live_stage(), bindings.published_plans)


def test_elements_columns_must_agree_in_length() -> None:
    # Each column holds one item per element, so columns of different lengths are refused.
    generation = binding_state.GenerationMetadata.__new__(binding_state.GenerationMetadata)
    with pytest.raises(ValueError, match="Each display element needs"):
        display_correspondence.DisplayElements(generation, ("a" * 32,), (), ("/A",), (True,))
