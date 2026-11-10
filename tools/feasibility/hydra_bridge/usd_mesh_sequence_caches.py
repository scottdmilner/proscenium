"""Mesh caches in a USD layer, for comparison (M4 Phase E, E6): Blender's Mesh Sequence Cache modifier reads them.

In place of sample attributes (mesh_caches.py), a varying mesh's content at each synchronized time code is a time
sample of a Mesh prim in a USD layer the display writes from its plans, and each of the mesh's holders reads that
prim through a Mesh Sequence Cache modifier. The display has one cache file, whose frame is keyed at each time code
cached, constant, so Blender reads the latest cached time code at or before the scene's time; with blending, linear,
so USD interpolates between them as it does: positions and float primvars of equal sizes, the rest held.

- **Each prim has a sample at every time cached** where a holder of it is present: its mesh's own content at the
  times before it first varied. A primvar its content lacks is blocked there, and one lost at an unchanged topology
  holds its latest values, as a mesh's held display color does (D13).
- **Topology** varies from sample to sample, as a USD mesh's does, so no mesh caches whole meshes.
- **The layer is in memory.** Blender's reader shares the process's layers, so it reads it unsaved; `save` writes
  it to its file, which a saved .blend reads from.
- **Not cached here:** what Blender's reader gives back otherwise than object_display.py holds it. A display color
with an
  opacity, as USD's displayColor is a color3f and the reader drops one of another type; a FLOAT2 on points, which it
  reads as a UV map, on corners; and a primvar whose type or domain varies, which USD holds once. These raise
  UncachedError, as material slots that vary do (mesh_caches.py).
- **Batches' carriers** keep their frames modifier (mesh_caches.py); their prototypes' meshes are cached here.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, override

import bpy
import numpy
from attribute_samples import FRAME_SEPARATOR
from mesh_caches import (
    MeshCaches,
    MeshHolderSynchronizationState,
    UncachedError,
    bounds_layer,
    content_key,
    holder_content_unchanged,
    holder_groups_with_retained_mesh_first,
    record,
)
from object_display import (
    ATTRIBUTE_FORMATS,
    DISPLAY_COLOR,
    PLAN_DOMAINS,
    POSITION,
    BufferFormat,
    MeshAttributeData,
    flat,
    mesh_attributes,
)
from pxr import Sdf, Vt

if TYPE_CHECKING:
    from collections.abc import Callable

    from keyframes import AnimationKeyWriter
    from mesh_caches import ContentKey, HolderKey
    from plan_types import ObjectRecord, Plan

MODIFIER = "proscenium sequence"
INTERPOLATIONS = {"POINT": "vertex", "FACE": "uniform", "CORNER": "faceVarying"}
type PrimvarKind = tuple[Sdf.ValueTypeName, str]  # its type, and its interpolation


@dataclass(frozen=True)
class MeshContent:
    """A mesh's content as a sample writes it: its attributes, positions and face material slots included."""

    attributes_by_name: dict[str, MeshAttributeData]
    corner_verts: numpy.ndarray
    face_offsets: numpy.ndarray

    def same_topology(self, other: MeshContent) -> bool:
        return (
            self.attributes_by_name[POSITION].values.size == other.attributes_by_name[POSITION].values.size
            and numpy.array_equal(self.corner_verts, other.corner_verts)
            and numpy.array_equal(self.face_offsets, other.face_offsets)
        )

    @override
    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, MeshContent)
            and self.same_topology(other)
            and self.attributes_by_name.keys() == other.attributes_by_name.keys()
            and all(
                numpy.array_equal(layer.values, other.attributes_by_name[n].values)
                for n, layer in self.attributes_by_name.items()
            )
        )

    __hash__ = None  # its arrays are mutable


class SequenceCaches(MeshCaches):
    """Every mesh a cached display's holders show, and of those that vary, their prims in a USD layer."""

    path: str  # the layer's file
    layer: Sdf.Layer
    cache_file: bpy.types.CacheFile
    prims: dict[int, Sdf.Path]  # by mesh session_uid, the prim of each mesh that varies
    contents: dict[int, MeshContent]  # by mesh session_uid, the content of its latest sample
    kinds: dict[int, dict[str, PrimvarKind]]  # by mesh session_uid, its prim's primvars
    _count: int  # the prims made

    def __init__(self, holder: Callable[[HolderKey], bpy.types.Object], path: str) -> None:
        self.path = path
        self.layer = Sdf.Layer.Find(path) or Sdf.Layer.CreateNew(path)  # the reader opens an existing file
        opened = set(bpy.data.cache_files)
        bpy.ops.cachefile.open(filepath=path)
        self.cache_file = next(c for c in bpy.data.cache_files if c not in opened)
        self.cache_file.override_frame = True
        super().__init__(holder)

    @override
    def reset(self, keys: AnimationKeyWriter, times: dict[float, int]) -> None:
        super().reset(keys, times)
        self.layer.Clear()
        self.prims, self.contents, self.kinds, self._count = {}, {}, {}, 0
        animation = self.cache_file.animation_data
        if animation is not None and animation.action is not None:
            bpy.data.actions.remove(animation.action)
        self.cache_file.animation_data_clear()
        for time in times:
            self._key_frame(time)

    @override
    def has_cached_variation(self, data: Any) -> bool:
        return data is not None and data.session_uid in self.prims

    @override
    def split(self, uid: int, parts: list[set[HolderKey]]) -> int:
        """Keep the first part's holders on the mesh, and give each other part a copy, with a copy of its prim."""
        mesh = self.meshes[uid]
        for part in parts[1:]:
            copy = mesh.copy()
            self.meshes[copy.session_uid] = copy
            self.users[copy.session_uid] = part
            self.users[uid] -= part
            for key in part:
                self.holder(key).data = copy
            if uid in self.prims:
                prim = self._new_prim()
                Sdf.CopySpec(self.layer, self.prims[uid], self.layer, prim)
                self.prims[copy.session_uid] = prim
                self.contents[copy.session_uid] = self.contents[uid]
                self.kinds[copy.session_uid] = dict(self.kinds[uid])
                self._read(copy.session_uid)
        return len(parts) - 1

    @override
    def cache(self, at: tuple[float, int], now: MeshHolderSynchronizationState) -> tuple[int, int]:
        """Write the sample of `at`'s time code of each mesh whose content varies; the meshes split, and written."""
        time = at[0]
        self._key_frame(time)
        present = now.object_indices_by_holder
        touched = {
            _uid(self.holder(key)) for key in present if not holder_content_unchanged(now, key)
        } & self.meshes.keys()
        touched |= self.prims.keys()
        split = written = 0
        for uid in touched:
            users = sorted(k for k in self.users[uid] if k in present)
            if not users:
                continue  # hidden here, so what it shows doesn't matter
            parts: dict[ContentKey, list[HolderKey]] = {}
            for key in users:
                parts.setdefault(content_key(now, key), []).append(key)
            ordered = holder_groups_with_retained_mesh_first(now, parts)
            split += self.split(uid, [set(keys) for _, keys in ordered])
            for content, keys in ordered:
                part_uid = _uid(self.holder(keys[0]))
                if all(holder_content_unchanged(now, k) for k in keys):
                    if part_uid not in self.prims:
                        continue  # what the mesh holds
                    found = self.contents[part_uid]
                else:
                    found = self._sample(part_uid, content, record(now, keys[0]), now.plan)
                if part_uid not in self.prims:
                    own = mesh_content(self.meshes[part_uid])
                    found = _holding(found, own)
                    if found == own:
                        continue
                    self._start(part_uid, own)
                written += self._write(part_uid, _holding(found, self.contents[part_uid]), time)
        return split, written

    def save(self) -> None:
        """Write the layer to its file, which a saved .blend's cache file reads."""
        self.layer.Save()

    @override
    def datablocks(self) -> set[bpy.types.ID]:
        return set(self.meshes.values())

    def _sample(self, uid: int, content: ContentKey, holder: ObjectRecord, plan: Plan) -> MeshContent:
        """A content's attributes and topology; a placeholder's are its bounds, on its bounds mesh's topology."""
        kind, index = content
        if kind == "mesh":
            data = plan.meshes_at([index])[0]
            if data["slot_count"] != len(self.meshes[uid].materials):
                raise UncachedError(f"{self.meshes[uid].name}: its material slots vary")
            return MeshContent(
                {layer.name: layer for layer in mesh_attributes(data)},
                _ints(data["corner_verts"]),
                _ints(data["face_offsets"]),
            )
        if holder["bounds"] is None:
            raise UncachedError(f"{holder['source']}: its placeholder's bounds appear or vanish")
        own = mesh_content(self.meshes[uid])
        return MeshContent({POSITION: bounds_layer(holder["bounds"])}, own.corner_verts, own.face_offsets)

    def _new_prim(self) -> Sdf.Path:
        self._count += 1
        return Sdf.Path(f"/Mesh_{self._count:06d}")

    def _start(self, uid: int, own: MeshContent) -> None:
        """A prim for a mesh first found to vary, showing its own content at every time cached before."""
        path = self.prims[uid] = self._new_prim()
        with Sdf.ChangeBlock():
            prim = Sdf.CreatePrimInLayer(self.layer, path)
            prim.specifier, prim.typeName = Sdf.SpecifierDef, "Mesh"
            scheme = Sdf.AttributeSpec(prim, "subdivisionScheme", Sdf.ValueTypeNames.Token, Sdf.VariabilityUniform)
            scheme.default = "none"
        self.kinds[uid] = {}
        for time in self.times:
            self._write(uid, own, time)
        self._read(uid)

    def _read(self, uid: int) -> None:
        """Have each of a mesh's holders read its prim, before any other modifier."""
        for key in self.users[uid]:
            obj = self.holder(key)
            modifier: Any = obj.modifiers.get(MODIFIER) or self._new_modifier(obj)
            modifier.object_path = str(self.prims[uid])

    def _new_modifier(self, obj: bpy.types.Object) -> Any:
        """A Mesh Sequence Cache modifier reading the cache file, first in `obj`'s stack."""
        modifier: Any = obj.modifiers.new(MODIFIER, "MESH_SEQUENCE_CACHE")
        modifier.cache_file = self.cache_file
        modifier.read_data = {"VERT", "POLY", "UV", "COLOR", "ATTRIBUTES"}
        if len(obj.modifiers) > 1:
            obj.modifiers.move(len(obj.modifiers) - 1, 0)
        return modifier

    def _write(self, uid: int, content: MeshContent, time: float) -> bool:
        """Write `content` as its mesh's prim's sample at `time`; whether one was written."""
        path = self.prims[uid]
        counts = numpy.diff(content.face_offsets, append=content.corner_verts.size).astype(numpy.int32)
        positions = content.attributes_by_name[POSITION].values.reshape(-1, 3)
        with Sdf.ChangeBlock():
            self._set(path, "points", Sdf.ValueTypeNames.Point3fArray, Vt.Vec3fArray.FromNumpy(positions), time)
            self._set(path, "faceVertexCounts", Sdf.ValueTypeNames.IntArray, Vt.IntArray.FromNumpy(counts), time)
            indices = Vt.IntArray.FromNumpy(content.corner_verts)
            self._set(path, "faceVertexIndices", Sdf.ValueTypeNames.IntArray, indices, time)
            kinds = self.kinds[uid]
            for name, layer in content.attributes_by_name.items():
                if name == POSITION:
                    continue
                kind, value = _primvar(layer)
                if kinds.setdefault(name, kind) != kind:
                    raise UncachedError(f"{self.meshes[uid].name}: its {name}'s type or domain varies")
                spec = self._set(path, f"primvars:{name}", kind[0], value, time)
                if spec is not None:  # absent at the times written before
                    spec.SetInfo("interpolation", kind[1])
                    for before in self.layer.ListTimeSamplesForPath(path.AppendProperty("points")):
                        if before != time:
                            self.layer.SetTimeSample(spec.path, before, Sdf.ValueBlock())
            for name in kinds.keys() - content.attributes_by_name.keys():  # absent here
                self.layer.SetTimeSample(path.AppendProperty(f"primvars:{name}"), time, Sdf.ValueBlock())
        self.contents[uid] = content
        self._read(uid)  # a holder first present now may share the mesh, with no modifier yet
        return True

    def _set(self, prim: Sdf.Path, name: str, kind: Sdf.ValueTypeName, value: Any, time: float) -> Any:
        """Set an attribute's sample at `time`; the attribute's spec if this made it, else None."""
        path = prim.AppendProperty(name)
        spec = None
        if self.layer.GetAttributeAtPath(path) is None:
            spec = Sdf.AttributeSpec(self.layer.GetPrimAtPath(prim), name, kind)
        self.layer.SetTimeSample(path, time, value)
        return spec

    def _key_frame(self, time: float) -> None:
        """Have the cache file read `time` from there on; with blending, nearer the next time the nearer it is."""
        interpolation = "LINEAR" if self.keys.blend else "CONSTANT"
        self.keys.insert(self.cache_file, "frame", 0, time, time, interpolation)


def mesh_content(mesh: bpy.types.Mesh) -> MeshContent:
    """A Blender mesh's own content, as new_mesh writes it."""
    held: Any = mesh
    found = {}
    for attribute in held.attributes:
        name, data_type, domain = attribute.name, attribute.data_type, attribute.domain
        if name.startswith(".") or FRAME_SEPARATOR in name or data_type not in ATTRIBUTE_FORMATS:
            continue
        if domain not in PLAN_DOMAINS:
            continue
        fmt, prop = ATTRIBUTE_FORMATS[data_type]
        width = {"FLOAT2": 2, "FLOAT_VECTOR": 3, "FLOAT_COLOR": 4}.get(data_type, 1)
        values = numpy.empty(len(attribute.data) * width, numpy.float32 if fmt == BufferFormat.FLOAT else numpy.int32)
        attribute.data.foreach_get(prop, values)
        found[name] = MeshAttributeData(name, data_type, domain, prop, values)
    if POSITION not in found:  # a mesh with no points
        found[POSITION] = MeshAttributeData(POSITION, "FLOAT_VECTOR", "POINT", "vector", numpy.empty(0, numpy.float32))  # ty: ignore[invalid-argument-type]
    corners = numpy.empty(len(held.loops), numpy.int32)
    if len(corners):
        held.attributes[".corner_vert"].data.foreach_get("value", corners)
    starts = numpy.empty(len(held.polygons), numpy.int32)
    held.polygons.foreach_get("loop_start", starts)
    return MeshContent(found, corners, starts)


def _holding(content: MeshContent, latest: MeshContent) -> MeshContent:
    """`content`, holding the latest values of an attribute it lacks if its topology is unchanged (D13)."""
    if not content.same_topology(latest) or latest.attributes_by_name.keys() <= content.attributes_by_name.keys():
        return content
    return replace(content, attributes_by_name={**latest.attributes_by_name, **content.attributes_by_name})


def _primvar(layer: MeshAttributeData) -> tuple[PrimvarKind, Any]:
    """An attribute as a primvar Blender's reader gives back as apply holds it: its kind, and its value."""
    interpolation = INTERPOLATIONS[layer.domain]
    values = layer.values
    if layer.data_type == "INT":
        return (Sdf.ValueTypeNames.IntArray, interpolation), Vt.IntArray.FromNumpy(values)
    if layer.data_type == "FLOAT":
        return (Sdf.ValueTypeNames.FloatArray, interpolation), Vt.FloatArray.FromNumpy(values)
    if layer.data_type == "FLOAT2":
        if layer.domain == "POINT":
            raise UncachedError(f"{layer.name}: the reader reads a FLOAT2 on points as a UV map, on corners")
        kind = Sdf.ValueTypeNames.TexCoord2fArray if layer.domain == "CORNER" else Sdf.ValueTypeNames.Float2Array
        return (kind, interpolation), Vt.Vec2fArray.FromNumpy(values.reshape(-1, 2))
    if layer.data_type == "FLOAT_VECTOR":
        return (Sdf.ValueTypeNames.Float3Array, interpolation), Vt.Vec3fArray.FromNumpy(values.reshape(-1, 3))
    colors = values.reshape(-1, 4)
    if layer.name != DISPLAY_COLOR:
        return (Sdf.ValueTypeNames.Color4fArray, interpolation), Vt.Vec4fArray.FromNumpy(colors)
    if not numpy.all(colors[:, 3] == 1.0):
        raise UncachedError(f"{layer.name}: the reader reads displayColor as a color3f, with no opacity")
    rgb = numpy.ascontiguousarray(colors[:, :3])
    return (Sdf.ValueTypeNames.Color3fArray, interpolation), Vt.Vec3fArray.FromNumpy(rgb)


def _ints(array: Any) -> numpy.ndarray:
    return numpy.frombuffer(flat(array, BufferFormat.INT), dtype=numpy.int32)


def _uid(holder: bpy.types.Object) -> int:
    data: Any = holder.data  # a holder's data is a mesh
    return data.session_uid
