"""The plan of each generation this session published for a binding, held for refreshes to compare against.

DECISIONS.md "Incremental refresh comparison": a refresh compares its new plan with the plan of the generation the
destination shows, read from the generation record the destination holds, so after an undo or redo it compares with
the generation restored. The record is the key, without its cached time codes, since planning is deterministic over
its inputs (PLAN-08) and the record holds them, so equal records mean equal plans; caching a time code changes no
generation's plan. A binding holds a bounded number of plans, dropping the oldest first. Nothing here is saved: a
file load clears it all, and a record with no plan held, as after reopening or an undo past the bound, finds none,
which the refresh answers with a full rebuild.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from proscenium_sync import planner
    from proscenium_sync.persistence import binding_state
    from proscenium_sync.source_access import BindingId

type GenerationKey = binding_state.GenerationMetadata  # a generation record without its cached time codes


def generation_key(generation: binding_state.GenerationMetadata) -> GenerationKey:
    """The generation record as a key: its cached time codes cleared, which change no plan."""
    return dataclasses.replace(generation, cached_time_codes=())


class HeldPlans:
    """Each binding's held plans, by generation key, oldest first."""

    _plans_by_binding: dict[BindingId, dict[GenerationKey, planner.Plan]]

    def __init__(self) -> None:
        self._plans_by_binding = {}

    def hold(self, generation: binding_state.GenerationMetadata, plan: planner.Plan, bound: int) -> None:
        """Hold plan as the published generation's, newest, keeping the binding's newest bound plans.

        A plan held before under an equal record is replaced, so a record names the plan last published with it.
        Raises ValueError for a bound below 1, which couldn't hold the generation just published.
        """
        if bound < 1:
            raise ValueError("A binding holds at least the plan of the generation it just published")
        plans_by_key = self._plans_by_binding.setdefault(generation.binding_id, {})
        key = generation_key(generation)
        plans_by_key.pop(key, None)  # so it's the newest
        plans_by_key[key] = plan
        for oldest in list(plans_by_key)[: max(0, len(plans_by_key) - bound)]:
            del plans_by_key[oldest]

    def plan_for(self, generation: binding_state.GenerationMetadata) -> planner.Plan | None:
        """The plan held for the generation that record describes, or None."""
        plans_by_key = self._plans_by_binding.get(generation.binding_id)
        return None if plans_by_key is None else plans_by_key.get(generation_key(generation))

    def release(self, binding_id: BindingId) -> None:
        """Drop the binding's plans: its next attachment gives a new source revision, which none of them has."""
        self._plans_by_binding.pop(binding_id, None)

    def clear(self) -> None:
        """Drop every binding's plans, as a file load does."""
        self._plans_by_binding.clear()
