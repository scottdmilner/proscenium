"""Lookups by binding identity, creation, and configuration writes, through the bindings' state.

The state is proscenium.runtime.state's. A lookup by identity uses the identity's canonical
candidate, and for one with none returns its CopiedBinding report, in band, as an unreadable configuration
is returned (source-access.md#copied-bindings); a write to it raises BindingDisabledError. Every candidate
a lookup decides on is checked before it answers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..core.canonical_candidate import DecisionReason
from ..core.source_access import SourceKind
from ..persistence import binding_records, records
from ..persistence.binding_records import BindingConfig
from ..persistence.records import RefusedRecord, RefusedRecordError
from . import copy_detection, state
from .copy_detection import CopiedBinding
from .state import Candidate, StaleError

if TYPE_CHECKING:
    import bpy

    from ..core.binding_ids import BindingId
    from .copy_detection import IdentityCandidates
    from .state import State


class BindingDisabledError(LookupError):  # raised like KeyError, for an identity with every candidate disabled
    """A write to a binding identity the canonical-candidate rule can't decide.

    Every candidate is disabled pending repair (source-access.md#copied-bindings).
    """

    report: CopiedBinding

    def __init__(self, report: CopiedBinding) -> None:
        super().__init__(f"binding {report.binding_id} has copies and no canonical candidate ({report.reason})")
        self.report = report


def binding_ids(scene: bpy.types.Scene | None = None) -> list[BindingId]:
    """The bindings, in the order they were found or made.

    With scene, those whose canonical candidate is on it, or, for a binding with none, those with a candidate on it.
    Every candidate is checked.
    """
    return state.query(lambda s: _listed(s, scene))


def binding_scene(binding_id: BindingId) -> bpy.types.Scene | CopiedBinding | None:
    """The scene holding a binding's configuration, or None if no binding has this identifier.

    Every lookup by identity, here and below, returns a binding's CopiedBinding report if it has no canonical
    candidate.
    """
    candidate = state.query(lambda s: canonical(s, binding_id))
    return candidate.scene if isinstance(candidate, Candidate) else candidate


def config(binding_id: BindingId) -> BindingConfig | RefusedRecord | CopiedBinding | None:
    """A binding's configuration, why it can't be read, or None if no binding has this identifier."""
    candidate = state.query(lambda s: canonical(s, binding_id))
    return candidate.config if isinstance(candidate, Candidate) else candidate


def configs() -> dict[BindingId, BindingConfig | RefusedRecord | CopiedBinding]:
    """Every binding's configuration or why it can't be read, as config() gives it.

    One pass over the bindings, checking each one's candidates.
    """
    return state.query(_configs)


def copied_bindings() -> list[CopiedBinding]:
    """Every binding identity that isn't unique, with its candidates and the rule's decision."""
    return state.query(_copied)


def attached_with_key(key: str) -> list[tuple[BindingId, BindingConfig]]:
    """The bindings whose readable configuration is an attached source with this exact key.

    A binding with copies and no canonical candidate isn't one of them.
    """
    return [
        (binding_id, config)
        for binding_id, config in configs().items()
        if isinstance(config, BindingConfig) and config.source_kind is SourceKind.ATTACHED and config.source_key == key
    ]


def create(scene: bpy.types.Scene, config: BindingConfig, name: str) -> BindingId:
    """Make a binding with binding_records.create, and record it; it has no manifest yet. Returns its identifier.

    Raises NotRegisteredError before changing anything, and what binding_records.create raises.
    """
    current = state.current_state()
    binding_id, config = binding_records.create(scene, config, name)
    current.add_binding(binding_id, Candidate(scene, scene.session_uid, config, None))
    return binding_id


def set_config(binding_id: BindingId, config: BindingConfig) -> None:
    """Store a binding's changed configuration; an unchanged one writes nothing.

    Raises RefusedRecordError, changing nothing, over one that can't be read; KeyError if there's no such binding;
    BindingDisabledError if it has no canonical candidate.
    """
    candidate = writable(binding_id)
    # records.write refuses only an unreadable or newer record, so an invalid one is refused here.
    if isinstance(candidate.config, RefusedRecord):
        raise RefusedRecordError(candidate.config)
    if config == candidate.config:
        return
    binding_records.write_config(candidate.scene, binding_id, config)
    moved = candidate.config.destination != config.destination
    candidate.config = config
    if moved:  # a destination changes only in repair: rebuilt whole, in the order a rebuild finds
        state.invalidate()
        return
    restore_entry(binding_id, candidate)


def canonical(current: State, binding_id: BindingId) -> Candidate | CopiedBinding | None:
    """The binding's canonical candidate, its report if it has none, or None if there's no such binding.

    Every candidate is checked (see state.valid).
    """
    identity = current.identities.get(binding_id)
    if identity is None or not identity.records:
        return None  # tagged collections alone aren't a binding
    return _decided(binding_id, identity)


def existing(binding_id: BindingId) -> Candidate | CopiedBinding:
    """The binding's canonical candidate, or its report if it has none.

    Raises KeyError if no binding has this identifier.
    """
    if (candidate := state.query(lambda s: canonical(s, binding_id))) is None:
        raise KeyError(binding_id)
    return candidate


def writable(binding_id: BindingId) -> Candidate:
    """The binding's canonical candidate, for a write.

    Raises KeyError if no binding has this identifier, and BindingDisabledError if it has no canonical candidate.
    """
    return state.query(lambda s: writable_in(s, binding_id))


def writable_in(current: State, binding_id: BindingId) -> Candidate:
    """writable(), as a question for state.query: the binding's canonical candidate in current."""
    if (candidate := canonical(current, binding_id)) is None:
        raise KeyError(binding_id)
    if isinstance(candidate, CopiedBinding):
        raise BindingDisabledError(candidate)
    return candidate


def restore_entry(binding_id: BindingId, candidate: Candidate) -> None:
    """Restore the canonical candidate's missing index entry, after a write to its records.

    Only if the index has none for it and its record and destination refer to each other
    (source-access.md#canonical-candidate). Detection writes nothing; a file with two indexes, or one that can't be
    read, is left as it is.
    """
    identity = state.current_state().identities[binding_id]
    config = candidate.config
    if identity.entries or isinstance(config, RefusedRecord) or config.destination is None:
        return
    if not copy_detection.refers_back(binding_id, candidate.scene, config):
        return
    try:
        binding_records.restore_entry(binding_id, config.destination)
    except (ValueError, RefusedRecordError):
        return
    identity.restored(config.destination)


def _listed(current: State, scene: bpy.types.Scene | None) -> list[BindingId]:
    uid = None if scene is None else scene.session_uid
    listed = []
    for binding_id, identity in current.identities.items():
        if not identity.records:
            continue  # tagged collections alone aren't a binding
        if uid is not None and all(c.scene_uid != uid for c in identity.records):
            continue  # none on scene, so it can't be listed there, whatever the rule decides: not checked
        _check_candidates(binding_id, identity)
        canonical_record = identity.canonical_record()
        reached = identity.records if canonical_record is None else [canonical_record]
        if uid is None or any(c.scene_uid == uid for c in reached):
            listed.append(binding_id)
    return listed


def _configs(current: State) -> dict[BindingId, BindingConfig | RefusedRecord | CopiedBinding]:
    by_id: dict[BindingId, BindingConfig | RefusedRecord | CopiedBinding] = {}
    for binding_id, identity in current.identities.items():
        if identity.records:
            candidate = _decided(binding_id, identity)
            by_id[binding_id] = candidate.config if isinstance(candidate, Candidate) else candidate
    return by_id


def _copied(current: State) -> list[CopiedBinding]:
    copied = []
    for binding_id, identity in current.identities.items():
        if identity.decision.reason is not DecisionReason.UNIQUE:
            _check_candidates(binding_id, identity)
            copied.append(copy_detection.report(binding_id, identity))
    return copied


def _decided(binding_id: BindingId, identity: IdentityCandidates) -> Candidate | CopiedBinding:
    """The canonical record of an identity with records, checked, or its report if every candidate is disabled."""
    _check_candidates(binding_id, identity)
    if (candidate := identity.canonical_record()) is None:
        return copy_detection.report(binding_id, identity)
    return candidate


def _check_candidates(binding_id: BindingId, identity: IdentityCandidates) -> None:
    """Raise StaleError if any candidate of the identity is gone: the rule's decision may have been different."""
    if not all(state.valid(binding_id, c) for c in identity.records) or not all(
        state.alive(c) and records.has(c, binding_records.TAG_KEY) for c in identity.tagged_copies
    ):
        raise StaleError
