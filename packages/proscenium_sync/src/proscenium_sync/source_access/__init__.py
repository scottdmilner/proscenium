"""Source access: the stages a binding reads its source from (docs/spec/source-access.md).

The compiled core receives a stage from here; it never opens one. It exports its modules, and BindingId.
"""

from typing import NewType

from . import binding_settings, canonical_candidate, source_entity_ids, stage_registry, stages

# A binding's persistent identifier (source-access.md#synchronization-api). A NewType, so the checker tells a binding
# identifier from any other string, such as a USD path or a resource identifier, while at runtime it is the str that
# records store.
BindingId = NewType("BindingId", str)

__all__ = ["BindingId", "binding_settings", "canonical_candidate", "source_entity_ids", "stage_registry", "stages"]
