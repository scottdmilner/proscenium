"""A binding's saved display built by hand, as F-OFFLINE describes it (fixtures.source_access.SavedDisplay).

Nothing publishes until M5, so tests that need a published display build it here, and record it as a
publication would: in the binding's manifest and generation. Needs the extension registered.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy

from proscenium.core.source_access import PayloadPolicy
from proscenium.persistence import binding_state
from proscenium.persistence.binding_state import Generation
from proscenium.persistence.ownership import Manifest, ManifestEntry
from proscenium.runtime import indexes

if TYPE_CHECKING:
    from fixtures.source_access import SavedDisplay


def publish_by_hand(binding_id: str, destination: bpy.types.Collection, display: SavedDisplay) -> None:
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
    obj.location = display.location
    for each in (parent, obj):
        destination.objects.link(each)
    datablocks = {"world": parent, "ref": obj, "ref-mesh": mesh, "ref-material": material}
    entries = {key: ManifestEntry(datablocks[key], *entry) for key, entry in display.entries.items()}
    indexes.set_manifest(binding_id, Manifest(entries))
    binding_state.write_generation(destination, Generation(binding_id, PayloadPolicy.LOAD_ALL, 0.0, ()))
    view_layer = bpy.context.view_layer
    assert view_layer is not None
    view_layer.update()  # matrix_world is computed at the update, and saved with the file


def expected_content(display: SavedDisplay) -> dict[str, dict[str, object]]:
    """collection_content (support.blend) of a destination holding display, from how the fixture is built."""
    world = [round(v, 6) for v in display.parent_location]
    ref = [round(p + o, 6) for p, o in zip(display.parent_location, display.location, strict=True)]

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
