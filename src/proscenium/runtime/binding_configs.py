"""Lookups by binding identity, binding creation, and configuration writes, through the bindings' state.

A lookup reaches the binding record of the identity's canonical candidate, its canonical record, after checking every
candidate the rule decides on, and returns what it finds as a FoundBinding: usable, with its configuration; unreadable,
with why (lifecycle.md#schema-versions); or disabled, with its copies (source-access.md#copied-bindings). A write to a
binding that isn't usable raises.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from ..core.canonical_candidate import DecisionReason
from ..persistence import binding_records, records
from ..persistence.records import RefusedRecord, RefusedRecordError
from . import copy_detection, state
from .state import StaleError

if TYPE_CHECKING:
    import bpy

    from ..core.binding_ids import BindingId
    from ..persistence.binding_records import BindingConfig
    from .copy_detection import CopiedBinding, IdentityCandidates
    from .state import BindingRecord, State


class BindingStatus(StrEnum):
    """Whether a binding can be used: whatever needs its configuration needs it usable."""

    USABLE = "usable"
    UNREADABLE = "unreadable"  # its configuration can't be read
    DISABLED = "disabled"  # it has copies and no canonical candidate


@dataclass(frozen=True, slots=True)
class FoundBinding:
    """A binding as a lookup by identity finds it. Exactly one of config, unreadable, and copies is set."""

    binding_id: BindingId
    scene: bpy.types.Scene | None  # the scene holding its canonical record; None if it is disabled
    config: BindingConfig | None  # its configuration, if it is usable
    unreadable: RefusedRecord | None  # why its configuration can't be read, if it can't
    copies: CopiedBinding | None  # its candidates, and why none is canonical, if it is disabled

    @property
    def status(self) -> BindingStatus:
        """Whether the binding can be used, and if not, why."""
        if self.copies is not None:
            return BindingStatus.DISABLED
        return BindingStatus.UNREADABLE if self.unreadable is not None else BindingStatus.USABLE

    @property
    def usable(self) -> bool:
        """Whether the binding can be used: its configuration can be read, and it isn't disabled."""
        return self.config is not None

    def usable_config(self) -> BindingConfig:
        """The configuration; raises RefusedRecordError or DisabledBindingError for a binding that isn't usable."""
        if self.unreadable is not None:
            raise RefusedRecordError(self.unreadable)
        if self.copies is not None:
            raise DisabledBindingError(self.copies)
        assert self.config is not None
        return self.config


class DisabledBindingError(LookupError):  # raised like KeyError
    """A binding with copies and no canonical candidate was asked for its configuration, or written to."""

    copies: CopiedBinding

    def __init__(self, copies: CopiedBinding) -> None:
        super().__init__(f"binding {copies.binding_id} has copies and no canonical candidate ({copies.reason})")
        self.copies = copies


def find_binding(binding_id: BindingId) -> FoundBinding | None:
    """The binding, or None if no binding has this identifier."""
    return state.query(lambda s: _found_in(s, binding_id))


def find_bindings(scene: bpy.types.Scene | None = None) -> list[FoundBinding]:
    """The bindings, in the order they were found or made; one pass over the state.

    With scene, those whose canonical candidate is on it, or, for a binding with none, those with a candidate on it.
    Every candidate is checked.
    """
    return state.query(lambda s: _listed(s, scene))


def copied_bindings() -> list[CopiedBinding]:
    """Every binding identity that isn't unique, with its candidates and the rule's decision."""
    return state.query(_copied)


def create(scene: bpy.types.Scene, config: BindingConfig, name: str) -> BindingId:
    """Make a binding with binding_records.create, and record it; it has no manifest yet. Returns its identifier.

    Raises NotRegisteredError before changing anything, and what binding_records.create raises.
    """
    current = state.current_state()
    created = binding_records.create(scene, config, name)
    current.add_binding(scene, created)
    return created.binding_id


def set_config(binding_id: BindingId, config: BindingConfig) -> None:
    """Store a binding's changed configuration; an unchanged one writes nothing.

    Raises RefusedRecordError, changing nothing, over one that can't be read; KeyError if there's no such binding;
    DisabledBindingError if it has no canonical candidate.
    """
    record = required_record(binding_id)
    # records.write refuses only an unreadable or newer record, so an invalid one is refused here.
    if isinstance(record.config, RefusedRecord):
        raise RefusedRecordError(record.config)
    if config == record.config:
        return
    binding_records.write_config(record.scene, binding_id, config)
    moved = record.config.destination != config.destination
    record.held.configs[binding_id] = config
    if moved:  # a destination changes only in repair: rebuilt whole, in the order a rebuild finds
        state.invalidate()
        return
    restore_entry(binding_id, record)


def required_record(binding_id: BindingId) -> BindingRecord:
    """The binding's canonical record, readable or not.

    Raises KeyError if no binding has this identifier, and DisabledBindingError if it has no canonical candidate.
    """
    return state.query(lambda s: required_record_in(s, binding_id))


def required_record_in(current: State, binding_id: BindingId) -> BindingRecord:
    """required_record(), as a question for state.query: the binding's canonical record in current."""
    identity = current.identities.get(binding_id)
    if identity is None or not identity.records:
        raise KeyError(binding_id)  # tagged collections alone aren't a binding
    _check_candidates(binding_id, identity)
    if (record := identity.canonical_record()) is None:
        raise DisabledBindingError(copy_detection.report(binding_id, identity))
    return record


def restore_entry(binding_id: BindingId, record: BindingRecord) -> None:
    """Add the binding index entry the canonical record is missing, after a write to its records.

    Only when the index has no entry for the identity, and the record and its destination refer to each other
    (source-access.md#canonical-candidate). A file with two indexes, or one that can't be read, is left alone. Writes
    restore entries; detection never does.
    """
    current = state.current_state()
    config = record.config
    if current.identities[binding_id].index_entries or isinstance(config, RefusedRecord) or config.destination is None:
        return
    if not copy_detection.refers_back(current, binding_id, record):
        return
    try:
        written = binding_records.restore_entry(binding_id, config.destination)
    except (ValueError, RefusedRecordError):
        return
    if written is not None:
        current.replace_index(binding_id, written)


def _found_in(current: State, binding_id: BindingId) -> FoundBinding | None:
    identity = current.identities.get(binding_id)
    if identity is None or not identity.records:
        return None  # tagged collections alone aren't a binding
    return _found(binding_id, identity)


def _listed(current: State, scene: bpy.types.Scene | None) -> list[FoundBinding]:
    uid = None if scene is None else scene.session_uid
    listed = []
    for binding_id, identity in current.identities.items():
        if not identity.records:
            continue  # tagged collections alone aren't a binding
        if uid is not None and all(r.scene_uid != uid for r in identity.records):
            continue  # none on scene, so it can't be listed there, whatever the rule decides: not checked
        found = _found(binding_id, identity)
        canonical = identity.canonical_record()
        reached = identity.records if canonical is None else [canonical]
        if uid is None or any(r.scene_uid == uid for r in reached):
            listed.append(found)
    return listed


def _copied(current: State) -> list[CopiedBinding]:
    copied = []
    for binding_id, identity in current.identities.items():
        if identity.decision.reason is not DecisionReason.UNIQUE:
            _check_candidates(binding_id, identity)
            copied.append(copy_detection.report(binding_id, identity))
    return copied


def _found(binding_id: BindingId, identity: IdentityCandidates) -> FoundBinding:
    """The binding an identity with records is, checked."""
    _check_candidates(binding_id, identity)
    if (record := identity.canonical_record()) is None:
        return FoundBinding(binding_id, None, None, None, copy_detection.report(binding_id, identity))
    if isinstance(record.config, RefusedRecord):
        return FoundBinding(binding_id, record.scene, None, record.config, None)
    return FoundBinding(binding_id, record.scene, record.config, None, None)


def _check_candidates(binding_id: BindingId, identity: IdentityCandidates) -> None:
    """Raise StaleError if any candidate of the identity is gone: the rule's decision may have been different."""
    for candidate in identity.candidates:
        if candidate.record is not None:
            present = state.valid(binding_id, candidate.record)
        else:  # a tagged copy
            copy = candidate.collection
            present = copy is not None and state.alive(copy) and records.has(copy, binding_records.TAG_KEY)
        if not present:
            raise StaleError
