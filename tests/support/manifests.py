"""Entry keys and entries for manifests that tests build by hand.

A manifest's entry keys are random (proscenium.binding.persistence.new_entry_key). A test names each entry instead:
key(name) is that name's own key, the same in every process, so assertions can name entries.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from proscenium.binding.persistence import ManifestEntry, RepresentationRole

if TYPE_CHECKING:
    import bpy


def key(name: str) -> str:
    """The entry key a test calls name: 32 hex digits derived from it."""
    return hashlib.md5(name.encode(), usedforsecurity=False).hexdigest()


def object_entry(datablock: bpy.types.ID | None, entity: str, uses: tuple[str, ...] = ()) -> ManifestEntry:
    """An entry for a drawn copy's only object, covering entity and using the entries named uses."""
    return ManifestEntry(datablock, [entity], RepresentationRole.OBJECT, [key(name) for name in uses], place=0)
