"""What a binding displays, compared by value with a clean binding's first synchronization of the same stage (TINC-01).

A refresh's display is right when it equals what a new binding attached to the same stage shows after one
synchronization: each drawn copy's source entity, hide flags, and world-space vertices (support/displayed_copies.py),
and the manifest's shape, each entry's role, source entities, place in its copy, and the entries it uses, named by
the same, since entry keys and datablocks differ between bindings. The correspondence joins it with Phase E's.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import bpy

from proscenium.binding.persistence import id_property_records
from proscenium.binding.results import ResultState
from proscenium.binding.runtime import ownership

from .displayed_copies import displayed_copies

if TYPE_CHECKING:
    from pxr import Usd

    from proscenium.api.bindings import Bindings
    from proscenium.binding.source_access import BindingId

    from .bounds_check import DisplayedCopy

# A manifest entry without its key or datablock: its role, source entities, and place in its copy.
type EntryShape = tuple[str, tuple[str, ...], int | None]


@dataclass(frozen=True, slots=True)
class DisplayState:
    """What a binding's published generation displays, by value."""

    copies: tuple[DisplayedCopy, ...]  # sorted by source entity, then vertices
    manifest_entries: frozenset[tuple[EntryShape, frozenset[EntryShape]]]  # each entry and those it uses


def display_state(binding_id: BindingId) -> DisplayState:
    """What binding_id's display shows."""
    copies = sorted(displayed_copies(binding_id), key=lambda copy: (copy.source_path, copy.world_vertices))
    manifest = ownership.manifest(binding_id)
    assert isinstance(manifest, id_property_records.LoadedRecord), manifest
    entries = manifest.record.entries
    shapes = {key: (str(e.role), tuple(e.source_entity_paths), e.object_index_in_copy) for key, e in entries.items()}
    return DisplayState(
        tuple(copies),
        frozenset(
            (shapes[key], frozenset(shapes[used] for used in e.dependency_entry_keys)) for key, e in entries.items()
        ),
    )


def clean_rebuild(bindings: Bindings, stage: Usd.Stage) -> DisplayState:
    """What a clean binding's first synchronization of stage displays; the binding is released after."""
    clean = bindings.create_binding(bpy.data.scenes["Scene"], name="Clean")
    assert clean.attach(stage).state is not ResultState.FATAL_FAILURE
    assert clean.synchronize(0).state is not ResultState.FATAL_FAILURE
    try:
        return display_state(clean.binding_id)
    finally:
        bindings.release(clean.binding_id)
