"""The whole published generation, and the file's datablocks, as failure-injection tests compare them (TLAY-03).

Correspondence, which M7 persists, joins the generation here when it does.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import bpy

from proscenium.binding.persistence import binding_state, manifests, records
from proscenium.binding.runtime import ownership_index
from support.blend import collection_content

if TYPE_CHECKING:
    from proscenium.binding.source_access.identifiers import BindingId


def published_generation(binding_id: BindingId, destination: bpy.types.Collection) -> dict[str, Any]:
    """The binding's published generation by value.

    Its manifest and generation record as stored, the manifest the ownership index holds, and the display: which
    objects the destination links, and each one's values.
    """
    return {
        "manifest": records.stored(destination, manifests.MANIFEST_KEY),
        "held manifest": ownership_index.manifest(binding_id),
        "generation": records.stored(destination, binding_state.GENERATION_KEY),
        "objects": {o.session_uid for o in destination.objects},
        "content": collection_content(destination),
    }


def datablocks() -> set[tuple[str, int]]:
    """Every datablock in the file, by kind and session_uid, so one made or removed shows."""
    return {(type(d).__name__, d.session_uid) for d in bpy.data.user_map()}
