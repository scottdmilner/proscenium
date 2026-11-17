"""The binding handle's interaction functions, the time code the display shows, and the applied settings.

bindings/'s surface over the display component and the planner (DECISIONS.md "Headless interaction functions"). Expected
values come from the interaction fixtures, F-TIME-VARIATIONS, and the spec's rule for the time code a display shows
(transforms.md#transforms-and-time-codes). support/interaction_checks.py checks the contract's results through it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import bpy
import pytest
from mathutils import Vector
from pxr import Gf, Sdf, Usd

from fixtures import interaction, time_variations
from proscenium_sync import planner
from proscenium_sync.bindings import PickedEntity, SourceUnavailableError, TargetSelection
from proscenium_sync.persistence import binding_state, id_property_records, manifests
from proscenium_sync.results import ResultState

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from proscenium_sync.bindings import BindingHandle, Bindings


def _attached(bindings: Bindings, stage: Usd.Stage) -> BindingHandle:
    handle = bindings.create_binding(bpy.data.scenes["Scene"], name="Shot")
    assert handle.attach(stage).state is not ResultState.FATAL_FAILURE
    return handle


def test_picks_resolve_through_the_handle(bindings: Bindings, tmp_path: Path) -> None:
    # ICON-36 through bindings/: each managed object with its world matrix, all a ray cast returns, resolves to its
    # entity
    # and floor, inside native instances included; an object the display doesn't show resolves to nothing.
    with interaction.nested_selection(tmp_path) as scene:
        handle = _attached(bindings, scene.stage)
        assert handle.synchronize(0.0).state is not ResultState.FATAL_FAILURE
        shown = handle.highlight_targets(["/World"])
        assert len(shown) == len(scene.elements[0.0])
        resolved = {}
        for obj in shown:
            picked = handle.resolve_pick(obj, obj.matrix_world)
            assert isinstance(picked, PickedEntity)
            resolved[picked.source_path] = picked.floor
        assert resolved == {e: scene.floors.get(e, e) for e in scene.elements[0.0]}
        other = bpy.data.objects.new("Unmanaged", None)
        assert handle.resolve_pick(other, other.matrix_world) is None


def test_selection_round_trips_through_the_handle(bindings: Bindings, tmp_path: Path) -> None:
    # ICON-30 through bindings/: the display's selected objects give their targets at the level, and the active one's.
    with interaction.kind_hierarchy(tmp_path) as scene:
        handle = _attached(bindings, scene.stage)
        assert handle.synchronize(0.0).state is not ResultState.FATAL_FAILURE
        [chair] = handle.select_targets(["/World/Props/Chair/Geom/Seat"], "component")
        assert chair == "/World/Props/Chair"
        objects = handle.highlight_targets([chair])
        view_layer = bpy.data.scenes["Scene"].view_layers[0]
        for obj in objects:
            obj.select_set(True, view_layer=view_layer)
        view_layer.objects.active = objects[0]
        assert handle.selection_from_blender("component", view_layer) == TargetSelection((chair,), chair)
        assert handle.displayed([chair, "/World/Props/Missing"]) == [True, False]


def test_without_a_live_stage_each_function_reports_it(bindings: Bindings, tmp_path: Path) -> None:
    # ICON-08 through bindings/: released after synchronizing, each interaction function raises SourceUnavailableError.
    with interaction.kind_hierarchy(tmp_path) as scene:
        handle = _attached(bindings, scene.stage)
        assert handle.synchronize(0.0).state is not ResultState.FATAL_FAILURE
        obj = handle.highlight_targets(["/World"])[0]
        handle.release()
        view_layer = bpy.data.scenes["Scene"].view_layers[0]
        calls: list[Callable[[], object]] = [
            lambda: handle.resolve_pick(obj, obj.matrix_world),
            lambda: handle.select_targets(["/World"], None),
            lambda: handle.displayed(["/World"]),
            lambda: handle.highlight_targets(["/World"]),
            lambda: handle.selection_from_blender(None, view_layer),
        ]
        for call in calls:
            with pytest.raises(SourceUnavailableError):
                call()


def test_nothing_published_displays_nothing(bindings: Bindings, tmp_path: Path) -> None:
    # Attached and never synchronized, the display shows nothing: no prim is displayed, no target highlighted, no
    # time code shown, and no settings applied; targets are still floors.
    with interaction.kind_hierarchy(tmp_path) as scene:
        handle = _attached(bindings, scene.stage)
        assert handle.displayed(["/World"]) == [False]
        assert handle.highlight_targets(["/World"]) == []
        assert handle.select_targets(["/World/Table/Top"], None) == ["/World/Table/Top"]
        assert handle.shown_time_code() is None
        assert handle.applied_settings() is None


def test_the_time_code_shown_follows_the_frame(bindings: Bindings, tmp_path: Path) -> None:
    # XFORM-13's rule through bindings/: synchronized at 0 and cached at 10 and 12.5, a frame shows its time code where
    # the
    # generation holds one, the latest before it elsewhere, and 0 before 0; at a subframe, its time code.
    target = bpy.data.scenes["Scene"]
    with time_variations.time_variations(tmp_path) as scene:
        handle = _attached(bindings, scene.stage)
        assert handle.synchronize(0.0).state is not ResultState.FATAL_FAILURE
        assert handle.cache([10.0, 12.5]).state is not ResultState.FATAL_FAILURE
        for frame, subframe, shown in (
            (0, 0.0, 0.0),
            (-3, 0.0, 0.0),
            (5, 0.0, 0.0),
            (11, 0.0, 10.0),
            (12, 0.5, 12.5),
            (30, 0.0, 12.5),
        ):
            target.frame_set(frame, subframe=subframe)
            assert handle.shown_time_code() == Usd.TimeCode(shown), (frame, subframe)


def test_a_default_synchronization_shows_the_default_time_code(bindings: Bindings, tmp_path: Path) -> None:
    with interaction.kind_hierarchy(tmp_path) as scene:
        handle = _attached(bindings, scene.stage)
        assert handle.synchronize(Usd.TimeCode.Default()).state is not ResultState.FATAL_FAILURE
        shown = handle.shown_time_code()
        assert shown is not None and shown.IsDefault()


def test_the_applied_settings_are_the_published_generations(bindings: Bindings, tmp_path: Path) -> None:
    # ICON-31's published generation's settings: those it was synchronized with, not those requested since.
    with interaction.kind_hierarchy(tmp_path) as scene:
        handle = _attached(bindings, scene.stage)
        assert handle.synchronize(0.0).state is not ResultState.FATAL_FAILURE
        applied = handle.requested_settings()
        assert handle.set_settings(coordinate_conversion=not applied.coordinate_conversion).is_success
        assert handle.applied_settings() == applied != handle.requested_settings()


def test_interaction_answers_for_the_time_code_shown(bindings: Bindings, tmp_path: Path) -> None:
    # XFORM-14 through bindings/: at the frame showing 15, Blink isn't displayed and Scatter's highlight covers its
    # third
    # point's object; at the frame showing 0, the reverse.
    target = bpy.data.scenes["Scene"]
    with time_variations.time_variations(tmp_path) as scene:
        handle = _attached(bindings, scene.stage)
        assert handle.synchronize(scene.synchronized).state is not ResultState.FATAL_FAILURE
        [call] = scene.cache_groupings[0]
        assert handle.cache(call).state is not ResultState.FATAL_FAILURE
        third = f"{time_variations.SCATTER}/__index_2/Pebble"
        for frame, blink, covered in ((15, False, True), (0, True, False)):
            target.frame_set(frame)
            assert handle.displayed([time_variations.BLINK]) == [blink], frame
            picked = {
                entity.source_path
                for obj in handle.highlight_targets([time_variations.SCATTER])
                if (entity := handle.resolve_pick(obj, obj.matrix_world)) is not None
            }
            assert (third in picked) is covered, frame


def _authored(layer: Sdf.Layer) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    """Each prim spec's authored kind, and its authored asset info, by path, as the fixture's layer holds them."""
    kinds: dict[str, str] = {}
    infos: dict[str, dict[str, Any]] = {}

    def visit(visited: Sdf.Path | str) -> None:
        path = Sdf.Path(visited)
        spec = layer.GetPrimAtPath(path) if path.IsPrimPath() else None
        if spec is None:
            return
        if spec.HasInfo("kind"):
            kinds[str(path)] = spec.GetInfo("kind")
        if spec.HasInfo("assetInfo"):
            infos[str(path)] = dict(spec.GetInfo("assetInfo"))

    layer.Traverse(Sdf.Path.absoluteRootPath, visit)
    return kinds, infos


def test_the_live_stage_gives_kinds_and_asset_metadata(bindings: Bindings, tmp_path: Path) -> None:
    # MODEL-01 on F-KIND-HIERARCHY: through the binding, before and after synchronizing, the live stage gives each
    # prim's kind and Chair's asset name, version, and identifier as the fixture's layer authors them; neither the
    # plan's type nor the binding's stored records carry asset metadata.
    with interaction.kind_hierarchy(tmp_path) as scene:
        kinds, infos = _authored(Sdf.Layer.FindOrOpen(str(scene.root_layer_path)))
        assert kinds and set(infos) == set(scene.asset_info) == {"/World/Props/Chair"}
        handle = _attached(bindings, scene.stage)

        def check() -> None:
            live = handle.live_stage()
            assert live is not None
            for path, kind in kinds.items():
                assert Usd.ModelAPI(live.GetPrimAtPath(path)).GetKind() == kind, path
            for path, info in infos.items():
                model = Usd.ModelAPI(live.GetPrimAtPath(path))
                assert (model.GetAssetName(), model.GetAssetVersion()) == (info["name"], info["version"]), path
                assert model.GetAssetIdentifier().path == info["identifier"].path, path

        check()
        assert handle.synchronize(0.0).state is not ResultState.FATAL_FAILURE
        check()
        assert not [name for name in dir(planner.Plan) if "asset" in name.lower()]
        destination = bpy.data.collections["Shot"]
        for key in (binding_state.GENERATION_KEY, manifests.MANIFEST_KEY):
            stored = str(id_property_records.stored(destination, key))
            assert "assetInfo" not in stored and "chair.usda" not in stored, key


def test_a_picks_matrix_reaches_the_planner_in_usds_convention() -> None:
    # The API takes Blender's matrix, as a ray cast returns it, and converts it once for the planner: a translation
    # lands in USD's last row, and a rotated point is where Blender puts it.
    from mathutils import Matrix

    from proscenium_sync.bindings import binding_interaction

    blender = Matrix.Translation((1.0, 2.0, 3.0)) @ Matrix.Rotation(0.5, 4, "Z")
    usd = binding_interaction.usd_matrix(blender)
    assert usd.ExtractTranslation() == Gf.Vec3d(1.0, 2.0, 3.0)
    moved = usd.Transform(Gf.Vec3d(1.0, 0.0, 0.0))
    assert Gf.IsClose(moved, Gf.Vec3d(*(blender @ Vector((1.0, 0.0, 0.0)))), 1e-6)
