"""Which partitions a refresh prepares, which copies it updates in place, and which entries it replaces.

synchronization.partition_replacement.changed_partitions, on F-EDIT-SEQUENCE. Each test's published manifest is built
from a plan as publication would make it: an object entry for each drawn copy, and a bounds mesh's and a shear
parent's where the copy's partition has them, each naming a datablock of its own, linked nowhere. Expected copies come
from the fixture's steps; expected entry keys from those built entries and the rules of incremental.md "Affected
Content", which the module's docstring states case by case.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import bpy
import pytest
from pxr import Usd

from fixtures import edit_sequence, evaluation
from proscenium_sync import planner
from proscenium_sync.persistence.manifests import Manifest, ManifestEntry, RepresentationRole
from proscenium_sync.synchronization import partition_replacement
from support.manifests import key

if TYPE_CHECKING:
    from collections.abc import Buffer, Iterator
    from pathlib import Path

    from fixtures.edit_sequence import EditSequenceScene

MOVED, BOUNDS, PARTICIPATION, KEYS = "moved", "bounds changed", "participation changed", "cached keys removed"
# What each step that updates copies in place changes of them (bpy_free/test_planner_plan_diff.py's cases).
CHANGE_BY_STEP = {
    "ancestor-transform": MOVED,
    "coalesced-transform": MOVED,
    "repeated-transform": MOVED,
    "ancestor-visibility": PARTICIPATION,
    "visibility-restored": PARTICIPATION,
    "purpose-render": PARTICIPATION,
    "bounds-changed": BOUNDS,
    "shared-contents-changed": MOVED,
    "point-moved": MOVED,
    "point-removed-by-index": MOVED,
}
CONTEXT = planner.PlanningContext(unit_scale=1.0, representation_version=1)
SETTINGS = planner.PlanSettings(evaluation.VIEWPORT_PURPOSES, evaluation.RENDER_PURPOSES)
SHARED = "shared frames"  # a shared datablock's entry, as the frames group a cache call samples with


@dataclass(frozen=True)
class Entry:
    name: str  # its key is key(name)
    source: str | None  # None for a shared datablock's
    role: RepresentationRole
    place: int | None = 0  # None for a shared datablock's
    present: bool = True
    uses: tuple[str, ...] = ()  # names


@dataclass
class Decided:
    prepared: set[str]  # by source path
    updated: dict[str, set[str]] = field(default_factory=dict)  # source path -> what its local update changes
    replaced: set[str] = field(default_factory=set)  # entry names


@pytest.fixture
def scene(tmp_path: Path) -> Iterator[EditSequenceScene]:
    with edit_sequence.edit_sequence(tmp_path) as scene:
        yield scene


def _plan_at(stage: Usd.Stage) -> planner.Plan:
    chain = planner.SceneIndexChain(stage)
    try:
        return planner.plan(chain.capture(Usd.TimeCode(0.0)), SETTINGS, CONTEXT)
    finally:
        chain.release()


def _indices(buffer: Buffer) -> list[int]:
    with memoryview(buffer) as view:
        return view.tolist()


def _published(plan: planner.Plan) -> list[Entry]:
    """The entries publishing plan would write: each copy's object, bounds mesh, and shear parent."""
    bounds = _indices(plan.copy_bounds_mesh_resource_indices)
    parents = _indices(plan.copy_shear_parent_resource_indices)
    entries = []
    for copy, entry in enumerate(plan.correspondence):
        source = entry.source_path
        entries.append(Entry(f"object {source}", source, RepresentationRole.OBJECT))
        if bounds[copy] >= 0:
            entries.append(Entry(f"bounds mesh {source}", source, RepresentationRole.BOUNDS_MESH))
        if parents[copy] >= 0:
            entries.append(Entry(f"shear parent {source}", source, RepresentationRole.SHEAR_PARENT))
    return entries


def _manifest(entries: list[Entry]) -> Manifest:
    """A manifest of entries, each present one naming a new datablock linked nowhere."""
    built = {}
    for e in entries:
        datablock = bpy.data.objects.new(e.name, None) if e.present else None
        place = None if e.source is None else e.place
        paths = [e.source] if e.source is not None else ["/"]
        built[key(e.name)] = ManifestEntry(datablock, paths, e.role, [key(u) for u in e.uses], place)
    return Manifest(built)


def _decided(
    previous: planner.Plan, plan: planner.Plan, entries: list[Entry], destination: bpy.types.Collection
) -> Decided:
    published = _manifest(entries)
    replacement = partition_replacement.changed_partitions(previous, plan, published, destination)
    sources = [entry.source_path for entry in plan.correspondence]
    names = {key(e.name): e.name for e in entries}
    assert list(replacement.prepared_copy_indices) == sorted(set(replacement.prepared_copy_indices))
    return Decided(
        {sources[c] for c in replacement.prepared_copy_indices},
        {
            sources[c]: {
                name
                for name, changes in (
                    (MOVED, update.moved),
                    (BOUNDS, update.bounds_changed),
                    (PARTICIPATION, update.participation_changed),
                    (KEYS, update.cached_keys_removed),
                )
                if changes
            }
            for c, update in replacement.updated_copies.items()
        },
        {names[k] for k in replacement.replaced_entry_keys},
    )


def _names(entries: list[Entry], sources: set[str]) -> set[str]:
    return {e.name for e in entries if e.source in sources}


@pytest.fixture
def destination() -> bpy.types.Collection:
    return bpy.data.collections.new("Destination")


def _equal_plans(scene: EditSequenceScene) -> tuple[planner.Plan, planner.Plan, list[Entry], str]:
    """Two equal plans, the entries publishing the first, and an unsheared copy's source path."""
    previous, plan = _plan_at(scene.stage), _plan_at(scene.stage)
    parents = _indices(plan.copy_shear_parent_resource_indices)
    first = next(e.source_path for c, e in enumerate(plan.correspondence) if parents[c] < 0)
    return previous, plan, _published(previous), first


def _sample(source: str) -> Entry:
    """A cache call's sampled bounds mesh for the copy at source, using the shared frames group that shows it."""
    return Entry(f"samples {source}", source, RepresentationRole.BOUNDS_MESH, uses=(SHARED,))


def test_an_equal_plan_replaces_nothing(scene: EditSequenceScene, destination: bpy.types.Collection) -> None:
    plan = _plan_at(scene.stage)
    assert _decided(plan, _plan_at(scene.stage), _published(plan), destination) == Decided(set())


def test_each_step_prepares_updates_and_replaces_what_the_fixture_names(
    scene: EditSequenceScene, destination: bpy.types.Collection
) -> None:
    # Built and rebuilt copies are prepared, their published entries replaced, as are retired copies'; updated copies
    # carry what their step changes.
    previous = _plan_at(scene.stage)
    for step in scene.steps:
        step.edit(scene.stage)
        plan = _plan_at(scene.stage)
        entries = _published(previous)
        prepared = {source for source, _ in step.built | step.rebuilt}
        retired = {source for source, _ in step.retired}
        expected = Decided(
            prepared,
            {source: {CHANGE_BY_STEP[step.name]} for source, _ in step.updated},
            _names(entries, prepared | retired),
        )
        assert _decided(previous, plan, entries, destination) == expected, step.name
        previous = plan


def test_what_the_published_partition_holds_decides_a_kept_copy(
    scene: EditSequenceScene, destination: bpy.types.Collection
) -> None:
    # A kept copy whose published resource is gone, that has a shear parent its plan lacks, a second object, or a
    # cache call's sample with a shared datablock is prepared anew, its entries replaced, the group with its last user;
    # an action, a cached generation's keys, updates it in place, retiring the action alone.
    previous, plan, entries, first = _equal_plans(scene)
    gone = f"object {first}"
    role = RepresentationRole
    cases = {
        "incomplete": [Entry(e.name, e.source, e.role, present=False) if e.name == gone else e for e in entries],
        "parented": [*entries, Entry(f"shear parent {first}", first, role.SHEAR_PARENT)],
        "doubled": [*entries, Entry(f"object 1 {first}", first, role.OBJECT, place=1)],
        "sampled": [*entries, Entry(SHARED, None, role.NODE_GROUP, None), _sample(first)],
    }
    for name, published in cases.items():
        expected = _names(published, {first}) | ({SHARED} if name == "sampled" else set())
        assert _decided(previous, plan, published, destination) == Decided({first}, {}, expected), name
    acted = [*entries, Entry(f"action {first}", first, role.ACTION)]
    expected = Decided(set(), {first: {KEYS}}, {f"action {first}"})
    assert _decided(previous, plan, acted, destination) == expected


def test_a_shared_datablock_stays_while_a_kept_entry_uses_it(
    scene: EditSequenceScene, destination: bpy.types.Collection
) -> None:
    previous, plan, entries, first = _equal_plans(scene)
    sampled = [*entries, Entry(SHARED, None, RepresentationRole.NODE_GROUP, None), _sample(first)]
    used = [*sampled, Entry("kept material", None, RepresentationRole.MATERIAL, None, uses=(SHARED,))]
    assert SHARED not in _decided(previous, plan, used, destination).replaced


def test_a_published_copy_neither_plan_draws_is_replaced(
    scene: EditSequenceScene, destination: bpy.types.Collection
) -> None:
    # As one a cache call built for a cached time code alone.
    previous, plan, entries, _ = _equal_plans(scene)
    stray = [*entries, Entry("object stray", "/World/OnlyCached", RepresentationRole.OBJECT)]
    assert _decided(previous, plan, stray, destination) == Decided(set(), {}, {"object stray"})


def test_a_kept_copy_other_content_uses_is_prepared(
    scene: EditSequenceScene, destination: bpy.types.Collection
) -> None:
    # A moved copy whose object another collection also links is prepared anew rather than updated in place (CHG-06).
    previous = _plan_at(scene.stage)
    step = next(s for s in scene.steps if CHANGE_BY_STEP.get(s.name) == MOVED and s.updated)
    step.edit(scene.stage)
    plan = _plan_at(scene.stage)
    entries = _published(previous)
    [(moved, _)] = sorted(step.updated)[:1]
    published = _manifest(entries)
    other = bpy.data.collections.new("Other")
    obj = published.entries[key(f"object {moved}")].datablock
    assert isinstance(obj, bpy.types.Object)
    other.objects.link(obj)
    replacement = partition_replacement.changed_partitions(previous, plan, published, destination)
    sources = [entry.source_path for entry in plan.correspondence]
    assert moved in {sources[c] for c in replacement.prepared_copy_indices}
    assert moved not in {sources[c] for c in replacement.updated_copies}
