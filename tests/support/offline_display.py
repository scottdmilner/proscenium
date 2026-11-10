"""A binding's saved display built by hand, as F-OFFLINE describes it (fixtures.source_access.SavedDisplay).

Nothing publishes until M5, so tests that need a published display build it here, and record it as a
publication would: in the binding's manifest and generation. Needs the extension registered.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy

from proscenium.binding.persistence import binding_state
from proscenium.binding.persistence.binding_state import GenerationMetadata
from proscenium.binding.persistence.manifests import Manifest, ManifestEntry
from proscenium.binding.runtime import ownership
from proscenium.binding.source_access.binding_settings import PayloadPolicy, new_settings
from proscenium.binding.source_access.stages import SourceRevision
from support.manifests import key

if TYPE_CHECKING:
    from fixtures.source_access import SavedDisplay
    from proscenium.binding.source_access.binding_ids import BindingId


def publish_by_hand(binding_id: BindingId, destination: bpy.types.Collection, display: SavedDisplay) -> None:
    """Build display in destination, write the manifest and generation naming it, and update world matrices."""
    parent = bpy.data.objects.new("World", None)
    parent.location = display.parent_location
    mesh = bpy.data.meshes.new("Ref")
    mesh.from_pydata(display.vertices, [], display.faces)
    material = bpy.data.materials.new("Ref")
    material.diffuse_color = display.material_color
    mesh.materials.append(material)
    obj = bpy.data.objects.new("Ref", mesh)
    obj.parent = parent
    obj.location = display.mesh_local_location
    for each in (parent, obj):
        destination.objects.link(each)
    datablocks = {"world": parent, "ref": obj, "ref-mesh": mesh, "ref-material": material}
    entries = {
        key(name): ManifestEntry(datablocks[name], covers, role, [key(u) for u in uses], place)  # ty: ignore[invalid-argument-type] - a stored role's string
        for name, (covers, role, uses, place) in display.entries.items()
    }
    ownership.set_manifest(binding_id, Manifest(entries))
    binding_state.write_generation(
        destination,
        GenerationMetadata(binding_id, new_settings(PayloadPolicy.LOAD_ALL), 1.0, 0.0, SourceRevision("saved"), ()),
    )
    view_layer = bpy.context.view_layer
    assert view_layer is not None
    view_layer.update()  # matrix_world is computed at the update, and saved with the file


def expected_content(display: SavedDisplay) -> dict[str, dict[str, object]]:
    """collection_content (support.blend) of a destination holding display, from how the fixture is built."""
    world = [round(v, 6) for v in display.parent_location]
    ref = [round(p + o, 6) for p, o in zip(display.parent_location, display.mesh_local_location, strict=True)]

    def matrix(translation: list[float]) -> list[list[float]]:
        return [[1.0 if i == j else 0.0 for j in range(3)] + [translation[i]] for i in range(3)] + [[0.0] * 3 + [1.0]]

    return {
        "World": {"matrix": matrix(world), "parent": None, "vertices": None, "faces": None, "materials": None},
        "Ref": {
            "matrix": matrix(ref),
            "parent": "World",
            "vertices": [[round(c, 6) for c in v] for v in display.vertices],
            "faces": [list(f) for f in display.faces],
            "materials": [["Ref", [round(c, 6) for c in display.material_color]]],
        },
    }
