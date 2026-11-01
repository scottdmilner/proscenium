"""A cached display (M4 Phase E, E3): structure built once, each time code's varying values cached as it arrives.

The composed stage's prims don't vary with time, so the display's objects are built once, by the object baseline
at the time code of the first synchronization, whichever that is. Each later synchronization at a time code not
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
- **Meshes** whose content varies hold each synchronization's values of each varying attribute as an attribute
  `<name>@<sample>` beside it (positions are `position@<sample>`), numbered in the order they arrive. A Geometry
  Nodes modifier on each of its objects stores them over the attribute, for the sample its `Sample` input names,
  where it has one (E4: a sample appends in constant time). That input is keyed like the transforms, so the
  modifier and the keys always show the same time; it is -1, the mesh's own values, at the times cached before
  the mesh first varied. A placeholder's bounds are cached the same way, on its bounds mesh.
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
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import bpy
import numpy
from apply import (
    BufferFormat,
    Layer,
    apply,
    flat,
    layers,
    new_material,
    new_mesh,
    new_object,
    object_color,
    shear_parent,
    shear_split,
    sheared,
    world,
)
from attribute_samples import (
    BASE,
    FRAME_SEPARATOR,
    MODIFIER,
    NEXT,
    NEXT_TIME,
    SAMPLE,
    TIME,
    Signature,
    frames_group,
    input_path,
    remove_samples,
    sample_mesh,
    stored,
)
from bpy_extras import anim_utils
from frames import Aspect, TrackKey, copy_of, place
from pxr import Tf, Usd
from topology import MeshSamples, samples_group

if TYPE_CHECKING:
    from collections.abc import Callable

    from plan_types import MeshRecord, ObjectRecord, Plan

TRANSFORM_PATHS = ("location", "rotation_euler", "scale")

type ContentKey = tuple[str, Any]  # ("mesh", plan mesh index) or ("bounds", its bounds)


class UncachedError(Exception):
    """A value varies that this display doesn't cache."""


@dataclass
class MeshCache:
    """What a mesh with cached frames holds: its own values, the latest frame's, and which attributes vary.

    Once its topology varies, its whole meshes, and no attributes.
    """

    base: dict[str, Layer]  # the values the mesh itself holds, by attribute
    latest: dict[str, Layer]  # its values at the latest synchronization that wrote it
    varying: dict[str, Layer] = field(default_factory=dict)  # by attribute, a layer of its kind
    whole: MeshSamples | None = None  # its whole meshes, once its topology varies, which split parts share
    shown: int = BASE  # of those, the sample at its latest synchronization


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
    keyed: dict[TrackKey, set[Aspect]]  # per track, the aspects it is keyed in
    predicted: dict[tuple[str, tuple[str, ...]], set[Aspect]]  # per copy, the aspects predicted to vary
    materials: list[bpy.types.Material | None]  # by current plan material; None for content not yet shown
    meshes: dict[int, bpy.types.Mesh]  # by session_uid: every mesh the tracks' objects use
    users: dict[int, set[TrackKey]]  # by mesh session_uid, the tracks whose objects use it
    caches: dict[int, MeshCache]  # by mesh session_uid, the meshes that hold frames
    groups: dict[Signature, bpy.types.NodeTree]  # the frames' node group for each set of varying attributes
    whole_group: bpy.types.NodeTree | None  # the whole meshes' node group, once a mesh's topology varies
    _channels: dict[int, Any]  # by object session_uid, its action's channelbag
    _timelines: dict[int, dict[float, int]]  # by object session_uid, the sample keyed at each time
    _listener: Any

    def __init__(  # noqa: PLR0913 - the source, the destination, and how it is displayed
        self,
        native: Any,
        stage: Usd.Stage,
        collection: bpy.types.Collection,
        time: float,
        predict: bool = True,
        blend: bool = False,
        **settings: Any,
    ) -> None:
        self.native = native
        self.stage = stage
        self.collection = collection
        self.predict = predict
        self.blend = blend
        self.settings = settings
        self.bridge = native.Bridge(stage)
        self.groups = {}
        self.whole_group = None
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

    def follow(self, scene: bpy.types.Scene, subframes: bool = False) -> Callable[..., None]:
        """Synchronize at `scene`'s frame at each frame change, before Blender evaluates it; returns the handler.

        With `subframes`, at its subframe too; without, a subframe shows its frame. Remove the handler from
        bpy.app.handlers.frame_change_pre to stop following.
        """

        def on_frame(changed: bpy.types.Scene, _depsgraph: Any = None) -> None:
            if changed == scene:
                self.synchronize(changed.frame_current + (changed.frame_subframe if subframes else 0.0))

        bpy.app.handlers.frame_change_pre.append(on_frame)
        return on_frame

    def confirmed(self) -> dict[tuple[str, tuple[str, ...]], set[Aspect]]:
        """Per copy, the aspects the time codes synchronized so far found varying."""
        found: dict[tuple[str, tuple[str, ...]], set[Aspect]] = {}
        for key, obj in self.objects.items():
            aspects = found.setdefault(key[:2], set())
            aspects |= self.keyed.get(key, set())
            cache = self.caches.get(_uid(obj.data)) if obj.data is not None else None
            if cache is not None and (cache.varying or cache.whole is not None):
                aspects.add(Aspect.BOUNDS if self.latest[key]["placeholder_type"] is not None else Aspect.MESH)
        return found

    def release(self) -> None:
        self._listener.Revoke()
        self.bridge.release()

    def _on_edit(self, _notice: Any, _sender: Any) -> None:
        self.edited = True

    def _build(self, time: float) -> None:
        """The structure at `time`, by the object baseline, with no time cached but its own."""
        snapshot = self.bridge.capture(time, time_dependencies=self.predict)
        self.plan = self.native.build_plan(snapshot, **self.settings)
        display = apply(self.plan, self.collection)
        records = dict(enumerate(self.plan.objects))
        self.objects, self.latest, self.current, self.mesh_index = {}, {}, {}, {}
        for index, record in records.items():
            key = (*copy_of(record), place(index, records, {}))
            self.objects[key], self.latest[key] = display.objects[index], record
            self.current[key], self.mesh_index[key] = index, record["mesh"]
        self.materials = list(display.materials)
        self.meshes, self.users, self.caches, self.keyed, self._channels = {}, {}, {}, {}, {}
        self._timelines = {}
        for key, obj in self.objects.items():
            self._use(obj.data, key)
        self.predicted = {}
        for key, record in self.latest.items():
            self.predicted.setdefault(key[:2], set()).update(map(Aspect, record["dirtied_aspects"]))
        self._split_predicted()
        self.cached = {time: BASE}
        self.edited = False

    def _split_predicted(self) -> None:
        """Give the copies predicted to vary in their meshes their own, one per prim whose values they show."""
        for uid, users in list(self.users.items()):
            parts: dict[str | None, set[TrackKey]] = {}
            for key in users:
                varies = {Aspect.MESH, Aspect.BOUNDS} & self.predicted[key[:2]]
                parts.setdefault(_shown(key) if varies else None, set()).add(key)
            self._split(uid, sorted(parts.values(), key=len, reverse=True))

    def _use(self, data: Any, key: TrackKey) -> None:
        if isinstance(data, bpy.types.Mesh):
            self.meshes[_uid(data)] = data
            self.users.setdefault(_uid(data), set()).add(key)

    def _split(self, uid: int, parts: list[set[TrackKey]]) -> int:
        """Keep the first part's tracks on the mesh, and give each other part a copy of it; the copies made."""
        mesh = self.meshes[uid]
        for part in parts[1:]:
            copy = mesh.copy()  # with the frames it holds
            self.meshes[_uid(copy)] = copy
            self.users[_uid(copy)] = part
            self.users[uid] -= part
            cache = self.caches.get(uid)
            if cache is not None:
                self.caches[_uid(copy)] = MeshCache(
                    cache.base, cache.latest, dict(cache.varying), cache.whole, cache.shown
                )
            for key in part:
                self.objects[key].data = copy  # shown its store when it is next written, as every part is
        return len(parts) - 1

    def _cache(self, time: float, plan: Plan, diff: Any, result: Synchronization) -> None:
        """Add `plan`, at `time`, to the caches, from its diff against the current plan."""
        sample = max(self.cached.values()) + 1
        at = {index: key for key, index in self.current.items()}
        changed = set(diff["changed"])
        kept = {index: at[old] for index, old in enumerate(diff["objects"]) if old != -1 and index not in changed}
        read = [index for index in range(plan.object_count) if index not in kept]
        records = dict(zip(read, plan.objects_at(read), strict=True))
        fresh = {(*copy_of(record), place(index, records, kept)): record for index, record in records.items()}
        present = {key: index for index, key in kept.items()} | {
            key: index for key, index in zip(fresh, records, strict=True)
        }
        self.materials = [self.materials[old] if old != -1 else None for old in diff["materials"]]
        old_meshes = {old: new for new, old in enumerate(diff["meshes"]) if old != -1}
        mesh_index = {key: fresh[key]["mesh"] if key in fresh else self._kept_mesh(key, old_meshes) for key in present}
        for key in sorted(fresh.keys() - self.objects.keys()):
            self._add_track(key, fresh[key], plan, mesh_index)
        result.split, result.written = self._cache_meshes((time, sample), plan, diff, present, fresh, mesh_index)
        result.keyed = self._key_tracks(time, present, fresh)
        self.latest |= fresh
        self.plan, self.current, self.mesh_index = plan, present, mesh_index
        self.cached[time] = sample

    def _kept_mesh(self, key: TrackKey, old_meshes: dict[int, int]) -> int | None:
        old = self.mesh_index[key]
        return None if old is None else old_meshes[old]

    def _add_track(
        self, key: TrackKey, record: ObjectRecord, plan: Plan, mesh_index: dict[TrackKey, int | None]
    ) -> None:
        """An object for a track first present now, hidden at the frames cached before.

        `mesh_index` holds the present tracks' meshes in `plan`.
        """
        mesh = None
        if record["mesh"] is not None:
            # A mesh another track shows the same content on now, or a new one.
            shared = [k for k, i in mesh_index.items() if i == record["mesh"] and k in self.objects]
            mesh = self.objects[shared[0]].data if shared else new_mesh(plan.meshes_at([record["mesh"]])[0])
        slots: list[Any] = [None if m is None else self._material(m, plan) for m in record["material_slots"]]
        data: Any = {
            **record,
            "mesh": None if mesh is None else 0,
            "material_slots": [None if m is None else slot for slot, m in enumerate(record["material_slots"])],
        }
        obj = new_object(-1, data, [mesh], slots, self.collection)  # ty: ignore[invalid-argument-type]
        self.objects[key], self.latest[key] = obj, record
        self._use(obj.data, key)
        for cached in self.cached:
            self._key_visibility(key, cached, None)
        self.keyed[key] = {Aspect.VISIBILITY}

    def _material(self, index: int, plan: Plan) -> bpy.types.Material:
        material = self.materials[index]
        if material is None:
            material = self.materials[index] = new_material(plan.materials[index])
        return material

    def _cache_meshes(  # noqa: PLR0913 - one time's plan, its diff, and its tracks
        self,
        at: tuple[float, int],  # the time code and its sample
        plan: Plan,
        diff: Any,
        present: dict[TrackKey, int],
        fresh: dict[TrackKey, ObjectRecord],
        mesh_index: dict[TrackKey, int | None],
    ) -> tuple[int, int]:
        """Write the sample attributes of each mesh whose content varies; the meshes split, and those written."""

        def content_key(key: TrackKey) -> ContentKey:
            index = mesh_index[key]
            return ("mesh", index) if index is not None else ("bounds", _bounds_key(self._record(key, fresh)))

        def same(key: TrackKey) -> bool:  # whether its content is what it was at the current plan
            if key not in fresh:
                return True
            if key not in self.mesh_index:
                return False
            index = mesh_index[key]
            if index is None:
                return _bounds_key(fresh[key]) == _bounds_key(self.latest[key])
            return diff["meshes"][index] == self.mesh_index[key]

        touched = {_uid(self.objects[key].data) for key in present if not same(key)} & self.meshes.keys()
        touched |= {uid for uid, cache in self.caches.items() if cache.varying or cache.whole is not None}
        split = written = 0
        for uid in touched:
            users = sorted(k for k in self.users[uid] if k in present)
            if not users:
                continue  # hidden here, so it shows what it holds
            parts: dict[ContentKey, list[TrackKey]] = {}
            for key in users:
                parts.setdefault(content_key(key), []).append(key)
            # The part whose content is unchanged keeps the mesh, so a mesh with no cache stays one.
            ordered = sorted(parts.items(), key=lambda item: (not all(same(k) for k in item[1]), -len(item[1])))
            split += self._split(uid, [set(keys) for _, keys in ordered])
            for content, keys in ordered:
                part_uid = _uid(self.objects[keys[0]].data)
                cache = self.caches.get(part_uid)
                record = None
                if all(same(k) for k in keys):
                    if cache is None:
                        continue  # what the mesh holds
                    values = cache.latest
                else:
                    values, record = self._content(content, keys[0], plan, fresh)
                if record is not None and (
                    (cache is not None and cache.whole is not None) or not self._same_topology(keys[0], values, record)
                ):
                    cache = self._whole(part_uid, cache)
                if cache is not None and cache.whole is not None:
                    self._write_whole(part_uid, cache, record, at[0])
                    written += 1
                    continue
                cache = cache or self._new_cache(part_uid, values, keys[0])
                if self._write(part_uid, cache, values, at):
                    written += 1
        return split, written

    def _record(self, key: TrackKey, fresh: dict[TrackKey, ObjectRecord]) -> ObjectRecord:
        return fresh.get(key) or self.latest[key]

    def _content(
        self, content: ContentKey, key: TrackKey, plan: Plan, fresh: dict[TrackKey, Any]
    ) -> tuple[dict[str, Layer], MeshRecord | None]:
        """A content's attributes, and for a mesh its plan record; a placeholder's are its bounds."""
        kind, index = content
        if kind == "mesh":
            record = plan.meshes_at([index])[0]
            return {layer.name: layer for layer in layers(record)}, record
        return {"position": _bounds_layer(self._record(key, fresh)["bounds"])}, None

    def _same_topology(self, key: TrackKey, found: dict[str, Layer], record: MeshRecord) -> bool:
        """Whether content has the faces, corners, material slots, and attributes of the mesh it would cache on."""
        topology = (flat(record["corner_verts"], BufferFormat.INT), flat(record["face_offsets"], BufferFormat.INT))
        mesh: Any = self.objects[key].data
        corners = numpy.empty(len(mesh.loops), numpy.int32)
        starts = numpy.empty(len(mesh.polygons), numpy.int32)
        if len(corners):
            mesh.attributes[".corner_vert"].data.foreach_get("value", corners)
        mesh.polygons.foreach_get("loop_start", starts)
        names = {a.name for a in mesh.attributes if FRAME_SEPARATOR not in a.name and not a.name.startswith(".")}
        return (
            len(found["position"].values) == 3 * len(mesh.vertices)
            and numpy.array_equal(corners, numpy.frombuffer(topology[0], numpy.int32))
            and numpy.array_equal(starts, numpy.frombuffer(topology[1], numpy.int32))
            and record["slot_count"] == len(mesh.materials)
            and found.keys() <= names
        )

    def _whole_group(self) -> bpy.types.NodeTree:
        if self.whole_group is None:
            self.whole_group = samples_group()
        return self.whole_group

    def _whole(self, uid: int, cache: MeshCache | None) -> MeshCache:
        """The cache of whole meshes of a mesh whose topology first varies, holding the samples shown so far.

        Each time cached before shows what the mesh showed there: its own values, or a sample of its attributes,
        which the mesh then no longer holds.
        """
        if cache is not None and cache.whole is not None:
            return cache
        mesh: Any = self.meshes[uid]
        store = MeshSamples(mesh.name)
        objects = [self.objects[key] for key in sorted(self.users[uid])]
        timeline = self._timelines.get(_uid(objects[0]), {})
        for obj in objects:
            self._unkey_inputs(obj)
            store.show(_modifier(obj), self._whole_group())
        varying = cache.varying if cache is not None else {}
        added: dict[int, int] = {}  # by sample of its attributes, the store's
        for time in sorted(self.cached):
            sample = timeline.get(time, BASE)
            if sample not in added:
                added[sample] = store.add(sample_mesh(mesh, sample, varying))
            for obj in objects:
                self._insert(obj, input_path(SAMPLE), 0, time, added[sample])
        remove_samples(mesh)
        whole = self.caches[uid] = MeshCache({}, {}, whole=store)
        return whole

    def _unkey_inputs(self, obj: bpy.types.Object) -> None:
        """Remove the keys of `obj`'s modifier inputs, which an attribute cache keyed."""
        channels = self._channels.get(_uid(obj))
        curves = channels.fcurves if channels is not None else []
        for curve in [c for c in curves if c.data_path.startswith(f'modifiers["{MODIFIER}"]')]:
            curves.remove(curve)
        self._timelines.pop(_uid(obj), None)

    def _write_whole(self, uid: int, cache: MeshCache, record: MeshRecord | None, time: float) -> None:
        """Add the whole mesh `record` as the sample of `time`, or for None the one shown at the latest again."""
        assert cache.whole is not None  # noqa: S101 - a whole cache
        if record is not None and record["slot_count"] != len(self.meshes[uid].materials):
            raise UncachedError(f"{self.meshes[uid].name}: its material slots vary")
        if record is not None:
            cache.shown = cache.whole.add(new_mesh(record))
        for key in self.users[uid]:
            obj = self.objects[key]
            cache.whole.show(_modifier(obj), self._whole_group())
            self._insert(obj, input_path(SAMPLE), 0, time, cache.shown)

    def _new_cache(self, uid: int, content: dict[str, Layer], key: TrackKey) -> MeshCache:
        """The cache of a mesh first found to vary, whose own values are the frames' before."""
        mesh: Any = self.meshes[uid]
        if self.latest[key]["mesh"] is None and content["position"].values.size != 3 * len(mesh.vertices):
            raise UncachedError(f"{key[0]}: its placeholder's bounds appear or vanish")
        base = {}
        for name, layer in content.items():
            values = numpy.empty_like(layer.values)
            mesh.attributes[name].data.foreach_get(layer.prop, values)
            base[name] = Layer(name, layer.data_type, layer.domain, layer.prop, values)
        cache = self.caches[uid] = MeshCache(base, base)
        return cache

    def _write(self, uid: int, cache: MeshCache, content: dict[str, Layer], at: tuple[float, int]) -> bool:
        """Add `content`'s varying attributes as the sample of `at`, first finding which vary; whether any were.

        Each object of the mesh is keyed to show that sample at that time.
        """
        mesh: Any = self.meshes[uid]
        time, sample = at
        added = {
            name: layer
            for name, layer in content.items()
            if name not in cache.varying and not numpy.array_equal(layer.values, cache.base[name].values)
        }
        objects = [self.objects[key] for key in self.users[uid]]
        if added:
            first = not cache.varying
            cache.varying |= added
            group = self._group(cache)
            for obj in objects:
                _modifier(obj).node_group = group
                for cached in self.cached if first else ():  # the mesh's own values, before it varied
                    self._key_sample(obj, cached, BASE)
        for name in cache.varying:
            layer = content[name]
            held = stored(layer)
            attribute = mesh.attributes.new(f"{name}{FRAME_SEPARATOR}{sample}", held.data_type, layer.domain)
            attribute.data.foreach_set(held.prop, held.values)
        if cache.varying:
            for obj in objects:
                self._key_sample(obj, time, sample)
        cache.latest = content
        return bool(cache.varying)

    def _key_sample(self, obj: bpy.types.Object, time: float, sample: int) -> None:
        """Key `obj` to show `sample` from `time`, and with blending, to mix it with the next as time passes."""
        timeline = self._timelines.setdefault(_uid(obj), {})
        timeline[time] = sample
        self._insert(obj, input_path(SAMPLE), 0, time, sample)
        if not self.blend:
            return
        later = [t for t in timeline if t > time]
        after = min(later) if later else time
        self._insert(obj, input_path(TIME), 0, time, time)
        self._insert(obj, input_path(NEXT), 0, time, timeline[after])
        self._insert(obj, input_path(NEXT_TIME), 0, time, after)
        earlier = [t for t in timeline if t < time]
        if earlier:  # the sample before now mixes into this one
            self._insert(obj, input_path(NEXT), 0, max(earlier), sample)
            self._insert(obj, input_path(NEXT_TIME), 0, max(earlier), time)

    def _group(self, cache: MeshCache) -> bpy.types.NodeTree:
        signature: Signature = tuple((n, layer.data_type, layer.domain) for n, layer in sorted(cache.varying.items()))
        if signature not in self.groups:
            self.groups[signature] = frames_group(signature, self.blend)
        return self.groups[signature]

    def _key_tracks(self, time: float, present: dict[TrackKey, int], fresh: dict[TrackKey, ObjectRecord]) -> int:
        """Key each track that varies at `time`; the tracks keyed."""
        keyed = 0
        for key in fresh.keys() | self.keyed.keys() | (self.objects.keys() - present.keys()):
            record = self._record(key, fresh) if key in present else None
            found = self._differences(key, record) if key in fresh or record is None else set()
            for aspect in found - self.keyed.get(key, set()):
                for cached in self.cached:  # what it held at each time cached before
                    self._key(aspect, key, cached, self.latest[key])
            aspects = self.keyed.setdefault(key, set())
            aspects |= found
            for aspect in aspects:
                if record is not None or aspect == Aspect.VISIBILITY:
                    self._key(aspect, key, time, record)
            keyed += bool(aspects)
        return keyed

    def _differences(self, key: TrackKey, record: ObjectRecord | None) -> set[Aspect]:
        """The aspects `record` changes from the track's latest one; an absent track's visibility."""
        old = self.latest[key]
        if record is None:
            return {Aspect.VISIBILITY} if old["viewport"] or old["render"] else set()
        found: set[Aspect] = set()
        if record["matrix"] != old["matrix"]:
            found.add(Aspect.TRANSFORM)
        if (record["viewport"], record["render"]) != (old["viewport"], old["render"]):
            found.add(Aspect.VISIBILITY)
        if record["properties"] != old["properties"]:
            found.add(Aspect.PROPERTIES)
        if record["viewport"] or record["render"]:
            slots = self.objects[key].material_slots
            materials = [None if m is None else self.materials[m] for m in record["material_slots"]]
            if any(slot.material != m for slot, m in zip(slots, materials, strict=True)):
                raise UncachedError(f"{key[0]}: its {Aspect.MATERIALS} vary")
        return found

    def _key(self, aspect: Aspect, key: TrackKey, time: float, record: ObjectRecord | None) -> None:
        if aspect == Aspect.VISIBILITY:
            self._key_visibility(key, time, record)
        elif aspect == Aspect.TRANSFORM and record is not None:
            self._key_transform(key, time, record)
        elif aspect == Aspect.PROPERTIES and record is not None:
            self._key_properties(key, time, record)

    def _key_visibility(self, key: TrackKey, time: float, record: ObjectRecord | None) -> None:
        obj = self.objects[key]
        self._insert(obj, "hide_viewport", 0, time, record is None or not record["viewport"])
        self._insert(obj, "hide_render", 0, time, record is None or not record["render"])

    def _key_transform(self, key: TrackKey, time: float, record: ObjectRecord) -> None:
        obj = self.objects[key]
        placed = world(record["matrix"])
        if obj.parent is None and sheared(placed):
            parent = shear_parent(obj, key[0], self.collection)
            for cached in self.cached:  # the identity, under the object's own keys
                self._insert_transform(parent, cached)
        if obj.parent is None:
            obj.matrix_basis = placed
        else:
            obj.parent.matrix_basis, obj.matrix_basis = shear_split(placed)
            self._insert_transform(obj.parent, time)
        self._insert_transform(obj, time)

    def _insert_transform(self, obj: bpy.types.Object, time: float) -> None:
        for path in TRANSFORM_PATHS:
            for index, value in enumerate(getattr(obj, path)):
                self._insert(obj, path, index, time, value)

    def _key_properties(self, key: TrackKey, time: float, record: ObjectRecord) -> None:
        obj = self.objects[key]
        for index, channel in enumerate(object_color(record)):
            self._insert(obj, "color", index, time, channel)
        for name, value in record["properties"].items():
            values = value if isinstance(value, list) else [value]
            if name not in obj or not all(isinstance(v, (bool, int, float)) for v in values):
                raise UncachedError(f"{key[0]}: its property {name} can't be keyed")
            for index, channel in enumerate(values):
                self._insert(obj, f'["{name}"]', index, time, float(channel))  # ty: ignore[invalid-argument-type]

    def _insert(self, obj: bpy.types.Object, path: str, index: int, time: float, value: float) -> None:
        """A constant key, which holds until the next."""
        channels = self._channels.get(_uid(obj))
        if channels is None:
            action = bpy.data.actions.new(f"{obj.name} frames")
            slot = action.slots.new(id_type="OBJECT", name=obj.name)
            animation = obj.animation_data_create()
            animation.action, animation.action_slot = action, slot
            channels = self._channels[_uid(obj)] = anim_utils.action_ensure_channelbag_for_slot(action, slot)
        curve = channels.fcurves.find(path, index=index) or channels.fcurves.new(path, index=index)
        point = curve.keyframe_points.insert(time, value, options={"FAST"})
        point.interpolation = "CONSTANT"

    def _remove(self) -> None:
        """Remove everything the display made but its node groups."""
        objects = list(self.collection.all_objects)
        data: set[Any] = {o.data for o in objects if o.data is not None} | set(self.meshes.values())
        for cache in self.caches.values():
            if cache.whole is not None:
                data |= set(cache.whole.datablocks())
        materials = {m for m in self.materials if m is not None}
        materials |= {s.material for o in objects for s in o.material_slots if s.material is not None}
        actions = {o.animation_data.action for o in objects if o.animation_data and o.animation_data.action}
        bpy.data.batch_remove([*objects, *data, *materials, *actions])


def _modifier(obj: bpy.types.Object) -> Any:
    return obj.modifiers.get(MODIFIER) or obj.modifiers.new(MODIFIER, "NODES")


def _bounds_key(record: ObjectRecord) -> Any:
    bounds = record["bounds"]
    return None if bounds is None else (tuple(bounds[0]), tuple(bounds[1]))


def _bounds_layer(bounds: Any) -> Layer:
    """A placeholder's bounds as its bounds mesh's corners (apply._bounds_mesh)."""
    low, high = bounds
    corners = [(x, y, z) for x in (low[0], high[0]) for y in (low[1], high[1]) for z in (low[2], high[2])]
    return Layer("position", "FLOAT_VECTOR", "POINT", "vector", numpy.array(corners, numpy.float32).ravel())  # ty: ignore[invalid-argument-type]


def _shown(key: TrackKey) -> str:
    """The prim whose values a track shows, as far as its source tells.

    Inside an instance, that is its path below the innermost instance root, which every instance shares. Prims of
    different prototypes at the same path below their roots look alike; a split corrects that later.
    """
    source, context = key[0], key[1]
    return source.removeprefix(context[-1]) if context else source


def _uid(data: Any) -> int:
    return data.session_uid
