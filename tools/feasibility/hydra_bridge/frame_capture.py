"""Every frame of a range, captured incrementally, and what varies between frames (M4 Phase E, E1).

Each frame is one capture and one plan, the plan reusing the previous frame's mesh builds (D9). The plan diff
says which objects each frame keeps unchanged, so only the others' records are read. A track is one object of
one drawn copy followed across frames: its source, its instance context, and its place among the copy's objects
(a copy shown in both destinations with different materials has two, the viewport's first). A copy's objects
change identity when its destinations do, so a track is what stays one object of an animated display while its
visibility changes.

Only the first frame's plan is kept. Later frames keep the records that changed and the meshes and materials of
new content: holding every plan of ALab's range took about 109 MB a frame (ad hoc), mostly mesh arrays a frame
rebuilds unchanged.

No bpy import: this is the layer above capture that the animation-data representations build from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

    from plan_types import MaterialRecord, MeshRecord, ObjectRecord, Plan

type TrackKey = tuple[str, tuple[str, ...], int]  # source, instance context, place among the copy's objects


class DisplayAspect(StrEnum):
    """An aspect of an object that can vary along a track, by the record fields compared.

    The values are the core's names for them (plan.h's AspectName).
    """

    TRANSFORM = "transform"  # matrix
    VISIBILITY = "visibility"  # the destinations it shows in, or whether the copy has this object at all
    MESH = "mesh"  # its mesh's content (B5), held color included
    MATERIALS = "materials"  # the material each slot holds, by content
    PROPERTIES = "properties"  # constant primvars as ID properties
    BOUNDS = "bounds"  # a placeholder's bounds


@dataclass
class CapturedFrameSequence:
    """A range's first plan, its tracks, and what changes along them."""

    time_codes: list[float]
    first_plan: Plan
    object_indices_by_track: dict[
        TrackKey, list[int | None]
    ]  # per track, per frame: its object's plan index, None when absent
    # Per track, by frame: its record wherever it changed (always at its first frame), held until the next.
    records_by_track_and_frame: dict[TrackKey, dict[int, ObjectRecord]]
    varying_aspects_by_track: dict[
        TrackKey, set[DisplayAspect]
    ]  # per track, the aspects that vary anywhere in the range; empty if none
    # Per frame, per mesh and per material: an identifier of its content, equal across frames for equal content.
    mesh_content_ids_by_frame: list[list[int]]
    material_content_ids_by_frame: list[list[int]]
    # By content identifier, for content first seen after the first frame (the first plan holds the rest).
    mesh_records_by_content_id: dict[int, MeshRecord] = field(default_factory=dict)
    material_records_by_content_id: dict[int, MaterialRecord] = field(default_factory=dict)

    def record(self, key: TrackKey, frame: int) -> ObjectRecord | None:
        """The track's record at `frame`: the last change at or before it, or None when it is absent."""
        if self.object_indices_by_track[key][frame] is None:
            return None
        return self.records_by_track_and_frame[key][max(f for f in self.records_by_track_and_frame[key] if f <= frame)]


def capture_frames(native: Any, bridge: Any, times: Sequence[float], **settings: Any) -> CapturedFrameSequence:
    """Capture and plan each of `times` on `bridge`, incrementally after the first; `settings` go to build_plan."""
    plan = native.build_plan(bridge.capture(times[0]), **settings)
    ids = _Identifiers()
    frames = CapturedFrameSequence([], plan, {}, {}, {}, [], [])
    current: dict[TrackKey, int] = {}  # by track, its object at the latest frame
    previous: Plan | None = None
    for frame, time in enumerate(times):
        if previous is None:
            kept: dict[int, TrackKey] = {}
            meshes, materials = ids.new(plan.mesh_count), ids.new(plan.material_count)
        else:
            plan = native.build_plan(bridge.capture(time, incremental=True), previous=previous, **settings)
            diff = native.diff_plans(previous, plan)
            meshes = ids.matched(diff["previous_mesh_indices"], frames.mesh_content_ids_by_frame[-1])
            materials = ids.matched(diff["previous_material_indices"], frames.material_content_ids_by_frame[-1])
            _keep_new(frames.mesh_records_by_content_id, diff["previous_mesh_indices"], meshes, plan.meshes_at)
            _keep_new(
                frames.material_records_by_content_id, diff["previous_material_indices"], materials, _materials_at(plan)
            )
            at = {index: key for key, index in current.items()}
            changed = set(diff["changed_object_indices"])
            kept = {
                i: at[old] for i, old in enumerate(diff["previous_object_indices"]) if old != -1 and i not in changed
            }
        frames.time_codes.append(time)
        frames.mesh_content_ids_by_frame.append(meshes)
        frames.material_content_ids_by_frame.append(materials)
        read = [i for i in range(plan.object_count) if i not in kept]
        records = dict(zip(read, plan.objects_at(read), strict=True))
        current = {key: index for index, key in kept.items()}
        for index, record in records.items():
            key = (*copy_of(record), place(index, records, kept))
            samples = frames.records_by_track_and_frame.setdefault(key, {})
            if samples:
                last = max(samples)
                frames.varying_aspects_by_track[key] |= _differences(frames, last, samples[last], frame, record)
            else:
                frames.object_indices_by_track[key] = [None] * frame
                # A copy's object that appears mid-range.
                frames.varying_aspects_by_track[key] = {DisplayAspect.VISIBILITY} if frame else set()
            samples[frame] = record
            current[key] = index
        for key, track in frames.object_indices_by_track.items():
            track.append(current.get(key))
            if key not in current:
                frames.varying_aspects_by_track[key].add(
                    DisplayAspect.VISIBILITY
                )  # the copy has no such object at this frame
        previous = plan
    return frames


class _Identifiers:
    """Content identifiers for meshes or materials, carried across frames by the diff's matches."""

    _next: int

    def __init__(self) -> None:
        self._next = 0

    def new(self, count: int) -> list[int]:
        start = self._next
        self._next += count
        return list(range(start, self._next))

    def matched(self, matches: list[int], before: list[int]) -> list[int]:
        return [before[match] if match != -1 else self.new(1)[0] for match in matches]


def _keep_new(kept: dict[int, Any], matches: list[int], ids: list[int], records_at: Any) -> None:
    new = [index for index, match in enumerate(matches) if match == -1]
    kept.update(zip((ids[index] for index in new), records_at(new), strict=True))


def _materials_at(plan: Plan) -> Any:
    def at(indices: list[int]) -> list[MaterialRecord]:
        if not indices:
            return []
        materials = plan.materials  # the plan has no materials_at; materials are few
        return [materials[index] for index in indices]

    return at


def copy_of(record: ObjectRecord) -> tuple[str, tuple[str, ...]]:
    """The drawn copy an object belongs to: its source and instance context."""
    return record["source"], tuple(record["instance_context"])


def place(index: int, records: dict[int, ObjectRecord], kept: dict[int, TrackKey]) -> int:
    """1 for the second of a copy's two objects, else 0: the planner puts a copy's objects next to each other."""
    if index == 0:
        return 0
    before = kept[index - 1][:2] if index - 1 in kept else copy_of(records[index - 1])
    return 1 if before == copy_of(records[index]) else 0


def _differences(
    frames: CapturedFrameSequence, then: int, old: ObjectRecord, frame: int, new: ObjectRecord
) -> set[DisplayAspect]:
    """What differs between a track's record at frame `then` and at `frame`, meshes and materials by content."""

    def mesh(at: int, record: ObjectRecord) -> int | None:
        return None if record["mesh"] is None else frames.mesh_content_ids_by_frame[at][record["mesh"]]

    def slots(at: int, record: ObjectRecord) -> list[int | None]:
        return [None if m is None else frames.material_content_ids_by_frame[at][m] for m in record["material_slots"]]

    found: set[DisplayAspect] = set()
    if old["matrix"] != new["matrix"]:
        found.add(DisplayAspect.TRANSFORM)
    if (old["viewport"], old["render"]) != (new["viewport"], new["render"]):
        found.add(DisplayAspect.VISIBILITY)
    if mesh(then, old) != mesh(frame, new):
        found.add(DisplayAspect.MESH)
    if slots(then, old) != slots(frame, new):
        found.add(DisplayAspect.MATERIALS)
    if old["properties"] != new["properties"]:
        found.add(DisplayAspect.PROPERTIES)
    if old["bounds"] != new["bounds"]:
        found.add(DisplayAspect.BOUNDS)
    return found
