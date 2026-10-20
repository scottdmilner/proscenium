"""The persistent selection as a record on the scene (interaction-contract.md#persistent-selection; ICON-24, SID-07)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy
import pytest

from fixtures import interaction, source_access
from proscenium import synchronization
from proscenium.records import NAMESPACE, VERSION_KEY, Loaded, RecordRefused, Refusal, Refused
from proscenium.selection import SELECTION_KEY, PersistentSelection, SelectionEntry, read_selection, write_selection
from proscenium.synchronization import Synchronization
from support import interaction_oracle
from support.blend import save_and_reopen

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture
def sync(monkeypatch: pytest.MonkeyPatch) -> Iterator[Synchronization]:
    fresh = Synchronization()
    monkeypatch.setattr(synchronization, "SYNCHRONIZATION", fresh)
    yield fresh


def _scene() -> bpy.types.Scene:
    return bpy.data.scenes["Scene"]


def test_a_selection_from_two_bindings_survives_save_and_reopen(sync: Synchronization, tmp_path: Path) -> None:
    # ICON-24 on F-BINDING-STATE: the same entries, in order, and the same active entry.
    with source_access.binding_state(tmp_path) as scene:
        first = sync.create_file_binding(_scene(), scene.root)
        second = sync.create_attached_binding(_scene(), scene.key)
    entries = (
        SelectionEntry(second.binding_id, "/World/Ref"),
        SelectionEntry(first.binding_id, "/World/PayA"),
        SelectionEntry(first.binding_id, "/World"),
    )
    selection = PersistentSelection(entries, entries[1])
    write_selection(_scene(), selection)
    save_and_reopen(tmp_path / "selection.blend")
    assert read_selection(_scene()) == Loaded(selection, 1)


def test_stored_entries_are_pairs_of_strings() -> None:
    entry = SelectionEntry("B1", "/World")
    write_selection(_scene(), PersistentSelection((entry,), None))
    assert _scene()[NAMESPACE][SELECTION_KEY].to_dict()["entries"] == [["B1", "/World"]]
    loaded = read_selection(_scene())
    assert isinstance(loaded, Loaded)
    assert loaded.record.entries == (("B1", "/World"),)  # a tuple, with names
    assert loaded.record.entries[0].path == "/World"


def test_the_oracles_targets_are_stored_exactly(tmp_path: Path) -> None:
    # Compatibility with M2's contract on F-NESTED-SELECTION: targets at every level persist as entries
    # whose paths are the oracle's own, so the oracle's expansion of them is unchanged.
    with interaction.nested_selection(tmp_path / "scene") as scene:
        generation = interaction_oracle.generation(scene.stage, scene.times[0])
        targets = sorted(
            {
                interaction_oracle.kind_target(scene.stage, floor, level)
                for floor in generation.floors.values()
                for level in interaction_oracle.levels()
            }
        )
        selection = PersistentSelection(tuple(SelectionEntry("B1", t) for t in targets), None)
        write_selection(_scene(), selection)
        save_and_reopen(tmp_path / "selection.blend")
        loaded = read_selection(_scene())
        assert isinstance(loaded, Loaded)
        assert [entry.path for entry in loaded.record.entries] == targets
        assert [generation.beneath(e.path) for e in loaded.record.entries] == [generation.beneath(t) for t in targets]


def test_replacing_the_attached_stage_leaves_the_selection(sync: Synchronization, tmp_path: Path) -> None:
    # SID-07 on F-REATTACH: the entries are stored apart from the attachment, so replacing the stage,
    # even with a confirmed different root layer, leaves them; they resolve against the next generation.
    handle = sync.create_attached_binding(_scene(), "shot")
    selection = PersistentSelection((SelectionEntry(handle.binding_id, "/World/Ref"),), None)
    write_selection(_scene(), selection)
    with source_access.reattach(tmp_path) as scene:
        sync.attach("shot", scene.caller)
        sync.attach("shot", scene.same_root)
        sync.attach("shot", scene.other_root, confirm=True)
        assert read_selection(_scene()) == Loaded(selection, 1)


def test_entries_for_a_binding_that_is_gone_stay_stored() -> None:
    selection = PersistentSelection((SelectionEntry("not-a-binding", "/World"),), None)
    write_selection(_scene(), selection)
    assert read_selection(_scene()) == Loaded(selection, 1)


@pytest.mark.parametrize(
    ("entries", "active", "problem"),
    [
        ([["B1", "/World"], ["B1", "/World"]], None, "an entry appears twice"),
        ([["B1", "/World"]], ["B1", "/Other"], "the active entry is not one of the entries"),
        ([["B1", "World"]], None, "not an absolute prim path"),
        ([["B1", "/World", "extra"]], None, "TypeError"),
    ],
)
def test_a_selection_that_cannot_be_read_is_refused_and_kept(entries: object, active: object, problem: str) -> None:
    stored = {VERSION_KEY: 1, "entries": entries, "active": active}
    _scene()[NAMESPACE] = {SELECTION_KEY: stored}
    result = read_selection(_scene())
    assert isinstance(result, Refused)
    assert result.refusal is Refusal.INVALID
    assert problem in result.message
    with pytest.raises(RecordRefused):
        write_selection(_scene(), PersistentSelection((), None))
    assert _scene()[NAMESPACE][SELECTION_KEY].to_dict()["entries"] == entries
