"""A scene's source selection: stored, resolved, mirrored, and changed by picks and boxes (interaction-contract.md).

DECISIONS.md "Headless interaction functions": Bindings gives callers each scene's source selection. The persistent
selection (proscenium.binding.persistence.source_selection) stores targets. Resolving it at the time code each
binding's display shows expands the entries that display's universe holds and reports the rest unresolved, kept stored
(ICON-25, ICON-26); an entry whose binding has no live stage is unresolved too. Setting it stores it and mirrors it
into the scene's active view layer (ICON-27 to ICON-29). A pick or a box changes it at a level, in a mode (M4 plan,
F2): a box identifies the viewport elements whose world bounds' centers lie inside it (ICON-40). Listeners are called
once for each change to a scene's stored selection. Nothing here pushes an undo step, as only a publishing
synchronization and a committing cleanup retry do.

The owner of the destinations' display decides when managed content is selectable, through each destination's
hide_select, which a selection tool sets as it becomes active or inactive (ICON-41). Blender deselects the objects of an
unselectable collection, and of an object a hide flag hides, without selecting them again, so the selection is
mirrored again when content becomes selectable, when a synchronization publishes objects anew (PH2-02), when a window
shows a view layer (ICON-39), and when the frame changes
for a scene whose selection has entries of a binding whose generation caches time codes, the only displays whose hide
flags change with the frame (DECISIONS.md "Headless interaction functions"). No overlay is hidden: Blender's outlines
show the selection.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

import bpy
from mathutils import Vector

from ..binding.persistence import id_property_records, source_selection
from ..binding.persistence.source_selection import PersistentSelection, SelectionEntry
from ..binding.runtime import binding_operations
from ..binding.source_access import stages
from ..interaction import blender_selection
from . import binding_interaction
from .binding_interaction import ShownDisplay

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from mathutils import Matrix

    from ..binding.source_access import BindingId
    from .bindings import Bindings

EMPTY = PersistentSelection((), None)


class SelectionMode(StrEnum):
    """How a pick's or a box's targets change a scene's source selection."""

    SET = "set"  # they replace it
    EXTEND = "extend"  # they join it
    TOGGLE = "toggle"  # each leaves it if in it, else joins it
    SUBTRACT = "subtract"  # they leave it


@dataclass(frozen=True)
class SelectionResolution:
    """A source selection's entries, each resolved or not at the time code its binding's display shows."""

    resolved: tuple[SelectionEntry, ...]  # in the selection's order
    unresolved: tuple[SelectionEntry, ...]  # stored still, and reported


def stored_selection(scene: bpy.types.Scene) -> PersistentSelection:
    """The scene's stored source selection, empty if it has none; RefusedRecordError for one that can't be read."""
    stored = source_selection.read_selection(scene)
    if stored is None:
        return EMPTY
    if isinstance(stored, id_property_records.RefusedRecord):
        raise id_property_records.RefusedRecordError(stored)
    return stored.record


def active_view_layer(scene: bpy.types.Scene) -> bpy.types.ViewLayer | None:
    """The view layer a window shows the scene with, or the context's; None while no window or context shows it."""
    window_manager = bpy.context.window_manager
    for window in window_manager.windows if window_manager is not None else ():
        if window.scene == scene:
            return window.view_layer
    return bpy.context.view_layer if bpy.context.scene == scene else None


def _displays(bindings: Bindings, scene: bpy.types.Scene) -> dict[BindingId, ShownDisplay]:
    """Each of the scene's bindings with a live stage, its display read once."""
    displays = {}
    for handle in bindings.in_scene(scene):
        try:
            displays[handle.binding_id] = ShownDisplay(bindings, handle.binding_id)
        except stages.SourceUnavailableError:
            continue
    return displays


def _resolve(selection: PersistentSelection, displays: dict[BindingId, ShownDisplay]) -> SelectionResolution:
    paths_by_binding: dict[BindingId, list[str]] = {}
    for entry in selection.entries:
        paths_by_binding.setdefault(entry.binding_id, []).append(entry.path)
    displayed: set[SelectionEntry] = set()
    for binding_id, paths in paths_by_binding.items():
        if (display := displays.get(binding_id)) is not None:
            shown = memoryview(display.correspondence.displayed(paths)).tolist()
            displayed |= {SelectionEntry(binding_id, p) for p, is_shown in zip(paths, shown, strict=True) if is_shown}
    return SelectionResolution(
        tuple(e for e in selection.entries if e in displayed), tuple(e for e in selection.entries if e not in displayed)
    )


def resolve(bindings: Bindings, scene: bpy.types.Scene) -> SelectionResolution:
    """The scene's stored source selection, resolved at the time code each binding's display shows."""
    return _resolve(stored_selection(scene), _displays(bindings, scene))


def _mirror(
    selection: PersistentSelection, displays: dict[BindingId, ShownDisplay], view_layer: bpy.types.ViewLayer
) -> None:
    """Mirror the selection's resolved entries into the view layer, binding by binding."""
    resolved = _resolve(selection, displays).resolved
    for binding_id, display in displays.items():
        if display.elements is None:
            continue
        targets = [e.path for e in resolved if e.binding_id == binding_id]
        covered = memoryview(display.correspondence.highlight_targets(targets)).tolist()
        active: list[int] = []
        if (entry := selection.active) is not None and entry.binding_id == binding_id and entry in resolved:
            active = memoryview(display.correspondence.highlight_targets([entry.path])).tolist()
        blender_selection.apply_selection(display.elements, view_layer, covered, active)


def mirror(bindings: Bindings, scene: bpy.types.Scene, view_layer: bpy.types.ViewLayer | None = None) -> None:
    """Mirror the scene's stored source selection into view_layer, by default the scene's active one if it has one."""
    if (layer := view_layer or active_view_layer(scene)) is not None:
        _mirror(stored_selection(scene), _displays(bindings, scene), layer)


def _store(
    bindings: Bindings,
    scene: bpy.types.Scene,
    selection: PersistentSelection,
    displays: dict[BindingId, ShownDisplay],
) -> None:
    """Store selection as the scene's, calling the listeners if it changed, and mirror it into the active view layer."""
    if selection != stored_selection(scene):
        source_selection.write_selection(scene, selection)
        for listener in list(bindings.selection_listeners):
            listener(scene)
    if (layer := active_view_layer(scene)) is not None:
        _mirror(selection, displays, layer)


def set_selection(bindings: Bindings, scene: bpy.types.Scene, selection: PersistentSelection) -> None:
    """Store selection as the scene's source selection and mirror it into the scene's active view layer."""
    _store(bindings, scene, selection, _displays(bindings, scene))


def _changed(
    selection: PersistentSelection, chosen: Sequence[SelectionEntry], mode: SelectionMode, picked: SelectionEntry | None
) -> PersistentSelection:
    """The selection mode makes of selection and the chosen targets; picked becomes active where it is selected."""
    chosen = list(dict.fromkeys(chosen))
    old = selection.entries
    if mode is SelectionMode.SET:
        entries = chosen
    elif mode is SelectionMode.EXTEND:
        entries = [*old, *(e for e in chosen if e not in old)]
    elif mode is SelectionMode.TOGGLE:
        entries = [*(e for e in old if e not in chosen), *(e for e in chosen if e not in old)]
    else:
        entries = [e for e in old if e not in chosen]
    if picked is not None and picked in entries and mode is not SelectionMode.SUBTRACT:
        active = picked
    else:
        active = selection.active if selection.active in entries else None
    return PersistentSelection(tuple(entries), active)


def select_by_pick(
    bindings: Bindings,
    scene: bpy.types.Scene,
    obj: bpy.types.Object | None,
    world_matrix: Matrix | None,
    level: str | None,
    mode: SelectionMode,
) -> None:
    """Change the scene's source selection by the target at level of what a pick hit, which becomes active.

    obj and world_matrix are what a ray cast returns; None for nothing hit.

    A pick of nothing, or of an object no binding's display shows, chooses no target, so it empties the selection in
    SET mode and leaves it as it is otherwise.
    """
    displays = _displays(bindings, scene)
    picked = None
    for binding_id, display in displays.items():
        if (
            obj is None
            or display.elements is None
            or obj not in (indices := display.elements.element_index_by_object())
        ):
            continue
        matrix = binding_interaction.usd_matrix(world_matrix if world_matrix is not None else obj.matrix_world)
        entity = display.correspondence.resolve_pick(indices[obj], matrix)
        if entity is not None:
            [target] = display.correspondence.select_targets([entity.source_path], level)
            picked = SelectionEntry(binding_id, target)
            break
    chosen = [] if picked is None else [picked]
    _store(bindings, scene, _changed(stored_selection(scene), chosen, mode, picked), displays)


def world_bounds_center(obj: bpy.types.Object) -> Vector:
    """The center of the object's world bounds: its local bounding box's center, in world space."""
    corners = [Vector(corner) for corner in obj.bound_box]
    return obj.matrix_world @ (sum(corners, Vector()) / len(corners))


def select_by_box(
    bindings: Bindings,
    scene: bpy.types.Scene,
    inside: Callable[[Vector], bool],
    level: str | None,
    mode: SelectionMode,
) -> None:
    """Change the scene's source selection by the targets at level of the viewport elements a box identifies.

    inside tells whether a world-space point lies inside the box; an element is identified when its world bounds' center
    does (ICON-40). The active entry stays active while it is selected.
    """
    displays = _displays(bindings, scene)
    chosen = []
    for binding_id, display in displays.items():
        if (elements := display.elements) is None:
            continue
        identified = [
            i
            for i, (obj, shown) in enumerate(zip(elements.objects, elements.visible_in_viewport, strict=True))
            if shown and inside(world_bounds_center(obj))
        ]
        targets = display.correspondence.selection_from_blender(identified, None, level).target_paths
        chosen += [SelectionEntry(binding_id, target) for target in targets]
    _store(bindings, scene, _changed(stored_selection(scene), chosen, mode, None), displays)


def managed_selectable(scene: bpy.types.Scene) -> bool:
    """Whether the scene's managed content is selectable: no destination of its bindings is unselectable."""
    return not any(
        f.destination is not None and f.destination.hide_select for f in binding_operations.find_bindings(scene)
    )


def set_managed_selectable(bindings: Bindings, scene: bpy.types.Scene, selectable: bool) -> None:
    """Make the scene's managed content selectable or not, mirroring its source selection back once it is.

    Blender deselects the objects of an unselectable destination, and the stored selection stays as it was.
    """
    for found in binding_operations.find_bindings(scene):
        if found.destination is not None:
            found.destination.hide_select = not selectable
    if selectable:
        mirror(bindings, scene)


def mirror_after_frame_change(bindings: Bindings, scene: bpy.types.Scene) -> None:
    """Mirror the scene's source selection again if a binding with entries in it caches time codes.

    Nothing while a synchronization, cache call, or cleanup retry runs, or over a stored selection that can't be read.
    """
    if bindings.running:
        return
    try:
        selection = stored_selection(scene)
    except id_property_records.RefusedRecordError:
        return
    for binding_id in dict.fromkeys(e.binding_id for e in selection.entries):
        if (shown := binding_interaction.shown_generation(binding_id)) is not None and shown[0].cached_time_codes:
            mirror(bindings, scene)
            return


def mirror_after_publication(bindings: Bindings, scene: bpy.types.Scene) -> None:
    """Mirror the scene's source selection again after a publication, whose rebuilt and built objects are unselected.

    The selection's entries whose identities a refresh kept resolve still (PH2-02). Nothing for an empty selection,
    one that can't be read, or a scene no window or context shows.
    """
    try:
        selection = stored_selection(scene)
    except id_property_records.RefusedRecordError:
        return
    if selection.entries and (layer := active_view_layer(scene)) is not None:
        _mirror(selection, _displays(bindings, scene), layer)
