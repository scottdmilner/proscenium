"""The batches of a cached display (M4 Phase E, E5): copies alike but for their placement, as instances of one mesh.

At the build, copies of the same mesh, material slots, object color, and primvar attribute types
(batched_display.attribute_type) become a batch of at least the display's minimum: a prototype object that no
scene links, on their mesh, and a carrier object on a mesh of one point per copy. Unlike Phase D's batches
(batched_display.py), a cached batch has one carrier, and each instance's destinations are its own, so copies
differing only in them share a batch:
- **Points:** each point's attributes are its copy's world transform, whether it shows in the viewport and in the
  render, and its constant primvars by name. The carrier's frames modifier caches them like any mesh's attributes
  (mesh_caches.py), ahead of the modifier that instances the prototype on each point shown in the destination
  being drawn, so each instance's transform, destinations, and primvars vary with time.
- **The prototype's mesh** is a holder's like a track's object's, so it caches its samples, whole meshes
  included, and splits from the objects it shares a mesh with when they come to differ.
- **Copies predicted to vary in their meshes** batch only with copies of the prim whose values they show. No copy
  is predicted to vary in its materials: USD's bindings aren't time-sampled, and a subset's faces are its mesh's.

At each synchronization, a batch keeps its tracks whose content is still its own: their mesh, its material
slots' materials, object color, and primvar attribute types. When track meshes differ, those whose mesh matches
the prototype's current one keep it, or else the most (the least track's on a tie). Any other track of it becomes an
object from then on, hidden at the times before, and shows nothing in the batch; a point shown nowhere keeps its
values but its destinations. A track first present then joins a batch of its content, on a point added to its
carrier's points, which every earlier sample shows in no destination and whose own values are its record's, so
joining varies only its destinations; any other becomes an object.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import bpy
import numpy
from batched_display import POINT_ATTRIBUTES, TRANSFORM, attribute_type, set_prototype
from frame_capture import DisplayAspect, TrackKey
from mesh_caches import MeshCache, new_cache
from object_display import ForeachProperty, MeshAttributeData, object_color

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from mesh_caches import HolderKey, MeshCaches
    from plan_types import ObjectRecord

VIEWPORT, RENDER = "proscenium_viewport", "proscenium_render"  # point attributes: the destinations it shows in
PROTOTYPE_INPUT = "Prototype"
MODIFIER = "proscenium batch"
type PrimvarAttributeTypes = tuple[tuple[str, str], ...]  # a copy's constant primvars: name, attribute data type
# Shared mesh, material slots, object color, and primvar attribute types determine batch compatibility.
type Content = tuple[int, tuple[Any, ...], tuple[float, ...], PrimvarAttributeTypes]


@dataclass
class CachedBatch:
    """A batch of a cached display: its prototype and carrier, and the track of each point."""

    batch_index: int
    prototype: bpy.types.Object
    carrier: bpy.types.Object
    tracks: list[TrackKey]  # by point
    latest_point_attributes: dict[
        str, MeshAttributeData
    ]  # its points' values at the latest synchronization, by attribute
    primvar_attribute_types: PrimvarAttributeTypes
    prototype_record: ObjectRecord  # a track's at the latest time one was present, as the prototype's
    mesh_index: int | None  # the prototype's content in the current plan; None when it has none there
    points_cache: MeshCache | None = None  # its points' cache, once synchronized

    @property
    def key(self) -> HolderKey:
        """The prototype's key as a holder of its mesh."""
        return ("prototype", self.batch_index)

    @property
    def points(self) -> bpy.types.Mesh:
        return self.carrier.data  # ty: ignore[invalid-return-type] - a carrier's data is its points

    def content(self) -> tuple[tuple[Any, ...], tuple[float, ...], PrimvarAttributeTypes]:
        """What its tracks share but their mesh: its materials, object color, and primvar attribute types."""
        return (
            tuple(s.material for s in self.prototype.material_slots),
            tuple(self.prototype.color),
            self.primvar_attribute_types,
        )


def batchable_primvar_types(record: ObjectRecord) -> PrimvarAttributeTypes | None:
    """A copy's primvar attribute types, or None if a point attribute can't hold one of them."""
    found = tuple(sorted((name, attribute_type(value)) for name, value in record["properties"].items()))
    return None if any(attribute_type_name is None for _, attribute_type_name in found) else found  # ty: ignore[invalid-return-type]


def batch_compatibility_key(record: ObjectRecord, materials: Callable[[int], Any]) -> Content | None:
    """A copy's content as its batch would hold it, or None for one no batch can hold."""
    held = batchable_primvar_types(record)
    if record["mesh"] is None or held is None:
        return None
    slots = tuple(None if m is None else materials(m) for m in record["material_slots"])
    color = tuple(numpy.array(object_color(record), numpy.float32).tolist())  # as Blender stores it
    return (record["mesh"], slots, color, held)


def initial_batch_track_groups(
    records: Mapping[TrackKey, ObjectRecord], shown: Callable[[TrackKey], str], minimum: int
) -> list[list[TrackKey]]:
    """The tracks that batch at the build, in groups of at least `minimum`, from whether each is predicted to deform."""
    found: dict[tuple[Any, ...], list[TrackKey]] = {}
    for key, record in records.items():
        held = batch_compatibility_key(record, lambda m: m)
        if held is None:
            continue
        deforms = DisplayAspect.MESH.value in record["dirtied_aspects"]
        found.setdefault((*held, shown(key) if deforms else None), []).append(key)
    return [members for members in found.values() if len(members) >= minimum]


def batch_group() -> bpy.types.NodeTree:
    """The carriers' node group: the Prototype input's object on each point shown in the destination drawn."""
    tree: Any = bpy.data.node_groups.new("Proscenium cached batch", "GeometryNodeTree")
    tree.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    tree.interface.new_socket(PROTOTYPE_INPUT, in_out="INPUT", socket_type="NodeSocketObject")
    tree.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    nodes, links = tree.nodes, tree.links
    group_in, group_out = nodes.new("NodeGroupInput"), nodes.new("NodeGroupOutput")
    info = nodes.new("GeometryNodeObjectInfo")
    info.inputs["As Instance"].default_value = True
    links.new(group_in.outputs[PROTOTYPE_INPUT], info.inputs["Object"])
    shown = nodes.new("GeometryNodeSwitch")
    shown.input_type = "BOOLEAN"
    links.new(nodes.new("GeometryNodeIsViewport").outputs[0], shown.inputs["Switch"])
    for name, side in ((RENDER, "False"), (VIEWPORT, "True")):
        flag = nodes.new("GeometryNodeInputNamedAttribute")
        flag.data_type = "BOOLEAN"
        flag.inputs["Name"].default_value = name
        links.new(flag.outputs["Attribute"], shown.inputs[side])
    instance = nodes.new("GeometryNodeInstanceOnPoints")
    links.new(group_in.outputs["Geometry"], instance.inputs["Points"])
    links.new(shown.outputs[0], instance.inputs["Selection"])
    links.new(info.outputs["Geometry"], instance.inputs["Instance"])
    transform = nodes.new("GeometryNodeInputNamedAttribute")
    transform.data_type = "FLOAT4X4"
    transform.inputs["Name"].default_value = TRANSFORM
    placed = nodes.new("GeometryNodeSetInstanceTransform")
    links.new(instance.outputs["Instances"], placed.inputs["Instances"])
    links.new(transform.outputs["Attribute"], placed.inputs["Transform"])
    links.new(placed.outputs["Instances"], group_out.inputs["Geometry"])
    return tree


def new_batch(  # noqa: PLR0913 - a batch's whole context
    number: int,
    tracks: list[TrackKey],
    records: Mapping[TrackKey, ObjectRecord],
    meshes: list[bpy.types.Mesh],
    materials: list[bpy.types.Material],
    collection: bpy.types.Collection,
    group: bpy.types.NodeTree,
) -> CachedBatch:
    """Batch `number` of `tracks`, whose records share their content: its prototype, points, and carrier."""
    first = records[tracks[0]]
    mesh = first["mesh"]
    assert mesh is not None  # noqa: S101 - the groups leave out placeholders
    prototype = bpy.data.objects.new(f"Prototype {number:06d}", meshes[mesh])
    set_prototype(prototype, first, meshes, materials)
    held = batchable_primvar_types(first)
    assert held is not None  # noqa: S101 - the groups leave out what no point can hold
    points = bpy.data.meshes.new(f"Carrier {number:06d}")
    points.vertices.add(len(tracks))
    found = point_layers(held, [records[key] for key in tracks], first)
    for layer in found.values():
        attribute: Any = points.attributes.new(layer.name, layer.data_type, "POINT")
        attribute.data.foreach_set(layer.foreach_property, layer.values)
    carrier = bpy.data.objects.new(f"Carrier {number:06d}", points)
    collection.objects.link(carrier)  # shown in both destinations: each point says which it shows in
    modifier: Any = carrier.modifiers.new(MODIFIER, "NODES")
    modifier.node_group = group
    tree: Any = group
    identifier = next(i.identifier for i in tree.interface.items_tree if i.name == PROTOTYPE_INPUT)
    getattr(modifier.properties.inputs, identifier).value = prototype
    return CachedBatch(number, prototype, carrier, list(tracks), found, held, first, mesh)


def point_layers(
    held: PrimvarAttributeTypes, records: list[ObjectRecord | None], blank: ObjectRecord
) -> dict[str, MeshAttributeData]:
    """The point attributes of copies with primvar attribute types `held`, one point per record.

    A None record shows nowhere, with `blank`'s other values.
    """

    def column(name: str, data_type: str, value: Callable[[ObjectRecord], Any]) -> MeshAttributeData:
        prop, dtype = POINT_ATTRIBUTES[data_type]
        values = numpy.array([value(r or blank) for r in records], dtype=dtype).ravel()
        return MeshAttributeData(name, data_type, "POINT", ForeachProperty(prop), values)  # ty: ignore[invalid-argument-type]

    found = [
        column(TRANSFORM, "FLOAT4X4", lambda r: r["matrix"]),
        column(VIEWPORT, "BOOLEAN", lambda r: r["viewport"]),
        column(RENDER, "BOOLEAN", lambda r: r["render"]),
        *(column(name, data_type, lambda r, n=name: r["properties"][n]) for name, data_type in held),
    ]
    layers = {layer.name: layer for layer in found}
    for index, record in enumerate(records):
        if record is None:
            layers[VIEWPORT].values[index] = layers[RENDER].values[index] = False
    return layers


def add_points(batch: CachedBatch, keys: list[TrackKey], records: list[ObjectRecord]) -> None:
    """Add a point for each of `keys` to `batch`, which every sample cached so far shows in no destination.

    A new point's samples are zero, so in no destination; its own values are its record's but its destinations, so
    joining varies only those.
    """
    points: Any = batch.points
    points.vertices.add(len(keys))
    batch.tracks += keys
    joined = point_layers(batch.primvar_attribute_types, list(records), records[0])
    for name in (VIEWPORT, RENDER):
        joined[name].values[:] = False
    for name, layer in joined.items():
        attribute = points.attributes[name]
        values = numpy.empty(len(batch.tracks) * (len(layer.values) // len(keys)), layer.values.dtype)
        attribute.data.foreach_get(layer.foreach_property, values)
        values[len(values) - len(layer.values) :] = layer.values
        attribute.data.foreach_set(layer.foreach_property, values)
    for kept in (batch.latest_point_attributes, batch.points_cache.base_attributes if batch.points_cache else {}):
        for name, layer in kept.items():
            grown = numpy.concatenate([layer.values, joined[name].values])
            kept[name] = MeshAttributeData(layer.name, layer.data_type, layer.domain, layer.foreach_property, grown)


def write_points(
    meshes: MeshCaches,
    batch: CachedBatch,
    records: list[ObjectRecord | None],
    at: tuple[float, int],
) -> bool:
    """Cache `batch`'s points at `at` (a time code and its sample), one record per point, None for none shown.

    A point shown nowhere keeps its latest values but its destinations. Returns whether any attribute varies.
    """
    found = point_layers(batch.primvar_attribute_types, records, batch.prototype_record)
    for index, record in enumerate(records):
        if record is None:
            for name, layer in found.items():
                if name not in (VIEWPORT, RENDER):
                    width = len(layer.values) // len(records)
                    layer.values[index * width : (index + 1) * width] = batch.latest_point_attributes[name].values[
                        index * width : (index + 1) * width
                    ]
    batch.latest_point_attributes = found
    if batch.points_cache is None:
        batch.points_cache = new_cache(batch.points, found)
    return meshes.write(batch.points, batch.points_cache, found, at, [batch.carrier])


@dataclass
class Regrouped:
    """What a synchronization changed in the batches' tracks."""

    departing_tracks: list[TrackKey]  # tracks a batch no longer holds, which become objects
    joined_tracks: list[TrackKey]  # tracks first present now, which a batch holds
    varying_aspects_by_track: dict[
        TrackKey, set[DisplayAspect]
    ]  # per track a batch holds or held, the aspects found varying
    prototype_holder_states: dict[
        HolderKey, tuple[int, ObjectRecord | None, int | None, int | None]
    ]  # per prototype with a track
    # present: a track's plan index, its record if read, the mesh in the plan, and the mesh in the current one


class Batches:
    """A cached display's batches, and the tracks they hold."""

    minimum_batch_size: int  # the smallest group that becomes a batch at the build
    group: bpy.types.NodeTree | None  # the carriers' node group, once a batch is built
    batches: list[CachedBatch]
    points: dict[TrackKey, tuple[CachedBatch, int]]  # every track a batch has held, and its point
    held: set[TrackKey]  # the tracks the batches hold now

    def __init__(self, minimum: int) -> None:
        self.minimum_batch_size = minimum
        self.group = None
        self.reset()

    def reset(self) -> None:
        self.batches, self.points, self.held = [], {}, set()

    def build(  # noqa: PLR0913 - the build's records, and where its data is
        self,
        records: Mapping[TrackKey, ObjectRecord],
        shown: Callable[[TrackKey], str],
        meshes: list[bpy.types.Mesh],
        materials: list[bpy.types.Material],
        collection: bpy.types.Collection,
    ) -> None:
        """Batch the build's tracks in groups of at least the minimum; the rest are the display's objects."""
        for members in initial_batch_track_groups(records, shown, self.minimum_batch_size):
            if self.group is None:
                self.group = batch_group()
            batch = new_batch(len(self.batches), members, records, meshes, materials, collection, self.group)
            self.batches.append(batch)
            for point, key in enumerate(members):
                self.points[key] = (batch, point)
            self.held.update(members)

    def regroup(  # noqa: PLR0913 - one synchronization's tracks, and before it
        self,
        present: Mapping[TrackKey, int],
        fresh: Mapping[TrackKey, ObjectRecord],
        mesh_index: Mapping[TrackKey, int | None],
        latest: Mapping[TrackKey, ObjectRecord],
        new_tracks: list[TrackKey],
        diff: Any,
        materials: Callable[[int], Any],
    ) -> Regrouped:
        """Keep each batch's tracks of its content, find those leaving, and place `new_tracks` in batches."""
        old_meshes = {old: new for new, old in enumerate(diff["previous_mesh_indices"]) if old != -1}
        result = Regrouped([], [], {}, {})
        before: dict[int, int | None] = {}  # by batch, its prototype's mesh in the current plan
        for batch in self.batches:
            members = [key for key in batch.tracks if key in self.held and key in present]
            share = batch.content()
            mapped = None if batch.mesh_index is None else old_meshes.get(batch.mesh_index)
            parts: dict[int | None, list[TrackKey]] = {}
            for key in members:
                if key not in fresh:  # unchanged since it was read and kept, but its mesh, as plans renumber
                    parts.setdefault(mesh_index[key], []).append(key)
                    continue
                held = batch_compatibility_key(fresh[key], materials)
                if held is not None and held[1:] == share:
                    parts.setdefault(held[0], []).append(key)
                else:
                    reasons = {DisplayAspect.MATERIALS if held and held[1] != share[0] else DisplayAspect.PROPERTIES}
                    reasons |= {DisplayAspect.MESH} if fresh[key]["mesh"] != mapped else set()
                    self._leave(key, result, reasons | _differences(fresh[key], latest[key]))
            # The tracks of the prototype's current mesh keep it, or else the most, then the least track: plans
            # from separate processes can order their records differently.
            chosen = (
                mapped if mapped in parts else min(parts, key=lambda m: (-len(parts[m]), min(parts[m])), default=None)
            )
            kept = parts.pop(chosen) if chosen is not None else []
            for others in parts.values():
                for key in others:
                    found = _differences(fresh[key], latest[key]) if key in fresh else set()
                    self._leave(key, result, {DisplayAspect.MESH, *found})
            before[batch.batch_index] = batch.mesh_index
            batch.mesh_index = mesh_index[kept[0]] if kept else mapped
            for key in members:
                if key in self.held and key in fresh:
                    result.varying_aspects_by_track.setdefault(key, set()).update(_differences(fresh[key], latest[key]))
            for key in batch.tracks:
                if key in self.held and key not in present and (latest[key]["viewport"] or latest[key]["render"]):
                    result.varying_aspects_by_track[key] = {DisplayAspect.VISIBILITY}
        joining: dict[int, list[TrackKey]] = {}  # by batch, the new tracks joining it
        for key in new_tracks:
            held = batch_compatibility_key(fresh[key], materials)
            alike = [b for b in self.batches if b.mesh_index is not None and held == (b.mesh_index, *b.content())]
            if alike:
                joining.setdefault(min(alike, key=lambda b: min(b.tracks)).batch_index, []).append(key)
        for number, keys in joining.items():
            batch = self.batches[number]
            add_points(batch, keys, [fresh[key] for key in keys])
            for point, key in enumerate(keys, start=len(batch.tracks) - len(keys)):
                self.points[key] = (batch, point)
                result.varying_aspects_by_track[key] = {DisplayAspect.VISIBILITY}
            self.held.update(keys)
            result.joined_tracks += keys
        for batch in self.batches:  # each prototype with a track present, as a holder of its mesh
            shown = [key for key in batch.tracks if key in self.held and key in present]
            if not shown:
                continue
            read = next((key for key in shown if key in fresh), None)
            batch.prototype_record = fresh[read] if read is not None else latest[shown[0]]
            record = None if read is None else fresh[read]
            result.prototype_holder_states[batch.key] = (
                present[shown[0]],
                record,
                batch.mesh_index,
                before[batch.batch_index],
            )
        return result

    def prototype(self, key: HolderKey) -> bpy.types.Object:
        """The prototype a holder key names."""
        return self.batches[key[1]].prototype  # ty: ignore[invalid-argument-type]

    def _leave(self, key: TrackKey, result: Regrouped, aspects: set[DisplayAspect]) -> None:
        self.held.discard(key)
        result.departing_tracks.append(key)
        result.varying_aspects_by_track[key] = aspects

    def write(
        self,
        meshes: MeshCaches,
        at: tuple[float, int],
        present: Mapping[TrackKey, int],
        fresh: Mapping[TrackKey, ObjectRecord],
        latest: Mapping[TrackKey, ObjectRecord],
        changed: set[TrackKey],
    ) -> int:
        """Cache every batch's points at `at`; the batches written.

        A batch none of whose tracks is in `changed` (read, joined, left, or present or absent anew) and whose
        points don't vary yet holds what it did.
        """
        written = 0
        for batch in self.batches:
            if (batch.points_cache is None or not batch.points_cache.varying_attributes) and changed.isdisjoint(
                batch.tracks
            ):
                continue
            records = [
                (fresh.get(key) or latest[key]) if key in self.held and key in present else None for key in batch.tracks
            ]
            written += write_points(meshes, batch, records, at)
        return written


def _differences(record: ObjectRecord, old: ObjectRecord) -> set[DisplayAspect]:
    """The aspects a batch's track changes in from its latest record, but its mesh, which its prototype's cache says."""
    found: set[DisplayAspect] = set()
    if record["matrix"] != old["matrix"]:
        found.add(DisplayAspect.TRANSFORM)
    if (record["viewport"], record["render"]) != (old["viewport"], old["render"]):
        found.add(DisplayAspect.VISIBILITY)
    if record["properties"] != old["properties"]:
        found.add(DisplayAspect.PROPERTIES)
    return found
