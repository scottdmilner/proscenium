"""F-EDIT-SEQUENCE: the change matrix's cases made one edit at a time (docs/spec/change-matrix.md).

edit_sequence copies Scene.INCREMENTAL, opens edit_sequence.usda as the caller's live stage, and yields the
drawn copies it starts with and a sequence of steps, each an edit to the live stage and what a refresh after it
affects, written out by hand from the matrix: the source-affected entities, and the drawn copies a local update
changes in place, whose partitions are rebuilt, retired, or built. A test applies the steps in order,
refreshing after each and checking the display against a clean full rebuild (TINC-01). The cases that change a
binding's settings or state rather than its source use the scene as it starts. tests/bpy_free/
test_edit_sequence_fixture.py checks each step's copies and changes against USD's own APIs.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pxr import Gf, Sdf, Usd, UsdGeom, Vt

from support.usd import open_stage_without_cache

from .scenes import Scene, copy_scene

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from pathlib import Path

# A drawn copy's identity: its source entity's path (an instance-proxy or point-instance path inside instance
# contents) and its instance context, outermost first.
type CopyIdentity = tuple[str, tuple[str, ...]]
# An edit to the live stage; what it returns, such as a USD setter's success, is ignored, since the fixture's test
# checks each edit's effect.
type StageEdit = Callable[[Usd.Stage], object]

GROUP, A, B = "/World/Group", "/World/Group/A", "/World/Group/B"
ODD, FOG, SHAPE, BODY = "/World/Odd", "/World/Fog", "/World/Shape", "/World/Shape/Body"
DORMANT, ADDED, RENAMED, MOVED_ODD = "/World/Dormant", "/World/Group/Added", "/World/Group/Renamed", "/World/Group/Odd"
LEAF, MOVER, GUIDE, FAR = "/World/Payloaded/Leaf", "/World/Mover", "/World/Guide", "/World/Far"
LEFT, RIGHT, CRATE_BOX = "/World/Instances/Left", "/World/Instances/Right", "/Prototypes/Crate/Box"
TAGGED, NUMBERED = "/World/Tagged", "/World/Numbered"

FAR_TRANSLATION = Gf.Vec3d(6, 15, 0)
FAR_RELOADED = Gf.Vec3d(6, 16, 0)  # Far's translation in edit_sequence_sub.usda once rewritten on disk
FAR_ATTACHED = Gf.Vec3d(6, 17, 0)  # and in the session layer of the stage attached in place of the first


def _plain(path: str) -> CopyIdentity:
    return (path, ())


def _instanced(instance: str) -> CopyIdentity:
    return (f"{instance}/Box", (instance,))


def _point(instancer: str, element: str) -> CopyIdentity:
    point = f"{instancer}/{element}"
    return (f"{point}/Pebble", (instancer, point))


INITIAL_COPIES = frozenset(
    {
        *map(_plain, (A, B, ODD, FOG, BODY, LEAF, MOVER, FAR)),
        _instanced(LEFT),
        _instanced(RIGHT),
        *(_point(TAGGED, f"__id_{point_id}") for point_id in (1, 2, 3)),
        *(_point(NUMBERED, f"__index_{index}") for index in (0, 1, 2)),
    }
)


@dataclass(frozen=True)
class EditStep:
    """One edit to the live stage, and what the refresh after it affects."""

    name: str
    change_rows: tuple[str, ...]  # the change matrix's case rows it makes
    edit: StageEdit
    source_affected: frozenset[str]  # the prims whose source state the edit changed
    updated: frozenset[CopyIdentity] = frozenset()  # kept, and changed in place by a local update
    rebuilt: frozenset[CopyIdentity] = frozenset()  # kept identities whose partitions are prepared anew
    retired: frozenset[CopyIdentity] = frozenset()
    built: frozenset[CopyIdentity] = frozenset()


def _translate(path: str, value: tuple[float, float, float]) -> StageEdit:
    return lambda stage: stage.GetAttributeAtPath(f"{path}.xformOp:translate").Set(Gf.Vec3d(value))


def _coalesced(stage: Usd.Stage) -> None:
    # Two edits before one refresh, so their notices arrive together.
    _translate(A, (1, 0, 0))(stage)
    _translate(A, (2, 0, 0))(stage)


def _op_order(path: str, ops: list[str]) -> StageEdit:
    return lambda stage: stage.GetAttributeAtPath(f"{path}.xformOpOrder").Set(Vt.TokenArray(ops))


def _visibility(path: str, value: str) -> StageEdit:
    return lambda stage: UsdGeom.Imageable(stage.GetPrimAtPath(path)).GetVisibilityAttr().Set(value)


def _purpose(path: str, value: str) -> StageEdit:
    return lambda stage: UsdGeom.Imageable(stage.GetPrimAtPath(path)).GetPurposeAttr().Set(value)


def _extent(path: str, maximum: tuple[float, float, float]) -> StageEdit:
    extent = Vt.Vec3fArray([Gf.Vec3f(0, 0, 0), Gf.Vec3f(maximum)])
    return lambda stage: UsdGeom.Boundable(stage.GetPrimAtPath(path)).CreateExtentAttr().Set(extent)


def _block_extent(stage: Usd.Stage) -> None:
    UsdGeom.Boundable(stage.GetPrimAtPath(FOG)).GetExtentAttr().Block()


def _type_to_points(stage: Usd.Stage) -> None:
    stage.GetPrimAtPath(ODD).SetTypeName("Points")


def _switch_variant(stage: Usd.Stage) -> None:
    stage.GetPrimAtPath(SHAPE).GetVariantSets().GetVariantSet("form").SetVariantSelection("marker")


def _add(stage: Usd.Stage) -> None:
    layer = stage.GetRootLayer()
    Sdf.CopySpec(layer, B, layer, ADDED)


def _active(path: str, *, active: bool) -> StageEdit:
    return lambda stage: stage.GetPrimAtPath(path).SetActive(active)


def _remove_dormant(stage: Usd.Stage) -> None:
    stage.RemovePrim(DORMANT)


def _namespace_edit(old: str, new: str) -> StageEdit:
    def edit(stage: Usd.Stage) -> None:
        batch = Sdf.BatchNamespaceEdit()
        batch.Add(Sdf.NamespaceEdit(old, new))
        if not stage.GetRootLayer().Apply(batch):
            raise RuntimeError(f"namespace edit {old} -> {new} failed")

    return edit


def _instanceable(path: str, *, instanceable: bool) -> StageEdit:
    return lambda stage: stage.GetPrimAtPath(path).SetInstanceable(instanceable)


def _move_crate_box(stage: Usd.Stage) -> None:
    UsdGeom.Xformable(stage.GetPrimAtPath(CRATE_BOX)).AddTranslateOp().Set(Gf.Vec3d(0, 0, 1))


def _move_point(stage: Usd.Stage) -> None:
    attribute = UsdGeom.PointInstancer(stage.GetPrimAtPath(TAGGED)).GetPositionsAttr()
    positions = list(attribute.Get())
    positions[1] = Gf.Vec3f(2, 10, 0)  # id 2's
    attribute.Set(Vt.Vec3fArray(positions))


def _remove_first_point(path: str) -> StageEdit:
    def edit(stage: Usd.Stage) -> None:
        instancer = UsdGeom.PointInstancer(stage.GetPrimAtPath(path))
        for attribute in (instancer.GetIdsAttr(), instancer.GetPositionsAttr(), instancer.GetProtoIndicesAttr()):
            if attribute.HasAuthoredValue():
                values = attribute.Get()
                attribute.Set(type(values)(list(values)[1:]))

    return edit


def _steps() -> tuple[EditStep, ...]:
    a, b, odd, fog = _plain(A), _plain(B), _plain(ODD), _plain(FOG)
    both = frozenset({a, b})  # Group's two meshes
    return (
        # Transforms: inherited from an ancestor, edits coalesced before one refresh, and a prim edited again.
        EditStep("ancestor-transform", ("CHG-14",), _translate(GROUP, (0, 0, 1)), frozenset({GROUP}), both),
        EditStep("coalesced-transform", ("CHG-14",), _coalesced, frozenset({A}), frozenset({a})),
        EditStep("repeated-transform", ("CHG-14",), _translate(A, (2, 1, 0)), frozenset({A}), frozenset({a})),
        # A shear appearing or vanishing gives or takes a shear parent, so the partition is rebuilt.
        EditStep(
            "shear-introduced",
            ("CHG-14",),
            _op_order(A, ["xformOp:translate", "xformOp:transform"]),
            frozenset({A}),
            rebuilt=frozenset({a}),
        ),
        EditStep(
            "shear-removed", ("CHG-14",), _op_order(A, ["xformOp:translate"]), frozenset({A}), rebuilt=frozenset({a})
        ),
        # Visibility and purpose: hide flags changed in place, and a copy leaving or entering both destinations.
        EditStep("ancestor-visibility", ("CHG-15",), _visibility(GROUP, "invisible"), frozenset({GROUP}), both),
        EditStep("visibility-restored", ("CHG-15",), _visibility(GROUP, "inherited"), frozenset({GROUP}), both),
        EditStep("purpose-render", ("CHG-16",), _purpose(B, "render"), frozenset({B}), frozenset({b})),
        EditStep("purpose-guide", ("CHG-16",), _purpose(B, "guide"), frozenset({B}), retired=frozenset({b})),
        EditStep("purpose-default", ("CHG-16",), _purpose(B, "default"), frozenset({B}), built=frozenset({b})),
        # Bounds: a box's bounds changed replace its bounds mesh, which its kept object is pointed at; a type
        # changed with the same bounds leaves the box equal; bounds appearing or vanishing turn a marker into a
        # box and back.
        EditStep("bounds-changed", ("CHG-17", "CHG-08"), _extent(ODD, (2, 2, 2)), frozenset({ODD}), frozenset({odd})),
        EditStep("type-changed", ("CHG-13", "CHG-07"), _type_to_points, frozenset({ODD})),
        EditStep("bounds-appeared", ("CHG-17",), _extent(FOG, (1, 1, 1)), frozenset({FOG}), rebuilt=frozenset({fog})),
        EditStep("bounds-vanished", ("CHG-17",), _block_extent, frozenset({FOG}), rebuilt=frozenset({fog})),
        # A variant switch recomposes Body from a box to a marker: a type and its bounds changed together.
        EditStep(
            "variant-switched",
            ("CHG-12", "CHG-13"),
            _switch_variant,
            frozenset({SHAPE, BODY}),
            rebuilt=frozenset({_plain(BODY)}),
        ),
        # Existence: added, activated, deactivated, and removed.
        EditStep("added", ("CHG-09",), _add, frozenset({ADDED}), built=frozenset({_plain(ADDED)})),
        EditStep(
            "activated",
            ("CHG-09",),
            _active(DORMANT, active=True),
            frozenset({DORMANT}),
            built=frozenset({_plain(DORMANT)}),
        ),
        EditStep(
            "deactivated",
            ("CHG-10",),
            _active(ADDED, active=False),
            frozenset({ADDED}),
            retired=frozenset({_plain(ADDED)}),
        ),
        EditStep("removed", ("CHG-10",), _remove_dormant, frozenset({DORMANT}), retired=frozenset({_plain(DORMANT)})),
        # Hierarchy: a copy's identity includes its source path, so a rename or move retires and builds.
        EditStep(
            "renamed",
            ("CHG-11",),
            _namespace_edit(B, RENAMED),
            frozenset({B, RENAMED}),
            retired=frozenset({b}),
            built=frozenset({_plain(RENAMED)}),
        ),
        EditStep(
            "moved",
            ("CHG-11",),
            _namespace_edit(ODD, MOVED_ODD),
            frozenset({ODD, MOVED_ODD}),
            retired=frozenset({odd}),
            built=frozenset({_plain(MOVED_ODD)}),
        ),
        # Instancing: a copy's identity includes its instance context. Right keeps the prototype's mesh it
        # shares while Left has its own.
        EditStep(
            "instanceable-off",
            ("CHG-18",),
            _instanceable(LEFT, instanceable=False),
            frozenset({LEFT}),
            retired=frozenset({_instanced(LEFT)}),
            built=frozenset({_plain(f"{LEFT}/Box")}),
        ),
        EditStep(
            "instanceable-on",
            ("CHG-18",),
            _instanceable(LEFT, instanceable=True),
            frozenset({LEFT}),
            retired=frozenset({_plain(f"{LEFT}/Box")}),
            built=frozenset({_instanced(LEFT)}),
        ),
        EditStep(
            "shared-contents-changed",
            ("CHG-19", "CHG-14"),
            _move_crate_box,
            frozenset({CRATE_BOX}),
            frozenset({_instanced(LEFT), _instanced(RIGHT)}),
        ),
        # Point instancers: with authored ids the other points' copies are kept; without them, removing a
        # point renumbers every later one, whose copies are retired and built anew.
        EditStep("point-moved", ("CHG-20",), _move_point, frozenset({TAGGED}), frozenset({_point(TAGGED, "__id_2")})),
        EditStep(
            "point-removed-by-id",
            ("CHG-20",),
            _remove_first_point(TAGGED),
            frozenset({TAGGED}),
            retired=frozenset({_point(TAGGED, "__id_1")}),
        ),
        EditStep(
            "point-removed-by-index",
            ("CHG-20",),
            _remove_first_point(NUMBERED),
            frozenset({NUMBERED}),
            rebuilt=frozenset({_point(NUMBERED, "__index_0"), _point(NUMBERED, "__index_1")}),
            retired=frozenset({_point(NUMBERED, "__index_2")}),
        ),
    )


@dataclass
class EditSequenceScene:
    root_layer_path: Path
    stage: Usd.Stage  # the caller's live stage
    initial_copies: frozenset[CopyIdentity]  # under the default settings, before any step
    steps: tuple[EditStep, ...]  # applied in order, each after the one before
    payloaded_copies: frozenset[CopyIdentity]  # drawn only while payloads load
    guide_copies: frozenset[CopyIdentity]  # drawn only when a destination's purposes include guide
    cached_time_codes: tuple[float, ...]  # cached after synchronizing at 0, then synchronized at 0 again
    keyed_copies: frozenset[CopyIdentity]  # the copies the cache keys: their keys go when synchronized again
    sub_layer_path: Path  # edit_sequence_sub.usda, which holds Far

    def rewrite_far_on_disk(self) -> None:
        """Move Far to FAR_RELOADED in edit_sequence_sub.usda's file only, for a reload to read.

        The modification time moves forward by 2 s, so a reload that goes by it sees the change.
        """
        mtime_ns = self.sub_layer_path.stat().st_mtime_ns
        copy = Sdf.Layer.OpenAsAnonymous(str(self.sub_layer_path))
        copy.GetAttributeAtPath(f"{FAR}.xformOp:translate").default = FAR_RELOADED
        copy.Export(str(self.sub_layer_path))
        os.utime(self.sub_layer_path, ns=(mtime_ns + 2_000_000_000, mtime_ns + 2_000_000_000))

    def open_attached_stage(self) -> Usd.Stage:
        """Open a new stage over the same layers, moving Far to FAR_ATTACHED in its session layer.

        Attached in place of the live stage, only Far's copy differs.
        """
        stage = open_stage_without_cache(self.root_layer_path)
        with Usd.EditContext(stage, stage.GetSessionLayer()):
            stage.GetAttributeAtPath(f"{FAR}.xformOp:translate").Set(FAR_ATTACHED)
        return stage


@contextmanager
def edit_sequence(dest: Path) -> Generator[EditSequenceScene]:
    """F-EDIT-SEQUENCE: see scenes/incremental/edit_sequence.usda."""
    root = copy_scene(Scene.INCREMENTAL, dest) / "edit_sequence.usda"
    yield EditSequenceScene(
        root_layer_path=root,
        stage=open_stage_without_cache(root),
        initial_copies=INITIAL_COPIES,
        steps=_steps(),
        payloaded_copies=frozenset({_plain(LEAF)}),
        guide_copies=frozenset({_plain(GUIDE)}),
        cached_time_codes=(5.0, 10.0),
        keyed_copies=frozenset({_plain(MOVER)}),
        sub_layer_path=root.parent / "edit_sequence_sub.usda",
    )
