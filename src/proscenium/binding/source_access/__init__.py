"""Source access: the stages a binding reads its source from (docs/spec/source-access.md).

The compiled core receives a stage from here; it never opens one.
"""

from .binding_ids import BindingId
from .binding_stages import (
    BindingStages,
    PayloadPolicy,
    SourceRevision,
    SourceUnavailableError,
    contributing_layers,
    dirty_layers,
)
from .requested_settings import RequestedSettings
from .stage_registry import StageRegistry

__all__ = [
    "BindingId",
    "BindingStages",
    "PayloadPolicy",
    "RequestedSettings",
    "SourceRevision",
    "SourceUnavailableError",
    "StageRegistry",
    "contributing_layers",
    "dirty_layers",
]
