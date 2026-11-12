"""Checks that a refresh acts on exactly the copies a change-matrix case names (change-matrix.md; M7 plan, C7).

refresh_acting_on refreshes a binding and checks that it displays what a clean binding of the same stage, settings,
and time code does (TINC-01, clean_rebuild.py), and acts on exactly the copies named (AFF-01, DISC-06): an updated copy
keeps its object, and its Blender selection (CHG-01, CHG-02); a rebuilt copy's resources are new and its old ones
retired (CHG-03); a retired copy's resources are gone, and a built copy's new. Every other copy keeps its resources and
their manifest entries, none of their transforms or geometry updated in the depsgraph, and a refresh acting on no copy
writes no display resource, only the generation record and last attempt, for what they record (CHG-07). Copies are
named by source entity, as the manifest names them; retiring and building at one path, as instanceable toggled does,
replaces that path's resources.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy

from proscenium.binding.persistence import id_property_records
from proscenium.binding.persistence.manifests import RepresentationRole
from proscenium.binding.results import ResultState
from proscenium.binding.runtime import ownership

from .blender_writes import ObservedWrites, observed_writes
from .clean_rebuild import clean_rebuild, display_state

if TYPE_CHECKING:
    from collections.abc import Callable, Collection

    import pytest
    from pxr import Usd

    from proscenium.api.bindings import BindingHandle, Bindings
    from proscenium.binding.persistence import manifests
    from proscenium.binding.results import Result
    from proscenium.binding.source_access import BindingId

type EntriesBySource = dict[str, dict[str, manifests.ManifestEntry]]


def entries_by_source(binding_id: BindingId) -> EntriesBySource:
    """The manifest's copy entries, by entry key, grouped by their copy's source entity."""
    manifest = ownership.manifest(binding_id)
    assert isinstance(manifest, id_property_records.LoadedRecord)
    grouped: EntriesBySource = {}
    for key, entry in manifest.record.entries.items():
        if (identity := entry.identity) is not None:
            grouped.setdefault(identity.entity, {})[key] = entry
    return grouped


def copy_object(entries: dict[str, manifests.ManifestEntry]) -> bpy.types.Object:
    """The object among one copy's entries."""
    [obj] = [e.datablock for e in entries.values() if e.role is RepresentationRole.OBJECT]
    assert isinstance(obj, bpy.types.Object)
    return obj


def _datablocks(entries: dict[str, manifests.ManifestEntry]) -> list[bpy.types.ID]:
    return [e.datablock for e in entries.values() if e.datablock is not None]


def refresh_acting_on(  # noqa: PLR0913 - the refresh, and the copies it acts on
    bindings: Bindings,
    handle: BindingHandle,
    stage: Usd.Stage,
    monkeypatch: pytest.MonkeyPatch,
    label: str,
    *,
    updated: Collection[str] = (),
    rebuilt: Collection[str] = (),
    retired: Collection[str] = (),
    built: Collection[str] = (),
    time_code: Usd.TimeCode | float = 0.0,
    refresh: Callable[[], Result] | None = None,
) -> tuple[EntriesBySource, EntriesBySource, ObservedWrites]:
    """Refresh handle, checking it acts on exactly the copies named; what it wrote, and the copy entries around it.

    The refresh is a synchronization at time_code unless refresh is given; stage, at time_code, is what a clean
    binding compares with. Returns the manifest's copy entries before and after, and what the refresh wrote.
    """
    view_layer = bpy.data.scenes["Scene"].view_layers[0]
    before = entries_by_source(handle.binding_id)
    replaced = {*rebuilt, *retired, *built}
    untouched = before.keys() - set(updated) - replaced
    # Every object selected, as Blender lets a shown one be, and an updated one active, so a refresh is seen keeping
    # both; Blender deselects an object the refresh hides.
    for entries in before.values():
        copy_object(entries).select_set(True)
    selected = {s for s, entries in before.items() if copy_object(entries).select_get(view_layer=view_layer)}
    active = copy_object(before[min(updated)]) if updated else None
    view_layer.objects.active = active
    with observed_writes(monkeypatch) as observed:
        result = handle.synchronize(time_code) if refresh is None else refresh()
        assert result.state is not ResultState.FATAL_FAILURE, label
    after = entries_by_source(handle.binding_id)
    clean = clean_rebuild(bindings, stage, handle.requested_settings(), time_code)
    assert display_state(handle.binding_id) == clean, label
    if not (updated or replaced):
        # No display resource written: only the records of what the generation now records.
        assert not observed.updated_ids and observed.created_id_count == 0, (label, observed)
        assert set(observed.record_writes) <= {"generation", "last attempt"}, (label, observed)
    written = set(observed.changed_ids)
    for source in untouched:
        assert after[source] == before[source], (label, source)
        for datablock in _datablocks(before[source]):
            assert f"{type(datablock).__name__}:{datablock.name}" not in written, (label, datablock)
        assert copy_object(after[source]).select_get(view_layer=view_layer) == (source in selected), (label, source)
    for source in updated:
        obj = copy_object(after[source])
        assert obj == copy_object(before[source]), (label, source)
        if not obj.hide_viewport:
            assert obj.select_get(view_layer=view_layer) == (source in selected), (label, source)
    if active is not None and not active.hide_viewport:
        assert view_layer.objects.active == active, label
    for source in replaced:
        old = _datablocks(before.get(source, {}))
        assert not any(id_property_records.alive(datablock) for datablock in old), (label, source)
        new = _datablocks(after.get(source, {}))
        assert all(datablock not in old for datablock in new), (label, source)
    assert after.keys() == (before.keys() - set(retired)) | set(built), label
    return before, after, observed
