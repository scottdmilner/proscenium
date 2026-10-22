"""Lookups by binding identity, creation, and configuration writes, through the bindings' state.

The state is proscenium.runtime.state's. A lookup by identity uses the identity's canonical
candidate, and raises BindingDisabledError for one with none (source-access.md#copied-bindings). Every candidate
a lookup decides on is checked before it answers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..core.canonical_candidate import CandidateEvidence, CanonicalDecision, DecisionReason
from ..core.source_access import SourceKind
from ..persistence import bindings, records
from ..persistence.bindings import BindingConfig
from ..persistence.records import RecordRefused, Refused
from . import copy_detection, state
from .state import Candidate, StaleError

if TYPE_CHECKING:
    import bpy

    from .copy_detection import CopiedBinding
    from .state import State

_UNIQUE = CanonicalDecision(0, DecisionReason.UNIQUE)


class BindingDisabledError(LookupError):  # raised like KeyError, for an identity with every candidate disabled
    """A lookup by a binding identity the canonical-candidate rule can't decide: every candidate is disabled
    pending repair (source-access.md#copied-bindings)."""

    report: CopiedBinding

    def __init__(self, report: CopiedBinding) -> None:
        super().__init__(f"binding {report.binding_id} has copies and no canonical candidate ({report.reason})")
        self.report = report


def binding_ids(scene: bpy.types.Scene | None = None) -> list[str]:
    """The bindings, in the order they were found or made; with scene, those whose canonical candidate is on it,
    or, for a binding with none, those with a candidate on it. Every candidate is checked.
    """
    return state.query(lambda s: _listed(s, scene))


def binding_scene(binding_id: str) -> bpy.types.Scene | None:
    """The scene holding a binding's configuration, or None if no binding has this identifier.

    Every lookup by identity, here and below, raises BindingDisabledError for a binding with no canonical candidate.
    """
    found = state.query(lambda s: canonical(s, binding_id))
    return None if found is None else found.scene


def config(binding_id: str) -> BindingConfig | Refused | None:
    """A binding's configuration, why it can't be read, or None if no binding has this identifier."""
    found = state.query(lambda s: canonical(s, binding_id))
    return None if found is None else found.config


def configs() -> dict[str, BindingConfig | Refused | CopiedBinding]:
    """Every binding's configuration, why it can't be read, or, for one with no canonical candidate, its
    candidates: one pass over the bindings, checking each one's candidates."""
    return state.query(_configs)


def copied_bindings() -> list[CopiedBinding]:
    """Every binding identity that isn't unique, with its candidates and the rule's decision."""
    return state.query(_copied)


def attached_with_key(key: str) -> list[tuple[str, BindingConfig]]:
    """The bindings whose configuration can be read and is an attached source with this exact key; one with copies
    and no canonical candidate isn't one of them."""
    return [
        (binding_id, config)
        for binding_id, config in configs().items()
        if isinstance(config, BindingConfig) and config.source is SourceKind.ATTACHED and config.key == key
    ]


def create(scene: bpy.types.Scene, config: BindingConfig, name: str) -> str:
    """Make a binding with bindings.create, and record it; it has no manifest yet. Returns its identifier.

    Raises NotRegisteredError before changing anything, and what bindings.create raises.
    """
    current = state.current_state()
    binding_id, config = bindings.create(scene, config, name)
    made = Candidate(scene, scene.session_uid, config, None)
    current.bindings[binding_id] = [made]
    assert config.destination is not None
    uid = config.destination.session_uid
    current.by_destination.setdefault(uid, []).append((binding_id, made))  # last, as among the bindings
    current.identities[binding_id] = copy_detection.IdentityCandidates(
        [], [CandidateEvidence(uid, mutual=True)], [uid], _UNIQUE
    )
    current.tagged |= {uid}
    return binding_id


def set_config(binding_id: str, config: BindingConfig) -> None:
    """Store a binding's changed configuration; an unchanged one writes nothing.

    Raises RecordRefused, changing nothing, over one that can't be read; KeyError if there's no such binding.
    """
    found = existing(binding_id)
    if config == found.config:
        return
    bindings.update(found.scene, binding_id, config)
    moved = isinstance(found.config, Refused) or found.config.destination != config.destination
    found.config = config
    if moved:  # a destination changes only in repair: rebuilt whole, in the order a rebuild finds
        state.invalidate()
        return
    restore_entry(binding_id, found)


def canonical(current: State, binding_id: str) -> Candidate | None:
    """The binding's canonical candidate, every candidate checked (see state.valid), or None if no binding has this
    identifier. Raises BindingDisabledError if it has none."""
    found = current.bindings.get(binding_id)
    if found is None:
        return None
    _check_candidates(current, binding_id, found)
    identity = current.identities[binding_id]
    if (index := identity.decision.canonical) is None:
        raise BindingDisabledError(copy_detection.report(binding_id, identity, [(b.scene, b.config) for b in found]))
    return found[index]  # a record: copies are never mutual, so with records the rule picks one


def existing(binding_id: str) -> Candidate:
    """The binding's canonical candidate, for a write. Raises KeyError if no binding has this identifier."""
    if (found := state.query(lambda s: canonical(s, binding_id))) is None:
        raise KeyError(binding_id)
    return found


def restore_entry(binding_id: str, found: Candidate) -> None:
    """After a write to the canonical candidate's records: restore its index entry if the index has none for it
    and its record and destination refer to each other (source-access.md#canonical-candidate). Detection
    writes nothing; a file with two indexes, or one that can't be read, is left as it is."""
    identity = state.current_state().identities[binding_id]
    if identity.entries or isinstance(found.config, Refused) or found.config.destination is None:
        return
    if not copy_detection.refers_back(binding_id, found.scene, found.config):
        return
    try:
        bindings.restore_entry(binding_id, found.config.destination)
    except (ValueError, RecordRefused):
        return
    identity.restored(found.config.destination)


def _listed(current: State, scene: bpy.types.Scene | None) -> list[str]:
    uid = None if scene is None else scene.session_uid
    listed = []
    for binding_id, found in current.bindings.items():
        if uid is not None and all(b.scene_uid != uid for b in found):
            continue  # none on scene, so it can't be listed there, whatever the rule decides: not checked
        _check_candidates(current, binding_id, found)
        index = current.identities[binding_id].decision.canonical
        here = found if index is None else [found[index]]
        if uid is None or any(b.scene_uid == uid for b in here):
            listed.append(binding_id)
    return listed


def _configs(current: State) -> dict[str, BindingConfig | Refused | CopiedBinding]:
    found: dict[str, BindingConfig | Refused | CopiedBinding] = {}
    for binding_id in current.bindings:
        try:
            candidate = canonical(current, binding_id)
        except BindingDisabledError as disabled:
            found[binding_id] = disabled.report
        else:
            assert candidate is not None
            found[binding_id] = candidate.config
    return found


def _copied(current: State) -> list[CopiedBinding]:
    copied = []
    for binding_id, identity in current.identities.items():
        if identity.decision.reason is not DecisionReason.UNIQUE:
            found = current.bindings.get(binding_id, [])
            _check_candidates(current, binding_id, found)
            copied.append(copy_detection.report(binding_id, identity, [(b.scene, b.config) for b in found]))
    return copied


def _check_candidates(current: State, binding_id: str, found: list[Candidate]) -> None:
    """Raise StaleError if any candidate of the identity is gone: the rule's decision may have been different."""
    copies = current.identities[binding_id].tagged_copies
    if not all(state.valid(binding_id, b) for b in found) or not all(
        state.alive(c) and records.has(c, bindings.TAG_KEY) for c in copies
    ):
        raise StaleError
