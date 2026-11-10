"""A cached display (M4 Phase E, E3): structure built once, each time code's varying values cached as it arrives.

The composed stage's prims don't vary with time, so the display's objects are built once, by the object baseline
or with a minimum batched (E5, cached_batches.py), at the time code of the first synchronization, whichever that
is. Each later synchronization at a time code not
yet cached, in any order, is a single-time capture and plan, whose varying values are added to caches the display
holds, so a cached time code plays back in Blender with no call to the bridge, and the bridge holds only the
current plan. A time code is a frame, its fraction a subframe; Blender shows each time the latest cached time
code at or before it, as keys hold until the next.

- **Objects** follow tracks (frames.py). A track's transform, visibility, and properties (its constant primvars,
  and its object color) are keyframes, one per synchronized time code, constant between them, from the first time
  it varies; it is keyed at every time cached before that with the value it held there. A track absent at a time
  (its copy has no such object there) is hidden there. A track first seen after the structure gets its object
  then, hidden at the times before.
- **A sheared transform** is keyed through a parent empty (apply.shear_split), created when a keyed track is
  first sheared and keyed as the identity at the frames cached before.
- **Batches** hold their tracks as points, whose transforms, destinations, and primvars their carriers' points
  cache; a track whose content leaves its batch's becomes an object then, and one first seen later joins a batch
  of its content if one has it.
- **Meshes** (mesh_caches.py), a track's object's or a batch's prototype's, whose content varies hold each
  synchronization's values of each varying attribute as an attribute `<name>@<sample>` beside it (positions are
  `position@<sample>`), numbered in the order they arrive. A Geometry Nodes modifier on each of its holders
  stores them over the attribute, for the sample its `Sample` input names,
  where it has one (E4: a sample appends in constant time). That input is keyed like the transforms, so the
  modifier and the keys always show the same time; it is -1, the mesh's own values, at the times cached before
  the mesh first varied. A placeholder's bounds are cached the same way, on its bounds mesh.
- **Mesh Sequence Cache modifiers, for comparison (E6):** with `sequence`, a USD file's path, the holders' meshes
  that vary are cached in a USD layer instead, which their modifiers read (sequence_caches.py).
- **A mesh whose topology varies** (E4) caches a whole mesh per sample instead (topology.py), from the first
  time its topology differs from its own, its earlier samples rebuilt from its attributes: a mesh per sample,
  whose geometry its objects' modifiers show by their keyed `Sample` input. Its samples don't blend.
- **Blending (an option, off by default):** with `blend`, a time between two of a mesh's samples shows its float
  attributes (positions, float primvars, colors, bounds) mixed linearly between them, as USD interpolates
  continuous values, and its integer attributes held. The modifier's inputs are then each object's surrounding
  samples and their time codes, keyed constant, and its group weighs them by the scene's time. Only the meshes
  blend: transforms, visibility, and properties hold, and so does any float primvar wherever USD holds it (a
  primvar whose indices alone vary blends anyway), so only a synchronized time is exact.
- **Sharing:** copies whose content is equal share a mesh, so a mesh whose copies come to differ splits, each
  part keeping the frames cached so far. With `predict`, the build's capture dirties what depends on time as a time
  change would (capture.h), and copies the plan finds dirtied in their meshes are split from the others before
  any other time arrives, by the prim whose values they show, so only a misprediction splits later.
- **Not cached here:** a mesh whose material slots vary, a placeholder's bounds that appear or vanish, a track
  whose materials vary while it shows, and a property that can't be keyed raise UncachedError.
- **Any source edit invalidates every cache:** an edit to the stage (Usd.Notice.ObjectsChanged) marks the display,
  and its next synchronization rebuilds it at that time code.
"""

from __future__ import annotations

import time as clock
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import bpy
from apply import (
    apply,
    create_shear_parent,
    new_material,
    new_mesh,
    new_object,
    object_color,
    shear_split,
    sheared,
    usd_matrix_to_blender,
)
from attribute_samples import BASE
from cached_batches import Batches
from frames import DisplayAspect, TrackKey, copy_of, place
from keyframes import AnimationKeyWriter
from mesh_caches import MeshCaches, MeshHolderSynchronizationState, UncachedError
from pxr import Tf, Usd
from sequence_caches import SequenceCaches

if TYPE_CHECKING:
    from collections.abc import Callable

    from mesh_caches import HolderKey
    from plan_types import ObjectRecord, Plan

__all__ = ["CachedDisplay", "Synchronization", "UncachedError"]


@dataclass
class Synchronization:
    """One synchronization: its time code, whether it rebuilt the display, and what it wrote."""

    time: float
    rebuilt: bool
    seconds: dict[str, float]  # by stage
    keyed: int = 0  # tracks keyed at this time code
    written: int = 0  # meshes whose sample attributes were written
    split: int = 0  # meshes split from another


class CachedDisplay:
    """A display of `stage` in `collection`, whose synchronized frames play back from its caches."""

    native: Any
    bridge: Any
    stage: Usd.Stage
    collection: bpy.types.Collection
    predict: bool
    blend: bool  # whether a time between samples mixes them
    settings: dict[str, Any]  # build_plan's
    plan: Plan  # the current plan, the bridge's only one
    cached: dict[float, int]  # the time codes cached, the structure's included, and the sample of each
    synchronized: list[Synchronization]  # every synchronization, in order
    edited: bool  # whether the stage was edited since the structure was built
    objects: dict[TrackKey, bpy.types.Object]
    latest: dict[TrackKey, ObjectRecord]  # each track's record at the latest time it was present
    current: dict[TrackKey, int]  # the present tracks' objects in the current plan
    mesh_index: dict[TrackKey, int | None]  # the present tracks' meshes in the current plan
    keyed: dict[TrackKey, set[DisplayAspect]]  # per track with an object, the aspects it is keyed in
    varied: dict[TrackKey, set[DisplayAspect]]  # per track, the aspects found varying, but in its mesh's cache
    batches: Batches | None  # with a minimum, the batches (E5)
    predicted: dict[tuple[str, tuple[str, ...]], set[DisplayAspect]]  # per copy, the aspects predicted to vary
    materials: list[bpy.types.Material | None]  # by current plan material; None for content not yet shown
    meshes: MeshCaches  # every mesh the tracks' objects show, and the caches of those that vary
    keys: AnimationKeyWriter
    _listener: Any

    def __init__(  # noqa: PLR0913 - the source, the destination, and how it is displayed
        self,
        native: Any,
        stage: Usd.Stage,
        collection: bpy.types.Collection,
        time: float,
        predict: bool = True,
        blend: bool = False,
        minimum: int | None = None,
        sequence: str | None = None,
        **settings: Any,
    ) -> None:
        """With `minimum`, copies alike but for their placement are batched, in groups of at least that many.

        With `sequence`, a USD file's path, meshes cache there, for Mesh Sequence Cache modifiers to read.
        """
        self.native = native
        self.stage = stage
        self.collection = collection
        self.predict = predict
        self.blend = blend
        self.settings = settings
        self.bridge = native.Bridge(stage)
        self.batches = None if minimum is None else Batches(minimum)
        self.meshes = MeshCaches(self._holder) if sequence is None else SequenceCaches(self._holder, sequence)
        self.synchronized = []
        self._listener = Tf.Notice.Register(Usd.Notice.ObjectsChanged, self._on_edit, stage)
        start = clock.perf_counter()
        self._build(time)
        self.synchronized.append(Synchronization(time, True, {"build": clock.perf_counter() - start}))

    def synchronize(self, time: float) -> Synchronization | None:
        """Cache `time` if it isn't yet, or rebuild there after an edit; None if it was cached."""
        if not self.edited and time in self.cached:
            return None
        seconds: dict[str, float] = {}

        def timed[T](name: str, call: Callable[[], T]) -> T:
            start = clock.perf_counter()
            result = call()
            seconds[name] = clock.perf_counter() - start
            return result

        if self.edited:
            timed("remove", self._remove)
            timed("build", lambda: self._build(time))
            result = Synchronization(time, True, seconds)
        else:
            result = Synchronization(time, False, seconds)
            snapshot = timed("capture", lambda: self.bridge.capture(time, incremental=True))
            plan = timed("planning", lambda: self.native.build_plan(snapshot, previous=self.plan, **self.settings))
            diff = timed("diff", lambda: self.native.diff_plans(self.plan, plan))
            timed("cache", lambda: self._cache(time, plan, diff, result))
        self.synchronized.append(result)
        return result

    def install_frame_change_handler(self, scene: bpy.types.Scene, subframes: bool = False) -> Callable[..., None]:
        """Synchronize at `scene`'s frame at each frame change, before Blender evaluates it; returns the handler.

        With `subframes`, at its subframe too; without, a subframe shows its frame. Remove the handler from
        bpy.app.handlers.frame_change_pre to stop following.
        """

        def on_frame(changed: bpy.types.Scene, _depsgraph: Any = None) -> None:
            if changed == scene:
                self.synchronize(changed.frame_current + (changed.frame_subframe if subframes else 0.0))

        bpy.app.handlers.frame_change_pre.append(on_frame)
        return on_frame

    def observed_varying_aspects(self) -> dict[tuple[str, tuple[str, ...]], set[DisplayAspect]]:
        """Per copy, the aspects the time codes synchronized so far found varying."""
        found: dict[tuple[str, tuple[str, ...]], set[DisplayAspect]] = {}
        batched = self.batches.points.keys() if self.batches is not None else set()
        for key in self.objects.keys() | batched:
            aspects = found.setdefault(key[:2], set())
            aspects |= self.varied.get(key, set())
            obj = self.objects.get(key)
            if obj is not None and self.meshes.has_cached_variation(obj.data):
                aspects.add(
                    DisplayAspect.BOUNDS if self.latest[key]["placeholder_type"] is not None else DisplayAspect.MESH
                )
            if self.batches is not None and key in self.batches.held:
                if self.meshes.has_cached_variation(self.batches.points[key][0].prototype.data):
                    aspects.add(DisplayAspect.MESH)
        return found

    def release(self) -> None:
        self._listener.Revoke()
        self.bridge.release()

    def _on_edit(self, _notice: Any, _sender: Any) -> None:
        self.edited = True

    def _holder(self, key: HolderKey) -> bpy.types.Object:
        if self.batches is not None and key[0] == "prototype":
            return self.batches.prototype(key)
        return self.objects[key]  # ty: ignore[invalid-argument-type]

    def _build(self, time: float) -> None:
        """The structure at `time`, by the object baseline or batched, with no time cached but its own."""
        snapshot = self.bridge.capture(time, time_dependencies=self.predict)
        self.plan = self.native.build_plan(snapshot, **self.settings)
        records = dict(enumerate(self.plan.objects))
        self.objects, self.latest, self.current, self.mesh_index = {}, {}, {}, {}
        for index, record in records.items():
            key = (*copy_of(record), place(index, records, {}))
            self.latest[key], self.current[key], self.mesh_index[key] = record, index, record["mesh"]
        self.cached = {time: BASE}
        self.keys = AnimationKeyWriter(self.blend)
        self.meshes.reset(self.keys, self.cached)
        self.keyed, self.varied = {}, {}
        if self.batches is None:
            display = apply(self.plan, self.collection)
            self.materials = list(display.materials)
            self.objects = {key: display.objects[index] for key, index in self.current.items()}
        else:
            materials = [new_material(data) for data in self.plan.materials]
            meshes = [new_mesh(data) for data in self.plan.meshes]
            self.materials = list(materials)
            self.batches.reset()
            self.batches.build(self.latest, _shown, meshes, materials, self.collection)
            for key, index in self.current.items():
                if key not in self.batches.held:
                    self.objects[key] = new_object(index, self.latest[key], meshes, materials, self.collection)
            for batch in self.batches.batches:
                self.meshes.register_mesh_holder(batch.prototype.data, batch.key)
        for key, obj in self.objects.items():
            self.meshes.register_mesh_holder(obj.data, key)
        self.predicted = {}
        for key, record in self.latest.items():
            self.predicted.setdefault(key[:2], set()).update(map(DisplayAspect, record["dirtied_aspects"]))
        self._split_predicted()
        self.edited = False

    def _split_predicted(self) -> None:
        """Give the copies predicted to vary in their meshes their own, one per prim whose values they show."""
        for uid, users in list(self.meshes.users.items()):
            parts: dict[str | None, set[HolderKey]] = {}
            for key in users:
                track = self._track(key)
                varies = {DisplayAspect.MESH, DisplayAspect.BOUNDS} & self.predicted[track[:2]]
                parts.setdefault(_shown(track) if varies else None, set()).add(key)
            self.meshes.split(uid, sorted(parts.values(), key=len, reverse=True))

    def _track(self, key: HolderKey) -> TrackKey:
        """A holder's track: itself, or a prototype's first, whose mesh prediction it shares (cached_batches.py)."""
        if self.batches is not None and key[0] == "prototype":
            return self.batches.batches[key[1]].tracks[0]  # ty: ignore[invalid-argument-type]
        return key  # ty: ignore[invalid-return-type]

    def _cache(self, time: float, plan: Plan, diff: Any, result: Synchronization) -> None:
        """Add `plan`, at `time`, to the caches, from its diff against the current plan."""
        sample = max(self.cached.values()) + 1
        at = {index: key for key, index in self.current.items()}
        changed = set(diff["changed_object_indices"])
        kept = {
            index: at[old]
            for index, old in enumerate(diff["previous_object_indices"])
            if old != -1 and index not in changed
        }
        read = [index for index in range(plan.object_count) if index not in kept]
        records = dict(zip(read, plan.objects_at(read), strict=True))
        fresh = {(*copy_of(record), place(index, records, kept)): record for index, record in records.items()}
        present = {key: index for index, key in kept.items()} | {
            key: index for key, index in zip(fresh, records, strict=True)
        }
        self.materials = [self.materials[old] if old != -1 else None for old in diff["previous_material_indices"]]
        old_meshes = {old: new for new, old in enumerate(diff["previous_mesh_indices"]) if old != -1}
        mesh_index = {key: fresh[key]["mesh"] if key in fresh else self._kept_mesh(key, old_meshes) for key in present}
        batched = self.batches.points.keys() if self.batches is not None else set()
        new = sorted(fresh.keys() - self.objects.keys() - batched)
        regrouped = None
        if self.batches is not None:
            regrouped = self.batches.regroup(present, fresh, mesh_index, self.latest, new, diff, self._material_or_new)
            for key, aspects in regrouped.varied.items():
                self.varied.setdefault(key, set()).update(aspects)
            new = [key for key in new if key not in regrouped.joined]
            for key in regrouped.leaving:  # shown by its batch until now
                self._add_track(key, fresh[key], plan, mesh_index, arrived=False)
        for key in new:
            self._add_track(key, fresh[key], plan, mesh_index)
        now = MeshHolderSynchronizationState(
            plan,
            diff,
            {key: index for key, index in present.items() if key in self.objects},
            {key: record for key, record in fresh.items() if key in self.objects},
            {**mesh_index},
            {**self.mesh_index},
            {**self.latest},
        )
        if regrouped is not None:
            for holder, (index, record, mesh, before) in regrouped.holders.items():
                now.present[holder], now.mesh_index[holder], now.previous[holder] = index, mesh, before
                now.latest[holder] = self._holder_record(holder)
                if record is not None:
                    now.fresh[holder] = record
        result.split, result.written = self.meshes.cache((time, sample), now)
        if self.batches is not None and regrouped is not None:
            moved = {key for key in self.batches.points if (key in present) != (key in self.current)}
            changed = fresh.keys() | moved | set(regrouped.joined) | set(regrouped.leaving)
            result.written += self.batches.write(self.meshes, (time, sample), present, fresh, self.latest, changed)
        result.keyed = self._key_tracks(time, present, {k: r for k, r in fresh.items() if k in self.objects})
        self.latest |= fresh
        self.plan, self.current, self.mesh_index = plan, present, mesh_index
        self.cached[time] = sample

    def _kept_mesh(self, key: TrackKey, old_meshes: dict[int, int]) -> int | None:
        old = self.mesh_index[key]
        return None if old is None else old_meshes[old]

    def _holder_record(self, key: HolderKey) -> ObjectRecord:
        """A prototype's record: a track's at the latest time one of its batch was present."""
        assert self.batches is not None  # noqa: S101 - only batches have prototypes
        return self.batches.batches[key[1]].record  # ty: ignore[invalid-argument-type]

    def _material_or_new(self, index: int) -> Any:
        """A plan material's Blender material, or for one not yet shown, a value no material equals."""
        return self.materials[index] or ("new", index)

    def _add_track(  # noqa: PLR0913 - the track, its plan, and why it has no object yet
        self,
        key: TrackKey,
        record: ObjectRecord,
        plan: Plan,
        mesh_index: dict[TrackKey, int | None],
        arrived: bool = True,
    ) -> None:
        """An object for a track first present now, hidden at the frames cached before.

        With `arrived` false, the track was a batch's until now. `mesh_index` holds the present tracks' meshes in
        `plan`.
        """
        mesh = None
        if record["mesh"] is not None:
            # A mesh another track or a batch shows the same content on now, or a new one.
            shared = [self.objects[k].data for k, i in mesh_index.items() if i == record["mesh"] and k in self.objects]
            batches = self.batches.batches if self.batches is not None else []
            shared += [b.prototype.data for b in batches if b.mesh == record["mesh"]]
            mesh = shared[0] if shared else new_mesh(plan.meshes_at([record["mesh"]])[0])
        slots: list[Any] = [None if m is None else self._material(m, plan) for m in record["material_slots"]]
        data: Any = {
            **record,
            "mesh": None if mesh is None else 0,
            "material_slots": [None if m is None else slot for slot, m in enumerate(record["material_slots"])],
        }
        obj = new_object(-1, data, [mesh], slots, self.collection)  # ty: ignore[invalid-argument-type]
        self.objects[key], self.latest[key] = obj, record
        self.meshes.register_mesh_holder(obj.data, key)
        for cached in self.cached:
            self._key_visibility(key, cached, None)
        self.keyed[key] = {DisplayAspect.VISIBILITY}
        if arrived:
            self.varied.setdefault(key, set()).add(DisplayAspect.VISIBILITY)

    def _material(self, index: int, plan: Plan) -> bpy.types.Material:
        material = self.materials[index]
        if material is None:
            material = self.materials[index] = new_material(plan.materials[index])
        return material

    def _key_tracks(self, time: float, present: dict[TrackKey, int], fresh: dict[TrackKey, ObjectRecord]) -> int:
        """Key each track that varies at `time`; the tracks keyed."""
        keyed = 0
        for key in fresh.keys() | self.keyed.keys() | (self.objects.keys() - present.keys()):
            record = (fresh.get(key) or self.latest[key]) if key in present else None
            found = self._differences(key, record) if key in fresh or record is None else set()
            for aspect in found - self.keyed.get(key, set()):
                for cached in self.cached:  # what it held at each time cached before
                    self._key(aspect, key, cached, self.latest[key])
            aspects = self.keyed.setdefault(key, set())
            aspects |= found
            self.varied.setdefault(key, set()).update(found)
            for aspect in aspects:
                if record is not None or aspect == DisplayAspect.VISIBILITY:
                    self._key(aspect, key, time, record)
            keyed += bool(aspects)
        return keyed

    def _differences(self, key: TrackKey, record: ObjectRecord | None) -> set[DisplayAspect]:
        """The aspects `record` changes from the track's latest one; an absent track's visibility."""
        old = self.latest[key]
        if record is None:
            return {DisplayAspect.VISIBILITY} if old["viewport"] or old["render"] else set()
        found: set[DisplayAspect] = set()
        if record["matrix"] != old["matrix"]:
            found.add(DisplayAspect.TRANSFORM)
        if (record["viewport"], record["render"]) != (old["viewport"], old["render"]):
            found.add(DisplayAspect.VISIBILITY)
        if record["properties"] != old["properties"]:
            found.add(DisplayAspect.PROPERTIES)
        if record["viewport"] or record["render"]:
            slots = self.objects[key].material_slots
            materials = [None if m is None else self.materials[m] for m in record["material_slots"]]
            if any(slot.material != m for slot, m in zip(slots, materials, strict=True)):
                raise UncachedError(f"{key[0]}: its {DisplayAspect.MATERIALS} vary")
        return found

    def _key(self, aspect: DisplayAspect, key: TrackKey, time: float, record: ObjectRecord | None) -> None:
        if aspect == DisplayAspect.VISIBILITY:
            self._key_visibility(key, time, record)
        elif aspect == DisplayAspect.TRANSFORM and record is not None:
            self._key_transform(key, time, record)
        elif aspect == DisplayAspect.PROPERTIES and record is not None:
            self._key_properties(key, time, record)

    def _key_visibility(self, key: TrackKey, time: float, record: ObjectRecord | None) -> None:
        obj = self.objects[key]
        self.keys.insert(obj, "hide_viewport", 0, time, record is None or not record["viewport"])
        self.keys.insert(obj, "hide_render", 0, time, record is None or not record["render"])

    def _key_transform(self, key: TrackKey, time: float, record: ObjectRecord) -> None:
        obj = self.objects[key]
        placed = usd_matrix_to_blender(record["matrix"])
        if obj.parent is None and sheared(placed):
            parent = create_shear_parent(obj, key[0], self.collection)
            for cached in self.cached:  # the identity, under the object's own keys
                self.keys.insert_transform(parent, cached)
        if obj.parent is None:
            obj.matrix_basis = placed
        else:
            obj.parent.matrix_basis, obj.matrix_basis = shear_split(placed)
            self.keys.insert_transform(obj.parent, time)
        self.keys.insert_transform(obj, time)

    def _key_properties(self, key: TrackKey, time: float, record: ObjectRecord) -> None:
        obj = self.objects[key]
        for index, channel in enumerate(object_color(record)):
            self.keys.insert(obj, "color", index, time, channel)
        for name, value in record["properties"].items():
            values = value if isinstance(value, list) else [value]
            if name not in obj or not all(isinstance(v, (bool, int, float)) for v in values):
                raise UncachedError(f"{key[0]}: its property {name} can't be keyed")
            for index, channel in enumerate(values):
                self.keys.insert(obj, f'["{name}"]', index, time, float(channel))  # ty: ignore[invalid-argument-type]

    def _remove(self) -> None:
        """Remove everything the display made but its node groups."""
        objects = list(self.collection.all_objects)
        objects += [b.prototype for b in self.batches.batches] if self.batches is not None else []
        data: set[Any] = {o.data for o in objects if o.data is not None} | self.meshes.datablocks()
        materials = {m for m in self.materials if m is not None}
        materials |= {s.material for o in objects for s in o.material_slots if s.material is not None}
        actions = {o.animation_data.action for o in objects if o.animation_data and o.animation_data.action}
        bpy.data.batch_remove([*objects, *data, *materials, *actions])


def _shown(key: TrackKey) -> str:
    """The prim whose values a track shows, as far as its source tells.

    Inside an instance, that is its path below the innermost instance root, which every instance shares. Prims of
    different prototypes at the same path below their roots look alike; a split corrects that later.
    """
    source, context = key[0], key[1]
    return source.removeprefix(context[-1]) if context else source
