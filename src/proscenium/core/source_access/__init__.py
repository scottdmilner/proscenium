"""Source access: the stages a binding reads its source from (docs/spec/source-access.md).

The compiled core receives a stage from here; it never opens one.
"""

from .binding_stages import BindingStages, PayloadPolicy, SourceUnavailableError, contributing_layers, dirty_layers
from .stage_registry import StageRegistry

__all__ = [
    "BindingStages",
    "PayloadPolicy",
    "SourceUnavailableError",
    "StageRegistry",
    "contributing_layers",
    "dirty_layers",
]
