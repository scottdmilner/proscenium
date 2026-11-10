"""Source access: the stages a binding reads its source from (docs/spec/source-access.md).

The compiled core receives a stage from here; it never opens one. It exports its modules.
"""

from . import binding_settings, canonical_candidate, identifiers, source_entities, stage_registry, stages

__all__ = ["binding_settings", "canonical_candidate", "identifiers", "source_entities", "stage_registry", "stages"]
