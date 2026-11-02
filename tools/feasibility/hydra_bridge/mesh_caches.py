"""The mesh caches of a cached display (M4 Phase E, E3 and E4): each varying mesh's samples, shared by its holders.

A holder is an object that shows a mesh: a track's object, or a batch's prototype (cached_batches.py). Copies
whose content is equal share a mesh, so a mesh whose holders come to differ splits, each part keeping the frames
cached so far.

- **Attributes:** a mesh whose topology holds caches each synchronization's values of each varying attribute as
  `<name>@<sample>` beside it (attribute_samples.py), which each holder's frames modifier shows for the sample its
  keyed `Sample` input names; -1, the mesh's own values, at the times cached before the mesh first varied.
- **Whole meshes:** a mesh whose topology varies (E4) caches a whole mesh per sample instead (topology.py), from
  the first time its topology differs from its own, its earlier samples rebuilt from its attributes. So does one
  whose content gains an attribute it lacks.
- **Attributes that come and go:** a mesh holds the constant display color all its copies share (D13), so its
  content can gain or lose that attribute. One gained has the mesh's own values before; one lost holds its latest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import bpy
import numpy
from apply import BufferFormat, Layer, flat, layers, new_mesh
from attribute_samples import (
    BASE,
    FRAME_SEPARATOR,
    SAMPLE,
    Signature,
    frames_group,
    input_path,
    remove_samples,
    sample_mesh,
    stored,
)
from keyframes import Keys, frames_modifier
from topology import MeshSamples, samples_group

if TYPE_CHECKING:
    from collections.abc import Callable

    from frames import TrackKey
    from plan_types import MeshRecord, ObjectRecord, Plan

type HolderKey = TrackKey | tuple[str, int]  # a track, or ("prototype", batch number)
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
class Synchronized:
    """One time code's holders: what each shows there, in the plan synchronized, and before it."""

    plan: Plan
    diff: Any
    present: dict[HolderKey, int]  # the holders present, with an object of theirs in `plan`
    fresh: dict[HolderKey, ObjectRecord]  # the records read from `plan`: those not kept unchanged
    mesh_index: dict[HolderKey, int | None]  # the present holders' meshes in `plan`
    previous: dict[HolderKey, int | None]  # the holders' meshes in the current plan
    latest: dict[HolderKey, ObjectRecord]  # each holder's record at the latest time it was present


class MeshCaches:
    """Every mesh a cached display's holders show, and the caches of those that vary."""

    keys: Keys
    times: dict[float, int]  # the time codes cached, and the sample of each
    holder: Callable[[HolderKey], bpy.types.Object]
    meshes: dict[int, bpy.types.Mesh]  # by session_uid
    users: dict[int, set[HolderKey]]  # by mesh session_uid, the holders that show it
    caches: dict[int, MeshCache]  # by mesh session_uid, the meshes that hold frames
    groups: dict[Signature, bpy.types.NodeTree]  # the frames' node group for each set of varying attributes
    whole_group: bpy.types.NodeTree | None  # the whole meshes' node group, once a mesh's topology varies

    def __init__(self, holder: Callable[[HolderKey], bpy.types.Object]) -> None:
        self.holder = holder
        self.groups = {}
        self.whole_group = None
        self.reset(Keys(blend=False), {})

    def reset(self, keys: Keys, times: dict[float, int]) -> None:
        """Forget every mesh, for a display built again; the node groups are kept."""
        self.keys, self.times = keys, times
        self.meshes, self.users, self.caches = {}, {}, {}

    def use(self, data: Any, key: HolderKey) -> None:
        if isinstance(data, bpy.types.Mesh):
            self.meshes[data.session_uid] = data
            self.users.setdefault(data.session_uid, set()).add(key)

    def varies(self, data: Any) -> bool:
        """Whether a holder's data caches frames."""
        cache = self.caches.get(data.session_uid) if data is not None else None
        return cache is not None and (bool(cache.varying) or cache.whole is not None)

    def split(self, uid: int, parts: list[set[HolderKey]]) -> int:
        """Keep the first part's holders on the mesh, and give each other part a copy of it; the copies made."""
        mesh = self.meshes[uid]
        for part in parts[1:]:
            copy = mesh.copy()  # with the frames it holds
            self.meshes[copy.session_uid] = copy
            self.users[copy.session_uid] = part
            self.users[uid] -= part
            cache = self.caches.get(uid)
            if cache is not None:
                self.caches[copy.session_uid] = MeshCache(
                    cache.base, cache.latest, dict(cache.varying), cache.whole, cache.shown
                )
            for key in part:
                self.holder(key).data = copy  # shown its store when it is next written, as every part is
        return len(parts) - 1

    def cache(self, at: tuple[float, int], now: Synchronized) -> tuple[int, int]:
        """Write the sample of `at` (a time code and its sample) of each mesh whose content varies.

        Returns the meshes split, and those written.
        """
        present = now.present
        touched = {_uid(self.holder(key)) for key in present if not same(now, key)} & self.meshes.keys()
        touched |= {uid for uid, cache in self.caches.items() if cache.varying or cache.whole is not None}
        split = written = 0
        for uid in touched:
            users = sorted(k for k in self.users[uid] if k in present)
            if not users:
                continue  # hidden here, so it shows what it holds
            parts: dict[ContentKey, list[HolderKey]] = {}
            for key in users:
                parts.setdefault(content_key(now, key), []).append(key)
            ordered = ordered_parts(now, parts)
            split += self.split(uid, [set(keys) for _, keys in ordered])
            for content, keys in ordered:
                part_uid = _uid(self.holder(keys[0]))
                cache = self.caches.get(part_uid)
                mesh_record = None
                if all(same(now, k) for k in keys):
                    if cache is None:
                        continue  # what the mesh holds
                    values = cache.latest
                else:
                    values, mesh_record = self._content(content, record(now, keys[0]), now.plan)
                if mesh_record is not None and (
                    (cache is not None and cache.whole is not None)
                    or not self._same_topology(keys[0], values, mesh_record)
                ):
                    cache = self._whole(part_uid, cache)
                if cache is not None and cache.whole is not None:
                    self._write_whole(part_uid, cache, mesh_record, at[0])
                    written += 1
                    continue
                if cache is None:
                    if now.latest[keys[0]]["mesh"] is None and values["position"].values.size != 3 * len(
                        self.meshes[part_uid].vertices
                    ):
                        raise UncachedError(f"{keys[0][0]}: its placeholder's bounds appear or vanish")
                    cache = self.caches[part_uid] = new_cache(self.meshes[part_uid], values)
                objects = [self.holder(key) for key in self.users[part_uid]]
                if self.write(self.meshes[part_uid], cache, values, at, objects):
                    written += 1
        return split, written

    def _content(
        self, content: ContentKey, record: ObjectRecord, plan: Plan
    ) -> tuple[dict[str, Layer], MeshRecord | None]:
        """A content's attributes, and for a mesh its plan record; a placeholder's are its bounds."""
        kind, index = content
        if kind == "mesh":
            mesh_record = plan.meshes_at([index])[0]
            return {layer.name: layer for layer in layers(mesh_record)}, mesh_record
        return {"position": bounds_layer(record["bounds"])}, None

    def _same_topology(self, key: HolderKey, found: dict[str, Layer], record: MeshRecord) -> bool:
        """Whether content has the faces, corners, material slots, and attributes of the mesh it would cache on."""
        topology = (flat(record["corner_verts"], BufferFormat.INT), flat(record["face_offsets"], BufferFormat.INT))
        mesh: Any = self.holder(key).data
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
        objects = [self.holder(key) for key in sorted(self.users[uid])]
        timeline = self.keys.timeline(objects[0])
        for obj in objects:
            self.keys.unkey_inputs(obj)
            store.show(frames_modifier(obj), self._whole_group())
        varying = cache.varying if cache is not None else {}
        added: dict[int, int] = {}  # by sample of its attributes, the store's
        for time in sorted(self.times):
            sample = timeline.get(time, BASE)
            if sample not in added:
                added[sample] = store.add(sample_mesh(mesh, sample, varying))
            for obj in objects:
                self.keys.insert(obj, input_path(SAMPLE), 0, time, added[sample])
        remove_samples(mesh)
        whole = self.caches[uid] = MeshCache({}, {}, whole=store)
        return whole

    def _write_whole(self, uid: int, cache: MeshCache, record: MeshRecord | None, time: float) -> None:
        """Add the whole mesh `record` as the sample of `time`, or for None the one shown at the latest again."""
        assert cache.whole is not None  # noqa: S101 - a whole cache
        if record is not None and record["slot_count"] != len(self.meshes[uid].materials):
            raise UncachedError(f"{self.meshes[uid].name}: its material slots vary")
        if record is not None:
            cache.shown = cache.whole.add(new_mesh(record))
        for key in self.users[uid]:
            obj = self.holder(key)
            cache.whole.show(frames_modifier(obj), self._whole_group())
            self.keys.insert(obj, input_path(SAMPLE), 0, time, cache.shown)

    def write(
        self,
        mesh: bpy.types.Mesh,
        cache: MeshCache,
        content: dict[str, Layer],
        at: tuple[float, int],
        objects: list[bpy.types.Object],
    ) -> bool:
        """Add `content`'s varying attributes to `mesh` as the sample of `at`, first finding which vary.

        Each of `objects`, which show the mesh, is keyed to show that sample at that time. An attribute content
        lacks holds its latest values, as a mesh's held display color does once its copies' colors differ (D13).
        Returns whether any attribute varies.
        """
        time, sample = at
        held_mesh: Any = mesh
        # An attribute content gains has the mesh's own values before: a mesh lacking it caches whole meshes.
        for name, layer in content.items():
            if name not in cache.base:
                cache.base |= new_cache(mesh, {name: layer}).base
        content = {**cache.latest, **content}
        added = {
            name: layer
            for name, layer in content.items()
            if name not in cache.varying and not numpy.array_equal(layer.values, cache.base[name].values)
        }
        if added:
            first = not cache.varying
            cache.varying |= added
            for obj in objects:
                for cached in self.times if first else ():  # the mesh's own values, before it varied
                    self.keys.key_sample(obj, cached, BASE)
        if cache.varying:
            group = self._group(cache)
            for obj in objects:  # a holder first present now may share the mesh, with no modifier yet
                modifier = frames_modifier(obj)
                if modifier.node_group != group:
                    modifier.node_group = group
        for name in cache.varying:
            layer = content[name]
            held = stored(layer)
            attribute = held_mesh.attributes.new(f"{name}{FRAME_SEPARATOR}{sample}", held.data_type, layer.domain)
            attribute.data.foreach_set(held.prop, held.values)
        if cache.varying:
            for obj in objects:
                self.keys.key_sample(obj, time, sample)
        cache.latest = content
        return bool(cache.varying)

    def _group(self, cache: MeshCache) -> bpy.types.NodeTree:
        signature: Signature = tuple((n, layer.data_type, layer.domain) for n, layer in sorted(cache.varying.items()))
        if signature not in self.groups:
            self.groups[signature] = frames_group(signature, self.keys.blend)
        return self.groups[signature]

    def datablocks(self) -> set[bpy.types.ID]:
        """Every mesh, and every whole mesh's sample, holder, and collection."""
        data: set[bpy.types.ID] = set(self.meshes.values())
        for cache in self.caches.values():
            if cache.whole is not None:
                data |= set(cache.whole.datablocks())
        return data


def content_key(now: Synchronized, key: HolderKey) -> ContentKey:
    index = now.mesh_index[key]
    return ("mesh", index) if index is not None else ("bounds", bounds_key(record(now, key)))


def record(now: Synchronized, key: HolderKey) -> ObjectRecord:
    """A present holder's record there."""
    return now.fresh.get(key) or now.latest[key]


def same(now: Synchronized, key: HolderKey) -> bool:
    """Whether a present holder's content is what it was at the current plan."""
    if key not in now.fresh:
        return True
    if key not in now.previous:
        return False
    index = now.mesh_index[key]
    if index is None:
        return bounds_key(now.fresh[key]) == bounds_key(now.latest[key])
    return now.diff["meshes"][index] == now.previous[key]


def ordered_parts(
    now: Synchronized, parts: dict[ContentKey, list[HolderKey]]
) -> list[tuple[ContentKey, list[HolderKey]]]:
    """A mesh's holders by content, the part that keeps the mesh first.

    That is the part whose content is unchanged, so a mesh with no cache stays one, else the largest.
    """
    return sorted(parts.items(), key=lambda item: (not all(same(now, k) for k in item[1]), -len(item[1])))


def new_cache(mesh: bpy.types.Mesh, content: dict[str, Layer]) -> MeshCache:
    """The cache of a mesh first found to vary, whose own values are the frames' before."""
    held: Any = mesh
    base = {}
    for name, layer in content.items():
        values = numpy.empty_like(layer.values)
        held.attributes[name].data.foreach_get(layer.prop, values)
        base[name] = Layer(name, layer.data_type, layer.domain, layer.prop, values)
    return MeshCache(base, base)


def _uid(holder: bpy.types.Object) -> int:
    data: Any = holder.data  # a holder's data is a mesh
    return data.session_uid


def bounds_key(record: ObjectRecord) -> Any:
    bounds = record["bounds"]
    return None if bounds is None else (tuple(bounds[0]), tuple(bounds[1]))


def bounds_layer(bounds: Any) -> Layer:
    """A placeholder's bounds as its bounds mesh's corners (apply._bounds_mesh)."""
    low, high = bounds
    corners = [(x, y, z) for x in (low[0], high[0]) for y in (low[1], high[1]) for z in (low[2], high[2])]
    return Layer("position", "FLOAT_VECTOR", "POINT", "vector", numpy.array(corners, numpy.float32).ravel())  # ty: ignore[invalid-argument-type]
