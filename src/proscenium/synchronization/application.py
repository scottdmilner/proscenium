"""The application layer: display plans applied to Blender as objects (pipeline.md#blender-application).

prepare makes drawn copies' partitions, each one copy's: its object drawing its bounding box and the bounds mesh it
draws, the eight corners of its local bounds, a mesh's provisional geometry description's or a placeholder's, or no
vertices when the plan has none; an empty marker's object, which holds no data; and a sheared copy's unselectable
empty, its shear parent. Each object is hidden in each destination it doesn't display in. Objects and their bounds
meshes are named so each lands at the end of Blender's sorted lists (_MANAGED_NAME). They're prepared in a staging
collection no scene links, so nothing prepared is visible, and preparation only creates datablocks: it never changes
one the published generation reaches (TXN-05). Each is held in the prepared work as soon as it exists
(preparation_resources), its partition's others made just before or after it (TXN-08).

It reads what it applies from the plan's copy table, its buffers, and converts only the resources and geometry
descriptions of the copies it prepares (Plan.resources_at, Plan.geometries_at), so preparing some partitions costs what
they hold. Each buffer view is released before prepare returns or raises, so nothing it borrowed outlives the
synchronization (SNAP-13). It reads nothing from USD: the plan has already decided what it shows (APP-08).

A Blender operation making or setting a resource that fails, a runtime failure, raises ResourceOperationError naming
the resource, so the transaction's diagnostic can (APP-05); the transaction itself finds a destination removed during
preparation, a state change. The plan authorizes no fallback yet, so each aborts the attempt (APP-06). Failures to
consume a resource, such as a texture that disappeared, come with M9's content.

The roles are a copy's, so each prepared resource takes the key of the published entry with its identity, or a new one
(manifests.existing_or_new_entry_keys), and the entries preparation makes are the manifest a publication writes.

A cache call keys the published display through time_code_keying, which shares this module's matrices and names.
"""

from __future__ import annotations

import contextlib
import itertools
import re
from typing import TYPE_CHECKING

import bpy
from mathutils import Matrix

from ..binding.persistence import manifests

if TYPE_CHECKING:
    from collections.abc import Buffer, Callable, Iterable, Iterator, Sequence

    from ..core import _core
    from .preparation_resources import PreparationResources

# A managed object's name, which its bounds mesh shares: a tilde, which sorts after ASCII letters, digits, and most
# punctuation, then its generation and its index in the plan's order, zero-padded, then its prim's name, so each lands
# at the end of Blender's sorted lists (DECISIONS.md "Managed object names").
_MANAGED_NAME = re.compile(r"~(\d{6})\.\d{7} ")

REPRESENTATION_VERSION = 1  # the representation this layer applies, which the planning context names

_NO_RESOURCE = -1  # in a copy-table buffer of resource indices: the copy has no such resource


class ResourceOperationError(RuntimeError):
    """Making or setting a planned resource failed in Blender: a runtime failure (pipeline.md#blender-application)."""

    role: manifests.RepresentationRole  # the resource's
    source_entity_path: str  # its copy's source entity

    def __init__(self, role: manifests.RepresentationRole, source_entity_path: str, cause: BaseException) -> None:
        super().__init__(f"Making the {role} of {source_entity_path} failed: {cause}")
        self.role = role
        self.source_entity_path = source_entity_path


class ManagedNames:
    """The names one synchronization gives what it makes: `~<generation>.<ordinal> <prim name>`.

    DECISIONS.md "Managed object names": the generation is one more than the one in the last managed name among
    Blender's objects and meshes, each list sorted by name, so every name sorts after those before and no two collide;
    the ordinal counts the names given, in the order asked for.
    """

    _prefix: str
    _ordinals: Iterator[int]

    def __init__(self) -> None:
        self._prefix = f"~{_next_generation_number():06d}."
        self._ordinals = itertools.count()

    def next_name(self, prim_name: str) -> str:
        """The next name, for a datablock of the prim named prim_name."""
        return f"{self._prefix}{next(self._ordinals):07d} {prim_name}"


def prepare(
    plan: _core.Plan,
    copy_indices: Iterable[int],
    published: manifests.Manifest,
    work: PreparationResources,
    names: ManagedNames | None = None,
) -> None:
    """Make the partitions of plan's drawn copies at copy_indices in work's staging collection, in that order.

    Each datablock is held in work as it's made (TXN-08). published is the binding's published manifest, whose
    entries' keys the prepared resources with their identities take. names are the synchronization's, new ones if
    not given. Raises ResourceOperationError, naming the
    resource, when making or setting one fails, and otherwise whatever Blender raises; what was made before stays in
    work, held.
    """
    copies = list(copy_indices)
    # Each staged object's hide flags, in the order linked, set together after the loop: assigning one runs Blender's
    # update, which resyncs every collection, at a cost that grows with the scene (34.7 s for 30,000 objects beside a
    # published display of as many, ad hoc). Objects an earlier call staged in work keep theirs, read first.
    hidden = _staged_hide_flags(work)
    with contextlib.ExitStack() as views:  # each view released on return or raise (SNAP-13)

        def view(buffer: Buffer) -> memoryview:
            return views.enter_context(memoryview(buffer))

        objects, meshes, parents = (
            view(plan.copy_object_resource_indices),
            view(plan.copy_bounds_mesh_resource_indices),
            view(plan.copy_shear_parent_resource_indices),
        )
        partitions = [(objects[c], meshes[c], parents[c]) for c in copies]
        resource_indices = [r for partition in partitions for r in partition if r != _NO_RESOURCE]
        resources = dict(zip(resource_indices, plan.resources_at(resource_indices), strict=True))
        identities = {
            i: manifests.CopyResourceIdentity(
                manifests.RepresentationRole(r.role), r.source_entity_path, r.object_index_in_copy
            )
            for i, r in resources.items()
        }
        keys = dict(zip(identities, manifests.existing_or_new_entry_keys(published, identities.values()), strict=True))
        bounds = local_bounds(plan, copies, view)
        worlds = view(plan.copy_world_matrices)
        viewport, render = view(plan.copy_visible_in_viewport), view(plan.copy_visible_in_render)
        shears = view(plan.copy_shear_split_indices)
        parent_worlds, bases = view(plan.shear_parent_world_matrices), view(plan.shear_object_basis_matrices)
        # Objects, and their bounds meshes, are named in the plan's order (DECISIONS.md "Managed object names").
        names = ManagedNames() if names is None else names
        for copy, (object_index, mesh_index, parent_index) in zip(copies, partitions, strict=True):
            name = resources[object_index].source_entity_path.rsplit("/", 1)[-1]
            made: list[tuple[int, bpy.types.ID]] = []  # resource index, datablock
            object_name = names.next_name(name)
            mesh = None
            making = object_index  # the resource being made or set, which a failure names
            try:
                if mesh_index != _NO_RESOURCE:
                    making = mesh_index
                    mesh = bpy.data.meshes.new(object_name)
                    work.track(keys[mesh_index], identities[mesh_index].role, mesh)
                    made.append((mesh_index, mesh))
                    mesh.from_pydata(corners(bounds[copy]), [], [])
                making = object_index
                obj = bpy.data.objects.new(object_name, mesh)
                work.track(keys[object_index], identities[object_index].role, obj)
                made.append((object_index, obj))
                work.ensure_staging_collection().objects.link(obj)
                obj.display_type = "BOUNDS"
                hidden["hide_viewport"].append(not viewport[copy])
                hidden["hide_render"].append(not render[copy])
                if parent_index == _NO_RESOURCE:
                    obj.matrix_world = matrix_from_buffer(worlds, copy)
                else:
                    # Blender objects hold no shear, so the parent and the object each hold part, as the plan splits it.
                    making = parent_index
                    parent = bpy.data.objects.new(names.next_name(f"{name} shear"), None)
                    work.track(keys[parent_index], identities[parent_index].role, parent)
                    made.append((parent_index, parent))
                    work.ensure_staging_collection().objects.link(parent)
                    hidden["hide_viewport"].append(False)
                    hidden["hide_render"].append(False)
                    parent.hide_select = True  # so a pick lands on the object
                    shear = shears[copy]
                    parent.matrix_world = matrix_from_buffer(parent_worlds, shear)
                    making = object_index
                    obj.parent = parent
                    obj.matrix_basis = matrix_from_buffer(bases, shear)
            except Exception as error:
                identity = identities[making]
                raise ResourceOperationError(identity.role, identity.entity, error) from error
            for index, datablock in made:
                resource = resources[index]
                uses = [keys[used] for used in resource.dependency_resource_indices]
                work.manifest_entries[keys[index]] = manifests.ManifestEntry(
                    datablock,
                    list(resource.source_entity_paths),
                    identities[index].role,
                    uses,
                    resource.object_index_in_copy,
                )
    if work.staging_collection is not None:  # none for no copies
        for flag, values in hidden.items():
            work.staging_collection.objects.foreach_set(flag, values)


def _next_generation_number() -> int:
    """One more than the generation in the last managed object or mesh name, or 0 for none.

    Blender keeps its objects and meshes sorted by name, so the last of each is usually managed and found at once; a
    user datablock sorting after the managed ones is passed over. A replacement bounds mesh can be of a newer
    generation than any object.
    """
    generations = [-1]
    for datablocks in (bpy.data.objects, bpy.data.meshes):
        for datablock in reversed(datablocks):
            if match := _MANAGED_NAME.match(datablock.name):
                generations.append(int(match.group(1)))
                break
    return max(generations) + 1


def _staged_hide_flags(work: PreparationResources) -> dict[str, list[bool]]:
    """The hide flags of the objects work's staging collection holds, in the order linked, by flag."""
    hidden: dict[str, list[bool]] = {"hide_viewport": [], "hide_render": []}
    if (staged := work.staging_collection) is not None and len(staged.objects):
        for flag, values in hidden.items():
            values.extend([False] * len(staged.objects))
            staged.objects.foreach_get(flag, values)
    return hidden


def local_bounds(
    plan: _core.Plan, copy_indices: Sequence[int], view: Callable[[Buffer], memoryview]
) -> dict[int, Sequence[float]]:
    """By copy index, each copy's local bounds as (min x, y, z, max x, y, z), or empty for none.

    Reads only the copies' own geometry descriptions; view opens a view of a plan's buffer, released with the caller's.
    """
    geometries, placeholders = view(plan.copy_geometry_indices), view(plan.copy_placeholder_bounds_indices)
    placeholder_bounds = view(plan.placeholder_bounds)
    used = sorted({g for c in copy_indices if (g := geometries[c]) >= 0})
    extents: dict[int, Sequence[float]] = {}
    for geometry_index, geometry in zip(used, plan.geometries_at(used), strict=True):
        with memoryview(geometry.extent) as extent:
            extents[geometry_index] = extent.tolist()
    found: dict[int, Sequence[float]] = {}
    for c in copy_indices:
        if (g := geometries[c]) >= 0:
            found[c] = extents[g]
        elif (p := placeholders[c]) >= 0:
            found[c] = placeholder_bounds[6 * p : 6 * p + 6].tolist()
        else:
            found[c] = []
    return found


def corners(bounds: Sequence[float]) -> list[tuple[float, float, float]]:
    """The eight corners of (min x, y, z, max x, y, z), or none for no bounds."""
    if not bounds:
        return []
    low, high = bounds[:3], bounds[3:]
    return [(x, y, z) for x in (low[0], high[0]) for y in (low[1], high[1]) for z in (low[2], high[2])]


def matrix_from_buffer(matrices: memoryview, index: int) -> Matrix:
    """Matrix `index` of a plan's buffer of them, whose 16 floats each are Blender's column-major layout."""
    columns = matrices[16 * index : 16 * index + 16].tolist()
    return Matrix([columns[i : i + 4] for i in range(0, 16, 4)]).transposed()
