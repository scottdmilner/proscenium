"""What a binding's interaction functions answer, by manifest entry key, to compare across a save and reopen.

Objects are new Python references after a reopen, and their names aren't source identifiers, so each answer names an
object by the manifest entry key that names it, which the saved manifest keeps. Needs the extension registered.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import bpy
from pxr import Gf

from proscenium.binding.persistence import id_property_records
from proscenium.binding.persistence.manifests import RepresentationRole
from proscenium.binding.runtime import ownership
from support import interaction_oracle

if TYPE_CHECKING:
    from pxr import Usd

    from proscenium.api.bindings import BindingHandle
    from proscenium.binding.source_access import BindingId


@dataclass(frozen=True)
class InteractionAnswers:
    """A binding's interaction answers, objects named by their manifest entry keys."""

    picks: dict[str, tuple[str, tuple[str, ...], str] | None]  # each object's entity, context, and floor
    universe: frozenset[str]  # the composed prims displayed reports
    highlights: dict[str, frozenset[str]]  # each universe prim's highlighted objects
    targets: dict[str | None, tuple[str, ...]]  # by level: the targets of every object's entity


def object_entry_keys(binding_id: BindingId) -> dict[bpy.types.Object, str]:
    """Each object the binding's manifest names in the object role, and its entry key."""
    manifest = ownership.manifest(binding_id)
    assert isinstance(manifest, id_property_records.LoadedRecord)
    return {
        obj: key
        for key, entry in manifest.record.entries.items()
        if entry.role is RepresentationRole.OBJECT and isinstance(obj := entry.datablock, bpy.types.Object)
    }


def answers(handle: BindingHandle, stage: Usd.Stage) -> InteractionAnswers:
    """What resolve_pick, displayed, highlight_targets, and select_targets answer for the binding's display."""
    keys = object_entry_keys(handle.binding_id)
    picks = {}
    for obj, key in keys.items():
        picked = handle.resolve_pick(obj, Gf.Matrix4d(*(v for row in obj.matrix_world for v in row)))
        picks[key] = None if picked is None else (picked.source_path, picked.instance_context, picked.floor)
    paths = interaction_oracle.all_paths(stage)
    universe = frozenset(p for p, shown in zip(paths, handle.displayed(paths), strict=True) if shown)
    highlights = {p: frozenset(keys[obj] for obj in handle.highlight_targets([p])) for p in universe}
    entities = sorted({pick[0] for pick in picks.values() if pick is not None})
    targets = {level: tuple(handle.select_targets(entities, level)) for level in interaction_oracle.levels()}
    return InteractionAnswers(picks, universe, highlights, targets)
